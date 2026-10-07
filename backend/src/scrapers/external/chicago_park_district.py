"""Scraper for Chicago Park District events.

The Park District is the broadest single source of events on the South and West
Sides, where commercial venues are thin on the ground: the South Shore Cultural
Center's theater, La Villita Park in Little Village, Eugene Field Park in
Albany Park. None of these publish a calendar anywhere else.

Each card carries a street address, so events are placed by point-in-polygon
against the neighborhood boundaries already in the database - no geocoding.
"""

import logging
import re
from datetime import datetime
from typing import Optional, Union

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.database.models import EventModel
from shared.database.neighborhoods import load_boundaries, resolve_neighborhood_id
from shared.geo import resolve_neighborhood
from shared.models import EventCreate

logger = logging.getLogger(__name__)


class ChicagoParkDistrictScraper:
    """Scrape the Park District's citywide events listing."""

    BASE_URL = "https://www.chicagoparkdistrict.com"
    EVENTS_URL = f"{BASE_URL}/events"
    REQUEST_TIMEOUT = 30000
    # The listing is paged; stop early when a page yields nothing new.
    MAX_PAGES = 47

    async def fetch_events(self) -> list[EventCreate]:
        """Fetch events across all pages of the listing."""
        events: list[EventCreate] = []
        seen: set[str] = set()
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True, args=["--disable-blink-features=AutomationControlled"]
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1512, "height": 1000},
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/129.0.0.0 Safari/537.36"
                        ),
                        locale="en-US",
                        timezone_id="America/Chicago",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )
                    await context.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                    )
                    page = await context.new_page()

                    for page_number in range(self.MAX_PAGES):
                        url = f"{self.EVENTS_URL}?page={page_number}"
                        await page.goto(
                            url, timeout=self.REQUEST_TIMEOUT, wait_until="domcontentloaded"
                        )
                        await page.wait_for_timeout(3500)
                        # Cards below the fold render on scroll.
                        for _ in range(3):
                            await page.mouse.wheel(0, 1600)
                            await page.wait_for_timeout(500)

                        found = self._parse(await page.content())
                        fresh = [e for e in found if e.origination_url not in seen]
                        if not fresh:
                            break
                        seen.update(e.origination_url for e in fresh)
                        events.extend(fresh)
                finally:
                    await browser.close()

        except Exception as exc:
            logger.error(f"Chicago Park District fetch failed: {exc}")

        logger.info(f"Chicago Park District: parsed {len(events)} events")
        return events

    def _parse(self, html: str) -> list[EventCreate]:
        soup = BeautifulSoup(html, "html.parser")
        events = []

        for row in soup.select(".views-row"):
            card = row.select_one(".node--type-event") or row
            title_elem = card.select_one(".event--title")
            if not title_elem:
                continue
            title = title_elem.get_text(" ", strip=True)
            if not title:
                continue

            # Dates come from three places depending on the card. Multi-day
            # events print a full "April 25, 2026 - October 31, 2026" in the
            # duration; single-day events print only clock times there and put
            # a yearless "Oct 7" in .event--date. <time datetime> exists on a
            # minority of cards and is the last resort.
            duration_elem = card.select_one(".event--duration")
            duration_text = duration_elem.get_text(" ", strip=True) if duration_elem else ""
            start, end = self._dates_from_text(duration_text)

            if not start:
                date_elem = card.select_one(".event--date")
                if date_elem:
                    start, end = self._dates_from_short(date_elem.get_text(" ", strip=True))

            if not start:
                stamps = sorted(
                    d for d in (self._parse_iso(t.get("datetime"))
                                for t in card.select("time[datetime]")) if d
                )
                if not stamps:
                    continue
                start = stamps[0]
                end = stamps[-1] if stamps[-1] != start else None

            location = card.select_one(".event--location")
            # The address renders across several lines, so collapse whitespace.
            address = " ".join(location.get_text(" ", strip=True).split()) if location else None

            link = card.select_one("a[href]")
            href = link["href"] if link else "/events"
            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            clock = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)", duration_text)

            events.append(EventCreate(
                name=title[:200],
                date=start,
                date_end=end,
                time=clock.group(1).upper().replace(".", "") if clock else None,
                category="community",
                origination_url=url,
                venue_name=self._venue_from_title(title),
                address=address,
            ))

        return events

    # "April 25, 2026 - October 31, 2026", or a single "October 8, 2026".
    _FULL_DATE_RE = re.compile(r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s*(\d{4})")

    @classmethod
    def _dates_from_text(cls, text: str) -> tuple[Optional[datetime], Optional[datetime]]:
        """Read the start and, for a run, the end out of the printed duration."""
        found = []
        for match in cls._FULL_DATE_RE.finditer(text or ""):
            for fmt in ("%B", "%b"):
                try:
                    month = datetime.strptime(match.group(1)[:9], fmt).month
                except ValueError:
                    continue
                try:
                    found.append(datetime(int(match.group(3)), month, int(match.group(2))))
                except ValueError:
                    pass
                break

        if not found:
            return None, None
        found.sort()
        return found[0], (found[-1] if found[-1] != found[0] else None)

    # Yearless: "Oct 7", or a run as "Apr 25 - Oct 31".
    _SHORT_DATE_RE = re.compile(r"([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2})")

    @classmethod
    def _dates_from_short(
        cls, text: str, today: Optional[datetime] = None
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """Read yearless dates, inferring the year.

        The listing only shows current and upcoming events, so a month earlier
        than this one belongs to next year.
        """
        today = today or datetime.now()
        parts = []
        for match in cls._SHORT_DATE_RE.finditer(text or ""):
            try:
                parts.append((datetime.strptime(match.group(1), "%b").month,
                              int(match.group(2))))
            except ValueError:
                continue
        if not parts:
            return None, None

        def build(month: int, day: int, year: int) -> Optional[datetime]:
            try:
                return datetime(year, month, day)
            except ValueError:
                return None

        if len(parts) == 1 or parts[0] == parts[-1]:
            month, day = parts[0]
            year = today.year + 1 if month < today.month else today.year
            return build(month, day, year), None

        # A run is anchored on its end: "Apr 25 - Oct 31" read in October is an
        # event already under way, not one starting next April.
        (start_month, start_day), (end_month, end_day) = parts[0], parts[-1]
        end_year = today.year + 1 if end_month < today.month else today.year
        start_year = end_year if start_month <= end_month else end_year - 1
        return build(start_month, start_day, start_year), build(end_month, end_day, end_year)

    @staticmethod
    def _parse_iso(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            # "2026-10-31T18:00:00Z"; stored naive to match the other sources.
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _venue_from_title(title: str) -> Optional[str]:
        """Park names are written into the title, as "... at Austin TH"."""
        match = re.search(r"\bat\s+([A-Z][\w'.\-]*(?:\s+[A-Z][\w'.\-]*){0,4})\s*$", title)
        return match.group(1).strip() if match else None

    async def scrape_and_save(self, db: Union[Session, AsyncSession]) -> int:
        """Fetch and save events, placing each one by its street address."""
        try:
            events = await self.fetch_events()
            saved_count = 0
            is_async = isinstance(db, AsyncSession)

            boundaries = await load_boundaries(db) if is_async else {}
            neighborhood_ids: dict[str, Optional[int]] = {}

            for event_data in events:
                url = event_data.origination_url
                if is_async:
                    result = await db.execute(select(EventModel).filter_by(origination_url=url))
                    existing = result.scalar_one_or_none()
                else:
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                neighborhood_id = None
                if boundaries and event_data.address:
                    # Place from the geocode cache and known venues only.
                    # Geocoding is rate limited to one request a minute, so
                    # doing it inline here would take hours for a few hundred
                    # park addresses and block the whole save. Run
                    # `backfill_neighborhoods.py --geocode` afterwards to place
                    # whatever is left, which is what that script is for.
                    name, latitude, longitude = await resolve_neighborhood(
                        db,
                        boundaries,
                        address=event_data.address,
                        venue_name=event_data.venue_name,
                        allow_network=False,
                    )
                    if latitude is not None and event_data.latitude is None:
                        event_data.latitude = latitude
                        event_data.longitude = longitude
                    if name:
                        if name not in neighborhood_ids:
                            neighborhood_ids[name] = await resolve_neighborhood_id(db, name)
                        neighborhood_id = neighborhood_ids[name]

                if not existing:
                    event = EventModel(
                        **event_data.model_dump(), source="chicago_park_district"
                    )
                    event.neighborhood_id = neighborhood_id
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()
                    existing.date = event_data.date
                    existing.date_end = event_data.date_end
                    if event_data.address and not existing.address:
                        existing.address = event_data.address
                    if neighborhood_id and not existing.neighborhood_id:
                        existing.neighborhood_id = neighborhood_id

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from Chicago Park District")
            return saved_count

        except Exception as exc:
            logger.error(f"Chicago Park District save error: {exc}")
            if isinstance(db, AsyncSession):
                await db.rollback()
            else:
                db.rollback()
            return 0
