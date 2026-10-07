"""
Unified Chicago Events Scraper - ALL neighborhoods/venues, iteratively refined.
"""

import httpx
import logging
from dataclasses import dataclass
from typing import Optional, Callable
from bs4 import BeautifulSoup
from .venue_scraper import VenueScraper, VenueConfig, VenueEvent, parse_cost
import re
import asyncio
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from shared.database.models import EventModel, VenueModel, NeighborhoodModel, Base
from shared.database.neighborhoods import canonical_neighborhood, resolve_neighborhood_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Upper bound on a single venue's scrape. Generous enough for Playwright venues
# that paginate through "load more" (Salt Shed takes ~40s), short enough that one
# unresponsive site doesn't hang the full run.
VENUE_SCRAPE_TIMEOUT = 120


_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def infer_event_year(month_str: str, today: Optional[datetime] = None) -> int:
    """Pick the year for a yearless venue date like "Oct 6".

    Venue calendars list upcoming shows only, so a month earlier than the
    current one belongs to next year (a January show listed in October).
    """
    today = today or datetime.now()
    for fmt in ("%b", "%B"):
        try:
            month = datetime.strptime(month_str[:3] if fmt == "%b" else month_str, fmt).month
        except ValueError:
            continue
        return today.year + 1 if month < today.month else today.year
    return today.year


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


