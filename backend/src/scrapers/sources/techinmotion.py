"""Tech in Motion Chicago event scraper.

Tech in Motion posts upcoming events at https://techinmotion.com/upcoming-events
as server-side-rendered HTML — no JS execution needed.  Each event card is an
``<a class="upcoming-events-card">`` element containing:

  - ``<p class="upcoming-events-card-title">``  — event title
  - Three ``<p class="font-sans text-[#4A5B6E] …">`` paragraphs — date, time,
    location (in that order)
  - ``<p class="font-sans text-sm font-light">``  — short description
  - ``href``  — landing URL on events.techinmotion.com (redirects to Eventbrite)

Only Chicago in-person events are ingested; virtual events are skipped.
"""

import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import EventModel
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)

LISTING_URL = "https://techinmotion.com/upcoming-events"
SOURCE = "techinmotion"
REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Tailwind classes shared by the date/time/location <p> elements
_META_P_CLASSES = {"font-sans", "text-2xs", "font-medium", "uppercase"}
_CHICAGO_ADDRESS = "Chicago, IL"


def _parse_date_time(date_str: str, time_str: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse 'Thursday | October 22, 2026' + '6 00 PM - 9 00 PM UTC' into datetimes."""
    date_str = re.sub(r"^[A-Za-z]+\s*\|\s*", "", date_str).strip()

    def normalise_time(t: str) -> str:
        return re.sub(r"(\d+)\s+(\d{2})", r"\1:\2", t.strip())

    try:
        date = datetime.strptime(date_str, "%B %d, %Y")
    except ValueError:
        logger.debug("TechInMotion: cannot parse date %r", date_str)
        return None, None

    date_start = date_end = None
    time_str = time_str.replace("UTC", "").strip()
    parts = [p.strip() for p in time_str.split("-")]
    if parts:
        try:
            start_t = datetime.strptime(normalise_time(parts[0]), "%I:%M %p")
            date_start = date.replace(hour=start_t.hour, minute=start_t.minute)
        except ValueError:
            date_start = date
    if len(parts) >= 2:
        try:
            end_t = datetime.strptime(normalise_time(parts[1]), "%I:%M %p")
            date_end = date.replace(hour=end_t.hour, minute=end_t.minute)
        except ValueError:
            pass

    return date_start, date_end


def _parse_card(card) -> Optional[EventCreate]:
    """Parse one ``<a class='upcoming-events-card'>`` into an EventCreate."""
    url = card.get("href", "").strip()
    if not url:
        return None

    title_el = card.select_one("p.upcoming-events-card-title")
    title = title_el.get_text(strip=True) if title_el else None
    if not title:
        return None

    meta_ps = [p for p in card.find_all("p") if _META_P_CLASSES.issubset(set(p.get("class", [])))]
    date_str = meta_ps[0].get_text(strip=True) if len(meta_ps) > 0 else ""
    time_str = meta_ps[1].get_text(strip=True) if len(meta_ps) > 1 else ""
    location = meta_ps[2].get_text(strip=True) if len(meta_ps) > 2 else ""

    if location.lower() in ("virtual", "online", ""):
        logger.debug("TechInMotion: skipping virtual event %r", title)
        return None
    if location and "chicago" not in location.lower():
        logger.debug("TechInMotion: skipping non-Chicago event %r (location=%r)", title, location)
        return None

    date_start, date_end = _parse_date_time(date_str, time_str)
    if not date_start:
        logger.debug("TechInMotion: skipping %r — could not parse date", title)
        return None

    desc_el = card.select_one("p.font-sans.text-sm.font-light")
    description = desc_el.get_text(strip=True) if desc_el else None

    return EventCreate(
        name=title,
        date=date_start,
        date_end=date_end,
        category="Tech",
        categories=["Tech", "Community"],
        subcategories=["Science & Tech"],
        details=description,
        origination_url=url,
        source=SOURCE,
        is_outdoor="indoor",
        address=_CHICAGO_ADDRESS,
        venue_name=None,
    )


class TechInMotionScraper:
    """Scrapes Tech in Motion Chicago upcoming events."""

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
            logger.error("TechInMotion: HTTP error fetching listing: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("a.upcoming-events-card")
        logger.info("TechInMotion: found %d cards on listing page", len(cards))

        events: list[EventCreate] = []
        for card in cards:
            event = _parse_card(card)
            if event:
                events.append(event)

        logger.info("TechInMotion: parsed %d Chicago in-person events", len(events))
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

        logger.info("TechInMotion: saved %d new events", saved)
        return saved
