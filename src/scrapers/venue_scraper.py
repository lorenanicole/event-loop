"""
Flexible venue scraper framework using Playwright + CSS selectors.
Each venue has a config with URL + CSS selectors. Uses Playwright for JS rendering.
"""

import httpx
import logging
import re
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional, Callable

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


@dataclass
class VenueConfig:
    """Configuration for scraping a venue."""
    name: str
    website_url: str
    event_page_url: str
    category: str
    address: str
    selectors: dict
    use_playwright: bool = False
    extractor_fn: Optional[Callable] = None


class VenueScraper:
    """Flexible venue scraper using config-driven extraction."""

    def __init__(self, config: VenueConfig):
        self.config = config

    async def scrape(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape events from venue using configured strategy."""
        if self.config.use_playwright:
            return await self._scrape_with_playwright()
        else:
            return await self._scrape_static(client)

    async def _scrape_static(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape static HTML page."""
        events = []
        try:
            response = await client.get(self.config.event_page_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f"{self.config.name}: got {response.status_code}")
                return events

            soup = BeautifulSoup(response.text, "html.parser")
            events = self._extract_events(soup)

        except Exception as e:
            logger.error(f"{self.config.name} scraping failed: {e}")

        return events

    async def _scrape_with_playwright(self) -> list[VenueEvent]:
        """Scrape JavaScript-rendered page with Playwright."""
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.config.event_page_url, timeout=15000, wait_until="networkidle")
                    await page.wait_for_timeout(2000)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    events = self._extract_events(soup)

                finally:
                    await browser.close()

        except ImportError:
            logger.debug(f"{self.config.name}: Playwright not available")
        except Exception as e:
            logger.error(f"{self.config.name} Playwright scraping failed: {e}")

        return events

    def _extract_events(self, soup: BeautifulSoup) -> list[VenueEvent]:
        """Extract events using config selectors or custom function."""
        if self.config.extractor_fn:
            return self.config.extractor_fn(soup, self.config)

        events = []
        try:
            event_selector = self.config.selectors.get("event_container")
            if not event_selector:
                logger.debug(f"{self.config.name}: No event_container selector")
                return events

            containers = soup.select(event_selector)
            logger.info(f"{self.config.name}: found {len(containers)} event containers")

            for container in containers:
                try:
                    event = self._extract_single_event(container)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.debug(f"{self.config.name}: failed to parse event: {e}")

            logger.info(f"{self.config.name}: extracted {len(events)} events")

        except Exception as e:
            logger.error(f"{self.config.name} extraction failed: {e}")

        return events

    def _extract_single_event(self, container) -> Optional[VenueEvent]:
        """Extract a single event from a container element."""
        selectors = self.config.selectors

        title_selector = selectors.get("title")
        if title_selector:
            title_elem = container.select_one(title_selector)
            title = title_elem.get_text(strip=True) if title_elem else None
        else:
            title = None

        if not title or len(title) < 2:
            return None

        date_selector = selectors.get("date")
        if date_selector:
            date_elem = container.select_one(date_selector)
            date = date_elem.get_text(strip=True) if date_elem else None
        else:
            date = None

        time_selector = selectors.get("time")
        if time_selector:
            time_elem = container.select_one(time_selector)
            time = time_elem.get_text(strip=True) if time_elem else None
        else:
            time = None

        url_selector = selectors.get("url")
        if url_selector:
            url_elem = container.select_one(url_selector)
            url = url_elem.get("href", self.config.website_url) if url_elem else self.config.website_url
            if not url.startswith("http"):
                url = f"{self.config.website_url}{url}"
        else:
            url = self.config.website_url

        return VenueEvent(
            name=title,
            date=date,
            time=time,
            location=f"{self.config.name}, {self.config.address}",
            url=url,
            venue_name=self.config.name,
            category=self.config.category
        )
