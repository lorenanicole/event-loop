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
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/shows/chicago")
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    events = []

                    # Look for show listings - Second City uses various markup
                    for show in soup.find_all("div", {"class": lambda x: x and "show" in x.lower()}):
                        try:
                            title_elem = show.find(["h3", "h4", "a"])
                            title = title_elem.get_text(strip=True) if title_elem else None

                            if not title:
                                continue

                            url = f"{self.venue_url}/shows/chicago"
                            date_str = show.find(["span", "p"], {"class": lambda x: x and "date" in x.lower()})
                            date = date_str.get_text(strip=True) if date_str else None

                            events.append(VenueEvent(
                                name=title,
                                date=date,
                                time=None,
                                location="Second City Chicago",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category,
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse Second City show: {e}")

                    logger.info(f"Scraped {len(events)} Second City shows")
                    return events
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
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/productions")
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    events = []

                    # Steppenwolf uses production cards/listings
                    for prod in soup.find_all("article") or soup.find_all("div", {"class": lambda x: x and "production" in x.lower()}):
                        try:
                            title_elem = prod.find(["h3", "h2", "a"])
                            title = title_elem.get_text(strip=True) if title_elem else None

                            if not title:
                                continue

                            link = prod.find("a", href=True)
                            url = link["href"] if link else f"{self.venue_url}/productions"
                            if not url.startswith("http"):
                                url = f"{self.venue_url}{url}"

                            date_elem = prod.find(["span", "p"], {"class": lambda x: x and ("date" in x.lower() or "run" in x.lower())})
                            date = date_elem.get_text(strip=True) if date_elem else None

                            events.append(VenueEvent(
                                name=title,
                                date=date,
                                time=None,
                                location="Steppenwolf Theatre",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category,
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse Steppenwolf production: {e}")

                    logger.info(f"Scraped {len(events)} Steppenwolf productions")
                    return events
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
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/chicago/shows")
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    events = []

                    # iO uses show cards or table rows
                    for show in soup.find_all("div", {"class": lambda x: x and "show" in x.lower()}) or soup.find_all("tr"):
                        try:
                            title_elem = show.find(["h3", "h4", "td", "a"])
                            title = title_elem.get_text(strip=True) if title_elem else None

                            if not title or len(title) < 2:
                                continue

                            link = show.find("a", href=True)
                            url = link["href"] if link else f"{self.venue_url}/chicago/shows"
                            if not url.startswith("http"):
                                url = f"{self.venue_url}{url}"

                            date_elem = show.find(["span", "td"], {"class": lambda x: x and "date" in x.lower() if x else False})
                            date = date_elem.get_text(strip=True) if date_elem else None

                            events.append(VenueEvent(
                                name=title,
                                date=date,
                                time=None,
                                location="iO Chicago",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category,
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse iO show: {e}")

                    logger.info(f"Scraped {len(events)} iO Theater shows")
                    return events
        except Exception as e:
            logger.error(f"Failed to scrape iO Theater: {e}")

        return []


class GoodmanTheatreScraper(VenueScraper):
    """Scraper for Goodman Theatre."""

    def __init__(self):
        super().__init__(
            venue_name="Goodman Theatre",
            venue_url="https://www.goodmantheatre.org",
            category="theater"
        )

    async def scrape_events(self) -> list[VenueEvent]:
        """Scrape Goodman Theatre productions."""
        try:
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/seasons")
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    events = []

                    for show in soup.find_all("article") or soup.find_all("div", {"class": lambda x: x and "show" in x.lower()}):
                        try:
                            title_elem = show.find(["h3", "h2", "a"])
                            title = title_elem.get_text(strip=True) if title_elem else None

                            if not title:
                                continue

                            link = show.find("a", href=True)
                            url = link["href"] if link else f"{self.venue_url}/seasons"
                            if not url.startswith("http"):
                                url = f"{self.venue_url}{url}"

                            events.append(VenueEvent(
                                name=title,
                                date=None,
                                time=None,
                                location="Goodman Theatre",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category,
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse Goodman show: {e}")

                    logger.info(f"Scraped {len(events)} Goodman Theatre shows")
                    return events
        except Exception as e:
            logger.error(f"Failed to scrape Goodman Theatre: {e}")

        return []


class HouseOfBluesScraper(VenueScraper):
    """Scraper for House of Blues Chicago."""

    def __init__(self):
        super().__init__(
            venue_name="House of Blues",
            venue_url="https://www.houseofblues.com/chicago",
            category="concert"
        )

    async def scrape_events(self) -> list[VenueEvent]:
        """Scrape House of Blues concerts."""
        try:
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.venue_url}/events")
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    events = []

                    for event in soup.find_all("div", {"class": lambda x: x and "event" in x.lower()}) or soup.find_all("article"):
                        try:
                            title_elem = event.find(["h3", "h2", "a"])
                            title = title_elem.get_text(strip=True) if title_elem else None

                            if not title:
                                continue

                            link = event.find("a", href=True)
                            url = link["href"] if link else f"{self.venue_url}/events"
                            if not url.startswith("http"):
                                url = f"{self.venue_url}{url}"

                            date_elem = event.find(["span", "p"], {"class": lambda x: x and "date" in x.lower() if x else False})
                            date = date_elem.get_text(strip=True) if date_elem else None

                            events.append(VenueEvent(
                                name=title,
                                date=date,
                                time=None,
                                location="House of Blues Chicago",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category,
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse House of Blues event: {e}")

                    logger.info(f"Scraped {len(events)} House of Blues concerts")
                    return events
        except Exception as e:
            logger.error(f"Failed to scrape House of Blues: {e}")

        return []


# Registry of all venue scrapers - major Chicago entertainment venues
VENUE_SCRAPERS = [
    SecondCityScraper(),
    SteppenwolfScraper(),
    IOTheaterScraper(),
    GoodmanTheatreScraper(),
    HouseOfBluesScraper(),
]

# Known Chicago entertainment venues (from OSM/web research)
CHICAGO_VENUES = [
    {"name": "Steppenwolf Theatre", "url": "https://www.steppenwolf.org", "type": "theater"},
    {"name": "Goodman Theatre", "url": "https://www.goodmantheatre.org", "type": "theater"},
    {"name": "Court Theatre", "url": "https://www.courttheatre.org", "type": "theater"},
    {"name": "Second City", "url": "https://www.secondcity.com", "type": "comedy"},
    {"name": "iO Theater", "url": "https://www.ioimprov.com", "type": "comedy"},
    {"name": "The Laugh Factory", "url": "https://www.laughfactorychicago.com", "type": "comedy"},
    {"name": "Zanies Chicago", "url": "https://www.zaniescomedyclub.com", "type": "comedy"},
    {"name": "House of Blues", "url": "https://www.houseofblues.com/chicago", "type": "concert"},
    {"name": "Congress Theater", "url": "https://www.congresschicago.com", "type": "concert"},
    {"name": "Aragon Ballroom", "url": "https://www.aragonchicago.com", "type": "concert"},
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
