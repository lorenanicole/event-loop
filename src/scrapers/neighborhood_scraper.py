"""
Generic neighborhood-based venue event scraper.
Specify a neighborhood name, get events from all venues in that area.

Supports multiple scraping strategies:
1. Playwright (JS rendering) - For dynamic sites
2. BeautifulSoup (direct HTML) - Fast fallback
3. SerpAPI search - Last resort fallback
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
USE_PLAYWRIGHT = True  # Try Playwright for JS rendering

# Venue scraping methods registry - persists which methods work for which venues
VENUE_SCRAPE_METHODS = {
    # Format: "Venue Name": {
    #     "method": "playwright|html|serp",
    #     "url": "working event page URL",
    #     "selector": "CSS selector if applicable",
    #     "notes": "any special handling needed"
    # }
}

def get_venue_scrape_method(venue_name: str) -> Optional[dict]:
    """Get cached scraping method for a venue."""
    return VENUE_SCRAPE_METHODS.get(venue_name)

def save_venue_scrape_method(venue_name: str, method: str, url: str, selector: Optional[str] = None, notes: str = ""):
    """Save which scraping method worked for a venue."""
    VENUE_SCRAPE_METHODS[venue_name] = {
        "method": method,
        "url": url,
        "selector": selector,
        "notes": notes,
        "last_updated": asyncio.get_event_loop().time() if asyncio._get_running_loop() else None
    }
    logger.info(f"Saved scraping method for {venue_name}: {method}")


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


@dataclass
class VenueConfig:
    """Configuration for a venue."""
    name: str
    website_url: str
    event_page_url: str
    category: str
    address: str


# Neighborhood -> Venues mapping
NEIGHBORHOOD_VENUES = {
    "Bucktown": [
        VenueConfig(
            name="The Hideout",
            website_url="https://www.hideoutchicago.com",
            event_page_url="https://www.hideoutchicago.com/calendar",
            category="music",
            address="1354 W Wabansia Ave"
        ),
        VenueConfig(
            name="Concord Music Hall",
            website_url="https://www.concordmusichal.com",
            event_page_url="https://www.concordmusichal.com/events",
            category="music",
            address="2047 N Milwaukee Ave"
        ),
    ],
    "Wicker Park": [
        VenueConfig(
            name="Subterranean",
            website_url="https://www.subt.net",
            event_page_url="https://wl.seetickets.us/",  # Their ticketing partner
            category="music",
            address="2011 W North Ave"
        ),
        VenueConfig(
            name="Chop Shop",
            website_url="https://www.chopshopmusic.com",
            event_page_url="https://www.chopshopmusic.com",  # Homepage has event info
            category="music",
            address="2033 W North Ave"
        ),
        VenueConfig(
            name="Empty Bottle",
            website_url="https://www.emptybottle.com",
            event_page_url="https://www.emptybottle.com",  # Homepage lists events
            category="music",
            address="1035 N Western Ave"
        ),
    ],
    "Lakeview": [
        VenueConfig(
            name="Schubas Tavern",
            website_url="https://www.schubastavern.com",
            event_page_url="https://lh-st.com/",
            category="music",
            address="3159 N Southport Ave"
        ),
    ],
    "Logan Square": [
        VenueConfig(
            name="Lincoln Hall",
            website_url="https://www.lincolnhallchicago.com",
            event_page_url="https://www.lincolnhallchicago.com/events",
            category="music",
            address="2424 N Lincoln Ave"
        ),
        VenueConfig(
            name="Thalia Hall",
            website_url="https://www.thaliahall.com",
            event_page_url="https://www.thaliahall.com/events",
            category="music",
            address="1807 S Allport St"
        ),
    ],
    "Pilsen": [
        VenueConfig(
            name="Lacuna Lofts",
            website_url="https://www.lacunalofts.com",
            event_page_url="https://www.lacunalofts.com/events",
            category="music",
            address="1807 S Allport St"
        ),
        VenueConfig(
            name="Artifact Events",
            website_url="https://www.artifactevents.com",
            event_page_url="https://www.artifactevents.com/events",
            category="music",
            address="4325 N Ravenswood Ave"
        ),
    ],
    "Uptown": [
        VenueConfig(
            name="Byline Bank Aragon Ballroom",
            website_url="https://www.aragonchicago.com",
            event_page_url="https://www.aragonchicago.com/events",
            category="music",
            address="1106 W Lawrence Ave"
        ),
        VenueConfig(
            name="Riviera Theatre",
            website_url="https://www.rivierachicago.com",
            event_page_url="https://www.rivierachicago.com/events",
            category="music",
            address="4746 N Broadway St"
        ),
    ],
}


class VenueScraper(ABC):
    """Base class for venue-specific event scrapers."""

    def __init__(self, config: VenueConfig):
        self.config = config
        self.venue_name = config.name
        self.website_url = config.website_url
        self.event_page_url = config.event_page_url
        self.category = config.category
        self.address = config.address

    @abstractmethod
    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Try to scrape events from venue's event page."""
        pass

    async def scrape_events(self, client: httpx.AsyncClient, serp_api_key: Optional[str] = None) -> list[VenueEvent]:
        """
        Try multiple strategies: Playwright (JS), BeautifulSoup (HTML), SerpAPI (search).
        Saves which method worked for future use.
        """
        # Strategy 1: Try Playwright for JS-heavy sites
        if USE_PLAYWRIGHT:
            events = await self._scrape_with_playwright()
            if events:
                save_venue_scrape_method(
                    self.venue_name,
                    "playwright",
                    self.event_page_url,
                    notes="Dynamic JS rendering"
                )
                logger.info(f"{self.venue_name}: scraped {len(events)} events via Playwright")
                return events

        # Strategy 2: Try direct HTML scraping
        try:
            response = await client.get(self.event_page_url, timeout=10)
            if response.status_code == 200:
                events = await self.scrape_events_from_page()
                if events:
                    save_venue_scrape_method(
                        self.venue_name,
                        "html",
                        self.event_page_url,
                        notes="Direct HTML parsing"
                    )
                    logger.info(f"{self.venue_name}: scraped {len(events)} events from HTML")
                    return events
        except Exception as e:
            logger.debug(f"{self.venue_name}: HTML scraping failed ({type(e).__name__})")

        # Strategy 3: SerpAPI search fallback
        if serp_api_key:
            events = await self._search_events_via_serp(client, serp_api_key)
            if events:
                save_venue_scrape_method(
                    self.venue_name,
                    "serp",
                    f"{SERP_API_URL}?q={self.venue_name}+Chicago+events",
                    notes="SerpAPI search fallback"
                )
            return events

        logger.warning(f"{self.venue_name}: no events found")
        return []

    async def _scrape_with_playwright(self) -> list[VenueEvent]:
        """Use Playwright to render JavaScript and parse dynamic content."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")
                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Parse events from rendered page
                    events = []
                    for event_elem in soup.find_all("div", class_=lambda x: x and any(w in x.lower() for w in ["event", "show", "card"]))[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "h2", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            if len(event_name) < 2:
                                continue

                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url
                            if not url.startswith("http"):
                                url = f"{self.website_url}{url}"

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,
                                time=None,
                                location=self.venue_name,
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")

                    return events

                finally:
                    await browser.close()

        except ImportError:
            logger.debug(f"{self.venue_name}: Playwright not available")
        except Exception as e:
            logger.debug(f"{self.venue_name}: Playwright failed ({type(e).__name__})")

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


class GenericVenueScraper(VenueScraper):
    """Generic scraper that works for any venue config."""

    async def scrape_events_from_page(self) -> list[VenueEvent]:
        """Generic HTML scraping - looks for common event patterns."""
        events = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.event_page_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Look for common event container patterns
                    for event_elem in soup.find_all("div", class_=lambda x: x and any(w in x.lower() for w in ["event", "show", "card", "item", "listing"]))[:10]:
                        try:
                            title = event_elem.find(["h3", "h4", "h2", "a"])
                            if not title:
                                continue

                            event_name = title.get_text(strip=True)
                            if len(event_name) < 2:
                                continue

                            link = event_elem.find("a", href=True)
                            url = link["href"] if link else self.website_url
                            if not url.startswith("http"):
                                url = f"{self.website_url}{url}"

                            # Try to extract date
                            date_elem = event_elem.find(["span", "p"], class_=lambda x: x and "date" in x.lower() if x else False)
                            date = date_elem.get_text(strip=True) if date_elem else None

                            events.append(VenueEvent(
                                name=event_name,
                                date=date,
                                time=None,
                                location=f"{self.venue_name}, {self.address}",
                                url=url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Failed to parse event: {e}")
        except Exception as e:
            logger.debug(f"{self.venue_name} page scrape failed: {e}")

        return events


async def scrape_neighborhood(neighborhood: str) -> list[VenueEvent]:
    """
    Scrape all venues in a neighborhood.

    Args:
        neighborhood: Neighborhood name (e.g., "Bucktown", "Wicker Park", "Logan Square")

    Returns:
        List of VenueEvent objects discovered across all venues in neighborhood
    """
    if neighborhood not in NEIGHBORHOOD_VENUES:
        available = ", ".join(sorted(NEIGHBORHOOD_VENUES.keys()))
        raise ValueError(f"Unknown neighborhood '{neighborhood}'. Available: {available}")

    all_events = []
    serp_api_key = os.environ.get("SERP_API_KEY")
    venue_configs = NEIGHBORHOOD_VENUES[neighborhood]

    logger.info(f"Scraping {len(venue_configs)} venues in {neighborhood}")

    async with httpx.AsyncClient(timeout=15) as client:
        for config in venue_configs:
            try:
                scraper = GenericVenueScraper(config)
                events = await scraper.scrape_events(client, serp_api_key)
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Error scraping {config.name}: {e}")

    logger.info(f"Total {neighborhood} events: {len(all_events)}")
    return all_events


def list_neighborhoods() -> list[str]:
    """Get list of available neighborhoods."""
    return sorted(NEIGHBORHOOD_VENUES.keys())


def list_venues_in_neighborhood(neighborhood: str) -> list[str]:
    """Get list of venues in a neighborhood."""
    if neighborhood not in NEIGHBORHOOD_VENUES:
        raise ValueError(f"Unknown neighborhood '{neighborhood}'")
    return [v.name for v in NEIGHBORHOOD_VENUES[neighborhood]]
