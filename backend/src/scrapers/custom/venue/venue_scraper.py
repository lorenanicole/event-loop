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
    date_end: Optional[str] = None  # For multi-day events
    time_end: Optional[str] = None  # End time for events with duration


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
    playwright_wait_until: str = "domcontentloaded"
    # Async extractor receiving the live Playwright page instead of soup.
    # Use for venues that render event cards from JS after load (Salt Shed).
    page_extractor_fn: Optional[Callable] = None


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
        """Scrape JavaScript-rendered page with Playwright + stealth."""
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                # Stealth mode to bypass bot detection (Cloudflare, etc)
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                    ]
                )
                page = await browser.new_page(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )

                # Hide automation signals
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """)

                try:
                    await page.goto(self.config.event_page_url, timeout=15000, wait_until=self.config.playwright_wait_until)
                    await page.wait_for_timeout(2000)

                    # Page-based extractors need the live DOM (JS-rendered cards,
                    # "load more" pagination), so they run before the browser closes.
                    if self.config.page_extractor_fn:
                        events = await self.config.page_extractor_fn(page, self.config)
                        return events

                    html = await page.content()

                    # Extract content from any iframes (for venues like Rhapsody Theater with ThunderTix)
                    frames = page.frames
                    iframe_content = []
                    for frame in frames:
                        try:
                            frame_text = await frame.evaluate("document.body.innerText")
                            if frame_text and len(frame_text) > 100:
                                iframe_content.append(frame_text)
                        except:
                            pass

                    # Create soup and inject iframe content if found
                    soup = BeautifulSoup(html, "html.parser")
                    if iframe_content:
                        # Append iframe content as hidden text node for extractor to find
                        body = soup.find('body')
                        if body:
                            iframe_text = " ".join(iframe_content)
                            import html as html_module
                            body.append(soup.new_string(f"\n{html_module.escape(iframe_text)}\n"))

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
