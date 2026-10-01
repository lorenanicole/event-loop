"""
Unified Chicago Events Scraper - ALL neighborhoods/venues, iteratively refined.
"""

import httpx
import logging
from dataclasses import dataclass
from typing import Optional, Callable
from bs4 import BeautifulSoup
from src.scrapers.venue_scraper import VenueScraper, VenueConfig, VenueEvent
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== CUSTOM EXTRACTORS =====

def extract_chop_shop(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Dice FM widget extraction."""
    events = []
    try:
        dice_container = soup.select_one("div.dice_events")
        if not dice_container:
            return events

        for article in dice_container.select("article"):
            title_link = article.select_one("a.dice_event-title")
            if not title_link:
                continue

            event_name = title_link.get_text(strip=True)
            if not event_name or len(event_name) < 2:
                continue

            ticket_link = article.find("a", href=lambda x: x and "link.dice.fm" in x)
            ticket_url = ticket_link.get("href", config.website_url) if ticket_link else config.website_url

            events.append(VenueEvent(
                name=event_name, date=None, time=None,
                location=f"{config.name}, {config.address}",
                url=ticket_url, venue_name=config.name, category=config.category
            ))
        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_outset(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Outset WordPress h3.listing__title extraction."""
    events = []
    try:
        event_items = soup.select("h3")
        logger.info(f"{config.name}: found {len(event_items)} h3 elements")

        for item in event_items:
            parent = item.parent
            if not parent or "listing__title" not in parent.get("class", []):
                continue

            event_name = item.get_text(strip=True)
            if not event_name or len(event_name) < 2:
                continue

            event_date = None
            for sibling in item.find_all_next(limit=10):
                if sibling.name == "h3":
                    break
                sibling_text = sibling.get_text(strip=True)
                if "•" in sibling_text or re.search(r'\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', sibling_text):
                    event_date = sibling_text
                    break

            events.append(VenueEvent(
                name=event_name, date=event_date, time=None,
                location=f"{config.name}, {config.address}",
                url=config.website_url, venue_name=config.name, category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_salt_shed(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Salt Shed - filter out navigation h2/h3."""
    events = []
    try:
        event_items = soup.select("h2, h3")
        logger.info(f"{config.name}: found {len(event_items)} heading elements")

        skip_terms = ["menu", "more", "about", "contact", "news", "follow", "social", "booking",
                      "newsletter", "signup", "subscribe", "home", "gallery", "press",
                      "your privacy", "your favorites", "favourite", "cart", "checkout"]

        for item in event_items:
            text = item.get_text(strip=True)
            if not text or len(text) < 3:
                continue
            if any(skip in text.lower() for skip in skip_terms):
                continue

            events.append(VenueEvent(
                name=text, date=None, time=None,
                location=f"{config.name}, {config.address}",
                url=config.website_url, venue_name=config.name, category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_concord(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Concord & similar - extract from [class*='show'] and article elements."""
    events = []
    try:
        event_containers = soup.select("[class*='show'], article")
        logger.info(f"{config.name}: found {len(event_containers)} containers")

        for container in event_containers:
            text = container.get_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]

            if not lines:
                continue

            event_name = None
            event_date = None

            for line in lines:
                if line == "Selling Fast" or not event_name:
                    if line != "Selling Fast" and len(line) > 3:
                        if not any(x in line for x in ['Doors', 'doors', 'age']):
                            event_name = line
                            break

            for line in lines:
                if re.search(r'\d{1,2}/\d{1,2}', line):
                    event_date = line
                    break

            if event_name and len(event_name) > 3:
                events.append(VenueEvent(
                    name=event_name, date=event_date, time=None,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url, venue_name=config.name, category=config.category
                ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_generic_li(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Generic extractor for venues using li elements for event listings."""
    events = []
    try:
        event_containers = soup.select("li")
        logger.info(f"{config.name}: found {len(event_containers)} li elements")

        for container in event_containers:
            text = container.get_text(strip=True)
            if not text or len(text) < 3:
                continue

            skip_terms = ['menu', 'sidebar', 'nav', 'footer', 'home', 'login', 'cart']
            if any(skip in text.lower() for skip in skip_terms):
                continue

            events.append(VenueEvent(
                name=text[:200], date=None, time=None,
                location=f"{config.name}, {config.address}",
                url=config.event_page_url or config.website_url,
                venue_name=config.name, category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from li")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_generic_item_class(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Generic extractor for venues using [class*='item'] for event listings."""
    events = []
    try:
        event_containers = soup.select("[class*='item']")
        logger.info(f"{config.name}: found {len(event_containers)} [class*='item'] elements")

        for container in event_containers:
            text = container.get_text(strip=True)
            if not text or len(text) < 3:
                continue

            skip_terms = ['menu', 'sidebar', 'nav', 'footer', 'home', 'login', 'cart']
            if any(skip in text.lower() for skip in skip_terms):
                continue

            events.append(VenueEvent(
                name=text[:200], date=None, time=None,
                location=f"{config.name}, {config.address}",
                url=config.event_page_url or config.website_url,
                venue_name=config.name, category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from [class*='item']")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


def extract_rosas_lounge(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Rosa's Lounge - extract from li a (event list links)."""
    events = []
    try:
        # Rosa's uses li > a structure for event listings
        event_links = soup.select("li a")
        logger.info(f"{config.name}: found {len(event_links)} event links")

        for link in event_links:
            text = link.get_text(strip=True)

            # Event names are substantial text
            if not text or len(text) < 2:
                continue

            # Skip navigation links
            skip_terms = ['Home', 'Login', 'Sign up', 'back', 'next', 'cart', 'search', 'checkout']
            if any(term in text for term in skip_terms):
                continue

            # Extract URL if available
            url = link.get("href", config.website_url)
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            # This is an event name
            events.append(VenueEvent(
                name=text,
                date=None,  # Dates not exposed in static calendar
                time=None,
                location=f"{config.name}, {config.address}",
                url=url if url != config.website_url else config.website_url,
                venue_name=config.name,
                category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events


# ===== NEIGHBORHOOD CONFIGS =====

CHICAGO_VENUES = {
    "Loop": [
        VenueConfig(
            name="Chicago Theatre",
            website_url="https://www.thechicagotheatre.com",
            event_page_url="https://www.msg.com/calendar?venues=KovZpZA6AJ6A",
            category="theater",
            address="175 N State St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_item_class,
        ),
        VenueConfig(
            name="Jazz Showcase",
            website_url="https://www.jazzshowcase.com",
            event_page_url="https://www.jazzshowcase.com/calendar",
            category="music",
            address="806 S Plymouth Ct",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_li,
        ),
        VenueConfig(
            name="Auditorium Theatre",
            website_url="https://www.auditoriumtheatre.org",
            event_page_url="https://www.auditoriumtheatre.org/events",
            category="theater",
            address="50 E Congress Pkwy",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_li,
        ),
        VenueConfig(
            name="CIBC Theatre",
            website_url="https://www.broadwayinchicago.com",
            event_page_url="https://www.broadwayinchicago.com/cibc",
            category="theater",
            address="18 W Monroe St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_item_class,
        ),
        VenueConfig(
            name="Goodman Theatre",
            website_url="https://www.goodmantheatre.org",
            event_page_url="https://www.goodmantheatre.org/plays",
            category="theater",
            address="170 N Dearborn St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_li,
        ),
        VenueConfig(
            name="House of Blues Chicago",
            website_url="https://www.houseofblues.com/chicago",
            event_page_url="https://www.houseofblues.com/chicago/events",
            category="music",
            address="329 N Dearborn St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_li,
        ),
        VenueConfig(
            name="Civic Opera House",
            website_url="https://www.lyricopera.org",
            event_page_url="https://www.lyricopera.org/season",
            category="theater",
            address="20 N Wacker Dr",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_li,
        ),
        VenueConfig(
            name="Jay Pritzker Pavilion",
            website_url="https://www.millenniumparkpavilion.org",
            event_page_url="https://www.millenniumparkpavilion.org/events",
            category="music",
            address="201 E Randolph St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_item_class,
        ),
    ],

    "Wicker Park": [
        VenueConfig(
            name="Subterranean",
            website_url="https://www.subt.net",
            event_page_url="https://subt.net/",
            category="music",
            address="2011 W North Ave",
            selectors={"event_container": "li.seetickets-list-event-container", "title": "p.event-title a", "date": "p.event-date"}
        ),
        VenueConfig(
            name="Chop Shop",
            website_url="https://chopshopchi.com",
            event_page_url="https://chopshopchi.com/calendar/index.html",
            category="music",
            address="2033 W North Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_chop_shop,
        ),
        VenueConfig(
            name="Empty Bottle",
            website_url="https://www.emptybottle.com",
            event_page_url="https://www.emptybottle.com/",
            category="music",
            address="1035 N Western Ave",
            selectors={"event_container": ".show-details", "title": "div.title", "date": "div.date"},
            use_playwright=True,
        ),
        VenueConfig(
            name="Den Theatre",
            website_url="https://www.dentheatre.com",
            event_page_url="https://thedentheatre.com/calendar?view=calendar&month=10-2026",
            category="comedy",
            address="1331 N Milwaukee Ave",
            selectors={"event_container": "li.item", "title": "span.item-title", "time": "span.item-time--12hr"},
            use_playwright=True,
        ),
        VenueConfig(
            name="Rosa's Lounge",
            website_url="https://www.rosaslounge.com",
            event_page_url="https://www.rosaslounge.com/calendar",
            category="music",
            address="3420 W Armitage Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_rosas_lounge,
        ),
    ],

    "Bucktown": [
        VenueConfig(
            name="The Hideout",
            website_url="https://www.hideoutchicago.com",
            event_page_url="https://www.hideoutchicago.com/shows",
            category="music",
            address="1354 W Wabansia Ave",
            selectors={"event_container": ".show-collection-item", "title": ".show-name", "date": ".show-start-date"}
        ),
        VenueConfig(
            name="Concord Music Hall",
            website_url="https://concordmusichall.com",
            event_page_url="https://concordmusichall.com/calendar/",
            category="music",
            address="2047 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_concord,
        ),
        VenueConfig(
            name="Salt Shed",
            website_url="https://www.saltshedchicago.com",
            event_page_url="https://www.saltshedchicago.com/",
            category="music",
            address="1357 N Elston Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_salt_shed,
        ),
        VenueConfig(
            name="Outset",
            website_url="https://outsetlive.com",
            event_page_url="https://outsetlive.com/events/",
            category="music",
            address="1675 N Elston Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_outset,
        ),
    ],

    "Avondale": [
        VenueConfig(
            name="Rockwell on the River",
            website_url="https://www.rockwellontheriver.com",
            event_page_url="https://www.rockwellontheriver.com/calendar/",
            category="music",
            address="3757 N Rockwell Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_salt_shed,
        ),
    ],

    "Rogers Park": [
        VenueConfig(
            name="Loyola University Performing Arts Center",
            website_url="https://www.luc.edu/performingarts",
            event_page_url="https://www.luc.edu/performingarts/calendar",
            category="theater",
            address="6525 N Sheridan Rd",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Rogers Park Music Venue",
            website_url="https://www.rogersparkcenter.org",
            event_page_url="https://www.rogersparkcenter.org/events",
            category="music",
            address="7211 N Clark St",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Uptown": [
        VenueConfig(
            name="Byline Bank Aragon Ballroom",
            website_url="https://www.aragonchicago.com",
            event_page_url="https://www.aragonchicago.com/events",
            category="music",
            address="1106 W Lawrence Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Riviera Theatre",
            website_url="https://www.rivierachicago.com",
            event_page_url="https://www.rivierachicago.com/events",
            category="music",
            address="4746 N Broadway St",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Lincoln Square": [
        VenueConfig(
            name="Lincoln Theatre",
            website_url="https://www.lincolntheatre.org",
            event_page_url="https://www.lincolntheatre.org/calendar",
            category="theater",
            address="4415 N Lincoln Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Old Town School of Folk Music",
            website_url="https://www.oldtownschool.org",
            event_page_url="https://www.oldtownschool.org/events",
            category="music",
            address="4544 N Lincoln Ave",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Lakeview": [
        VenueConfig(
            name="Schubas Tavern",
            website_url="https://www.schubastavern.com",
            event_page_url="https://www.schubastavern.com/events",
            category="music",
            address="3159 N Southport Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="The Vic Theatre",
            website_url="https://www.thevictheatre.com",
            event_page_url="https://www.thevictheatre.com/events",
            category="music",
            address="3145 N Sheffield Ave",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Logan Square": [
        VenueConfig(
            name="Lincoln Hall",
            website_url="https://www.lincolnhallchicago.com",
            event_page_url="https://www.lincolnhallchicago.com/events",
            category="music",
            address="2424 N Lincoln Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Thalia Hall",
            website_url="https://www.thaliahall.com",
            event_page_url="https://www.thaliahall.com/events",
            category="music",
            address="1807 S Allport St",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Humboldt Park": [
        VenueConfig(
            name="Martyrs'",
            website_url="https://www.martyrschicago.com",
            event_page_url="https://www.martyrschicago.com/events",
            category="music",
            address="3855 N Lincoln Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="The Loft on Lake",
            website_url="https://www.theloftonlake.com",
            event_page_url="https://www.theloftonlake.com/events",
            category="music",
            address="3453 W Lake St",
            selectors={},
            use_playwright=True,
        ),
    ],

    "West Town": [
        VenueConfig(
            name="Morgan Manufacturing",
            website_url="https://www.morganmanufacturing.com",
            event_page_url="https://www.morganmanufacturing.com/events",
            category="music",
            address="401 N Spaulding Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Morgan Ballroom",
            website_url="https://www.morganballroom.com",
            event_page_url="https://www.morganballroom.com/events",
            category="music",
            address="401 N Spaulding Ave",
            selectors={},
            use_playwright=True,
        ),
    ],

    "West Loop": [
        VenueConfig(
            name="Green Dolphin Street",
            website_url="https://www.greendolphinchicago.com",
            event_page_url="https://www.greendolphinchicago.com/events",
            category="music",
            address="2200 N Ashland Ave",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Morgan Manufacturing West",
            website_url="https://www.morganmanufacturing.com",
            event_page_url="https://www.morganmanufacturing.com/events",
            category="music",
            address="401 N Spaulding Ave",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Near West Side": [
        VenueConfig(
            name="United Center",
            website_url="https://www.unitedcenter.com",
            event_page_url="https://www.unitedcenter.com/events",
            category="music",
            address="1901 W Madison St",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Uptown": [
        VenueConfig(
            name="Green Mill Jazz Club",
            website_url="https://www.greenmilljazz.com",
            event_page_url="https://greenmilljazz.com/calendar/",
            category="music",
            address="4802 N Broadway Ave",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Lincoln Park": [
        VenueConfig(
            name="Steppenwolf Theatre Company",
            website_url="https://www.steppenwolf.org",
            event_page_url="https://www.steppenwolf.org/whats-on/current-season",
            category="theater",
            address="1650 N Halsted St",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Second City",
            website_url="https://www.secondcity.com",
            event_page_url="https://www.secondcity.com/shows",
            category="comedy",
            address="1616 N Wells St",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Lake View": [
        VenueConfig(
            name="Metro Chicago",
            website_url="https://www.metrochicago.com",
            event_page_url="https://www.metrochicago.com/events",
            category="music",
            address="3730 N Clark St",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="The Vic Theatre",
            website_url="https://www.victheater.com",
            event_page_url="https://www.victheater.com/events",
            category="music",
            address="3145 N Sheffield Ave",
            selectors={},
            use_playwright=True,
        ),
    ],

    "Lincoln Square": [
        VenueConfig(
            name="Old Town School of Folk Music",
            website_url="https://www.oldtownschool.org",
            event_page_url="https://www.oldtownschool.org/events",
            category="music",
            address="4544 N Lincoln Ave",
            selectors={},
            use_playwright=True,
        ),
    ],
}


async def scrape_chicago_events() -> dict[str, list[VenueEvent]]:
    """Scrape ALL Chicago neighborhoods/venues."""
    results = {}
    total_events = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for neighborhood, venues in CHICAGO_VENUES.items():
            logger.info(f"\n{'='*60}")
            logger.info(f"Scraping {neighborhood} ({len(venues)} venues)")
            logger.info('='*60)

            neighborhood_events = []
            for config in venues:
                try:
                    scraper = VenueScraper(config)
                    events = await scraper.scrape(client)
                    neighborhood_events.extend(events)
                    total_events += len(events)
                except Exception as e:
                    logger.error(f"Error scraping {config.name}: {e}")

            results[neighborhood] = neighborhood_events
            logger.info(f"{neighborhood}: {len(neighborhood_events)} total events\n")

    logger.info(f"\n{'='*60}")
    logger.info(f"✅ TOTAL CHICAGO EVENTS: {total_events}")
    logger.info('='*60)

    for neighborhood in sorted(results.keys()):
        events = results[neighborhood]
        by_venue = {}
        for e in events:
            by_venue.setdefault(e.venue_name, []).append(e)

        print(f"\n{neighborhood}: {len(events)} events")
        for venue in sorted(by_venue.keys()):
            print(f"  • {venue}: {len(by_venue[venue])}")

    return results


if __name__ == "__main__":
    import asyncio
    asyncio.run(scrape_chicago_events())
