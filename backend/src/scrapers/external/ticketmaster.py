import logging
import os
import httpx
from datetime import datetime, timedelta
from typing import Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from shared.localtime import to_chicago_naive
from shared.models import EventCreate
from shared.database.models import EventModel
from shared.database.neighborhoods import load_boundaries, resolve_neighborhood_id
from shared.geo import chicago_neighborhoods
from app.ai.event_enrichment import extract_from_event_text

logger = logging.getLogger(__name__)

# Rows written before the lock is released. SQLite serializes writers, and
# these scrapers used to add several hundred events inside one transaction -
# which held the write lock for minutes and failed every `INSERT INTO
# chat_threads` a chat tried to make meanwhile, with "database is locked".
# Raising busy_timeout to 30s did not help: no wait beats a transaction held
# that long. Committing in batches does, by letting go between them.
WRITE_BATCH = 50



def _meaningful(name) -> Optional[str]:
    """A classification name, or None when it is a placeholder.

    Discovery fills unknown levels with the literal string "Undefined", and
    occasionally "Undefined Undefined". Those are not categories, and treating
    them as one is how 128 events ended up filed under "Undefined".
    """
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned or cleaned.lower().replace("undefined", "").strip() == "":
        return None
    return cleaned


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
            start = dates.get("start", {})

            # `dateTime` is UTC. Storing it as-is moved every evening show
            # forward a day - an 8pm gig became 01:00 tomorrow - so prefer the
            # localDate/localTime the API gives alongside it, and fall back to
            # converting the UTC instant rather than trusting its wall clock.
            event_date = None
            if start.get("localDate"):
                stamp = f"{start['localDate']}T{start.get('localTime') or '00:00:00'}"
                try:
                    event_date = datetime.fromisoformat(stamp)
                except (ValueError, TypeError):
                    event_date = None
            if event_date is None and start.get("dateTime"):
                try:
                    event_date = to_chicago_naive(
                        datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
                    )
                except (ValueError, TypeError):
                    event_date = None
            if event_date is None:
                return None

            # Discovery describes an event at three widths: segment ("Music"),
            # genre ("Jazz") and subGenre ("Big Band"). Only the segment was
            # read, which is why 572 events arrived as "Music" or
            # "Arts & Theatre" and nothing finer.
            #
            # The segment still decides the stored category, because it is the
            # one controlled value. Genre and subGenre become the
            # classification hint, where they do real work: a title is often
            # just a performer's name, and "Jazz" next to "Branford Marsalis"
            # is what earns it the Music label on its own merits rather than
            # by inheritance.
            # Every level can come back named "Undefined", which is Discovery's
            # placeholder for "we do not know" - not a category. Storing it
            # verbatim put 128 events in the UI under a filter tile labelled
            # "Undefined", so it is treated as absent at every level, here and
            # in the hint.
            category = "Other"
            category_hint = None
            classifications = data.get("classifications", [])
            if classifications:
                first = classifications[0] or {}
                segment_name = _meaningful((first.get("segment") or {}).get("name"))
                if segment_name:
                    category = segment_name
                hint_parts = [
                    _meaningful((first.get(level) or {}).get("name"))
                    for level in ("genre", "subGenre")
                ]
                category_hint = " ".join(p for p in hint_parts if p) or None

            # Deliberately not falling back to the venue's name as a hint. It
            # was tried: the concept matcher finds "Theatre" inside "Vic
            # Theatre" and files a live podcast recording as Theater. A venue
            # is mostly one kind of thing and not always, so it may inform the
            # default category but must never speak for an individual event.

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
            venue_name = None
            address = None
            latitude = None
            longitude = None
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

                # Street address and coordinates were previously folded into the
                # details blob and lost. They are what place an event in a
                # neighborhood, so keep them as structured fields.
                street = (venue.get("address") or {}).get("line1")
                address = ", ".join(p for p in (street, city, state) if p) or None

                coordinates = venue.get("location") or {}
                try:
                    latitude = float(coordinates["latitude"])
                    longitude = float(coordinates["longitude"])
                except (KeyError, TypeError, ValueError):
                    latitude = longitude = None

            details = " | ".join(details_parts) if details_parts else None

            # Extract cost and age_range from title and details
            cost, age_range = extract_from_event_text(title, details)

            # Discovery returns a structured priceRanges array. Prefer it over
            # whatever a title happens to mention: scanning text found a price
            # for only 40 of 591 stored events, while the API carries one for
            # most of them.
            api_cost = self._price_from_ranges(data.get("priceRanges"))
            if api_cost:
                cost = api_cost

            event = EventCreate(
                name=title,
                date=event_date,
                category=category,
                category_hint=category_hint,
                details=details,
                origination_url=url,
                venue_name=venue_name,
                address=address,
                latitude=latitude,
                longitude=longitude,
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

    @staticmethod
    def _price_from_ranges(price_ranges) -> Optional[str]:
        """Render Ticketmaster's priceRanges array as a displayable price.

        An event can carry several ranges (standard, VIP, resale), so the
        overall span is what gets shown. Only `standard` ticket types are
        considered where the type is given, since resale ranges can run far
        above what the event actually costs.
        """
        if not isinstance(price_ranges, list):
            return None

        values = []
        for entry in price_ranges:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") and entry["type"] != "standard":
                continue
            for key in ("min", "max"):
                try:
                    values.append(float(entry[key]))
                except (KeyError, TypeError, ValueError):
                    continue

        if not values:
            return None
        low, high = min(values), max(values)
        if low == 0 and high == 0:
            return "Free"

        def money(value: float) -> str:
            # Whole dollars read better without cents; 25.5 must not become
            # "$25.5", which looks like a truncation.
            return f"${value:.0f}" if value == int(value) else f"${value:.2f}"

        return money(low) if low == high else f"{money(low)}-{money(high)}"

    async def scrape_and_save(self, db: Union[Session, AsyncSession], days_ahead: int = 30) -> int:
        """Fetch and save events (sync or async)"""
        try:
            events = await self.fetch_events(days_ahead=days_ahead)
            saved_count = 0
            seen_urls = set()

            is_async = isinstance(db, AsyncSession)

            # Neighborhood boundaries come from our own tables and are read once
            # for the whole run, so placing each venue costs nothing further.
            boundaries = await load_boundaries(db) if is_async else {}
            neighborhood_ids: dict[str, Optional[int]] = {}

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
                    result = await db.execute(
                        select(EventModel).filter_by(origination_url=url)
                    )
                    existing = result.scalar_one_or_none()
                else:
                    # Sync query
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                # Place the venue by its coordinates, caching the id per
                # neighborhood so repeated venues cost one lookup in total.
                neighborhood_id = None
                if boundaries:
                    name = chicago_neighborhoods.locate_in(
                        event_data.latitude, event_data.longitude, boundaries
                    )
                    if name:
                        if name not in neighborhood_ids:
                            neighborhood_ids[name] = await resolve_neighborhood_id(db, name)
                        neighborhood_id = neighborhood_ids[name]

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="ticketmaster")
                    event.neighborhood_id = neighborhood_id
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()
                    # Refresh location on rows stored before these fields were
                    # captured, so existing events gain a neighborhood too.
                    if event_data.latitude is not None:
                        existing.latitude = event_data.latitude
                        existing.longitude = event_data.longitude
                    if event_data.address and not existing.address:
                        existing.address = event_data.address
                    if event_data.venue_name and not existing.venue_name:
                        existing.venue_name = event_data.venue_name
                    if neighborhood_id and not existing.neighborhood_id:
                        existing.neighborhood_id = neighborhood_id
                    # Backfill the price onto rows stored before priceRanges
                    # was read. Only ever filled in, never blanked out.
                    if event_data.cost:
                        existing.cost = event_data.cost

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
