"""
Unified Chicago Events Scraper - ALL neighborhoods/venues in one place.
Strategic, config-driven approach using flexible VenueScraper framework.
Scales to all 77+ neighborhoods without N+1 scripts.
"""

import httpx
import logging
from dataclasses import dataclass
from typing import Optional, Callable
from bs4 import BeautifulSoup
from src.scrapers.venue_scraper import VenueScraper, VenueConfig, VenueEvent
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== CUSTOM EXTRACTORS =====

def extract_chop_shop(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Dice FM widget extraction for Chop Shop."""
    events = []
    try:
        dice_container = soup.select_one("div.dice_events")
        if not dice_container:
            return events

        for article in dice_container.select("article"):
            title_link = article.select_one("a.dice_event-title")
            if not title_link:
                continue

            event_name = title_link.get_text(strip=True)
            if not event_name or len(event_name) < 2:
                continue

            ticket_link = article.find("a", href=lambda x: x and "link.dice.fm" in x)
            ticket_url = ticket_link.get("href", config.website_url) if ticket_link else config.website_url

            events.append(VenueEvent(
                name=event_name, date=None, time=None,
                location=f"{config.name}, {config.address}",
                url=ticket_url, venue_name=config.name, category=config.category
            ))
        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_text_based(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from h2/h3 text (for Concord, Salt Shed, etc)."""
    events = []
    try:
        containers = soup.select("[class*='show'], article, [class*='event']")
        logger.info(f"{config.name}: found {len(containers)} containers")

        for container in containers:
            text = container.get_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]

            if not lines:
                continue

            event_name = None
            event_date = None

            for line in lines:
                if len(line) > 3 and not any(x in line for x in ['ticket', 'door', 'age', 'newsletter', 'subscribe']):
                    event_name = line
                    break

            for line in lines:
                if re.search(r'\d{1,2}/\d{1,2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', line):
                    event_date = line
                    break

            if event_name and len(event_name) > 3:
                events.append(VenueEvent(
                    name=event_name, date=event_date, time=None,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url, venue_name=config.name, category=config.category
                ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


# ===== NEIGHBORHOOD CONFIGS =====

CHICAGO_VENUES = {
    "Wicker Park": [
        VenueConfig(
            name="Subterranean",
            website_url="https://www.subt.net",
            event_page_url="https://subt.net/",
            category="music",
            address="2011 W North Ave",
            selectors={"event_container": "li.seetickets-list-event-container", "title": "p.event-title a", "date": "p.event-date"}
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
            selectors={"event_container": ".show-details", "title": "div.title", "date": "div.date"},
            use_playwright=True,
        ),
        VenueConfig(
            name="Den Theatre",
            website_url="https://www.dentheatre.com",
            event_page_url="https://thedentheatre.com/calendar?view=calendar&month=10-2026",
            category="comedy",
            address="1331 N Milwaukee Ave",
            selectors={"event_container": "li.item", "title": "span.item-title", "time": "span.item-time--12hr"},
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
            extractor_fn=extract_text_based,
        ),
    ],

    "Bucktown": [
        VenueConfig(
            name="The Hideout",
            website_url="https://www.hideoutchicago.com",
            event_page_url="https://www.hideoutchicago.com/shows",
            category="music",
            address="1354 W Wabansia Ave",
            selectors={"event_container": ".show-collection-item", "title": ".show-name", "date": ".show-start-date"}
        ),
        VenueConfig(
            name="Concord Music Hall",
            website_url="https://concordmusichall.com",
            event_page_url="https://concordmusichall.com/calendar/",
            category="music",
            address="2047 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_text_based,
        ),
        VenueConfig(
            name="Salt Shed",
            website_url="https://www.saltshedchicago.com",
            event_page_url="https://www.saltshedchicago.com/",
            category="music",
            address="1357 N Elston Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_text_based,
        ),
        VenueConfig(
            name="Outset",
            website_url="https://outsetlive.com",
            event_page_url="https://outsetlive.com/events/",
            category="music",
            address="1675 N Elston Ave",
            selectors={"event_container": "h3", "title": "h3"},
            use_playwright=True,
        ),
    ],

    "Avondale": [
        VenueConfig(
            name="Sleeping Village",
            website_url="https://www.sleepingvillagechicago.com",
            event_page_url="https://www.sleepingvillagechicago.com/",
            category="music",
            address="3734 W Belmont Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_text_based,
        ),
        VenueConfig(
            name="Rockwell on the River",
            website_url="https://www.rockwellontheriver.com",
            event_page_url="https://www.rockwellontheriver.com/calendar/",
            category="music",
            address="3757 N Rockwell Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_text_based,
        ),
    ],
}


async def scrape_chicago_events() -> dict[str, list[VenueEvent]]:
    """Scrape ALL Chicago neighborhoods/venues in one unified operation."""
    results = {}
    total_events = 0
    
    async with httpx.AsyncClient(timeout=15) as client:
        for neighborhood, venues in CHICAGO_VENUES.items():
            logger.info(f"\n{'='*60}")
            logger.info(f"Scraping {neighborhood} ({len(venues)} venues)")
            logger.info('='*60)
            
            neighborhood_events = []
            for config in venues:
                try:
                    scraper = VenueScraper(config)
                    events = await scraper.scrape(client)
                    neighborhood_events.extend(events)
                    total_events += len(events)
                except Exception as e:
                    logger.error(f"Error scraping {config.name}: {e}")
            
            results[neighborhood] = neighborhood_events
            logger.info(f"{neighborhood}: {len(neighborhood_events)} total events\n")

    logger.info(f"\n{'='*60}")
    logger.info(f"✅ TOTAL CHICAGO EVENTS: {total_events}")
    logger.info('='*60)
    
    # Print summary
    for neighborhood in sorted(results.keys()):
        events = results[neighborhood]
        by_venue = {}
        for e in events:
            by_venue.setdefault(e.venue_name, []).append(e)
        
        print(f"\n{neighborhood}: {len(events)} events")
        for venue in sorted(by_venue.keys()):
            print(f"  • {venue}: {len(by_venue[venue])}")
    
    return results


if __name__ == "__main__":
    import asyncio
    asyncio.run(scrape_chicago_events())
