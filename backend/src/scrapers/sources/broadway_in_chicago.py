"""Scraper for Broadway In Chicago, which programs five Loop-area theaters.

An external source rather than a venue scraper: one site carries the calendar
for CIBC Theatre, the James M. Nederlander, the Cadillac Palace, the Broadway
Playhouse and the Auditorium, none of which publish a usable calendar of their
own. The venue scrapers for CIBC and Nederlander were returning nothing for
exactly this reason.

Shows are runs, not single nights ("Sep 29 - Oct 11, 2026"), so each one is
stored with a date and a date_end and surfaces for any day in between.
"""

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.database.models import EventModel
from shared.geo.neighborhoods import resolve_neighborhood_id
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)

# Rows written before the lock is released. SQLite serializes writers, and
# these scrapers used to add several hundred events inside one transaction -
# which held the write lock for minutes and failed every `INSERT INTO
# chat_threads` a chat tried to make meanwhile, with "database is locked".
# Raising busy_timeout to 30s did not help: no wait beats a transaction held
# that long. Committing in batches does, by letting go between them.
WRITE_BATCH = 50


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class BroadwayInChicagoScraper:
    """Scrape the Broadway In Chicago season listing."""

    SHOWS_URL = "https://www.broadwayinchicago.com/shows/"
    REQUEST_TIMEOUT = 30000

    # The theatre name printed on each card is the only location signal the
    # listing gives, so it is mapped to the address and neighborhood here.
    THEATRES = {
        "cibc theatre": ("CIBC Theatre", "18 W Monroe St", "Loop"),
        "james m. nederlander theatre": (
            "James M. Nederlander Theatre",
            "24 W Randolph St",
            "Loop",
        ),
        "nederlander theatre": ("James M. Nederlander Theatre", "24 W Randolph St", "Loop"),
        "cadillac palace theatre": ("Cadillac Palace Theatre", "151 W Randolph St", "Loop"),
        # 175 E Chestnut is in Streeterville; "Near North Side" is a
        # community area the city's neighborhood layer does not publish, so
        # nothing could ever be placed there by point-in-polygon.
        "broadway playhouse at water tower place": (
            "Broadway Playhouse",
            "175 E Chestnut St",
            "Streeterville",
        ),
        "broadway playhouse": ("Broadway Playhouse", "175 E Chestnut St", "Streeterville"),
        "auditorium theatre": ("Auditorium Theatre", "50 E Ida B Wells Dr", "Loop"),
    }

    # "Sep 8 - Nov 8, 2026" and "Oct 13 - Oct 18, 2026". The trailing year
    # belongs to the end of the run; a run whose end month precedes its start
    # month crosses New Year, so the start is a year earlier.
    _RUN_RE = re.compile(
        r"(?P<m1>[A-Za-z]{3,9})\.?\s+(?P<d1>\d{1,2})\s*[–—-]\s*"
        r"(?:(?P<m2>[A-Za-z]{3,9})\.?\s+)?(?P<d2>\d{1,2}),?\s*(?P<y>\d{4})"
    )

    async def fetch_events(self) -> list[EventCreate]:
        """Fetch the current season's shows."""
        try:
            html = await self._fetch_html()
            if not html:
                return []
            return self._parse(html)
        except Exception as exc:
            logger.error(f"Broadway In Chicago fetch failed: {exc}")
            return []

    async def _fetch_html(self) -> str | None:
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
                await page.goto(
                    self.SHOWS_URL, timeout=self.REQUEST_TIMEOUT, wait_until="domcontentloaded"
                )
                await page.wait_for_timeout(4000)
                # Cards below the fold are deferred until scrolled to.
                for _ in range(4):
                    await page.mouse.wheel(0, 1600)
                    await page.wait_for_timeout(800)
                return await page.content()
            finally:
                await browser.close()

    def _parse(self, html: str) -> list[EventCreate]:
        soup = BeautifulSoup(html, "html.parser")
        events = []
        seen = set()

        for link in soup.select('a[href*="/shows/"]'):
            href = link.get("href") or ""
            # Skip the index and any anchor that isn't a show page.
            if href.rstrip("/").endswith("/shows"):
                continue

            # The date, title and theatre sit in the card around the link.
            card = link
            for _ in range(4):
                if card.parent is None:
                    break
                card = card.parent
                text = card.get_text("\n", strip=True)
                if self._RUN_RE.search(" ".join(text.split("\n"))):
                    break
            else:
                continue

            lines = [l.strip() for l in card.get_text("\n", strip=True).split("\n") if l.strip()]
            run = self._RUN_RE.search(" ".join(lines))
            if not run:
                continue

            dates = self._parse_run(run)
            if not dates:
                continue
            start, end = dates

            theatre = next(
                (self.THEATRES[l.lower()] for l in lines if l.lower() in self.THEATRES), None
            )
            title = self._title(lines, theatre)
            if not title:
                continue

            url = href if href.startswith("http") else f"https://www.broadwayinchicago.com{href}"
            if url in seen:
                continue
            seen.add(url)

            venue_name, address, _ = theatre or (None, None, None)
            events.append(
                EventCreate(
                    name=title[:200],
                    date=start,
                    date_end=end,
                    category="theater",
                    origination_url=url,
                    venue_name=venue_name,
                    address=f"{venue_name}, {address}, Chicago, IL" if venue_name else None,
                )
            )

        logger.info(f"Broadway In Chicago: parsed {len(events)} shows")
        return events

    def _parse_run(self, run: re.Match) -> tuple[datetime, datetime] | None:
        start_month = _MONTHS.get(run.group("m1")[:3].lower())
        end_month = _MONTHS.get((run.group("m2") or run.group("m1"))[:3].lower())
        if not start_month or not end_month:
            return None
        end_year = int(run.group("y"))
        start_year = end_year - 1 if end_month < start_month else end_year
        try:
            return (
                datetime(start_year, start_month, int(run.group("d1"))),
                datetime(end_year, end_month, int(run.group("d2"))),
            )
        except ValueError:
            return None

    def _title(self, lines: list[str], theatre) -> str | None:
        """The title is the line that is neither the date, the theatre nor a CTA."""
        theatre_name = theatre[0].lower() if theatre else None
        for line in lines:
            low = line.lower()
            if low in self.THEATRES or (theatre_name and low == theatre_name):
                continue
            if low.startswith(
                (
                    "show and ticket",
                    "buy tickets",
                    "tickets",
                    "learn more",
                    "more info",
                    "group",
                    "info",
                )
            ):
                continue
            # Date fragments: "Sep 8", "-", "Nov 8, 2026".
            if re.fullmatch(r"[–—-]", line):
                continue
            if re.fullmatch(r"[A-Za-z]{3,9}\.?\s+\d{1,2},?\s*(\d{4})?", line):
                continue
            if len(line) >= 3:
                return line
        return None

    async def scrape_and_save(self, db: Session | AsyncSession) -> int:
        """Fetch and save shows, skipping any already stored."""
        try:
            events = await self.fetch_events()
            saved_count = 0
            is_async = isinstance(db, AsyncSession)
            neighborhood_ids: dict[str, int | None] = {}

            # The theatre name gives the neighborhood directly, so there is no
            # geocoding step here as there is for coordinate-based sources.
            by_venue = {name: hood for name, _, hood in self.THEATRES.values()}

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
                if is_async:
                    result = await db.execute(select(EventModel).filter_by(origination_url=url))
                    existing = result.scalar_one_or_none()
                else:
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                neighborhood_id = None
                hood = by_venue.get(event_data.venue_name or "")
                if hood and is_async:
                    if hood not in neighborhood_ids:
                        neighborhood_ids[hood] = await resolve_neighborhood_id(db, hood)
                    neighborhood_id = neighborhood_ids[hood]

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="broadway_in_chicago")
                    event.neighborhood_id = neighborhood_id
                    db.add(event)
                    saved_count += 1
                else:
                    # Runs get extended and venues get reassigned mid-season,
                    # so refresh those without touching anything else.
                    existing.date_retrieved = datetime.utcnow()
                    existing.date = event_data.date
                    existing.date_end = event_data.date_end
                    if event_data.venue_name and not existing.venue_name:
                        existing.venue_name = event_data.venue_name
                    if event_data.address and not existing.address:
                        existing.address = event_data.address
                    if neighborhood_id and not existing.neighborhood_id:
                        existing.neighborhood_id = neighborhood_id

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from Broadway In Chicago")
            return saved_count

        except Exception as exc:
            logger.error(f"Broadway In Chicago save error: {exc}")
            if isinstance(db, AsyncSession):
                await db.rollback()
            else:
                db.rollback()
            return 0
