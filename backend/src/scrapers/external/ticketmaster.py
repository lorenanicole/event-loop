import logging
import os
import httpx
from datetime import datetime, timedelta
from typing import Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from shared.models import EventCreate
from shared.database.models import EventModel
from app.ai.event_enrichment import extract_from_event_text

logger = logging.getLogger(__name__)


class TicketmasterScraper:
    """Scraper for Ticketmaster events using official Discovery API."""

    BASE_URL = "https://app.ticketmaster.com/discovery/v2"
    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    def __init__(self):
        self.api_key = os.getenv("TICKETMASTER_API_KEY")
        if not self.api_key:
            raise ValueError("TICKETMASTER_API_KEY not found in environment.")

    async def fetch_events(self, days_ahead: int = 30) -> list[EventCreate]:
        """Fetch events from Ticketmaster for Chicago area"""
        try:
            events = []

            start_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            end_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

            params = {
                "apikey": self.api_key,
                "city": "Chicago",
                "stateCode": "IL",
                "countryCode": "US",
                "startDateTime": start_date,
                "endDateTime": end_date,
                "sort": "date,asc",
                "size": 200,
                "includeSpellcheck": "no",
            }

            url = f"{self.BASE_URL}/events"
            page = 0

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                while True:
                    params["page"] = page

                    try:
                        response = await client.get(url, params=params, headers={"User-Agent": self.USER_AGENT})
                        response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 401:
                            logger.error("Ticketmaster API key invalid")
                        elif e.response.status_code == 429:
                            logger.warning("Ticketmaster rate limit")
                        break

                    data = response.json()
                    events_data = data.get("_embedded", {}).get("events", [])

                    if not events_data:
                        break

                    for event_data in events_data:
                        try:
                            event = self._parse_event(event_data)
                            if event:
                                events.append(event)
                        except Exception:
                            continue

                    page_info = data.get("page", {})
                    if page_info.get("number", 0) >= page_info.get("totalPages", 1) - 1:
                        break

                    page += 1

            logger.info(f"Fetched {len(events)} events from Ticketmaster")
            return events

        except Exception as e:
            logger.error(f"Ticketmaster fetch error: {e}")
            return []

    def _parse_event(self, data: dict) -> Optional[EventCreate]:
        """Parse a single event"""
        try:
            event_id = data.get("id")
            title = data.get("name", "").strip()

            if not title or not event_id:
                return None

            dates = data.get("dates", {})
            start_date = dates.get("start", {}).get("dateTime")

            if not start_date:
                return None

            try:
                event_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

            category = "Other"
            classifications = data.get("classifications", [])
            if classifications:
                segment = classifications[0].get("segment", {})
                if segment:
                    category = segment.get("name", "Other")

            description = None
            if data.get("info"):
                description = data["info"].strip()[:500]

            if data.get("pleaseNote"):
                note = data["pleaseNote"].strip()[:300]
                description = f"{description} | Note: {note}" if description else f"Note: {note}"

            url = data.get("url") or f"https://www.ticketmaster.com/event/{event_id}"

            details_parts = []
            if description:
                details_parts.append(description)

            embedded = data.get("_embedded", {})
            venues = embedded.get("venues", [])
            if venues:
                venue = venues[0]
                venue_name = venue.get("name")
                if venue_name:
                    details_parts.append(f"Venue: {venue_name}")

                city = venue.get("city", {}).get("name")
                state = venue.get("state", {}).get("name")
                if city or state:
                    location = f"{city}, {state}" if city and state else city or state
                    details_parts.append(f"Location: {location}")

            details = " | ".join(details_parts) if details_parts else None

            # Extract cost and age_range from title and details
            cost, age_range = extract_from_event_text(title, details)

            event = EventCreate(
                name=title,
                date=event_date,
                category=category,
                details=details,
                origination_url=url,
            )

            # Add cost and age_range to the event if extracted
            if cost:
                event.cost = cost
            if age_range:
                event.age_range = age_range

            return event

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    async def scrape_and_save(self, db: Union[Session, AsyncSession], days_ahead: int = 30) -> int:
        """Fetch and save events (sync or async)"""
        try:
            events = await self.fetch_events(days_ahead=days_ahead)
            saved_count = 0
            seen_urls = set()

            is_async = isinstance(db, AsyncSession)

            for event_data in events:
                url = event_data.origination_url
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if is_async:
                    # Async query
                    result = await db.execute(
                        select(EventModel).filter_by(origination_url=url)
                    )
                    existing = result.scalar_one_or_none()
                else:
                    # Sync query
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="ticketmaster")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from Ticketmaster")
            return saved_count

        except Exception as e:
            logger.error(f"Save error: {e}")
            if is_async:
                await db.rollback()
            else:
                db.rollback()
            return 0
