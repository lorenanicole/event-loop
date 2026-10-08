"""Cuddle Bunny CCC event scraper.

Cuddle Bunny (https://cuddlebunnyccc.com/events-calendar) is a rabbit
café in Chicago's Lakeview neighborhood. The site renders event cards
via JS (Webflow/custom CMS). Playwright is required.

Each event appears twice (collapsed + expanded), so we de-duplicate by
title+date. No per-event URLs exist; all events link to the calendar page.

Block structure after render:
  <h3 class="x-el-h3">Oct 14th</h3>   — date (year inferred)
  <h4 class="x-el-h4">Sketch-a-Bun…</h4>  — title
  spans containing "7:00 PM - 8:00 PM"     — time range
  longer span                               — description excerpt
"""

import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import EventModel
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)

LISTING_URL = "https://cuddlebunnyccc.com/events-calendar"
SOURCE = "cuddlebunny"
VENUE_ADDRESS = "3729 N Southport Ave, Chicago, IL 60613"
VENUE_NAME = "Cuddle Bunny CCC"

_MONTH_ABBREVS = {
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
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*(?:AM|PM))\s*-\s*(\d{1,2}:\d{2}\s*(?:AM|PM))", re.I)


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse 'Oct 14th' → datetime. Year = current, or next year if date is past."""
    date_str = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", date_str).strip()
    for abbr, month_num in _MONTH_ABBREVS.items():
        if abbr in date_str.lower():
            m = re.search(r"\d+", date_str)
            if not m:
                return None
            try:
                day = int(m.group())
            except ValueError:
                return None
            now = datetime.now()
            candidate = datetime(now.year, month_num, day)
            if candidate.date() < now.date():
                candidate = datetime(now.year + 1, month_num, day)
            return candidate
    return None


def _parse_time(base: datetime, time_str: str) -> Optional[datetime]:
    for fmt in ("%I:%M %p", "%I:%M%p"):
        try:
            t = datetime.strptime(time_str.strip(), fmt)
            return base.replace(hour=t.hour, minute=t.minute)
        except ValueError:
            continue
    return None


def _parse_block(date_h3) -> Optional[EventCreate]:
    """Extract one event from an h3 date element and its surrounding block."""
    date_text = date_h3.get_text(strip=True)
    if not any(m in date_text.lower() for m in _MONTH_ABBREVS):
        return None
    base_date = _parse_date(date_text)
    if not base_date:
        return None

    # Walk up to the enclosing block that also contains the h4 title
    container = date_h3.parent
    for _ in range(8):
        h4 = container.find("h4", class_="x-el-h4")
        if h4:
            break
        container = container.parent
    else:
        return None

    title = h4.get_text(strip=True) if h4 else None
    if not title:
        return None

    block_text = container.get_text(" ", strip=True)
    time_match = _TIME_RE.search(block_text)
    date_start = date_end = None
    if time_match:
        date_start = _parse_time(base_date, time_match.group(1))
        date_end = _parse_time(base_date, time_match.group(2))
    date_start = date_start or base_date

    # Longest span that is not a time/nav label
    description = None
    for span in container.find_all("span", class_="x-el-span"):
        text = span.get_text(strip=True)
        if len(text) > 40 and "PM" not in text and "AM" not in text and "Event" not in text:
            description = text[:500]
            break

    # No per-event page — use title+date as a stable slug for the URL key
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    url = f"{LISTING_URL}#{slug}-{base_date.strftime('%Y%m%d')}"

    return EventCreate(
        name=title,
        date=date_start,
        date_end=date_end,
        category="Community",
        categories=["Community", "Arts"],
        subcategories=["Animals & Pets", "Classes & Workshops"],
        details=description,
        origination_url=url,
        source=SOURCE,
        is_outdoor="indoor",
        address=VENUE_ADDRESS,
        venue_name=VENUE_NAME,
    )


class CuddleBunnyScraper:
    """Scrapes Cuddle Bunny CCC public events via Playwright."""

    async def fetch_events(self) -> list[EventCreate]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("CuddleBunny: playwright not installed")
            return []

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(LISTING_URL, wait_until="load", timeout=30_000)
                await page.wait_for_timeout(5_000)
                html = await page.content()
                await browser.close()
        except Exception as exc:
            logger.error("CuddleBunny fetch failed: %s", exc)
            return []

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        seen: set[tuple[str, str]] = set()
        events: list[EventCreate] = []

        date_h3s = [
            h
            for h in soup.find_all("h3", class_="x-el-h3")
            if any(m in h.get_text().lower() for m in _MONTH_ABBREVS)
        ]
        logger.info("CuddleBunny: found %d date headers", len(date_h3s))

        for h3 in date_h3s:
            ev = _parse_block(h3)
            if not ev:
                continue
            key = (ev.name, ev.date.strftime("%Y%m%d"))
            if key in seen:
                continue
            seen.add(key)
            events.append(ev)

        logger.info("CuddleBunny: parsed %d unique events", len(events))
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
        logger.info("CuddleBunny: saved %d new events", saved)
        return saved
