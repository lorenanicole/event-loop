"""The Mahjong Society Chicago event scraper.

Squarespace-powered site — fully server-side rendered. Events live at
https://themahjongsociety.com/event-calendar as ``article.eventlist-event``
elements. Each contains:

  - ``.eventlist-title a``          — event title + relative URL
  - ``time.event-date``             — ``datetime="YYYY-MM-DD"``
  - ``time.event-time-localized-start`` — start time text "6:30 PM"
  - ``time.event-time-localized-end``   — end time text "8:30 PM"
  - ``.eventlist-meta-address``     — venue name
  - ``.eventlist-excerpt``          — description snippet

All events are in the Chicago area; no city filter needed.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import EventModel
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)

BASE_URL = "https://themahjongsociety.com"
LISTING_URL = f"{BASE_URL}/event-calendar"
SOURCE = "mahjongsociety"
REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _parse_card(article) -> Optional[EventCreate]:
    """Parse one ``article.eventlist-event`` into an EventCreate."""
    # Title + URL
    title_a = article.select_one(".eventlist-title a")
    if not title_a:
        return None
    title = title_a.get_text(strip=True)
    href = title_a.get("href", "")
    url = href if href.startswith("http") else f"{BASE_URL}{href}"

    # Date from <time class="event-date" datetime="YYYY-MM-DD">
    date_el = article.select_one("time.event-date")
    if not date_el or not date_el.get("datetime"):
        return None
    try:
        base_date = datetime.strptime(date_el["datetime"], "%Y-%m-%d")
    except ValueError:
        return None

    # Start/end times
    def _parse_time(el) -> Optional[datetime]:
        if not el:
            return None
        text = el.get_text(strip=True)  # "6:30 PM"
        for fmt in ("%I:%M %p", "%I %p"):
            try:
                t = datetime.strptime(text, fmt)
                return base_date.replace(hour=t.hour, minute=t.minute)
            except ValueError:
                continue
        return None

    start = _parse_time(article.select_one("time.event-time-localized-start"))
    end = _parse_time(article.select_one("time.event-time-localized-end"))
    date_start = start or base_date

    # Venue
    venue_el = article.select_one(".eventlist-meta-address")
    venue = venue_el.get_text(strip=True).replace("(map)", "").strip() if venue_el else None

    # Description
    desc_el = article.select_one(".eventlist-excerpt")
    description = desc_el.get_text(" ", strip=True) if desc_el else None

    return EventCreate(
        name=title,
        date=date_start,
        date_end=end,
        category="Community",
        categories=["Community", "Arts"],
        subcategories=["Games & Social", "Classes & Workshops"],
        details=description,
        origination_url=url,
        source=SOURCE,
        is_outdoor="indoor",
        address="Chicago, IL",
        venue_name=venue,
    )


class MahjongSocietyScraper:
    """Scrapes The Mahjong Society Chicago upcoming events."""

    async def fetch_events(self) -> list[EventCreate]:
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                resp = await client.get(LISTING_URL)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("MahjongSociety: HTTP error: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.select("article.eventlist-event")
        logger.info("MahjongSociety: found %d event cards", len(articles))

        events: list[EventCreate] = []
        for art in articles:
            ev = _parse_card(art)
            if ev:
                events.append(ev)

        logger.info("MahjongSociety: parsed %d events", len(events))
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
        logger.info("MahjongSociety: saved %d new events", saved)
        return saved
