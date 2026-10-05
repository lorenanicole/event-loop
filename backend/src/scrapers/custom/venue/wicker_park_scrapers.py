"""
Wicker Park Venue-Specific Scrapers
Tailored scraping strategies for each Wicker Park venue's unique HTML structure

Based on HTML analysis:
- Subterranean: Static WordPress/SeeTickets (easy)
- Chop Shop: Dice FM widget (requires Playwright)
- Empty Bottle: Squarespace events (medium)
- Den Theatre: Squarespace tickets (medium)
"""

import httpx
import logging
import asyncio
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


class WickerParkVenueScraper(ABC):
    """Base class for Wicker Park venue scrapers."""

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


class SubterraneanScraper(WickerParkVenueScraper):
    """
    Subterranean (2011 W North Ave) - WordPress/SeeTickets
    Static HTML, easy BeautifulSoup parsing
    """

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape using SeeTickets event container selectors."""
        events = []
        try:
            response = await client.get(self.event_page_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f"Subterranean: got {response.status_code}")
                return events

            soup = BeautifulSoup(response.text, "html.parser")

            # Query all event containers: li.seetickets-list-event-container
            event_containers = soup.select("li.seetickets-list-event-container")
            logger.info(f"Subterranean: found {len(event_containers)} event containers")

            for container in event_containers:
                try:
                    # Extract fields using specific selectors
                    name_elem = container.select_one("p.event-title a")
                    if not name_elem:
                        continue

                    event_name = name_elem.get_text(strip=True)
                    date_elem = container.select_one("p.event-date")
                    event_date = date_elem.get_text(strip=True) if date_elem else None

                    # Door/show times
                    door_time_elem = container.select_one("span.door-time")
                    show_time_elem = container.select_one("span.event-time")
                    event_time = None
                    if door_time_elem and show_time_elem:
                        event_time = f"{door_time_elem.get_text(strip=True)} / {show_time_elem.get_text(strip=True)}"
                    elif show_time_elem:
                        event_time = show_time_elem.get_text(strip=True)

                    # Ticket URL
                    ticket_elem = container.select_one("a.seetickets-buy-btn")
                    ticket_url = ticket_elem.get("href", self.website_url) if ticket_elem else self.website_url

                    # Extract artist/headliners if available
                    headliners_elem = container.select_one("p.headliners")
                    artists = f" - {headliners_elem.get_text(strip=True)}" if headliners_elem else ""

                    events.append(VenueEvent(
                        name=f"{event_name}{artists}",
                        date=event_date,
                        time=event_time,
                        location=f"{self.venue_name}, {self.address}",
                        url=ticket_url,
                        venue_name=self.venue_name,
                        category=self.category
                    ))
                except Exception as e:
                    logger.debug(f"Subterranean: failed to parse event: {e}")

            logger.info(f"Subterranean: extracted {len(events)} events")

        except Exception as e:
            logger.error(f"Subterranean scraping failed: {e}")

        return events


class ChopShopScraper(WickerParkVenueScraper):
    """
    Chop Shop (2033 W North Ave) - Dice FM widget
    Requires Playwright for JavaScript rendering
    """

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape using Playwright to render Dice FM widget."""
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                # Headless with stealth to bypass Cloudflare anti-bot detection
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

                # Add stealth script to hide automation
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """)

                try:
                    await page.goto(self.event_page_url, timeout=15000, wait_until="networkidle")
                    await page.wait_for_timeout(1000)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Find Dice widget container with events
                    dice_container = soup.select_one("div.dice_events")
                    if not dice_container:
                        logger.debug("Chop Shop: dice_events container not found")
                        return events

                    # Get event articles from Dice widget
                    event_articles = dice_container.select("article")
                    logger.info(f"Chop Shop: found {len(event_articles)} event articles")

                    for article in event_articles:
                        try:
                            # Extract title from a.dice_event-title
                            title_link = article.select_one("a.dice_event-title")
                            if not title_link:
                                continue

                            event_name = title_link.get_text(strip=True)
                            if not event_name or len(event_name) < 2:
                                continue

                            # Extract ticket link
                            ticket_link = article.find("a", href=lambda x: x and "link.dice.fm" in x)
                            if not ticket_link:
                                ticket_link = title_link
                            ticket_url = ticket_link.get("href", self.website_url) if ticket_link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=None,  # Dice widget doesn't expose date in static HTML
                                time=None,
                                location=f"{self.venue_name}, {self.address}",
                                url=ticket_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Chop Shop: failed to parse article: {e}")

                    logger.info(f"Chop Shop: extracted {len(events)} events")

                finally:
                    await browser.close()

        except ImportError:
            logger.debug("Chop Shop: Playwright not available")
        except Exception as e:
            logger.error(f"Chop Shop Playwright scraping failed: {e}")

        return events


class EmptyBottleScraper(WickerParkVenueScraper):
    """
    Empty Bottle (1035 N Western) - Squarespace events
    Static HTML with TicketWeb ticketing
    """

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape event cards from homepage using Playwright for JS rendering."""
        import re
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")

                    # Wait for calendar event items to render
                    try:
                        await page.wait_for_selector(".show-details", timeout=5000)
                    except:
                        logger.debug("Empty Bottle: .show-details selector not found")

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Find all show event containers (.show-details elements)
                    event_items = soup.select(".show-details")
                    logger.info(f"Empty Bottle: found {len(event_items)} show details")

                    for item in event_items:
                        try:
                            # Extract event title from div.title
                            title_elem = item.select_one("div.title")
                            if not title_elem:
                                continue

                            event_title = title_elem.get_text(strip=True)
                            if not event_title or len(event_title) < 2:
                                continue

                            # Extract date from div.date
                            date_elem = item.select_one("div.date")
                            event_date = date_elem.get_text(strip=True) if date_elem else None

                            # Extract time from div.start-time
                            time_elem = item.select_one("div.start-time")
                            event_time = time_elem.get_text(strip=True) if time_elem else None

                            # Extract artist names from ul.performing li elements
                            artists = []
                            performing_list = item.select_one("ul.performing")
                            if performing_list:
                                artists = [li.get_text(strip=True) for li in performing_list.find_all("li") if li.get_text(strip=True)]

                            # Append artists to event title
                            full_title = event_title
                            if artists:
                                full_title = f"{event_title} - {', '.join(artists[:2])}"

                            # Extract venue link
                            venue_link = item.select_one("a.venue")
                            ticket_url = venue_link.get("href", self.website_url) if venue_link else self.website_url

                            events.append(VenueEvent(
                                name=full_title,
                                date=event_date,
                                time=event_time,
                                location=f"{self.venue_name}, {self.address}",
                                url=ticket_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Empty Bottle: failed to parse show: {e}")

                    logger.info(f"Empty Bottle: extracted {len(events)} events")

                finally:
                    await browser.close()

        except ImportError:
            logger.debug("Empty Bottle: Playwright not available")
        except Exception as e:
            logger.error(f"Empty Bottle scraping failed: {e}")

        return events


class DenTheatreScraper(WickerParkVenueScraper):
    """
    Den Theatre (1331 N Milwaukee) - Squarespace summary component
    Shows load dynamically via JavaScript - requires Playwright
    """

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape comedy shows using Playwright for JS rendering."""
        events = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")

                    # Wait for show content to render
                    try:
                        await page.wait_for_selector("a[href*='ovationtix']", timeout=5000)
                    except:
                        logger.debug("Den Theatre: Ovation ticket selector not found")

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Find all calendar event items (li.item elements)
                    event_items = soup.select("li.item")
                    logger.info(f"Den Theatre: found {len(event_items)} calendar items")

                    import re
                    for item in event_items:
                        try:
                            # Extract show title from span.item-title
                            title_elem = item.select_one("span.item-title")
                            if not title_elem:
                                continue

                            show_title = title_elem.get_text(strip=True)
                            if not show_title or len(show_title) < 2:
                                continue

                            # Extract time from span.item-time--12hr
                            time_elem = item.select_one("span.item-time--12hr")
                            show_time = time_elem.get_text(strip=True) if time_elem else None

                            # Extract event URL from a.item-link href
                            link_elem = item.select_one("a.item-link")
                            event_url = link_elem.get("href", "") if link_elem else ""

                            # Parse date from URL path: /calendar/YYYY/MM/DD/...
                            event_date = None
                            if event_url:
                                date_match = re.search(r'/calendar/(\d{4})/(\d{2})/(\d{2})/', event_url)
                                if date_match:
                                    year, month, day = date_match.groups()
                                    event_date = f"{month}/{day}/{year}"

                                # Make URL absolute if relative
                                if not event_url.startswith("http"):
                                    event_url = f"{self.website_url}{event_url}"
                            else:
                                event_url = self.website_url

                            events.append(VenueEvent(
                                name=show_title,
                                date=event_date,
                                time=show_time,
                                location=f"{self.venue_name}, {self.address}",
                                url=event_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Den Theatre: failed to parse calendar item: {e}")

                    logger.info(f"Den Theatre: extracted {len(events)} events")

                finally:
                    await browser.close()

        except ImportError:
            logger.debug("Den Theatre: Playwright not available")
        except Exception as e:
            logger.error(f"Den Theatre scraping failed: {e}")

        return events


async def scrape_wicker_park_venues() -> list[VenueEvent]:
    """Scrape all 4 Wicker Park venues with venue-specific strategies."""
    scrapers = [
        SubterraneanScraper(
            venue_name="Subterranean",
            website_url="https://www.subt.net",
            event_page_url="https://subt.net/",
            category="music",
            address="2011 W North Ave"
        ),
        ChopShopScraper(
            venue_name="Chop Shop",
            website_url="https://chopshopchi.com",
            event_page_url="https://chopshopchi.com/calendar/index.html",
            category="music",
            address="2033 W North Ave"
        ),
        EmptyBottleScraper(
            venue_name="Empty Bottle",
            website_url="https://www.emptybottle.com",
            event_page_url="https://www.emptybottle.com/",
            category="music",
            address="1035 N Western Ave"
        ),
        DenTheatreScraper(
            venue_name="Den Theatre",
            website_url="https://www.dentheatre.com",
            event_page_url="https://thedentheatre.com/calendar?view=calendar&month=10-2026",
            category="comedy",
            address="1331 N Milwaukee Ave"
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

    logger.info(f"Total Wicker Park events: {len(all_events)}")
    return all_events
