"""
Scrape event calendars from Chicago entertainment venue websites.
Extracts events from individual venue pages and normalizes them.
"""

import httpx
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VenueEvent:
    """Event scraped from a venue website."""
    name: str
    date: Optional[str]
    time: Optional[str]
    location: str
    url: str
    venue_name: str
    category: str  # "comedy", "theater", "concert", etc.


class VenueScraper(ABC):
    """Base class for venue-specific scrapers."""

    def __init__(self, venue_name: str, venue_url: str, category: str):
        self.venue_name = venue_name
        self.venue_url = venue_url
        self.category = category

    @abstractmethod
    async def scrape_events(self) -> list[VenueEvent]:
        """Scrape events from this venue's website."""
        pass


class SecondCityScraper(VenueScraper):
    """Scraper for Second City comedy venue."""

    def __init__(self):
        super().__init__(
            venue_name="Second City",
            venue_url="https://www.secondcity.com",
            category="comedy"
        )

    async def scrape_events(self) -> list[VenueEvent]:
        """Scrape Second City shows."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/shows")
                if response.status_code == 200:
                    # TODO: Parse HTML with BeautifulSoup
                    # Extract show dates, times, and URLs
                    logger.info(f"Fetched Second City page: {response.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Failed to scrape Second City: {e}")

        return []


class SteppenwolfScraper(VenueScraper):
    """Scraper for Steppenwolf Theater."""

    def __init__(self):
        super().__init__(
            venue_name="Steppenwolf Theatre Company",
            venue_url="https://www.steppenwolf.org",
            category="theater"
        )

    async def scrape_events(self) -> list[VenueEvent]:
        """Scrape Steppenwolf productions."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/shows")
                if response.status_code == 200:
                    # TODO: Parse HTML for productions/shows
                    logger.info(f"Fetched Steppenwolf page: {response.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Failed to scrape Steppenwolf: {e}")

        return []


class IOTheaterScraper(VenueScraper):
    """Scraper for iO Theater (improv comedy)."""

    def __init__(self):
        super().__init__(
            venue_name="iO Theater",
            venue_url="https://www.ioimprov.com",
            category="comedy"
        )

    async def scrape_events(self) -> list[VenueEvent]:
        """Scrape iO Theater shows."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/chicago/shows")
                if response.status_code == 200:
                    # TODO: Parse HTML for improv shows
                    logger.info(f"Fetched iO Theater page: {response.status_code}")
                    return []
        except Exception as e:
            logger.error(f"Failed to scrape iO Theater: {e}")

        return []


# Registry of all venue scrapers
VENUE_SCRAPERS = [
    SecondCityScraper(),
    SteppenwolfScraper(),
    IOTheaterScraper(),
    # TODO: Add more venues as needed
]


async def scrape_all_venues() -> list[VenueEvent]:
    """Scrape events from all registered venue scrapers."""
    all_events = []

    for scraper in VENUE_SCRAPERS:
        try:
            events = await scraper.scrape_events()
            all_events.extend(events)
            logger.info(f"{scraper.venue_name}: scraped {len(events)} events")
        except Exception as e:
            logger.error(f"Error scraping {scraper.venue_name}: {e}")

    logger.info(f"Total events scraped from venues: {len(all_events)}")
    return all_events