def jsonld_offer_cost(event_data: dict) -> Optional[str]:
    """Read a price out of a schema.org Event's `offers`.

    This is the one structured price in the whole pipeline, so prefer its
    numeric fields over sniffing text. `offers` may be a single object or a
    list of them (one per ticket tier), in which case report the range.
    """
    offers = event_data.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None

    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        spec = offer.get("priceSpecification")
        source = spec if isinstance(spec, dict) else offer
        for key in ("price", "lowPrice", "highPrice", "minPrice", "maxPrice"):
            value = source.get(key)
            if value in (None, ""):
                continue
            try:
                prices.append(float(str(value).replace("$", "").replace(",", "")))
            except ValueError:
                continue

    if not prices:
        return None
    low, high = min(prices), max(prices)
    if low == 0 and high == 0:
        return "Free"

    def money(value: float) -> str:
        return f"${value:.0f}" if value == int(value) else f"${value:.2f}"

    return money(low) if low == high else f"{money(low)}-{money(high)}"


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
                                category=config.category,
                                cost=jsonld_offer_cost(event_data),
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
                        category=config.category,
                        cost=jsonld_offer_cost(event_data),
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
                url=ticket_url, venue_name=config.name, category=config.category,
                cost=parse_cost(article.get_text(" ", strip=True)),
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
                    url=event_url, venue_name=config.name, category=config.category,
                    cost=parse_cost(container.get_text(" ", strip=True)),
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
                category=config.category,
                cost=parse_cost(link.get_text(" ", strip=True)),
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
                category=config.category,
                cost=parse_cost(item.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")

    return events



def extract_rhapsody_theater(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Rhapsody Theater ThunderTix iframe (rendered by Playwright)."""
    import re
    events = []
    try:
        # Get all text from the page (includes iframe content rendered by Playwright)
        text = soup.get_text()

        # Look for time + event pattern
        # Example: "7:00p Kiki Queens - Drag to the Future"
        pattern = r'(\d{1,2}):(\d{2})\s*([ap])\s+([A-Za-z0-9\s\-:&]+?)(?=\d{1,2}:|Oct|Day|SUN|$)'
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)

        # Don't deduplicate - each time entry is a separate show
        for hour, minute, ampm, event_name in matches:
            title = event_name.strip()
            if len(title) > 3:
                # Map time to approximate date (Oct 15-17 visible in calendar)
                events.append(VenueEvent(
                    name=title,
                    date="Oct 15, 2026",
                    time=f"{hour}:{minute}{ampm}",
                    location=f"{config.name}, {config.address}",
                    url=config.website_url,
                    venue_name=config.name,
                    category=config.category
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from ThunderTix calendar")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


async def extract_salt_shed_playwright(page, config: VenueConfig) -> list[VenueEvent]:
    """Extract Salt Shed events from dynamically loaded cards using Playwright."""
    import re
    events = []
    try:
        # Wait for All Events container
        await page.wait_for_selector('div[data-venue-events]', timeout=30000)

        # Scroll and load all cards
        for _ in range(20):
            try:
                # Try to click "load more" button
                more = page.locator('text=/load more|show more|see more/i')
                if await more.count():
                    await more.first.click()
                    await page.wait_for_timeout(1200)
                else:
                    # Scroll if no button
                    await page.mouse.wheel(0, 4000)
                    await page.wait_for_timeout(1000)
            except:
                break

        # Extract all cards using JavaScript
        cards = await page.evaluate("""
        () => {
            const root = document.querySelector('div[data-venue-events]');
            if (!root) return [];
            const isTix = el => /get\\s*tickets/i.test(el.textContent || '');
            const tixIn = el => [...el.querySelectorAll('a,button')].filter(isTix);

            const cards = [];
            for (const btn of tixIn(root)) {
                let card = btn;
                while (card.parentElement && card.parentElement !== root &&
                       tixIn(card.parentElement).length === 1) {
                    card = card.parentElement;
                }
                if (!cards.includes(card)) cards.push(card);
            }

            const leafText = (card, re) => {
                const el = [...card.querySelectorAll('*')]
                    .find(e => e.children.length === 0 && re.test((e.textContent || '').trim()));
                return el ? el.textContent.trim() : null;
            };

            return cards.map(card => {
                const heading = card.querySelector('h1,h2,h3,h4,h5,h6');
                const date = leafText(card, /^(mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i);
                const doors = leafText(card, /^doors/i);
                const link = [...card.querySelectorAll('a[href]')].find(isTix)
                    || card.querySelector('a[href]');
                return {
                    date: date,
                    doors: doors ? doors.replace(/^doors:\\s*/i, '') : null,
                    title: heading ? heading.textContent.trim().replace(/\\s+/g, ' ') : null,
                    url: link ? link.href : null,
                };
            });
        }
        """)

        # Parse extracted cards
        for card in cards:
            if card['date'] and card['title']:
                # Parse date like "TUE, OCT 6"
                date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})', card['date'], re.IGNORECASE)
                if date_match:
                    month = date_match.group(1)
                    day = date_match.group(2)

                    events.append(VenueEvent(
                        name=card['title'],
                        date=f"{month} {day}, {infer_event_year(month)}",
                        time=card['doors'],
                        location=f"{config.name}, {config.address}",
                        url=card.get('url') or config.website_url,
                        venue_name=config.name,
                        category=config.category
                    ))

        logger.info(f"{config.name}: extracted {len(events)} events from dynamic cards")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_salt_shed(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Salt Shed (ve-events__card articles)."""
    import re
    events = []
    try:
        # Salt Shed uses article.ve-events__card for each event
        articles = soup.select('article.ve-events__card')

        for article in articles:
            text = article.get_text(strip=True)

            # Look for date pattern: "Sat, Feb 20" or similar
            date_match = re.search(r'(\w{3}),?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})', text)
            if not date_match:
                continue

            month = date_match.group(2)
            day = date_match.group(3)

            # Look for time pattern: "Doors: 6:00 PM"
            time_match = re.search(r'Doors:\s*(\d{1,2}):(\d{2})\s*([AP]M)', text, re.IGNORECASE)
            time_str = f"{time_match.group(1)}:{time_match.group(2)}{time_match.group(3)}" if time_match else None

            # Extract title - text after PM until age restriction or venue name (non-greedy)
            title_match = re.search(r'[AP]M\s+(.+?)(?:17 & Over|All Ages|The Salt Shed|Shed)', text, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else None

            if title and len(title) > 3:
                events.append(VenueEvent(
                    name=title,
                    date=f"{month} {day}, 2026",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(article.get_text(" ", strip=True)),
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from ve-events__card")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_eb_item(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from the `.eb-item` show grid.

    Used by the 16 on Center venues (Thalia Hall and siblings). Each card holds
    its own fields, so no text mining is needed:

        .date        "THU OCTOBER 8"
        .start-time  "DOORS: 7:00PM"
        .title       the billing
        a[ticketweb] the per-event ticket link

    Note the page also carries four `.recent-show` cards. Matching those instead
    is why this venue reported exactly four events while the grid held seventy.
    """
    import re
    events = []
    try:
        for item in soup.select('.eb-item'):
            title_elem = item.select_one('.title')
            title = title_elem.get_text(" ", strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            date_elem = item.select_one('.date')
            date_text = date_elem.get_text(" ", strip=True) if date_elem else ""
            match = re.search(
                r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})',
                date_text,
                re.IGNORECASE,
            )
            if not match:
                continue
            month = match.group(1).title()[:3]
            day = match.group(2)

            time_elem = item.select_one('.start-time')
            time_str = time_elem.get_text(" ", strip=True) if time_elem else None

            link = item.select_one('a[href*="ticketweb"]') or item.select_one('a[href]')
            url = link.get('href', config.website_url) if link else config.website_url
            if not url.startswith('http'):
                url = f"{config.website_url}{url}"

            venue_elem = item.select_one('.venue')
            venue_name = venue_elem.get_text(" ", strip=True) if venue_elem else config.name

            events.append(VenueEvent(
                name=title,
                date=f"{month} {day}, {infer_event_year(month)}",
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=venue_name or config.name,
                category=config.category,
                cost=parse_cost(item.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from .eb-item grid")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_lh_st(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from lh-st.com, which lists Lincoln Hall and Schubas together.

    One site serves both rooms, so every card names its venue ("SCHUBAS",
    "SCHUBAS (UPSTAIRS)", "LINCOLN HALL") and the config's own name decides
    which cards it keeps. Without that filter the two venues would each claim
    all 132 shows.
    """
    import re
    events = []
    try:
        # "Schubas Tavern" -> "schubas", "Lincoln Hall" -> "lincoln hall"
        wanted = config.name.lower().replace(" tavern", "").strip()

        for card in soup.select('.card'):
            title_elem = card.select_one('.card-title')
            title = title_elem.get_text(" ", strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            text = card.get_text(" ", strip=True)
            if wanted not in text.lower():
                continue

            # "OCT 07"
            match = re.search(
                r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{1,2})\b',
                text,
                re.IGNORECASE,
            )
            if not match:
                continue
            month = match.group(1).title()
            day = match.group(2)

            time_elem = card.select_one('.tessera-showTime')
            time_str = time_elem.get_text(" ", strip=True) if time_elem else None

            ages_elem = card.select_one('.showAges')
            link = card.select_one('a[href]')
            url = link.get('href', config.website_url) if link else config.website_url
            if not url.startswith('http'):
                url = f"{config.website_url}{url}"

            events.append(VenueEvent(
                name=title,
                date=f"{month} {day}, {infer_event_year(month)}",
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(card.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from lh-st cards")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_martyrs(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Martyrs' calendar (a Drupal view).

    Each row pairs a schedule line with the billing:

        .views-field-field-show-schedule-value  "Fri, Oct 9th - Doors 6:30PM - Show 7:30PM - $20"
        .views-field-field-show-bands-nid       "Phil Angotti & Friends ..."
    """
    import re
    events = []
    try:
        for schedule in soup.select('.views-field-field-show-schedule-value'):
            line = schedule.get_text(" ", strip=True)
            match = re.search(
                r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})',
                line,
                re.IGNORECASE,
            )
            if not match:
                continue
            month, day = match.group(1).title(), match.group(2)

            # The billing lives in a sibling field within the same row.
            row = schedule
            bands = None
            for _ in range(4):
                row = row.parent
                if row is None:
                    break
                bands = row.select_one('.views-field-field-show-bands-nid')
                if bands:
                    break
            title = bands.get_text(" ", strip=True) if bands else None
            if not title or len(title) < 3:
                continue

            # "Doors 6:30PM - Show 7:30PM" -> keep the show time where given
            show = re.search(r'Show\s*(\d{1,2}(?::\d{2})?\s*[APap]\.?[Mm])', line)
            doors = re.search(r'Doors\s*(\d{1,2}(?::\d{2})?\s*[APap]\.?[Mm])', line)
            time_str = (show or doors).group(1).upper().replace(" ", "") if (show or doors) else None

            cost = None
            if re.search(r'no cover|free', line, re.IGNORECASE):
                cost = "Free"
            else:
                price = re.search(r'\$(\d+)', line)
                if price:
                    cost = f"${price.group(1)}"

            events.append(VenueEvent(
                name=title[:200],
                date=f"{month} {day}, {infer_event_year(month)}",
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=config.event_page_url,
                venue_name=config.name,
                category=config.category,
                cost=cost,
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from calendar rows")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_old_town_school(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Old Town School of Folk Music.

    Each `.concertListing` row shows the month and day as two separate tiles
    ("OCT" / "08"), which is why reading them produced a month with no day.
    The row also carries a full line that has everything, so parse that:

        "Thursday · October 08 2026 · 1:00 PM CDT · Maurer Hall"
    """
    import re
    events = []
    try:
        line_pattern = re.compile(
            r'(January|February|March|April|May|June|July|August|September|October|November|December)'
            r'\s+(\d{1,2})\s+(\d{4})(?:.*?(\d{1,2}:\d{2}\s*[AP]M))?',
            re.IGNORECASE,
        )
        for row in soup.select('.concertListing'):
            text = row.get_text(" ", strip=True)
            match = line_pattern.search(text)
            if not match:
                continue
            month, day, year, time_str = match.groups()

            # The billing is the first heading in the row.
            heading = row.find(['h2', 'h3', 'h4'])
            title = heading.get_text(" ", strip=True) if heading else None
            if not title:
                # Fall back to the longest link text, which is the show name.
                links = [a.get_text(" ", strip=True) for a in row.select('a')]
                links = [t for t in links if t and 'ticket' not in t.lower()]
                title = max(links, key=len) if links else None
            if not title or len(title) < 3:
                continue

            link = row.select_one('a[href]')
            url = link.get('href', config.website_url) if link else config.website_url
            if not url.startswith('http'):
                url = f"{config.website_url}{url}"

            events.append(VenueEvent(
                name=title[:200],
                date=f"{month[:3].title()} {day}, {year}",
                time=time_str.upper() if time_str else None,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(row.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from concert listings")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_squarespace_eventlist(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from a Squarespace event list (The Loft on Lake).

    Squarespace renders the date in a machine-readable `<time datetime>`, which
    is far better than the "APR" tile beside it - reading the tiles produced
    run-together values like "Apr1911:00 AM1". Past events are marked by the
    `eventlist-event--past` class and skipped here.
    """
    events = []
    try:
        for item in soup.select('.eventlist-event'):
            classes = " ".join(item.get('class', []))
            if 'past' in classes:
                continue

            title_elem = item.select_one('.eventlist-title, .eventlist-title-link')
            title = title_elem.get_text(" ", strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            stamp = item.select_one('time[datetime]')
            iso = stamp.get('datetime') if stamp else None
            if not iso:
                continue
            try:
                parsed = datetime.strptime(iso[:10], "%Y-%m-%d")
            except ValueError:
                continue

            time_elem = item.select_one('.event-time-12hr')
            # Squarespace uses a narrow no-break space inside times.
            time_str = time_elem.get_text(" ", strip=True).replace(" ", " ") if time_elem else None

            link = item.select_one('a[href]')
            url = link.get('href', config.website_url) if link else config.website_url
            if not url.startswith('http'):
                url = f"{config.website_url}{url}"

            events.append(VenueEvent(
                name=title[:200],
                date=f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}",
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(item.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} upcoming events from Squarespace list")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


async def extract_eventscalendar_widget(page, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from a Wix site embedding an eventscalendar.co widget.

    The venue page carries no events: it embeds plugin.eventscalendar.co in an
    iframe that renders nothing under automation, which is why this venue was
    previously written off as "cross-origin, not scrapable".

    The widget feeds itself from a public JSON endpoint, so listen for that
    response instead of fighting the iframe. The project ids are captured from
    live traffic rather than hardcoded, so they can change without breaking
    this. The listener has to be attached before the requests fire, hence the
    reload - navigation has already happened by the time an extractor runs.
    """
    events = []
    try:
        payloads = []

        async def capture(response):
            # Two feeds matter: the widget's own project data, and the broker
            # that proxies the venue's Eventbrite listings. The project feed is
            # largely historical; the broker carries what is actually coming up.
            if not any(part in response.url for part in ("/data/public/events", "/eventbrite/events")):
                return
            try:
                payloads.append(await response.json())
            except Exception:
                pass

        page.on("response", capture)
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        # Wix defers the widget until it scrolls into view, and the broker call
        # only fires then - without this the feed is never requested.
        for _ in range(5):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(1200)
        await page.wait_for_timeout(3000)
        page.remove_listener("response", capture)

        seen = set()
        for payload in payloads:
            # The project feed nests under "value", the broker under "events".
            items = (payload or {}).get("value") or (payload or {}).get("events") or []
            for item in items:
                title = (item.get("title") or "").strip()
                start = item.get("start")
                if not title or not start:
                    continue
                try:
                    # Epoch milliseconds, UTC.
                    when = datetime.utcfromtimestamp(start / 1000)
                except (TypeError, ValueError, OSError):
                    continue

                key = (when.date(), title.lower())
                if key in seen:
                    continue
                seen.add(key)

                events.append(VenueEvent(
                    name=title[:200],
                    date=f"{when.strftime('%b')} {when.day}, {when.year}",
                    time=when.strftime("%-I:%M %p") if (when.hour or when.minute) else None,
                    location=f"{config.name}, {config.address}",
                    url=config.event_page_url,
                    venue_name=config.name,
                    category=config.category,
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from calendar widget API")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_tessitura_calendar(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from a Tessitura ticketing calendar (`tn-events-calendar`).

    Theaters often publish nothing dated on their marketing site while their
    ticketing subdomain carries the full performance calendar - Goodman's own
    site yields nothing, my.goodmantheatre.org yields the lot.

    The month grid shows only a day number per cell, but each cell also carries
    a screen-reader label with the complete date ("Thursday 1 October 2026"),
    which is both unambiguous and immune to month-boundary spillover.
    """
    import re
    events = []
    try:
        full_date = re.compile(
            r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
            re.IGNORECASE,
        )
        for cell in soup.select('.tn-events-calendar__day'):
            items = cell.select('.tn-events-calendar__day-event-list-item')
            if not items:
                continue

            label = cell.select_one('.sr-only')
            match = full_date.search(label.get_text(" ", strip=True)) if label else None
            if not match:
                continue
            day, month, year = match.group(1), match.group(2)[:3].title(), match.group(3)

            for item in items:
                name_elem = item.select_one('.tn-events-calendar__event-name')
                title = name_elem.get_text(" ", strip=True) if name_elem else None
                if not title or len(title) < 3:
                    continue

                time_elem = item.select_one('.tn-events-calendar__event-time')
                raw_time = time_elem.get_text(" ", strip=True) if time_elem else ""
                stamp = re.search(r'(\d{1,2}:\d{2}\s*[APap]\.?[Mm])', raw_time)

                link = item.select_one('a[href]')
                url = link.get('href', config.event_page_url) if link else config.event_page_url
                if not url.startswith('http'):
                    url = f"{config.website_url}{url}"

                events.append(VenueEvent(
                    name=title[:200],
                    date=f"{month} {day}, {year}",
                    time=stamp.group(1).upper().replace(" ", "") if stamp else None,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(item.get_text(" ", strip=True)),
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from Tessitura calendar")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
# "SEP 11-OCT 18, 2026" / "OCT 27-MAR 20, 2027" - a run, not a single night.
_RUN_RE = re.compile(
    rf"(?P<m1>{_MONTH})\s*(?P<d1>\d{{1,2}})\s*[–—-]\s*"
    rf"(?:(?P<m2>{_MONTH})\s*)?(?P<d2>\d{{1,2}})(?:,?\s*(?P<y>\d{{4}}))?",
    re.I,
)
# "Oct 7 - Wednesday", "Thu, Oct 08", "October 17, 2026"
_ONE_RE = re.compile(
    rf"(?P<m>{_MONTH})\s*(?P<d>\d{{1,2}})(?:,?\s*(?P<y>\d{{4}}))?", re.I
)
_BOILERPLATE = (
    "tickets", "buy tickets", "more info", "learn more", "details", "sold out",
    "rsvp", "doors", "on sale", "free", "info", "read more", "get tickets",
)


_WEEKDAY_RE = re.compile(
    r"\b(?:Mon|Tue|Tues|Wed|Weds|Thu|Thur|Thurs|Fri|Sat|Sun)(?:day|sday|nesday|rsday|urday)?\b",
    re.I,
)


def extract_songkick_venue(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract a venue's concerts from its Songkick venue page.

    For venues that have no website at all. Several real Chicago music venues
    are web-invisible - Los Globos and V-Live in Little Village both draw
    touring regional Mexican acts but promote on Instagram and sell through
    third-party ticketers - so a listing aggregator is the only way to see
    them. Songkick emits a full ISO timestamp per concert, so dates are exact.
    """
    events = []
    seen = set()

    for item in soup.select("ul.event-listings li"):
        stamp = item.select_one("time[datetime]")
        link = item.select_one('a[href*="/concerts/"]')
        if not stamp or not link:
            continue
        try:
            when = datetime.fromisoformat((stamp.get("datetime") or "").strip())
        except ValueError:
            continue

        # "Mazizo Musical / Los Globos, Chicago, IL, US / BUY TICKETS / ..."
        title = None
        for line in item.get_text("\n", strip=True).split("\n"):
            line = line.strip()
            low = line.lower()
            if not line or len(line) < 3:
                continue
            if low.startswith(("buy tickets", "interested", "going", "don't miss",
                               "dont miss", "tickets")):
                continue
            # The venue's own name and the date header are not the event.
            if config.name.lower() in low or low.startswith(_WEEKDAY_PREFIXES):
                continue
            title = line
            break
        if not title:
            continue

        key = (when.date(), title.lower())
        if key in seen:
            continue
        seen.add(key)

        href = link.get("href") or ""
        url = href if href.startswith("http") else f"https://www.songkick.com{href}"

        events.append(VenueEvent(
            name=title[:200],
            date=f"{when.strftime('%b')} {when.day}, {when.year}",
            time=when.strftime("%-I:%M %p") if (when.hour or when.minute) else None,
            location=f"{config.name}, {config.address}",
            url=url,
            venue_name=config.name,
            category=config.category,
        ))

    logger.info(f"{config.name}: extracted {len(events)} events from Songkick")
    return events


_WEEKDAY_PREFIXES = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def _title_from(lines: list[str]) -> Optional[str]:
    """Pick the event title out of a card's text lines.

    The title is the first line that is neither the date nor a call to action.
    A line like "OCT 7 - WEDNESDAY" is all date, so the weekday is stripped
    alongside the date before checking whether real words are left - otherwise
    the weekday alone passes for a title.
    """
    for line in lines:
        if line.lower().rstrip(":").startswith(_BOILERPLATE):
            continue
        remainder = _WEEKDAY_RE.sub("", _RUN_RE.sub("", _ONE_RE.sub("", line)))
        if len(re.sub(r"[^A-Za-z]", "", remainder)) <= 3:
            continue
        # Some venues run the title straight into the blurb in one text node
        # ("Plim Plim in the Gateway Theater > DATE: October 15 TIME: 6:00pm").
        # Cut at the marker that starts the blurb.
        title = re.split(r"\s*[►▶‣]\s*|\s+DATE:\s*|\s+TIME:\s*", line)[0].strip()
        if len(title) >= 3:
            return title
    return None


def extract_dated_list_items(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from a list where each item is "<date> <title> <CTA>".

    Written once for the many venues that share this shape - a WordPress show
    archive, a Wix event list, a season grid - rather than one extractor each.
    It keys off the date text in each item instead of class names, which is
    what makes it portable: Wix in particular ships obfuscated classes like
    `li.qElViY` that change on every redeploy.

    Only the innermost matching element is kept, so the surrounding list
    container doesn't get reported as one giant event.
    """
    # A candidate must carry both a date and a title. Requiring only a date
    # would select the innermost element, which on Wix-style markup is a bare
    # "Thu, Oct 08" div with the title in a sibling.
    candidates = []
    for el in soup.select("li, article, div[class], a[class]"):
        text = el.get_text("\n", strip=True)
        if not (10 <= len(text) <= 400):
            continue
        if not _ONE_RE.search(text):
            continue
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if _title_from(lines):
            candidates.append(el)

    # Of the nested candidates keep the innermost, so the list container isn't
    # reported as one giant event. Checked by identity against a set rather
    # than pairwise, which would be quadratic on a large page.
    qualified = {id(el) for el in candidates}
    chosen = [
        el for el in candidates
        if not any(id(d) in qualified for d in el.descendants if d is not el)
    ]

    events = []
    seen = set()
    for el in chosen:
        lines = [l.strip() for l in el.get_text("\n", strip=True).split("\n") if l.strip()]

        date_str = date_end_str = None
        run = _RUN_RE.search(" ".join(lines))
        if run:
            start_month = run.group("m1")[:3].title()
            end_month = (run.group("m2") or run.group("m1"))[:3].title()
            # A run whose end month precedes its start month crosses New Year.
            crosses = _MONTHS.get(end_month, 0) < _MONTHS.get(start_month, 0)
            if run.group("y"):
                # "OCT 27-MAR 20, 2027": a trailing year belongs to the END of
                # the run, so the start is the year before when it crosses.
                end_year = int(run.group("y"))
                start_year = end_year - 1 if crosses else end_year
            else:
                start_year = infer_event_year(start_month)
                end_year = start_year + 1 if crosses else start_year
            date_str = f"{start_month} {int(run.group('d1'))}, {start_year}"
            date_end_str = f"{end_month} {int(run.group('d2'))}, {end_year}"
        else:
            one = _ONE_RE.search(" ".join(lines))
            if not one:
                continue
            year = one.group("y") or infer_event_year(one.group("m"))
            date_str = f"{one.group('m')[:3].title()} {int(one.group('d'))}, {year}"

        title = _title_from(lines)
        if not title:
            continue

        key = (date_str, title.lower())
        if key in seen:
            continue
        seen.add(key)

        clock = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)", " ".join(lines))
        link = el.select_one("a[href]") or (el if el.name == "a" and el.get("href") else None)
        url = link["href"] if link else config.event_page_url
        if not url.startswith("http"):
            url = f"{config.website_url.rstrip('/')}{url if url.startswith('/') else '/' + url}"

        events.append(VenueEvent(
            name=title[:200],
            date=date_str,
            date_end=date_end_str,
            time=clock.group(1).upper().replace(".", "") if clock else None,
            location=f"{config.name}, {config.address}",
            url=url,
            venue_name=config.name,
            category=config.category,
            cost=parse_cost(el.get_text(" ", strip=True)),
        ))

    logger.info(f"{config.name}: extracted {len(events)} events from dated list items")
    return events


def scrolling(extractor_fn, passes: int = 5):
    """Wrap a soup extractor so it runs after scrolling the page.

    Wix and similar builders defer list items until they scroll into view, so
    the scraper's flat post-load wait sees an empty list no matter how long it
    is. Scrolling is what actually triggers the render.
    """
    async def page_extractor(page, config: VenueConfig) -> list[VenueEvent]:
        for _ in range(passes):
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(800)
        await page.wait_for_timeout(1500)
        return extractor_fn(BeautifulSoup(await page.content(), "html.parser"), config)

    return page_extractor


def extract_tribe_events(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from The Events Calendar, the common WordPress plugin.

    Worth one shared extractor rather than per-venue selectors: the plugin is
    everywhere on smaller arts venues, and it emits a machine-readable
    `<time datetime="2026-10-17">` so dates need no parsing or year guessing.

    Handles both the list view and the month view, which use different
    container classes but the same inner markup.
    """
    containers = soup.select(
        ".tribe-events-calendar-list__event, "
        ".tribe-events-calendar-month__calendar-event, "
        ".tribe-events-calendar-month__multiday-event, "
        "article.type-tribe_events"
    )

    events = []
    seen = set()
    for item in containers:
        # The first full ISO date wins; month view also emits bare "14:00"
        # times in <time>, so require the YYYY-MM-DD shape.
        iso = None
        for tag in item.select("time[datetime]"):
            value = (tag.get("datetime") or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]) and len(value) >= 10:
                iso = value[:10]
                break
        if not iso:
            continue
        try:
            when = datetime.strptime(iso, "%Y-%m-%d")
        except ValueError:
            continue

        title_elem = item.select_one(
            ".tribe-events-calendar-list__event-title a, "
            ".tribe-events-calendar-list__event-title, "
            ".tribe-events-calendar-month__calendar-event-title a, "
            ".tribe-events-calendar-month__multiday-event-bar-title, "
            "[class*='event-title'] a, [class*='event-title'], h3 a, h3"
        )
        title = title_elem.get_text(" ", strip=True) if title_elem else None
        if not title or len(title) < 3:
            continue

        # Multi-day events repeat once per day in the month view.
        key = (when.date(), title.lower())
        if key in seen:
            continue
        seen.add(key)

        time_elem = item.select_one("[class*='event-datetime'], [class*='event-time']")
        time_text = time_elem.get_text(" ", strip=True) if time_elem else item.get_text(" ", strip=True)
        clock = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)", time_text)

        link = item.select_one("a[href]")
        url = link["href"] if link else config.event_page_url
        if not url.startswith("http"):
            url = f"{config.website_url.rstrip('/')}{url}"

        events.append(VenueEvent(
            name=title[:200],
            date=f"{when.strftime('%b')} {when.day}, {when.year}",
            time=clock.group(1).upper().replace(".", "") if clock else None,
            location=f"{config.name}, {config.address}",
            url=url,
            venue_name=config.name,
            category=config.category,
            cost=parse_cost(item.get_text(" ", strip=True)),
        ))

    logger.info(f"{config.name}: extracted {len(events)} events from The Events Calendar")
    return events


async def extract_ace_calendar(page, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from an Adage `ace-cal-grid` month calendar (Lyric Opera).

    The marketing season page lists productions without performance dates; the
    calendar carries the dated performances. Each day cell is keyed by
    `aria-labelledby="Day-<epoch>"` - midnight Chicago local - so dates come out
    exact and no year has to be inferred.

    Only one month renders at a time, so page forward through the season. The
    header is read after each click because a season has empty months in it
    (December here) and the click is otherwise unverifiable.
    """
    from zoneinfo import ZoneInfo
    chicago = ZoneInfo("America/Chicago")
    next_selector = (
        "button[aria-label*='next' i], a[aria-label*='next' i], "
        "[class*=next] button, button[class*=next]"
    )
    skip_prefixes = ("buy ticket", "tickets", "learn more", "more info", "details")

    events = []
    seen = set()
    try:
        # The calendar is client-rendered behind a Cloudflare check, so it is
        # not in the DOM yet when the scraper's generic post-load wait expires.
        await page.wait_for_selector(".ace-cal-grid-day", timeout=25000)
        await page.wait_for_timeout(1500)

        for month in range(9):
            soup = BeautifulSoup(await page.content(), "html.parser")

            for cell in soup.select(".ace-cal-grid-day"):
                stamp = re.search(r"Day-(\d{9,11})", cell.get("aria-labelledby") or "")
                if not stamp:
                    continue
                try:
                    when = datetime.fromtimestamp(int(stamp.group(1)), tz=chicago)
                except (ValueError, OSError):
                    continue

                for card in cell.select(".ace-cal-grid-event"):
                    title = time_str = cost = None
                    for line in card.get_text("\n", strip=True).split("\n"):
                        line = line.strip()
                        low = line.lower()
                        if not line:
                            continue
                        if re.fullmatch(r"\d{1,2}(:\d{2})?\s*[ap]\.?m\.?", low):
                            time_str = time_str or line
                        elif low.startswith("starting at") or line.startswith("$"):
                            cost = cost or line
                        elif low.startswith(skip_prefixes):
                            continue
                        elif title is None:
                            title = line

                    if not title:
                        continue

                    key = (when.date(), title.lower())
                    if key in seen:
                        continue
                    seen.add(key)

                    link = card.find("a", href=True)
                    url = link["href"] if link else config.event_page_url
                    if not url.startswith("http"):
                        url = f"{config.website_url}{url}"

                    events.append(VenueEvent(
                        name=title[:200],
                        date=f"{when.strftime('%b')} {when.day}, {when.year}",
                        time=time_str,
                        location=f"{config.name}, {config.address}",
                        url=url,
                        venue_name=config.name,
                        category=config.category,
                        cost=cost,
                    ))

            if month == 8:
                break
            header = await page.evaluate(
                "() => document.querySelector('.ace-cal-grid-month')?.innerText.split('\\n')[0]"
            )
            try:
                await page.click(next_selector, timeout=4000)
                await page.wait_for_timeout(3000)
            except Exception:
                break
            moved = await page.evaluate(
                "() => document.querySelector('.ace-cal-grid-month')?.innerText.split('\\n')[0]"
            )
            if moved == header:
                break

        logger.info(f"{config.name}: extracted {len(events)} events from ace calendar")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return events


def extract_den_theatre(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from the Den Theatre calendar.

    Calendar cells render as "7:15 PM  Chad Daniels" with no date of their own -
    the date lives in the event link, /calendar/2026/10/1/chad-daniels - so that
    is what gets parsed. The time comes from `.item-time--12hr`, and the title is
    whatever follows it in the cell.
    """
    import re
    events = []
    try:
        seen = set()
        for item in soup.select('.item'):
            link = item.select_one('a[href]')
            href = link.get('href', '') if link else ''
            stamp = re.search(r'/calendar/(\d{4})/(\d{1,2})/(\d{1,2})', href)
            if not stamp:
                continue
            year, month, day = (int(g) for g in stamp.groups())

            time_elem = item.select_one('.item-time--12hr')
            # Squarespace separates the time from the billing with a narrow
            # no-break space and a non-breaking space.
            time_str = time_elem.get_text(strip=True).replace(" ", " ") if time_elem else None

            # The cell renders the time three times over - 12hr, 24hr and
            # localized - so strip those elements out before reading the
            # billing, or the title comes back as "19:15 7:15 PM Chad Daniels".
            from copy import copy
            billing = copy(item)
            for stamp in billing.select('[class*="item-time"]'):
                stamp.decompose()
            title = billing.get_text(" ", strip=True).replace(" ", " ").replace(" ", " ")
            title = re.sub(r'^\s*\d{1,2}:\d{2}\s*([AP]M)?\s*', '', title, flags=re.IGNORECASE).strip()
            if not title or len(title) < 3:
                continue

            key = (year, month, day, title.lower())
            if key in seen:
                continue
            seen.add(key)

            when = datetime(year, month, day)
            events.append(VenueEvent(
                name=title[:200],
                date=f"{when.strftime('%b')} {when.day}, {when.year}",
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=href if href.startswith('http') else f"{config.website_url}{href}",
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(item.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from calendar items")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_dice_widget(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from an embedded Dice.fm event-list widget.

    The venue's own page carries no events at all - it ships an empty
    `#dice-event-list-widget` div that the Dice script fills in at runtime. The
    rendered markup uses styled-component class names ("sc-64038102-3 SpeZo")
    that change with every Dice build, so matching on them cannot hold.

    Anchor on what is stable instead: each card links to link.dice.fm and
    states its date as "Wed 7 Oct - 2:30pm".
    """
    import re
    events = []
    try:
        when = re.compile(
            r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+'
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
            r'(?:\s*[‐-―\-—]\s*(\d{1,2}(?::\d{2})?\s*[ap]m))?',
            re.IGNORECASE,
        )
        seen = set()

        for link in soup.select('a[href*="dice.fm"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue

            # Climb until an ancestor carries the date line - that block is the card.
            card = link
            match = None
            for _ in range(6):
                card = card.parent
                if card is None:
                    break
                match = when.search(card.get_text("\n", strip=True))
                if match:
                    break
            if not match:
                continue

            lines = [l.strip() for l in card.get_text("\n", strip=True).split("\n") if l.strip()]
            # The billing is the first line that is neither the date nor a button.
            title = next(
                (l for l in lines
                 if not when.search(l)
                 and not re.fullmatch(r'(buy now|join the waiting list|more info|sold out|\+)', l, re.IGNORECASE)
                 and len(l) > 3),
                None,
            )
            if not title:
                continue

            seen.add(href)
            day, month, time_str = match.group(1), match.group(2).title(), match.group(3)
            events.append(VenueEvent(
                name=title[:200],
                date=f"{month} {day}, {infer_event_year(month)}",
                time=time_str.upper().replace(" ", "") if time_str else None,
                location=f"{config.name}, {config.address}",
                url=href,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(link.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from Dice widget")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_green_mill(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from the Green Mill's month calendar.

    The calendar cells show only a day number, but every event links to
    /events/YYYY-MM-DD/, so the date comes from the href rather than the text.
    Each cell can hold several sets ("(5pm - 7pm) ANDY BROWN"), which are
    emitted as separate events.
    """
    import re
    events = []
    try:
        seen = set()
        for link in soup.select('a[href*="/events/"]'):
            href = link.get('href', '')
            stamp = re.search(r'/events/(\d{4})-(\d{2})-(\d{2})', href)
            if not stamp:
                continue
            year, month, day = stamp.groups()

            cell = link.find_parent(class_='eventful') or link.parent
            text = cell.get_text("\n", strip=True) if cell else link.get_text(strip=True)

            for line in text.split("\n"):
                line = line.strip()
                # "(8pm - midnight) ALAN GRESIK'S SWING ORCHESTRA"
                billing = re.match(r'^\(([^)]*)\)\s*(.+)$', line)
                if billing:
                    time_str, title = billing.group(1).strip(), billing.group(2).strip()
                elif len(line) > 4 and not line.isdigit():
                    time_str, title = None, line
                else:
                    continue
                # A bare time range is the set time, not the act.
                if re.fullmatch(r'[\d:apm\s–—.\-]+', title, re.IGNORECASE):
                    continue
                if len(title) < 4:
                    continue

                key = (year, month, day, title.lower())
                if key in seen:
                    continue
                seen.add(key)

                when = datetime(int(year), int(month), int(day))
                events.append(VenueEvent(
                    name=title[:200],
                    date=f"{when.strftime('%b')} {when.day}, {when.year}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=href if href.startswith('http') else f"{config.website_url}{href}",
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(line),
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from calendar links")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_day_month_card(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from cards that stack the date as separate day/month tiles.

    Covers the Aragon Ballroom (`.chakra-card`) and Concord Music Hall
    (`.show.columns`), which both render something like:

        WED / 07 / OCT / <billing>

    The tiles are read from the card's text rather than per-element, since the
    two sites order and class them differently.
    """
    import re
    events = []
    try:
        containers = soup.select('.chakra-card') or soup.select('.show')
        month_day = re.compile(
            r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s*(\d{1,2})\b|'
            r'\b(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\b',
            re.IGNORECASE,
        )
        for card in containers:
            lines = [l.strip() for l in card.get_text("\n", strip=True).split("\n") if l.strip()]
            if not lines:
                continue

            joined = " ".join(lines)
            match = month_day.search(joined)
            if not match:
                continue
            month = (match.group(1) or match.group(4)).title()[:3]
            day = match.group(2) or match.group(3)

            # The billing is the longest line that is not a date tile, a weekday,
            # a doors notice or a merchandising label.
            noise = re.compile(
                r'^(MON|TUE|WED|THU|FRI|SAT|SUN)|^\d{1,2}$|doors|selling fast|sold out|'
                r'^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?$|presents?$|'
                # Button labels sit in the same card and are often the longest line.
                r'buy tickets?|get tickets?|more info|tickets available|on sale|waiting list|'
                r'^\s*(free|rsvp|learn more)\s*$',
                re.IGNORECASE,
            )
            candidates = [l for l in lines if not noise.search(l) and len(l) > 4]
            if not candidates:
                continue
            title = max(candidates, key=len)

            doors = re.search(r'(\d{1,2}(?::\d{2})?\s*[APap]\.?[Mm])', joined)
            link = card.select_one('a[href]')
            url = link.get('href', config.website_url) if link else config.website_url
            if not url.startswith('http'):
                url = f"{config.website_url}{url}"

            events.append(VenueEvent(
                name=title[:200],
                date=f"{month} {day}, {infer_event_year(month)}",
                time=doors.group(1).upper().replace(" ", "") if doors else None,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(card.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from date-tile cards")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_bramble(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Bramble Arts Loft ("What's Playing" ticket links).

    Bramble publishes no dates on its own site - each show is just a link out to
    a different ticketing platform (Universe, Tickettailor, Eventbrite), and none
    of those expose structured dates. So titles and URLs only; date stays None.
    """
    import re
    events = []
    try:
        seen = set()
        ticketing = re.compile(r'universe\.com|tickettailor\.com|eventbrite\.com|pointtheatreproject\.com', re.IGNORECASE)

        for link in soup.select('a[href]'):
            href = link.get('href', '')
            if not ticketing.search(href):
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 3 or href in seen:
                continue
            seen.add(href)

            events.append(VenueEvent(
                name=title,
                date=None,
                time=None,
                location=f"{config.name}, {config.address}",
                url=href,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(link.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from ticket links (no dates published)")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_outset(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Outset (listings block with "15 Oct • 6:30pm" meta)."""
    import re
    events = []
    try:
        for listing in soup.select('.listings-block-list__listing'):
            title_elem = listing.select_one('.listing__title')
            title = title_elem.get_text(strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            meta_elem = listing.select_one('.listingDateTime')
            meta = meta_elem.get_text(" ", strip=True) if meta_elem else ""

            date_match = re.search(
                r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', meta, re.IGNORECASE
            )
            if not date_match:
                continue
            day, month = date_match.group(1), date_match.group(2).title()

            time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*[ap]m)', meta, re.IGNORECASE)
            time_str = time_match.group(1).upper().replace(" ", "") if time_match else None

            link = listing.select_one('.listing__titleLink')
            url = link.get('href', config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            events.append(VenueEvent(
                name=title,
                date=f"{month} {day}, {infer_event_year(month)}",
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(listing.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from listings block")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_united_center(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from United Center (a.eventLink rows on the events list)."""
    import re
    events = []
    try:
        seen = set()
        # Each event links to /events/YYYY/MM/DD/slug/ - the date lives in the href,
        # which is more reliable than the calendar cell text.
        for link in soup.select('a.eventLink[href]'):
            href = link.get('href', '')
            date_match = re.search(r'/events/(\d{4})/(\d{2})/(\d{2})/', href)
            if not date_match:
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            url = href if href.startswith('http') else f"{config.website_url}{href}"
            if url in seen:
                continue
            seen.add(url)

            year, month, day = date_match.groups()
            event_date = datetime(int(year), int(month), int(day))
            date_str = f"{event_date.strftime('%b')} {event_date.day}, {event_date.year}"

            # Time appears next to the title in the row: "Gorillaz (07:30 PM)"
            row = link.find_parent('li') or link.parent
            time_match = re.search(r'\((\d{1,2}:\d{2}\s*[AP]M)\)', row.get_text(" ", strip=True), re.IGNORECASE)
            time_str = time_match.group(1).upper() if time_match else None

            events.append(VenueEvent(
                name=title,
                date=date_str,
                time=time_str,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(link.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events from event links")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_cobra_lounge(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Cobra Lounge (uses article containers with Dice FM)."""
    events = []
    try:
        # Cobra Lounge uses article tags
        articles = soup.select('article')

        for article in articles:
            # Get img alt text (event title)
            img = article.find('img')
            if img and img.get('alt'):
                title = img.get('alt').strip()

                # Cobra events might not have visible dates, so use None
                # Extract any visible text that might be date-related
                text = article.get_text()
                import re
                date_match = re.search(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', text)
                date_str = None
                if date_match:
                    date_str = f"{date_match.group(2)} {date_match.group(1)}, 2026"

                events.append(VenueEvent(
                    name=title,
                    date=date_str,
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(article.get_text(" ", strip=True)),
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from articles")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_auditorium_theatre(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Auditorium Theatre (uses eventItem divs)."""
    import re
    events = []
    try:
        # Auditorium Theatre uses div.eventItem with nested structure
        containers = soup.select('div.eventItem')

        for container in containers:
            # Get all text from container
            text = container.get_text(strip=True)

            # Skip if no content
            if len(text) < 10:
                continue

            # Date pattern: "Thu,Oct8, 2026" or similar
            date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{1,2}),?\s*2026', text)
            if not date_match:
                continue

            month = date_match.group(1)
            day = date_match.group(2)

            # Title is usually first substantial text before date
            lines = text.split('Buy Tickets')[0].split('More Info')[0].split(',')[1:] if ',' in text else text.split()
            title = None
            for line in lines:
                cleaned = line.strip()
                if 4 <= len(cleaned) <= 200 and not any(c.isdigit() for c in cleaned[:3]):
                    title = cleaned
                    break

            if title:
                events.append(VenueEvent(
                    name=title,
                    date=f"{month} {day}, 2026",
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=config.website_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(line),
                ))

        logger.info(f"{config.name}: extracted {len(events)} events from eventItem")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


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
                        category=config.category,
                        cost=parse_cost(container.get_text(" ", strip=True)),
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
                        category=config.category,
                        cost=parse_cost(line),
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
                    category=config.category,
                    cost=parse_cost(line),
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
                category=config.category,
                cost=parse_cost(item.get_text(" ", strip=True)),
            ))

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events

CHICAGO_VENUES = {
    "Loop": [
        # CIBC Theatre and the James M. Nederlander are programmed by Broadway
        # In Chicago and publish no calendar of their own, so they are covered
        # by scrapers.external.broadway_in_chicago instead of here.
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
            extractor_fn=extract_auditorium_theatre,
        ),
        VenueConfig(
            name="Goodman Theatre",
            website_url="https://www.goodmantheatre.org",
            event_page_url="https://my.goodmantheatre.org/Events",
            category="theater",
            address="170 N Dearborn St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tessitura_calendar,
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
            event_page_url="https://www.lyricopera.org/calendar/",
            category="theater",
            address="20 N Wacker Dr",
            selectors={},
            use_playwright=True,
            page_extractor_fn=extract_ace_calendar,
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
            extractor_fn=extract_dice_widget,
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
            selectors={},
            use_playwright=True,
            extractor_fn=extract_den_theatre,
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
            extractor_fn=extract_day_month_card,
        ),
        VenueConfig(
            name="Salt Shed",
            website_url="https://www.saltshedchicago.com",
            event_page_url="https://www.saltshedchicago.com/home#shows",
            category="music",
            address="1357 N Elston Ave",
            selectors={},
            use_playwright=True,
            page_extractor_fn=extract_salt_shed_playwright,
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
            extractor_fn=extract_green_mill,
        ),
        VenueConfig(
            name="Byline Bank Aragon Ballroom",
            website_url="https://www.aragonballroomchicago.com",
            event_page_url="https://www.aragonballroomchicago.com/",
            category="music",
            address="1106 W Lawrence Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_day_month_card,
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
            selectors={},
            use_playwright=True,
            extractor_fn=extract_lh_st,
            
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

    "Edgewater": [
        VenueConfig(
            name="Uncommon Ground",
            website_url="https://www.uncommonground.com",
            event_page_url="https://www.uncommonground.com/events-page",
            category="music",
            address="3800 N Clark St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_squarespace_eventlist,
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
            extractor_fn=extract_jamusa_events,
        ),
        VenueConfig(
            name="Schubas Tavern",
            website_url="https://lh-st.com",
            event_page_url="https://lh-st.com",
            category="music",
            address="3159 N Southport Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_lh_st,
            
        ),
    ],

    "Lincoln Square": [
        VenueConfig(
            name="Old Town School of Folk Music",
            website_url="https://www.oldtownschool.org",
            event_page_url="https://www.oldtownschool.org/concerts",
            category="music",
            address="4544 N Lincoln Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_old_town_school,
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
            website_url="https://www.thaliahallchicago.com",
            event_page_url="https://www.thaliahallchicago.com/shows",
            category="music",
            address="1807 S Allport St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_eb_item,
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
            extractor_fn=extract_squarespace_eventlist,
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
            event_page_url="https://www.thelincolnlodge.com/calendar",
            category="comedy",
            address="2040 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            page_extractor_fn=extract_eventscalendar_widget,
        ),
    ],

    "Humboldt Park": [
        VenueConfig(
            name="Martyrs'",
            website_url="https://martyrslive.com",
            event_page_url="https://martyrslive.com/calendar",
            category="music",
            address="3855 N Lincoln Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_martyrs,
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
    ],

    "Near West Side": [
        VenueConfig(
            name="United Center",
            website_url="https://www.unitedcenter.com",
            event_page_url="https://www.unitedcenter.com/events/",
            category="music",
            address="1901 W Madison St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_united_center,
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
            extractor_fn=extract_cobra_lounge,
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
            event_page_url="https://www.rhapsodytheater.com/upcoming-events/",
            category="theater",
            address="1328 W Morse Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_rhapsody_theater,
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

    # South Side coverage. Every venue above is North or Central, which left
    # the whole South Side unrepresented in the neighborhood filter even though
    # these venues publish full calendars.
    "Beverly": [
        VenueConfig(
            name="Beverly Arts Center",
            website_url="https://thebeverlyartscenter.com",
            event_page_url="https://thebeverlyartscenter.com/events",
            category="arts",
            address="2407 W 111th St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
    ],

    "Hyde Park": [
        VenueConfig(
            name="Hyde Park Art Center",
            website_url="https://www.hydeparkart.org",
            event_page_url="https://www.hydeparkart.org/events/",
            category="arts",
            address="5020 S Cornell Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
        VenueConfig(
            name="The Promontory",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/2716303-promontory",
            category="music",
            address="5311 S Lake Park Ave W",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],

    "Albany Park": [
        VenueConfig(
            # In Mayfair, inside the Albany Park community area. The 658-seat
            # Mayfair Theatre here is the city's main Irish music stage.
            name="Irish American Heritage Center",
            website_url="https://www.irish-american.org",
            event_page_url="https://www.irish-american.org/events/",
            category="music",
            address="4626 N Knox Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],

    "Jefferson Park": [
        VenueConfig(
            name="Copernicus Center",
            website_url="https://copernicuscenter.org",
            event_page_url="https://copernicuscenter.org/events/",
            category="music",
            address="5216 W Lawrence Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],

    "Bronzeville": [
        VenueConfig(
            # The oldest Black American art center in the US, 1940.
            name="South Side Community Art Center",
            website_url="https://sscartcenter.org",
            event_page_url="https://sscartcenter.org/events/",
            category="arts",
            address="3831 S Michigan Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
        VenueConfig(
            name="Room 43",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/620356-room-43",
            category="music",
            address="1043 E 43rd St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="Bronzeville Winery",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/4506126-bronzeville-winery",
            category="music",
            address="4420 S Cottage Grove Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],

    # Little Village's music venues are real but web-invisible: Los Globos and
    # V-Live both book touring regional Mexican acts, and neither has a working
    # site - Los Globos has none at all and vlivechicago.com refuses
    # connections. Songkick carries both calendars.
    "Little Village": [
        VenueConfig(
            name="Los Globos",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/4345062-los-globos",
            category="music",
            address="3059 S Central Park Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="V-Live",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/498306-v-live",
            category="music",
            address="2501 S Kedzie Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="Apollo's 2000",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/49204-apollos-2000",
            category="music",
            address="2875 W Cermak Rd",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="Cermak Hall",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/4378690-cermak-hall",
            category="music",
            address="2701 W Cermak Rd",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],

    "Near South Side": [
        VenueConfig(
            name="Reggies Chicago",
            website_url="https://www.reggieslive.com",
            event_page_url="https://www.reggieslive.com/2026/10/?post_type=show",
            category="music",
            address="2105 S State St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],

    "Streeterville": [
        VenueConfig(
            name="Chicago Shakespeare Theater",
            website_url="https://www.chicagoshakes.com",
            event_page_url="https://www.chicagoshakes.com/plays-and-events",
            category="theater",
            address="800 E Grand Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Lookingglass Theatre",
            website_url="https://lookingglasstheatre.org",
            event_page_url="https://lookingglasstheatre.org/whats-on/",
            category="theater",
            address="821 N Michigan Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],

    "Avondale": [
        VenueConfig(
            name="Chief O'Neill's Pub",
            website_url="https://chiefoneillspub.com",
            event_page_url="https://chiefoneillspub.com/events/",
            category="music",
            address="3471 N Elston Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Avondale Music Hall",
            website_url="https://avondalemusichall.com",
            event_page_url="https://avondalemusichall.com/",
            category="music",
            address="3528 W Belmont Ave",
            selectors={},
            use_playwright=True,
            page_extractor_fn=scrolling(extract_dated_list_items),
        ),
    ],

    "Washington Park": [
        VenueConfig(
            name="DuSable Black History Museum",
            website_url="https://www.dusablemuseum.org",
            event_page_url="https://www.dusablemuseum.org/events/",
            category="arts",
            address="740 E 56th Pl",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
    ],



    "South Shore": [
        VenueConfig(
            name="South Shore Cultural Center",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/36861-south-shore-cultural-center",
            category="music",
            address="7059 S South Shore Dr",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="Lee's Unleaded Blues",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/532626-lees-unleaded-blues",
            category="music",
            address="7401 S South Chicago Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],

    "Grand Crossing": [
        VenueConfig(
            name="The New Apartment Lounge",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/777551-new-apartment-lounge",
            category="music",
            address="504 E 75th St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],

    "North Center": [
        VenueConfig(
            name="Constellation",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/3028939-constellation-chicago",
            category="music",
            address="3111 N Western Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],
}


def venue_to_neighborhood() -> dict[str, str]:
    """Map lowercased venue name -> canonical neighborhood name.

    CHICAGO_VENUES is keyed by neighborhood, so it is the authoritative source
    for which part of the city a venue sits in.
    """
    mapping: dict[str, str] = {}
    for neighborhood, configs in CHICAGO_VENUES.items():
        for config in configs:
            mapping.setdefault(config.name.strip().lower(), canonical_neighborhood(neighborhood))
    return mapping


async def _url_taken(session, url: str) -> bool:
    """True if some event row already claims this origination_url."""
    result = await session.execute(
        select(EventModel.id).where(EventModel.origination_url == url)
    )
    return result.scalars().first() is not None


async def save_events_to_db(
    async_session_maker,
    config: VenueConfig,
    events: list[VenueEvent],
    neighborhood: Optional[str] = None,
) -> None:
    """Save extracted events to database (upsert to avoid duplicates)."""
    if not events:
        return

    async with async_session_maker() as session:
        try:
            # Which part of the city these events belong to, so the UI can
            # offer neighborhoods as a filter.
            neighborhood_id = await resolve_neighborhood_id(session, neighborhood)
            # origination_url is UNIQUE in the schema, but venues routinely reuse a
            # single URL across shows (a homepage fallback, or one tour page covering
            # two nights). Track what this batch has claimed so a collision can be
            # given a deterministic unique variant instead of raising - an IntegrityError
            # here rolls back every event for the venue, not just the colliding one.
            used_urls = set()

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
                    # Only fill a price in, never blank one out: a venue that
                    # stops printing the price on its listing page should not
                    # erase a price already collected.
                    if event.cost:
                        existing_event.cost = event.cost
                    if neighborhood_id:
                        existing_event.neighborhood_id = neighborhood_id
                else:
                    # Resolve a unique origination_url. The suffix is derived from the
                    # event's identity (source + date + name), so a later rescrape of the
                    # same event rebuilds the same URL and updates in place.
                    base_url = event.url or config.website_url
                    origination_url = base_url
                    if base_url in used_urls or await _url_taken(session, base_url):
                        date_key = parsed_date.strftime("%Y-%m-%d") if parsed_date else "nodate"
                        origination_url = f"{base_url}#{source_name}-{date_key}-{event.name[:60]}"
                        if origination_url in used_urls:
                            origination_url = f"{origination_url}-{i}"
                    used_urls.add(origination_url)

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
                        origination_url=origination_url,
                        source=source_name,
                        details=None,
                        cost=event.cost,
                        neighborhood_id=neighborhood_id,
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
                    # Hard cap per venue: a site that never finishes loading (or a
                    # browser that won't close) would otherwise stall the whole run.
                    events = await asyncio.wait_for(
                        scraper.scrape(client), timeout=VENUE_SCRAPE_TIMEOUT
                    )
                    neighborhood_events.extend(events)
                    total_events += len(events)

                    # Save events to database
                    await save_events_to_db(async_session, config, events, neighborhood)

                except asyncio.TimeoutError:
                    logger.error(f"{config.name}: timed out after {VENUE_SCRAPE_TIMEOUT}s, skipping")
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
