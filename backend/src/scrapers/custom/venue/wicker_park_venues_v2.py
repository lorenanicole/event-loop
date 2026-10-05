"""
Wicker Park venues - flexible config-driven scraping.
Uses VenueScraper framework for extensibility.
"""

import httpx
import logging
from .venue_scraper import VenueScraper, VenueConfig, VenueEvent
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)


def extract_chop_shop(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract Chop Shop events from Dice FM widget."""
    events = []
    try:
        # Chop Shop uses Dice FM widget
        dice_container = soup.select_one("div.dice_events")
        if not dice_container:
            logger.debug("Chop Shop: dice_events container not found")
            return events

        event_articles = dice_container.select("article")
        logger.info(f"Chop Shop: found {len(event_articles)} event articles")

        for article in event_articles:
            try:
                title_link = article.select_one("a.dice_event-title")
                if not title_link:
                    continue

                event_name = title_link.get_text(strip=True)
                if not event_name or len(event_name) < 2:
                    continue

                ticket_link = article.find("a", href=lambda x: x and "link.dice.fm" in x)
                if not ticket_link:
                    ticket_link = title_link
                ticket_url = ticket_link.get("href", config.website_url) if ticket_link else config.website_url

                events.append(VenueEvent(
                    name=event_name,
                    date=None,
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=ticket_url,
                    venue_name=config.name,
                    category=config.category
                ))
            except Exception as e:
                logger.debug(f"Chop Shop: failed to parse article: {e}")

        logger.info(f"Chop Shop: extracted {len(events)} events")

    except Exception as e:
        logger.error(f"Chop Shop extraction failed: {e}")

    return events


def extract_rosas_lounge(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract Rosa's Lounge events from calendar page."""
    events = []
    try:
        containers = soup.select("article, [class*='event'], [class*='show']")
        logger.info(f"Rosa's Lounge: found {len(containers)} containers")

        for container in containers:
            text = container.get_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]

            if not lines:
                continue

            event_name = None
            event_date = None

            for line in lines:
                if len(line) > 3 and not any(x in line for x in ['ticket', 'door', 'age']):
                    event_name = line
                    break

            for line in lines:
                if re.search(r'\d{1,2}/\d{1,2}|January|February|March|April|May|June|July|August|September|October|November|December', line):
                    event_date = line
                    break

            if event_name and len(event_name) > 3:
                events.append(VenueEvent(
                    name=event_name,
                    date=event_date,
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url,
                    venue_name=config.name,
                    category=config.category
                ))

        logger.info(f"Rosa's Lounge: extracted {len(events)} events")

    except Exception as e:
        logger.error(f"Rosa's Lounge extraction failed: {e}")

    return events


# Wicker Park venues with their scraping configs
WICKER_PARK_VENUES = [
    VenueConfig(
        name="Subterranean",
        website_url="https://www.subt.net",
        event_page_url="https://subt.net/",
        category="music",
        address="2011 W North Ave",
        selectors={
            "event_container": "li.seetickets-list-event-container",
            "title": "p.event-title a",
            "date": "p.event-date",
            "time": "span.event-time",
        }
    ),
    VenueConfig(
        name="Chop Shop",
        website_url="https://chopshopchi.com",
        event_page_url="https://chopshopchi.com/calendar/index.html",
        category="music",
        address="2033 W North Ave",
        selectors={},
        use_playwright=True,
        extractor_fn=extract_chop_shop,
    ),
    VenueConfig(
        name="Empty Bottle",
        website_url="https://www.emptybottle.com",
        event_page_url="https://www.emptybottle.com/",
        category="music",
        address="1035 N Western Ave",
        selectors={
            "event_container": ".show-details",
            "title": "div.title",
            "date": "div.date",
            "time": "div.start-time",
        },
        use_playwright=True,
    ),
    VenueConfig(
        name="Den Theatre",
        website_url="https://www.dentheatre.com",
        event_page_url="https://thedentheatre.com/calendar?view=calendar&month=10-2026",
        category="comedy",
        address="1331 N Milwaukee Ave",
        selectors={
            "event_container": "li.item",
            "title": "span.item-title",
            "time": "span.item-time--12hr",
        },
        use_playwright=True,
    ),
    VenueConfig(
        name="Rosa's Lounge",
        website_url="https://www.rosaslounge.com",
        event_page_url="https://www.rosaslounge.com/calendar",
        category="music",
        address="3420 W North Ave",
        selectors={},
        use_playwright=True,
        extractor_fn=extract_rosas_lounge,
    ),
]


async def scrape_wicker_park_venues() -> list[VenueEvent]:
    """Scrape all Wicker Park venues using flexible framework."""
    all_events = []
    
    async with httpx.AsyncClient(timeout=15) as client:
        for config in WICKER_PARK_VENUES:
            try:
                scraper = VenueScraper(config)
                events = await scraper.scrape(client)
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Error scraping {config.name}: {e}")

    logger.info(f"Total Wicker Park events: {len(all_events)}")
    return all_events
