"""Illinois Science Council event scraper.

Uses The Events Calendar (WordPress plugin) at https://www.illinoisscience.org/events/
The calendar loads events via JS, so Playwright is required to wait for the
tribe-events list to populate.

Each event article has class ``tribe-events-calendar-list__event-article`` with:
  - ``.tribe-event-url``                       — event URL
  - ``.tribe-events-calendar-list__event-title`` — title
  - ``time.tribe-events-calendar-list__event-datetime-wrapper-start``
    ``datetime`` attribute — ISO start datetime
  - ``time[datetime]`` (end)                   — ISO end datetime
  - ``.tribe-venue``                            — venue name
  - ``.tribe-address``                          — address
  - ``.tribe-events-calendar-list__event-description`` — description
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import to_naive_utc
from shared.database.models import EventModel
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)

LISTING_URL = "https://www.illinoisscience.org/events/"
SOURCE = "illinoisscience"


def _parse_article(article) -> Optional[EventCreate]:
    """Parse one tribe-events article element."""

    # Title + URL
    title_el = article.select_one(".tribe-events-calendar-list__event-title a")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    url = title_el.get("href", "").strip()
    if not url:
        return None

    # Start datetime
    start_time_el = article.select_one("time[datetime]")
    if not start_time_el or not start_time_el.get("datetime"):
        return None
    try:
        date_start = to_naive_utc(datetime.fromisoformat(start_time_el["datetime"]))
    except ValueError:
        return None

    # End datetime (second time element if present)
    times = article.select("time[datetime]")
    date_end = None
    if len(times) > 1:
        try:
            date_end = to_naive_utc(datetime.fromisoformat(times[1]["datetime"]))
        except ValueError:
            pass

    # Venue / address
    venue_el = article.select_one(".tribe-venue")
    venue = venue_el.get_text(strip=True) if venue_el else None
    addr_el = article.select_one(".tribe-address")
    address = addr_el.get_text(" ", strip=True) if addr_el else "Chicago, IL"

    # Cost from title/description
    desc_el = article.select_one(".tribe-events-calendar-list__event-description")
    description = desc_el.get_text(" ", strip=True) if desc_el else None

    return EventCreate(
        name=title,
        date=date_start,
        date_end=date_end,
        category="Community",
        categories=["Community", "Tech"],
        subcategories=["Science & Tech", "Classes & Workshops"],
        details=description,
        origination_url=url,
        source=SOURCE,
        is_outdoor="indoor",
        address=address or "Chicago, IL",
        venue_name=venue,
    )


class IllinoisScienceScraper:
    """Scrapes Illinois Science Council upcoming events via Playwright."""

    async def fetch_events(self) -> list[EventCreate]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("IllinoisScience: playwright not installed")
            return []

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(LISTING_URL, wait_until="networkidle", timeout=30_000)

                # Wait for tribe events to load (or confirm empty)
                try:
                    await page.wait_for_selector(
                        ".tribe-events-calendar-list__event-article, .tribe-events-c-messages__message--notice",
                        timeout=15_000,
                    )
                except Exception:
                    pass  # proceed with whatever is on the page

                html = await page.content()
                await browser.close()
        except Exception as exc:
            logger.error("IllinoisScience fetch failed: %s", exc)
            return []

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select(".tribe-events-calendar-list__event-article")
        logger.info("IllinoisScience: found %d event articles", len(articles))

        events: list[EventCreate] = []
        for art in articles:
            ev = _parse_article(art)
            if ev:
                events.append(ev)

        logger.info("IllinoisScience: parsed %d events", len(events))
        return events

    async def scrape_and_save(self, db: AsyncSession) -> int:
        events = await self.fetch_events()
        saved = 0
        for ev in events:
            existing = await db.scalar(
                select(EventModel).where(EventModel.origination_url == ev.origination_url)
            )
            if existing:
                existing.date_retrieved = datetime.now().replace(tzinfo=None)
                continue
            db.add(EventModel(**ev.model_dump(), source=SOURCE))
            saved += 1
        if events:
            await db.commit()
        logger.info("IllinoisScience: saved %d new events", saved)
        return saved
