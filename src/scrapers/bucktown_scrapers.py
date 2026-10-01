"""
Bucktown Venue-Specific Scrapers
Tailored scraping strategies for each Bucktown venue's unique HTML structure
"""

import httpx
import logging
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class VenueEvent:
    """Event discovered from venue."""
    name: str
    date: Optional[str]
    time: Optional[str]
    location: str
    url: str
    venue_name: str
    category: str


class BucktownVenueScraper(ABC):
    """Base class for Bucktown venue scrapers."""

    def __init__(self, venue_name: str, website_url: str, event_page_url: str, category: str, address: str):
        self.venue_name = venue_name
        self.website_url = website_url
        self.event_page_url = event_page_url
        self.category = category
        self.address = address

    @abstractmethod
    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape events from venue."""
        pass


class TheHideoutScraper(BucktownVenueScraper):
    """The Hideout - Webflow show collection"""

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        events = []
        try:
            response = await client.get(self.event_page_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f"The Hideout: got {response.status_code}")
                return events

            soup = BeautifulSoup(response.text, "html.parser")

            # Webflow show-collection-item elements
            event_items = soup.select(".show-collection-item")
            logger.info(f"The Hideout: found {len(event_items)} event items")

            for item in event_items:
                try:
                    # Extract title from .show-name
                    title_elem = item.select_one(".show-name")
                    if not title_elem:
                        continue

                    event_name = title_elem.get_text(strip=True)
                    if not event_name or len(event_name) < 2:
                        continue

                    # Extract date from .show-start-date
                    date_elem = item.select_one(".show-start-date")
                    event_date = date_elem.get_text(strip=True) if date_elem else None

                    # Extract slug for URL building
                    slug_elem = item.select_one(".show-slug")
                    slug = slug_elem.get_text(strip=True) if slug_elem else None

                    event_url = self.website_url
                    if slug:
                        event_url = f"{self.website_url}/{slug}"

                    events.append(VenueEvent(
                        name=event_name,
                        date=event_date,
                        time=None,
                        location=f"{self.venue_name}, {self.address}",
                        url=event_url,
                        venue_name=self.venue_name,
                        category=self.category
                    ))
                except Exception as e:
                    logger.debug(f"The Hideout: failed to parse event: {e}")

            logger.info(f"The Hideout: extracted {len(events)} events")

        except Exception as e:
            logger.error(f"The Hideout scraping failed: {e}")

        return events


class ConcordMusicHallScraper(BucktownVenueScraper):
    """Concord Music Hall - requires Playwright due to 403 on direct access"""

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")

                    # Wait for calendar to load
                    try:
                        await page.wait_for_selector(".event", timeout=5000)
                    except:
                        logger.debug("Concord: event selector not found")

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Look for event listings
                    event_items = soup.select(".event, [class*='event'], article")
                    logger.info(f"Concord: found {len(event_items)} event items")

                    for item in event_items[:30]:
                        try:
                            # Extract title
                            title_elem = item.find(["h3", "h2", "a"])
                            if not title_elem:
                                continue

                            event_name = title_elem.get_text(strip=True)
                            if not event_name or len(event_name) < 2:
                                continue

                            # Extract date
                            date_text = item.get_text()
                            event_date = None
                            import re
                            date_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}', date_text)
                            if date_match:
                                event_date = date_match.group(0)

                            # Extract link
                            link = item.find("a", href=True)
                            event_url = link.get("href", self.website_url) if link else self.website_url
                            if not event_url.startswith("http"):
                                event_url = f"{self.website_url}{event_url}"

                            events.append(VenueEvent(
                                name=event_name,
                                date=event_date,
                                time=None,
                                location=f"{self.venue_name}, {self.address}",
                                url=event_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Concord: failed to parse event: {e}")

                    logger.info(f"Concord: extracted {len(events)} events")

                finally:
                    await browser.close()

        except ImportError:
            logger.debug("Concord: Playwright not available")
        except Exception as e:
            logger.error(f"Concord scraping failed: {e}")

        return events


class SaltShedScraper(BucktownVenueScraper):
    """Salt Shed - requires Playwright for JavaScript rendering"""

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")

                    # Wait for event content
                    try:
                        await page.wait_for_selector("h2, h3, .event", timeout=5000)
                    except:
                        logger.debug("Salt Shed: event selector not found")

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Look for event headings/blocks
                    event_items = soup.select("h2, h3")
                    logger.info(f"Salt Shed: found {len(event_items)} heading elements")

                    for item in event_items[:50]:
                        try:
                            text = item.get_text(strip=True)
                            # Skip generic headers
                            if not text or len(text) < 3 or text.lower() in ["menu", "more", "about", "contact"]:
                                continue

                            # Skip if it looks like a date (likely already processed)
                            import re
                            if re.match(r'(January|February|March|April|May|June|July|August|September|October|November|December)', text):
                                continue

                            events.append(VenueEvent(
                                name=text,
                                date=None,
                                time=None,
                                location=f"{self.venue_name}, {self.address}",
                                url=self.website_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Salt Shed: failed to parse: {e}")

                    logger.info(f"Salt Shed: extracted {len(events)} events")

                finally:
                    await browser.close()

        except ImportError:
            logger.debug("Salt Shed: Playwright not available")
        except Exception as e:
            logger.error(f"Salt Shed scraping failed: {e}")

        return events


class OutsetScraper(BucktownVenueScraper):
    """Outset - requires Playwright for JavaScript rendering"""

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")

                    # Wait for event content
                    try:
                        await page.wait_for_selector(".event, h3, article", timeout=5000)
                    except:
                        logger.debug("Outset: event selector not found")

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Look for event listings
                    event_items = soup.select(".event, article, [class*='event']")
                    logger.info(f"Outset: found {len(event_items)} event items")

                    for item in event_items[:30]:
                        try:
                            # Extract title
                            title_elem = item.find(["h3", "h2", "a"])
                            if not title_elem:
                                continue

                            event_name = title_elem.get_text(strip=True)
                            if not event_name or len(event_name) < 2:
                                continue

                            # Extract date
                            date_text = item.get_text()
                            event_date = None
                            import re
                            date_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}', date_text)
                            if date_match:
                                event_date = date_match.group(0)

                            # Extract link
                            link = item.find("a", href=True)
                            event_url = link.get("href", self.website_url) if link else self.website_url
                            if not event_url.startswith("http"):
                                event_url = f"{self.website_url}{event_url}"

                            events.append(VenueEvent(
                                name=event_name,
                                date=event_date,
                                time=None,
                                location=f"{self.venue_name}, {self.address}",
                                url=event_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Outset: failed to parse event: {e}")

                    logger.info(f"Outset: extracted {len(events)} events")

                finally:
                    await browser.close()

        except ImportError:
            logger.debug("Outset: Playwright not available")
        except Exception as e:
            logger.error(f"Outset scraping failed: {e}")

        return events


async def scrape_bucktown_venues() -> list[VenueEvent]:
    """Scrape all 4 Bucktown venues with venue-specific strategies."""
    scrapers = [
        TheHideoutScraper(
            venue_name="The Hideout",
            website_url="https://www.hideoutchicago.com",
            event_page_url="https://www.hideoutchicago.com/shows",
            category="music",
            address="1354 W Wabansia Ave"
        ),
        ConcordMusicHallScraper(
            venue_name="Concord Music Hall",
            website_url="https://www.concordmusichall.com",
            event_page_url="https://www.concordmusichall.com/calendar/",
            category="music",
            address="2047 N Milwaukee Ave"
        ),
        SaltShedScraper(
            venue_name="Salt Shed",
            website_url="https://www.saltshedchicago.com",
            event_page_url="https://www.saltshedchicago.com/",
            category="music",
            address="1357 N Elston Ave"
        ),
        OutsetScraper(
            venue_name="Outset",
            website_url="https://outsetlive.com",
            event_page_url="https://outsetlive.com/events/",
            category="music",
            address="1675 N Elston Ave"
        ),
    ]

    all_events = []

    async with httpx.AsyncClient(timeout=15) as client:
        for scraper in scrapers:
            try:
                events = await scraper.scrape_events(client)
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Error scraping {scraper.venue_name}: {e}")

    logger.info(f"Total Bucktown events: {len(all_events)}")
    return all_events
