"""
Bucktown/Wicker Park venue event discovery.
Hybrid approach: Try to scrape event pages, fall back to SerpAPI if unavailable.
"""

import httpx
import logging
import os
import asyncio
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

SERP_API_URL = "https://serpapi.com/search"
RATE_LIMIT_DELAY = 0.5


@dataclass
class VenueEvent:
    """Event discovered from venue or search."""
    name: str
    date: Optional[str]
    time: Optional[str]
    location: str
    url: str
    venue_name: str
    category: str


class VenueScraper(ABC):
    """Base class for venue-specific event scrapers."""

    def __init__(self, venue_name: str, website_url: str, event_page_url: str, category: str):
        self.venue_name = venue_name
        self.website_url = website_url
        self.event_page_url = event_page_url
        self.category = category

    @abstractmethod
    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Try to scrape events from venue's event page."""
        pass

    async def scrape_events(self, client: httpx.AsyncClient, serp_api_key: Optional[str] = None) -> list[VenueEvent]:
        """
        Try direct scraping first, fall back to SerpAPI search if unavailable.
        """
        try:
            # Try to fetch event page
            response = await client.get(self.event_page_url, timeout=10)
            if response.status_code == 200:
                events = await self.scrape_events_from_page()
                if events:
                    logger.info(f"{self.venue_name}: scraped {len(events)} events from page")
                    return events
        except Exception as e:
            logger.debug(f"{self.venue_name}: event page unavailable ({type(e).__name__})")

        # Fallback: SerpAPI search
        if serp_api_key:
            return await self._search_events_via_serp(client, serp_api_key)

        logger.warning(f"{self.venue_name}: no events found (set SERP_API_KEY for fallback)")
        return []

    async def _search_events_via_serp(self, client: httpx.AsyncClient, api_key: str) -> list[VenueEvent]:
        """Fallback: search for events via SerpAPI."""
        events = []

        try:
            await asyncio.sleep(RATE_LIMIT_DELAY)

            response = await client.get(
                SERP_API_URL,
                params={
                    "q": f"{self.venue_name} Chicago events 2026",
                    "api_key": api_key,
                    "engine": "google",
                    "num": 5,
                }
            )
            response.raise_for_status()
            results = response.json()

            # Parse organic results for event links
            if "organic_results" in results:
                for result in results["organic_results"][:5]:
                    try:
                        title = result.get("title", "")
                        link = result.get("link", "")

                        if any(x in title.lower() for x in ["event", "concert", "show", "ticket"]):
                            events.append(VenueEvent(
                                name=title[:100],
                                date=None,
                                time=None,
                                location=self.venue_name,
                                url=link,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                    except Exception as e:
                        logger.debug(f"Failed to parse SerpAPI result: {e}")

            if events:
                logger.info(f"{self.venue_name}: found {len(events)} events via SerpAPI")

        except Exception as e:
            logger.error(f"SerpAPI search failed for {self.venue_name}: {e}")

        return events


class SubterraneanScraper(VenueScraper):
    """Subterranean (2011 W North Ave) - indie rock/experimental."""

    def __init__(self):
        super().__init__(
            venue_name="Subterranean",
            website_url="https://www.subt.net",
            event_page_url="https://www.subt.net/calendar",
            category="music"
        )

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Scrape from Subterranean calendar page."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Parse event listings
                    for event_elem in soup.find_all("div", class_=lambda x: x and "event" in x.lower())[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location="Subterranean, 2011 W North Ave",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"Subterranean page scrape failed: {e}")

        return events


class ChopShopScraper(VenueScraper):
    """Chop Shop (2033 W North Ave) - indie/rock."""

    def __init__(self):
        super().__init__(
            venue_name="Chop Shop",
            website_url="https://www.chopshopmusic.com",
            event_page_url="https://www.chopshopmusic.com/events",
            category="music"
        )

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Scrape from Chop Shop events page."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    for event_elem in soup.find_all("div", class_=lambda x: x and any(w in x.lower() for w in ["event", "show", "card"]))[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url
                            if not url.startswith("http"):
                                url = f"{self.website_url}{url}"

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location="Chop Shop, 2033 W North Ave",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"Chop Shop page scrape failed: {e}")

        return events


class SchubaScraper(VenueScraper):
    """Schubas Tavern (3159 N Southport) - indie/folk."""

    def __init__(self):
        super().__init__(
            venue_name="Schubas Tavern",
            website_url="https://www.schubastavern.com",
            event_page_url="https://lh-st.com/",
            category="music"
        )

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Scrape from Schubas ticketing partner (lh-st.com)."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    for event_elem in soup.find_all("div", class_=lambda x: x and "event" in x.lower())[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location="Schubas Tavern, 3159 N Southport Ave",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"Schubas page scrape failed: {e}")

        return events


class HideoutScraper(VenueScraper):
    """The Hideout (1354 W Wabansia) - intimate venue."""

    def __init__(self):
        super().__init__(
            venue_name="The Hideout",
            website_url="https://www.hideoutchicago.com",
            event_page_url="https://www.hideoutchicago.com/calendar",
            category="music"
        )

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Scrape from Hideout calendar."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    for event_elem in soup.find_all("div", class_=lambda x: x and "event" in x.lower())[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location="The Hideout, 1354 W Wabansia Ave",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"Hideout page scrape failed: {e}")

        return events


class EmptyBottleScraper(VenueScraper):
    """Empty Bottle (1035 N Western) - indie music."""

    def __init__(self):
        super().__init__(
            venue_name="Empty Bottle",
            website_url="https://www.emptybottle.com",
            event_page_url="https://www.emptybottle.com/calendar",
            category="music"
        )

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Scrape from Empty Bottle calendar."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    for event_elem in soup.find_all("div", class_=lambda x: x and "event" in x.lower())[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location="Empty Bottle, 1035 N Western Ave",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"Empty Bottle page scrape failed: {e}")

        return events


class ConcordScraper(VenueScraper):
    """Concord Music Hall (2047 N Milwaukee) - indie/rock."""

    def __init__(self):
        super().__init__(
            venue_name="Concord Music Hall",
            website_url="https://www.concordmusichal.com",
            event_page_url="https://www.concordmusichal.com/events",
            category="music"
        )

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Scrape from Concord events page."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    for event_elem in soup.find_all("div", class_=lambda x: x and "event" in x.lower())[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location="Concord Music Hall, 2047 N Milwaukee Ave",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"Concord page scrape failed: {e}")

        return events


# Scraper registry
BUCKTOWN_WICKER_PARK_SCRAPERS = [
    SubterraneanScraper(),
    ChopShopScraper(),
    SchubaScraper(),
    HideoutScraper(),
    EmptyBottleScraper(),
    ConcordScraper(),
]


async def scrape_bucktown_wicker_park() -> list[VenueEvent]:
    """Scrape all Bucktown/Wicker Park venues with SerpAPI fallback."""
    all_events = []
    serp_api_key = os.environ.get("SERP_API_KEY")

    async with httpx.AsyncClient(timeout=15) as client:
        for scraper in BUCKTOWN_WICKER_PARK_SCRAPERS:
            try:
                events = await scraper.scrape_events(client, serp_api_key)
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Error scraping {scraper.venue_name}: {e}")

    logger.info(f"Total Bucktown/Wicker Park events: {len(all_events)}")
    return all_events
