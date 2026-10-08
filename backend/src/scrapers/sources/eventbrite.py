import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.database import to_naive_utc
from shared.database.models import EventModel
from shared.enrichment import extract_from_event_text
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)


class EventbriteScraper:
    """Scraper for Eventbrite events using official public API."""

    BASE_URL = "https://www.eventbriteapi.com/v3"
    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    def __init__(self):
        self.api_key = os.getenv("EVENTBRITE_API_KEY")
        if not self.api_key:
            raise ValueError("EVENTBRITE_API_KEY not found in environment.")
        self.headers = {
            "User-Agent": self.USER_AGENT,
            "Authorization": f"Bearer {self.api_key}",
        }

    async def fetch_events(self, days_ahead: int = 30) -> list[EventCreate]:
        """Fetch events from Eventbrite for Chicago area"""
        try:
            events = []
            chicago_coords = {
                "latitude": 41.8781,
                "longitude": -87.6298,
                "radius": 40,
            }

            start_date = datetime.now()
            end_date = start_date + timedelta(days=days_ahead)

            params = {
                "q": "event",
                "location.latitude": chicago_coords["latitude"],
                "location.longitude": chicago_coords["longitude"],
                "location.within": chicago_coords["radius"],
                "start_date.gte": start_date.isoformat(),
                "start_date.lte": end_date.isoformat(),
                "sort_by": "date",
                "expand": "category,subcategory,venue",
                "page_size": 200,
            }

            url = f"{self.BASE_URL}/events/search/"
            page = 1

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                while True:
                    params["page"] = page

                    try:
                        response = await client.get(url, params=params, headers=self.headers)
                        response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 401:
                            logger.error("Eventbrite API key invalid")
                        elif e.response.status_code == 429:
                            logger.warning("Eventbrite rate limit")
                        break

                    data = response.json()
                    events_data = data.get("events", [])

                    if not events_data:
                        break

                    for event_data in events_data:
                        try:
                            event = self._parse_event(event_data)
                            if event:
                                events.append(event)
                        except Exception:
                            continue

                    pagination = data.get("pagination", {})
                    if not pagination.get("has_more_items"):
                        break

                    page += 1

            logger.info(f"Fetched {len(events)} events from Eventbrite")
            return events

        except Exception as e:
            logger.error(f"Eventbrite fetch error: {e}")
            return []

    def _parse_event(self, data: dict) -> EventCreate | None:
        """Parse a single event"""
        try:
            event_id = data.get("id")
            title = data.get("name", {}).get("text", "").strip()

            if not title or not event_id:
                return None

            start_time = data.get("start", {}).get("utc")
            if not start_time:
                return None

            try:
                event_date = to_naive_utc(datetime.fromisoformat(start_time))
            except ValueError, TypeError:
                return None

            category = data.get("category", {}).get("name", "Other")
            description = data.get("description", {}).get("text")
            if description:
                description = description.strip()[:500]

            url = data.get("url") or f"https://www.eventbrite.com/e/{event_id}"

            details_parts = []
            if description:
                details_parts.append(description)

            venue = data.get("venue")
            if venue:
                venue_name = venue.get("name")
                if venue_name:
                    details_parts.append(f"Venue: {venue_name}")

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

    async def scrape_and_save(self, db: Session | AsyncSession, days_ahead: int = 30) -> int:
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
                    result = await db.execute(select(EventModel).filter_by(origination_url=url))
                    existing = result.scalar_one_or_none()
                else:
                    # Sync query
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="eventbrite")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.now(timezone.utc).replace(tzinfo=None)

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from Eventbrite")
            return saved_count

        except Exception as e:
            logger.error(f"Save error: {e}")
            if is_async:
                await db.rollback()
            else:
                db.rollback()
            return 0
