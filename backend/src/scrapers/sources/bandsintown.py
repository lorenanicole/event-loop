import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.database.models import EventModel
from shared.enrichment import extract_from_event_text
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)


class BandsinTownScraper:
    """Scraper for BandsinTown music events using official free API."""

    BASE_URL = "https://www.bandsintown.com/api/v2"
    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    async def fetch_events(self, days_ahead: int = 30) -> list[EventCreate]:
        """Fetch events from BandsinTown for Chicago area"""
        try:
            events = []

            # Chicago coordinates
            chicago_lat = 41.8781
            chicago_lon = -87.6298
            radius = 25  # miles

            # Date range
            start_date = datetime.now().strftime("%Y-%m-%d")
            end_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

            url = f"{self.BASE_URL}/events/search"

            params = {
                "location": f"{chicago_lat},{chicago_lon}",
                "radius": radius,
                "date": f"{start_date},{end_date}",
                "app_id": "EventDiscovery/1.0",
            }

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": self.USER_AGENT},
                )
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list):
                    for event_data in data:
                        try:
                            event = self._parse_event(event_data)
                            if event:
                                events.append(event)
                        except Exception:
                            continue

            logger.info(f"Fetched {len(events)} events from BandsinTown")
            return events

        except Exception as e:
            logger.error(f"BandsinTown fetch error: {e}")
            return []

    def _parse_event(self, data: dict) -> EventCreate | None:
        """Parse a single event from API response"""
        try:
            # Extract artist name and venue
            artist_name = None
            if data.get("artist"):
                artist_name = data["artist"].get("name")

            title = None
            if artist_name and data.get("venue"):
                venue_name = data["venue"].get("name", "Unknown Venue")
                title = f"{artist_name} at {venue_name}"
            elif artist_name:
                title = artist_name

            if not title:
                return None

            # Parse date
            event_date_str = data.get("datetime")
            if not event_date_str:
                return None

            try:
                # BandsinTown returns ISO format datetime
                event_date = datetime.fromisoformat(event_date_str)
            except ValueError, TypeError:
                return None

            # Category
            category = "Music"

            # Details
            details_parts = []

            if data.get("venue"):
                venue = data["venue"]
                venue_name = venue.get("name")
                if venue_name:
                    details_parts.append(f"Venue: {venue_name}")

                city = venue.get("city")
                region = venue.get("region")
                if city or region:
                    location = f"{city}, {region}" if city and region else city or region
                    details_parts.append(f"Location: {location}")

            if data.get("description"):
                description = data["description"].strip()[:300]
                details_parts.append(description)

            details = " | ".join(details_parts) if details_parts else None

            # URL
            url = data.get("url") or f"https://www.bandsintown.com/e/{data.get('id')}"
            if not url:
                return None

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
                    event = EventModel(**event_data.model_dump(), source="bandsintown")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from BandsinTown")
            return saved_count

        except Exception as e:
            logger.error(f"Save error: {e}")
            if is_async:
                await db.rollback()
            else:
                db.rollback()
            return 0
