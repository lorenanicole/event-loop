"""
Unified Chicago Events Scraper - ALL neighborhoods/venues, iteratively refined.
"""

import httpx
import logging
from dataclasses import dataclass
from typing import Optional, Callable
from bs4 import BeautifulSoup
from .venue_scraper import VenueScraper, VenueConfig, VenueEvent
import re
import asyncio
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from shared.database.models import EventModel, VenueModel, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_date_range(date_str: Optional[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse date string to start and end dates. Returns (start_date, end_date)."""
    if not date_str or not date_str.strip():
        return None, None

    date_str = date_str.strip()

    try:
        # Try ISO format first: "2026-10-06T04:59:00+00:00" or "2026-10-06T04:59:00Z"
        try:
            # Handle Z timezone
            iso_str = date_str.replace('Z', '+00:00')
            start = datetime.fromisoformat(iso_str)
            return start, None
        except (ValueError, AttributeError):
            pass

        # Try date range: "Oct 23 - 27, 2026"
        range_match = re.search(r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s+(\d{4})', date_str)
        if range_match:
            month_str = range_match.group(1)
            start_day = range_match.group(2)
            end_day = range_match.group(3)
            year = range_match.group(4)
            try:
                start = datetime.strptime(f"{month_str} {start_day} {year}", "%b %d %Y")
                end = datetime.strptime(f"{month_str} {end_day} {year}", "%b %d %Y")
                return start, end
            except ValueError:
                pass

        # Try two-month range: "Oct 1 – Nov 4, 2026"
        multi_month = re.search(
            r'(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s+(\d{4})',
            date_str
        )
        if multi_month:
            start_month = multi_month.group(1)
            start_day = multi_month.group(2)
            end_month = multi_month.group(3)
            end_day = multi_month.group(4)
            year = multi_month.group(5)
            try:
                start = datetime.strptime(f"{start_month} {start_day} {year}", "%b %d %Y")
                end = datetime.strptime(f"{end_month} {end_day} {year}", "%b %d %Y")
                return start, end
            except ValueError:
                pass

        # Try single date: "Oct 2, 2026" or "October 3, 2026"
        for fmt in ["%B %d, %Y", "%b %d, %Y", "%a, %b %d, %Y", "%b %d %Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                date_only = date_str.split("-")[0].split("–")[0].strip()
                start = datetime.strptime(date_only, fmt)
                return start, None
            except ValueError:
                continue

        # Try date without year: "Oct 4" or "Mon October 5" (assume current/next year)
        # Handle weekday: "Mon October 5"
        weekday_date = re.search(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+)\s+(\d{1,2})', date_str)
        if weekday_date:
            month_str = weekday_date.group(1)
            day_str = weekday_date.group(2)
            for year in [2026, 2027]:
                for fmt in ["%B %d %Y", "%b %d %Y"]:
                    try:
                        start = datetime.strptime(f"{month_str} {day_str} {year}", fmt)
                        return start, None
                    except ValueError:
                        continue

        # Try date without year: "Oct 4" (assume current/next year)
        short_date = re.search(r'(\w+)\s+(\d{1,2})', date_str)
        if short_date:
            month_str = short_date.group(1)
            day_str = short_date.group(2)
            # Assume current year (2026) - Jazz Showcase uses abbreviated dates for upcoming shows
            for year in [2026, 2027]:
                try:
                    start = datetime.strptime(f"{month_str} {day_str} {year}", "%b %d %Y")
                    return start, None
                except ValueError:
                    continue

        logger.debug(f"Could not parse date: {date_str}")
        return None, None

    except Exception as e:
        logger.debug(f"Date parsing error for '{date_str}': {e}")
        return None, None


def extract_events_from_json_ld(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from JSON-LD schema.org data embedded in HTML."""
    events = []
    try:
        # Find all JSON-LD script tags
        for script in soup.find_all('script', {'type': 'application/ld+json'}):
            try:
                data = json.loads(script.string)

                # Handle @graph wrapper
                if '@graph' in data:
                    items = data['@graph']
                elif isinstance(data, list):
                    items = data
                else:
                    items = [data]

                # Extract events from the structure
                for item in items:
                    # Check if it's an Event or contains Events
                    if item.get('@type') == 'Event':
                        event_data = item
                    elif item.get('@type') == 'Place' and 'Events' in item:
                        # Handle Place with Events array
                        for event_data in item.get('Events', []):
                            if event_data.get('@type') != 'Event':
                                continue

                            name = event_data.get('name', '').strip()
                            if not name or len(name) < 2:
                                continue

                            # Parse ISO datetime: "2026-10-06T04:59:00Z"
                            start_date = None
                            end_date = None

                            if 'startDate' in event_data:
                                try:
                                    dt = datetime.fromisoformat(
                                        event_data['startDate'].replace('Z', '+00:00')
                                    )
                                    start_date = dt
                                except (ValueError, AttributeError):
                                    pass

                            if 'endDate' in event_data:
                                try:
                                    dt = datetime.fromisoformat(
                                        event_data['endDate'].replace('Z', '+00:00')
                                    )
                                    end_date = dt
                                except (ValueError, AttributeError):
                                    pass

                            url = event_data.get('url', config.website_url)

                            events.append(VenueEvent(
                                name=name,
                                date=start_date.isoformat() if start_date else None,
                                date_end=end_date.isoformat() if end_date else None,
                                time=None,
                                location=f"{config.name}, {config.address}",
                                url=url,
                                venue_name=config.name,
                                category=config.category
                            ))
                        continue
                    else:
                        continue

                    # Handle single Event item
                    name = event_data.get('name', '').strip()
                    if not name or len(name) < 2:
                        continue

                    start_date = None
                    end_date = None

                    if 'startDate' in event_data:
                        try:
                            dt = datetime.fromisoformat(
                                event_data['startDate'].replace('Z', '+00:00')
                            )
                            start_date = dt
                        except (ValueError, AttributeError):
                            pass

                    if 'endDate' in event_data:
                        try:
                            dt = datetime.fromisoformat(
                                event_data['endDate'].replace('Z', '+00:00')
                            )
                            end_date = dt
                        except (ValueError, AttributeError):
                            pass

                    url = event_data.get('url')
                    if not url:
                        slug = re.sub(r'[^\w\s-]', '', name).replace(' ', '-').lower()
                        url = f"{config.website_url.rstrip('/')}#{slug}"

                    events.append(VenueEvent(
                        name=name,
                        date=start_date.isoformat() if start_date else None,
                        date_end=end_date.isoformat() if end_date else None,
                        time=None,
                        location=f"{config.name}, {config.address}",
                        url=url,
                        venue_name=config.name,
                        category=config.category
                    ))

            except (json.JSONDecodeError, AttributeError, KeyError) as e:
                logger.debug(f"{config.name}: Error parsing JSON-LD: {e}")
                continue

        logger.info(f"{config.name}: extracted {len(events)} events from JSON-LD")
        return events

    except Exception as e:
        logger.error(f"{config.name}: JSON-LD extraction failed: {e}")
        return events


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


def extract_concord(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Concord & similar - extract from [class*='show'] and article elements."""
    events = []
    try:
        event_containers = soup.select("[class*='show'], article")
        logger.info(f"{config.name}: found {len(event_containers)} containers")

        for idx, container in enumerate(event_containers):
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
                # Extract event URL: look for link in container, fall back to generated URL
                event_url = config.website_url
                link = container.find('a', href=True)
                if link and link.get('href'):
                    href = link.get('href')
                    if href.startswith('/'):
                        event_url = config.website_url.rstrip('/') + href
                    elif href.startswith('http'):
                        event_url = href
                else:
                    slug = re.sub(r'[^\w\s-]', '', event_name).replace(' ', '-').lower()
                    event_url = f"{config.website_url.rstrip('/')}#{slug}-{idx}"

                events.append(VenueEvent(
                    name=event_name, date=event_date, time=None,
                    location=f"{config.name}, {config.address}",
                    url=event_url, venue_name=config.name, category=config.category
                ))

        logger.info(f"{config.name}: extracted {len(events)} events")
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


def extract_hideout(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from The Hideout's show-name/show-start-date structure."""
    events = []
    try:
        show_items = soup.select("div.show-collection-item, div.w-dyn-item")
        logger.info(f"{config.name}: found {len(show_items)} show items")

        for idx, item in enumerate(show_items):
            name_elem = item.select_one("div.show-name")
            date_elem = item.select_one("div.show-start-date")

            if not name_elem:
                continue

            name = name_elem.get_text(strip=True)
            if not name or len(name) < 2:
                continue

            date_str = date_elem.get_text(strip=True) if date_elem else None

            # Extract event URL: look for link in item, fall back to generated URL
            event_url = config.website_url
            link = item.find('a', href=True)
            if link and link.get('href'):
                href = link.get('href')
                if href.startswith('/'):
                    event_url = config.website_url.rstrip('/') + href
                elif href.startswith('http'):
                    event_url = href
            else:
                slug = re.sub(r'[^\w\s-]', '', name).replace(' ', '-').lower()
                event_url = f"{config.website_url.rstrip('/')}#{slug}-{idx}"

            events.append(VenueEvent(
                name=name,
                date=date_str,  # "October 3, 2026" format
                time=None,
                location=f"{config.name}, {config.address}",
                url=event_url,
                venue_name=config.name,
                category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")

    return events



def extract_jamusa_events(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Jam Presents/Jamusa.com venues (Park West, Riviera Theatre)."""
    import re
    events = []
    try:
        # Jam Presents uses div.eventItem containers
        containers = soup.select('div.eventItem')

        for container in containers:
            text = container.get_text(strip=True)

            # Date format: "Oct7Wed" or "Oct23Mon"
            date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{1,2})\w{3}', text)
            if not date_match:
                continue

            month = date_match.group(1)
            day = date_match.group(2)

            # Extract title - look for artist name after "Jam Presents"
            title_match = re.search(r'Jam Presents(.+?)(?:with |Doors:|$)', text)
            if title_match:
                title = title_match.group(1).strip()
                if len(title) > 3 and len(title) < 200:
                    events.append(VenueEvent(
                        name=title,
                        date=f"{month} {day}, 2026",
                        time=None,
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,
                        venue_name=config.name,
                        category=config.category
                    ))

        logger.info(f"{config.name}: extracted {len(events)} events from Jam Presents")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_generic_javascript_events(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Generic extractor for JavaScript-rendered event pages using Playwright."""
    import re
    events = []
    try:
        # More permissive container selectors - cast wider net
        for selector in ['div', '[class*="event"]', 'article', '.show', '.item', 'li']:
            containers = soup.select(selector)
            if not containers:
                continue

            for container in containers:
                text = container.get_text(strip=True)

                # Skip empty or very short text
                if len(text) < 20 or len(text) > 2000:
                    continue

                # Look for date pattern (month + day)
                date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})', text)
                if not date_match:
                    continue

                # Extract title - take first substantial line
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                title = None
                for line in lines:
                    if 8 <= len(line) <= 200 and not line.startswith('http'):
                        title = line
                        break

                if title:
                    events.append(VenueEvent(
                        name=title,
                        date=f"{date_match.group(1)} {date_match.group(2)}, 2026",
                        time=None,
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,
                        venue_name=config.name,
                        category=config.category
                    ))

        # Deduplicate by title
        seen = set()
        unique_events = []
        for e in events:
            key = (e.name, e.date)
            if key not in seen:
                seen.add(key)
                unique_events.append(e)

        logger.info(f"{config.name}: extracted {len(unique_events)} events from rendered HTML")
        return unique_events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_zanies_calendar(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from FullCalendar grid (Zanies uses calendar widget)."""
    events = []
    # Note: This extractor runs AFTER Playwright renders, so calendar data is in HTML
    try:
        # Get all calendar day cells with data-date attribute
        day_cells = soup.select('[data-date]')

        for cell in day_cells:
            date_str = cell.get('data-date')

            # Get events in this cell
            event_titles = cell.select('[class*="event-title"], .fc-event-title')

            for event_el in event_titles:
                text = event_el.get_text(strip=True)
                if not text or 'Timezone' in text:
                    continue

                # Parse title and time
                lines = text.split('\n')
                title = lines[0].strip()

                # Find time (HH:MM AM/PM pattern)
                time_str = None
                for line in lines:
                    if ':' in line and ('AM' in line.upper() or 'PM' in line.upper()):
                        time_str = line.strip()
                        break

                # Parse date to datetime
                try:
                    parsed_date = datetime.fromisoformat(date_str)
                except:
                    parsed_date = None

                events.append(VenueEvent(
                    name=title,
                    date=parsed_date.isoformat() if parsed_date else None,
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url,  # No individual event URLs, use venue URL
                    venue_name=config.name,
                    category=config.category
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from calendar")
    except Exception as e:
        logger.error(f"{config.name} calendar extraction failed: {e}")

    return events


def extract_squarespace_events(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Squarespace li[class*='item'] structure."""
    events = []
    try:
        event_items = soup.select("li[class*='item']")
        logger.info(f"{config.name}: found {len(event_items)} event items")

        for idx, item in enumerate(event_items):
            text = item.get_text(strip=True)
            if not text or len(text) < 3:
                continue

            # Skip navigation and UI items
            skip_terms = ['home', 'calendar', 'faqs', 'faq', 'contact', 'about', 'menu', 'search',
                         'login', 'signup', 'cart', 'checkout', 'gallery', 'photos', 'videos',
                         'news', 'blog', 'press', 'instagram', 'facebook', 'twitter', 'social']
            if any(term in text.lower() for term in skip_terms):
                continue

            # Also skip month names if very short (likely navigation)
            if any(month in text.lower() for month in
                   ['january', 'february', 'march', 'april', 'may', 'june',
                    'july', 'august', 'september', 'october', 'november', 'december']):
                if len(text) < 20:
                    continue

            # Extract time
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))', text)
            time_str = time_match.group(1) if time_match else None
            event_name = re.sub(r'^\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)\s*', '', text).strip()

            # Extract date
            date_str = None
            ends_match = re.search(r'\(ends?\s+(.+?)\)', event_name, re.IGNORECASE)
            if ends_match:
                date_str = ends_match.group(1).strip()
                event_name = re.sub(r'\(ends?.+?\)', '', event_name).strip()

            if not event_name or len(event_name) < 2:
                continue

            # Extract event URL: look for link in item, fall back to website URL
            event_url = config.website_url
            link = item.find('a', href=True)
            if link and link.get('href'):
                href = link.get('href')
                # Convert relative URLs to absolute
                if href.startswith('/'):
                    event_url = config.website_url.rstrip('/') + href
                elif href.startswith('http'):
                    event_url = href

            events.append(VenueEvent(
                name=event_name, date=date_str, time=time_str,
                location=f"{config.name}, {config.address}",
                url=event_url, venue_name=config.name,
                category=config.category
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events

CHICAGO_VENUES = {
    "Loop": [
        VenueConfig(
            name="Chicago Theatre",
            website_url="https://www.thechicagotheatre.com",
            event_page_url="https://www.thechicagotheatre.com",
            category="theater",
            address="175 N State St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Jazz Showcase",
            website_url="https://www.jazzshowcase.com",
            event_page_url="https://www.jazzshowcase.com/calendar",
            category="music",
            address="806 S Plymouth Ct",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_squarespace_events,
        ),
        VenueConfig(
            name="Auditorium Theatre",
            website_url="https://www.auditoriumtheatre.org",
            event_page_url="https://www.auditoriumtheatre.org/events",
            category="theater",
            address="50 E Congress Pkwy",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_javascript_events,
        ),
        VenueConfig(
            name="CIBC Theatre",
            website_url="https://www.broadwayinchicago.com",
            event_page_url="https://www.broadwayinchicago.com/cibc",
            category="theater",
            address="18 W Monroe St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Goodman Theatre",
            website_url="https://www.goodmantheatre.org",
            event_page_url="https://www.goodmantheatre.org/plays",
            category="theater",
            address="170 N Dearborn St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="House of Blues Chicago",
            website_url="https://www.houseofblues.com/chicago",
            event_page_url="https://www.houseofblues.com/chicago/events",
            category="music",
            address="329 N Dearborn St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Civic Opera House",
            website_url="https://www.lyricopera.org",
            event_page_url="https://www.lyricopera.org/season",
            category="theater",
            address="20 N Wacker Dr",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Jay Pritzker Pavilion",
            website_url="https://www.millenniumparkpavilion.org",
            event_page_url="https://www.millenniumparkpavilion.org/events",
            category="music",
            address="201 E Randolph St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Buddy Guy's Legends",
            website_url="https://buddyguy.com",
            event_page_url="https://buddyguy.com/",
            category="music",
            address="700 S Wabash Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="James M. Nederlander Theatre",
            website_url="https://www.jimmynet.com",
            event_page_url="https://www.jimmynet.com/events",
            category="theater",
            address="24 W Randolph St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
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
            extractor_fn=extract_events_from_json_ld,
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
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Rosa's Lounge",
            website_url="https://www.rosaslounge.com",
            event_page_url="https://www.rosaslounge.com/calendar",
            category="music",
            address="3420 W Armitage Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
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
            extractor_fn=extract_hideout,
        ),
        VenueConfig(
            name="Salt Shed",
            website_url="https://www.saltshedchicago.com",
            event_page_url="https://www.saltshedchicago.com/",
            category="music",
            address="1357 N Elston Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Outset",
            website_url="https://outsetlive.com",
            event_page_url="https://outsetlive.com/events/",
            category="music",
            address="1675 N Elston Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "Avondale": [
        VenueConfig(
            name="Rockwell on the River",
            website_url="https://www.rockwellontheriver.com",
            event_page_url="https://www.rockwellontheriver.com/calendar/",
            category="music",
            address="3757 N Rockwell Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
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
            name="Green Mill Jazz Club",
            website_url="https://www.greenmilljazz.com",
            event_page_url="https://www.greenmilljazz.com/calendar/",
            category="music",
            address="4802 N Broadway Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_squarespace_events,
        ),
        VenueConfig(
            name="Byline Bank Aragon Ballroom",
            website_url="https://www.aragonballroomchicago.com",
            event_page_url="https://www.aragonballroomchicago.com/",
            category="music",
            address="1106 W Lawrence Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Riviera Theatre",
            website_url="https://www.jamusa.com/riviera-theatre",
            event_page_url="https://www.jamusa.com/riviera-theatre",
            category="music",
            address="4746 N Racine Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_jamusa_events,
        ),
    ],

    "Lincoln Park": [
        VenueConfig(
            name="Steppenwolf Theatre Company",
            website_url="https://www.steppenwolf.org",
            event_page_url="https://www.steppenwolf.org/whats-on/current-season",
            category="theater",
            address="1650 N Halsted St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Lincoln Hall",
            website_url="https://www.lh-st.com",
            event_page_url="https://lh-st.com/",
            category="music",
            address="2424 N Lincoln Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Kingston Mines",
            website_url="https://www.kingstonmines.com",
            event_page_url="https://kingstonmines.com/",
            category="music",
            address="2548 N Halsted St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Second City",
            website_url="https://www.secondcity.com",
            event_page_url="https://www.secondcity.com/shows",
            category="comedy",
            address="1616 N Wells St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Park West",
            website_url="https://www.jamusa.com/venues/park-west",
            event_page_url="https://www.jamusa.com/venues/park-west",
            category="music",
            address="322 W Armitage Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_jamusa_events,
        ),
    ],

    "Lake View": [
        VenueConfig(
            name="Metro Chicago",
            website_url="https://www.metrochicago.com",
            event_page_url="https://www.metrochicago.com/events",
            category="music",
            address="3730 N Clark St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="The Vic Theatre",
            website_url="https://www.jamusa.com/venues/the-vic",
            event_page_url="https://www.jamusa.com/venues/the-vic",
            category="music",
            address="3145 N Sheffield Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Schubas Tavern",
            website_url="https://www.schubastavern.com",
            event_page_url="https://www.schubastavern.com/calendar",
            category="music",
            address="3159 N Southport Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "Lincoln Square": [
        VenueConfig(
            name="Lincoln Theatre",
            website_url="https://www.lincolntheatre.org",
            event_page_url="https://www.lincolntheatre.org/calendar",
            category="theater",
            address="4415 N Lincoln Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
        ),
        VenueConfig(
            name="Old Town School of Folk Music",
            website_url="https://www.oldtownschool.org",
            event_page_url="https://www.oldtownschool.org/events",
            category="music",
            address="4544 N Lincoln Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
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
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
        ),
        VenueConfig(
            name="The Vic Theatre",
            website_url="https://www.thevictheatre.com",
            event_page_url="https://www.thevictheatre.com/events",
            category="music",
            address="3145 N Sheffield Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
        ),
    ],

    "River North": [
        VenueConfig(
            name="Sound Bar",
            website_url="https://sound-bar.com",
            event_page_url="https://sound-bar.com/events",
            category="music",
            address="226 W Ontario St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "Pilsen": [
        VenueConfig(
            name="Thalia Hall",
            website_url="https://thaliahallchicago.com",
            event_page_url="https://thaliahallchicago.com/events",
            category="music",
            address="1807 S Allport St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "Logan Square": [
        VenueConfig(
            name="The Whistler",
            website_url="https://whistlerchicago.com",
            event_page_url="https://whistlerchicago.com/events",
            category="music",
            address="2421 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Cole's Bar",
            website_url="https://colesbarchicago.com",
            event_page_url="https://colesbarchicago.com",
            category="music",
            address="2338 N Milwaukee Ave",
            selectors={
                "event_container": "article.evcard",
                "title": "h3.evcard-title",
                "date": "div.evcard-header",
                "time": "p.evcard-time",
                "url": "a.evcard-btn"
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="The Lincoln Lodge",
            website_url="https://www.thelincolnlodge.com",
            event_page_url="https://www.thelincolnlodge.com",
            category="comedy",
            address="2040 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_javascript_events,
        ),
    ],

    "Humboldt Park": [
        VenueConfig(
            name="Martyrs'",
            website_url="https://www.martyrschicago.com",
            event_page_url="https://www.martyrschicago.com/events",
            category="music",
            address="3855 N Lincoln Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
        ),
        VenueConfig(
            name="The Loft on Lake",
            website_url="https://www.theloftonlake.com",
            event_page_url="https://www.theloftonlake.com/events",
            category="music",
            address="3453 W Lake St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
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
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
        ),
        VenueConfig(
            name="Morgan Ballroom",
            website_url="https://www.morganballroom.com",
            event_page_url="https://www.morganballroom.com/events",
            category="music",
            address="401 N Spaulding Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
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
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
        ),
    ],

    "Old Town": [
        VenueConfig(
            name="Zanies Comedy Club",
            website_url="https://chicago.zanies.com",
            event_page_url="https://chicago.zanies.com/chicago",
            category="comedy",
            address="1548 N Wells St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_zanies_calendar,
        ),
        VenueConfig(
            name="A Red Orchid Theatre",
            website_url="https://aredorchidtheatre.org",
            event_page_url="https://aredorchidtheatre.org",
            category="theater",
            address="1641 N Halsted St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "West Loop": [
        VenueConfig(
            name="City Winery",
            website_url="https://citywinery.com",
            event_page_url="https://citywinery.com/pages/events/chicago",
            category="music",
            address="1200 W Randolph St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Cobra Lounge",
            website_url="https://cobralounge.com",
            event_page_url="https://cobralounge.com/events",
            category="music",
            address="235 N Ashland Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_javascript_events,
        ),
        VenueConfig(
            name="Epiphany Center for the Arts",
            website_url="https://epiphanychi.com",
            event_page_url="https://epiphanychi.com/art-events",
            category="arts",
            address="311 W Carroll Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "Rogers Park": [
        VenueConfig(
            name="Rhapsody Theater",
            website_url="https://www.rhapsodytheater.com",
            event_page_url="https://www.rhapsodytheater.com/events",
            category="theater",
            address="1328 W Morse Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_generic_javascript_events,
        ),
        VenueConfig(
            name="Lifeline Theatre",
            website_url="https://lifelinetheatre.com",
            event_page_url="https://lifelinetheatre.com",
            category="theater",
            address="4912 N Clark St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
    ],

    "Andersonville": [
        VenueConfig(
            name="Bramble Arts Loft",
            website_url="https://www.brambleartsloft.com",
            event_page_url="https://www.brambleartsloft.com",
            category="arts",
            address="5545 N Clark St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Patio Theater",
            website_url="https://www.thepatiotheater.com",
            event_page_url="https://www.thepatiotheater.com",
            category="music",
            address="6008 W Irving Park Rd",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],

    "Edgewater": [
        VenueConfig(
            name="Uncommon Ground",
            website_url="https://www.uncommonground.com",
            event_page_url="https://www.uncommonground.com",
            category="music",
            address="1401 W Devon Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time'
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],
}


async def save_events_to_db(async_session_maker, config: VenueConfig, events: list[VenueEvent]) -> None:
    """Save extracted events to database (upsert to avoid duplicates)."""
    if not events:
        return

    async with async_session_maker() as session:
        try:
            # Add or update events
            for i, event in enumerate(events):
                # Parse date string to datetime objects
                parsed_date, parsed_date_end = parse_date_range(event.date) if event.date else (None, None)
                parsed_date_end_override, _ = parse_date_range(event.date_end) if event.date_end else (None, None)

                # Use override if provided, otherwise use parsed end date
                final_date_end = parsed_date_end_override or parsed_date_end

                # Create unique source name per venue: chicago_venue_rosa_s_lounge
                venue_slug = config.name.lower().replace(" ", "_").replace("'", "s")
                source_name = f"chicago_venue_{venue_slug}"

                # Check if event already exists by name + date + source
                # This handles venues that don't have unique event URLs (all use fallback)
                existing = await session.execute(
                    select(EventModel).where(
                        (EventModel.name == event.name) &
                        (EventModel.source == source_name) &
                        (EventModel.date == parsed_date)  # Same event on same date
                    )
                )
                existing_event = existing.scalars().first()

                if existing_event:
                    # Update existing event with new date info
                    existing_event.date = parsed_date
                    existing_event.date_end = final_date_end
                    existing_event.time = event.time
                    existing_event.time_end = event.time_end
                    existing_event.date_retrieved = datetime.utcnow()
                else:
                    # Create new event
                    event_model = EventModel(
                        name=event.name,
                        date=parsed_date,
                        date_end=final_date_end,
                        time=event.time,
                        time_end=event.time_end,
                        category=event.category,
                        address=event.location,
                        venue_name=event.venue_name or config.name,
                        origination_url=event.url or f"#venue-{config.name}-{i}",  # Make each event unique
                        source=source_name,
                        details=None,
                    )
                    session.add(event_model)

            await session.commit()
            logger.info(f"Saved {len(events)} events to database for {config.name}")

        except Exception as e:
            logger.error(f"Error saving events for {config.name}: {e}")
            await session.rollback()


async def scrape_chicago_events() -> dict[str, list[VenueEvent]]:
    """Scrape ALL Chicago neighborhoods/venues and save to database."""
    results = {}
    total_events = 0

    # Initialize database - use shared database and create all tables
    from shared.database import AsyncSessionLocal, init_db

    await init_db()
    async_session = AsyncSessionLocal

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

                    # Save events to database
                    await save_events_to_db(async_session, config, events)

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
