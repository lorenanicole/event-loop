"""
Avondale venues - using flexible config-driven scraping framework.
Strategic approach: discover event pages, identify DOM selectors, configure extraction.
"""

import logging

import httpx

from .venue_scraper import VenueConfig, VenueEvent, VenueScraper

logger = logging.getLogger(__name__)

# Avondale venues with scraping configs
AVONDALE_VENUES = [
    VenueConfig(
        name="Sleeping Village",
        website_url="https://www.sleepingvillagechicago.com",
        event_page_url="https://www.sleepingvillagechicago.com/",
        category="music",
        address="3734 W Belmont Ave",
        selectors={
            "event_container": "article, [class*='event'], [class*='show']",
            "title": "h2, h3, a[href*='event']",
            "date": "span, p",
        },
        use_playwright=True,
    ),
    VenueConfig(
        name="Rockwell on the River",
        website_url="https://www.rockwellontheriver.com",
        event_page_url="https://www.rockwellontheriver.com/calendar/",
        category="music",
        address="3757 N Rockwell Ave",
        selectors={
            "event_container": "[class*='event'], article, li",
            "title": "h3, h2, .event-title",
            "date": "[class*='date'], span",
        },
        use_playwright=True,
    ),
    VenueConfig(
        name="Avondale Music Hall",
        website_url="https://www.avondalemusichair.com",
        event_page_url="https://www.avondalemusichair.com/events/",
        category="music",
        address="3730 N Rockwell Ave",
        selectors={
            "event_container": "[class*='event'], article",
            "title": "h2, h3, .event-name",
            "date": "[class*='date']",
        },
        use_playwright=True,
    ),
]


async def scrape_avondale_venues() -> list[VenueEvent]:
    """Scrape all Avondale venues using flexible framework."""
    all_events = []

    async with httpx.AsyncClient(timeout=15) as client:
        for config in AVONDALE_VENUES:
            try:
                scraper = VenueScraper(config)
                events = await scraper.scrape(client)
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Error scraping {config.name}: {e}")

    logger.info(f"Total Avondale events: {len(all_events)}")
    return all_events
