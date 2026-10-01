import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models import EventCreate
from src.database.models import EventModel
from src.ai.event_enrichment import (
    extract_from_event_text,
    extract_is_outdoor,
    extract_address,
    extract_venue_name,
)

logger = logging.getLogger(__name__)


class DO312Scraper:
    """
    Scraper for DO312 events using their public JSON API.
    """

    BASE_URL = "https://do312.com"
    API_ENDPOINT = f"{BASE_URL}/events.json"

    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    async def fetch_events(self, days_ahead: int = 30) -> list[EventCreate]:
        """Fetch events from DO312 JSON API with pagination"""
        try:
            events = []
            page = 1

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT, follow_redirects=True) as client:
                while True:
                    params = {
                        "page": page,
                    }

                    response = await client.get(
                        self.API_ENDPOINT,
                        params=params,
                        headers={"User-Agent": self.USER_AGENT},
                    )
                    response.raise_for_status()
                    data = response.json()

                    events_data = data.get("events", [])
                    if not events_data:
                        break

                    for event_data in events_data:
                        try:
                            event = self._parse_event_data(event_data)
                            if event:
                                events.append(event)
                        except Exception as parse_err:
                            logger.debug(f"Skipped event: {parse_err}")
                            continue

                    # Check pagination
                    paging = data.get("paging", {})
                    if page >= paging.get("total_pages", 1):
                        break

                    page += 1

            logger.info(f"Fetched {len(events)} events from DO312 API")
            return events

        except Exception as e:
            logger.error(f"DO312 fetch error: {type(e).__name__}: {e}")
            return []

    def _parse_event_data(self, data: dict) -> Optional[EventCreate]:
        """Parse a single event from API response"""
        try:
            title = data.get("title", "").strip()
            if not title:
                return None

            begin_date_str = data.get("tz_adjusted_begin_date") or data.get("begin_date")
            if not begin_date_str:
                return None

            try:
                clean_str = begin_date_str.replace("Z", "").split(".")[0]
                event_date = datetime.fromisoformat(clean_str)
            except Exception:
                logger.debug(f"Date parse failed for {title}: {begin_date_str}")
                return None

            category = data.get("category", "Other")

            description_parts = []
            if data.get("excerpt"):
                description_parts.append(data["excerpt"])
            if data.get("description"):
                description_parts.append(data["description"])
            details = " ".join(description_parts) if description_parts else None

            permalink = data.get("permalink")
            if not permalink:
                return None

            origination_url = f"{self.BASE_URL}{permalink}"

            # Extract cost and age_range from title and details
            cost, age_range = extract_from_event_text(title, details)

            # Extract location data
            full_text = f"{title} {details or ''}".strip()
            is_outdoor = extract_is_outdoor(full_text)
            address = extract_address(full_text)
            venue_name = extract_venue_name(title)

            event = EventCreate(
                name=title,
                date=event_date,
                category=category,
                details=details,
                origination_url=origination_url,
            )

            # Add enriched data to the event if extracted
            if cost:
                event.cost = cost
            if age_range:
                event.age_range = age_range
            if is_outdoor:
                event.is_outdoor = is_outdoor
            if address:
                event.address = address
            if venue_name:
                event.venue_name = venue_name

            return event

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    async def scrape_and_save(self, db: Union[Session, AsyncSession], days_ahead: int = 30) -> int:
        """Fetch events and save new ones to database (sync or async)"""
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
                    event = EventModel(**event_data.model_dump(), source="do312")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from DO312")
            return saved_count

        except Exception as e:
            logger.error(f"Save error: {e}")
            if is_async:
                await db.rollback()
            else:
                db.rollback()
            return 0
