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
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(self.event_page_url, timeout=10000, wait_until="networkidle")

                    # Wait for Dice widget to render
                    try:
                        await page.wait_for_selector(".dice-event-item", timeout=5000)
                    except:
                        logger.debug("Chop Shop: Dice widget selector not found, trying alternatives")

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Try different selectors for Dice widget
                    event_items = soup.select(".dice-event-item")
                    if not event_items:
                        event_items = soup.select("[class*='event']")

                    logger.info(f"Chop Shop: found {len(event_items)} event items")

                    for item in event_items[:10]:
                        try:
                            # Extract event details from Dice widget
                            title_elem = item.find(["h3", "h2", "a"])
                            if not title_elem:
                                continue

                            event_name = title_elem.get_text(strip=True)
                            if len(event_name) < 2:
                                continue

                            # Look for date info
                            date_elem = item.find(["span", "p"], class_=lambda x: x and "date" in x.lower() if x else False)
                            event_date = date_elem.get_text(strip=True) if date_elem else None

                            # Find ticket link
                            ticket_link = item.find("a", href=lambda x: x and "dice.fm" in x)
                            ticket_url = ticket_link.get("href", self.website_url) if ticket_link else self.website_url

                            events.append(VenueEvent(
                                name=event_name,
                                date=event_date,
                                time=None,
                                location=f"{self.venue_name}, {self.address}",
                                url=ticket_url,
                                venue_name=self.venue_name,
                                category=self.category
                            ))
                        except Exception as e:
                            logger.debug(f"Chop Shop: failed to parse event: {e}")

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
        """Scrape Squarespace event items."""
        events = []
        try:
            response = await client.get(self.event_page_url, timeout=10)
            if response.status_code != 200:
                logger.warning(f"Empty Bottle: got {response.status_code}")
                return events

            soup = BeautifulSoup(response.text, "html.parser")

            # Squarespace event collection selectors
            event_items = soup.select(".event-item")
            if not event_items:
                event_items = soup.select("[data-item-id]")

            logger.info(f"Empty Bottle: found {len(event_items)} event items")

            for item in event_items:
                try:
                    # Extract event title
                    title_elem = item.select_one(".event-title") or item.find("h3")
                    if not title_elem:
                        continue

                    event_name = title_elem.get_text(strip=True)

                    # Extract date
                    date_elem = item.select_one(".event-date")
                    event_date = date_elem.get_text(strip=True) if date_elem else None

                    # Extract time
                    time_elem = item.select_one(".event-time")
                    event_time = time_elem.get_text(strip=True) if time_elem else None

                    # Extract ticket link (TicketWeb)
                    ticket_elem = item.find("a", href=lambda x: x and ("ticketweb" in x.lower() or "tickets" in x.lower()))
                    ticket_url = ticket_elem.get("href", self.website_url) if ticket_elem else self.website_url

                    events.append(VenueEvent(
                        name=event_name,
                        date=event_date,
                        time=event_time,
                        location=f"{self.venue_name}, {self.address}",
                        url=ticket_url,
                        venue_name=self.venue_name,
                        category=self.category
                    ))
                except Exception as e:
                    logger.debug(f"Empty Bottle: failed to parse event: {e}")

            logger.info(f"Empty Bottle: extracted {len(events)} events")

        except Exception as e:
            logger.error(f"Empty Bottle scraping failed: {e}")

        return events


class DenTheatreScraper(WickerParkVenueScraper):
    """
    Den Theatre (1331 N Milwaukee) - Squarespace comedy/tickets
    Static HTML with Ovation Ticketing
    """

    async def scrape_events(self, client: httpx.AsyncClient) -> list[VenueEvent]:
        """Scrape Squarespace event items for comedy shows."""
        events = []
        try:
            # Follow redirects to final URL
            response = await client.get(self.event_page_url, timeout=10, follow_redirects=True)
            if response.status_code != 200:
                logger.warning(f"Den Theatre: got {response.status_code}")
                return events

            soup = BeautifulSoup(response.text, "html.parser")

            # Squarespace event collection selectors (similar to Empty Bottle)
            event_items = soup.select(".event-item")
            if not event_items:
                event_items = soup.select("[data-event-id]")

            logger.info(f"Den Theatre: found {len(event_items)} event items")

            for item in event_items:
                try:
                    # Extract event title (comedy shows)
                    title_elem = item.select_one(".event-title a") or item.select_one(".event-title") or item.find("h3")
                    if not title_elem:
                        continue

                    event_name = title_elem.get_text(strip=True)

                    # Extract date
                    date_elem = item.select_one(".event-date")
                    event_date = date_elem.get_text(strip=True) if date_elem else None

                    # Extract ticket link (Ovation)
                    ticket_elem = item.find("a", href=lambda x: x and ("ovationtix" in x.lower() or "tickets" in x.lower()))
                    ticket_url = ticket_elem.get("href", self.website_url) if ticket_elem else self.website_url

                    events.append(VenueEvent(
                        name=event_name,
                        date=event_date,
                        time=None,
                        location=f"{self.venue_name}, {self.address}",
                        url=ticket_url,
                        venue_name=self.venue_name,
                        category=self.category
                    ))
                except Exception as e:
                    logger.debug(f"Den Theatre: failed to parse event: {e}")

            logger.info(f"Den Theatre: extracted {len(events)} events")

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
            event_page_url="https://www.emptybottle.com/ebp-events",
            category="music",
            address="1035 N Western Ave"
        ),
        DenTheatreScraper(
            venue_name="Den Theatre",
            website_url="https://www.dentheatre.com",
            event_page_url="https://thedentheatre.com/tickets-1",
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
