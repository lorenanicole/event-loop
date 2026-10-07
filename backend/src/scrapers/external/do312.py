import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.ai.event_enrichment import (
    extract_address,
    extract_from_event_text,
    extract_is_outdoor,
    extract_venue_name,
)
from scrapers.custom.venue.chicago_events_scraper import venue_to_neighborhood
from shared.database.models import EventModel
from shared.database.neighborhoods import load_boundaries, resolve_neighborhood_id
from shared.geo import resolve_neighborhood
from shared.models import EventCreate

logger = logging.getLogger(__name__)

# Rows written before the lock is released. SQLite serializes writers, and
# these scrapers used to add several hundred events inside one transaction -
# which held the write lock for minutes and failed every `INSERT INTO
# chat_threads` a chat tried to make meanwhile, with "database is locked".
# Raising busy_timeout to 30s did not help: no wait beats a transaction held
# that long. Committing in batches does, by letting go between them.
WRITE_BATCH = 50


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

            async with httpx.AsyncClient(
                timeout=self.REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
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

    def _parse_event_data(self, data: dict) -> EventCreate | None:
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

            # The API states this outright, which beats inferring it from prose.
            # `ticket_info` is deliberately not used for price: it is free text
            # and usually holds showtimes or "Sold Out" rather than a figure.
            if data.get("is_free"):
                cost = "Free"

            full_text = f"{title} {details or ''}".strip()
            is_outdoor = extract_is_outdoor(full_text)

            # The API returns a structured venue with coordinates, which is far
            # more reliable than pattern-matching an address out of the blurb.
            # Fall back to the text extraction only when the venue is missing.
            venue = data.get("venue") or {}
            venue_name = venue.get("title") or extract_venue_name(title)
            address = (
                venue.get("full_address") or venue.get("address") or extract_address(full_text)
            )
            try:
                latitude = float(venue["latitude"])
                longitude = float(venue["longitude"])
            except KeyError, TypeError, ValueError:
                latitude = longitude = None

            # Multi-day runs so the UI can show "Oct 22 - Dec 6" rather than
            # treating a whole theatre run as a single night.
            date_end = None
            end_str = data.get("tz_adjusted_end_date") or data.get("end_date")
            if end_str:
                try:
                    date_end = datetime.fromisoformat(end_str.replace("Z", "").split(".")[0])
                except TypeError, ValueError:
                    date_end = None
            if date_end and date_end.date() <= event_date.date():
                date_end = None

            event = EventCreate(
                name=title,
                date=event_date,
                date_end=date_end,
                category=category,
                details=details,
                origination_url=origination_url,
                latitude=latitude,
                longitude=longitude,
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

    async def scrape_and_save(self, db: Session | AsyncSession, days_ahead: int = 30) -> int:
        """Fetch events and save new ones to database (sync or async)"""
        try:
            events = await self.fetch_events(days_ahead=days_ahead)
            saved_count = 0
            seen_urls = set()

            is_async = isinstance(db, AsyncSession)

            # Boundaries come from our own tables and are read once per run, so
            # placing each venue costs no network calls.
            boundaries = await load_boundaries(db) if is_async else {}
            venue_map = venue_to_neighborhood()
            neighborhood_ids: dict[str, int | None] = {}

            async def neighborhood_id_for(event_data) -> int | None:
                """Place an event, caching the id per neighborhood."""
                if not boundaries:
                    return None
                name, latitude, longitude = await resolve_neighborhood(
                    db,
                    boundaries,
                    latitude=event_data.latitude,
                    longitude=event_data.longitude,
                    address=event_data.address,
                    venue_name=event_data.venue_name,
                    venue_map=venue_map,
                    # The venue payload already carries coordinates, so an
                    # external geocoder is only a last resort here.
                    allow_network=True,
                )
                if latitude is not None and event_data.latitude is None:
                    event_data.latitude, event_data.longitude = latitude, longitude
                if not name:
                    return None
                if name not in neighborhood_ids:
                    neighborhood_ids[name] = await resolve_neighborhood_id(db, name)
                return neighborhood_ids[name]

            processed = 0
            for event_data in events:
                processed += 1
                if processed % WRITE_BATCH == 0:
                    # Release the write lock so an
                    # interactive write can get in.
                    if is_async:
                        await db.commit()
                    else:
                        db.commit()
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

                neighborhood_id = await neighborhood_id_for(event_data) if is_async else None

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="do312")
                    event.neighborhood_id = neighborhood_id
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()
                    # Refresh rows stored before venue data was captured.
                    if event_data.latitude is not None:
                        existing.latitude = event_data.latitude
                        existing.longitude = event_data.longitude
                    if event_data.address and not existing.address:
                        existing.address = event_data.address
                    if event_data.venue_name and not existing.venue_name:
                        existing.venue_name = event_data.venue_name
                    if event_data.date_end and not existing.date_end:
                        existing.date_end = event_data.date_end
                    if event_data.cost and not existing.cost:
                        existing.cost = event_data.cost
                    if neighborhood_id and not existing.neighborhood_id:
                        existing.neighborhood_id = neighborhood_id

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
