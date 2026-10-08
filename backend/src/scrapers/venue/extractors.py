"""One extractor per way a venue publishes its calendar.

Split out of chicago_events_scraper. Every function here takes a parsed page
and a `VenueConfig` and returns `VenueEvent`s; none of them names a venue or
writes anything, so the list grows without the rest of the scraper changing.

They exist because there is no common format. Some venues publish schema.org
JSON-LD and need almost nothing (`extract_events_from_json_ld`); some are a
widget from a ticketing platform shared by several venues (Dice, Tessitura,
Songkick, Tickeri, AEG's "Showtime", The Events Calendar); and some are
hand-built pages whose only structure is that each card happens to start with
a date, which is what the generic `extract_dated_list_items` reads.
"""

import json
import logging
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from shared.localtime import to_chicago_naive

from .venue_parsing import (
    _MONTH,
    _MONTHS,
    _ONE_RE,
    _RUN_RE,
    _WEEKDAY_PREFIXES,
    _card_lines,
    _dates_from_text,
    _title_from,
    infer_event_year,
    jsonld_offer_cost,
)
from .venue_scraper import VenueConfig, VenueEvent, parse_cost

logger = logging.getLogger(__name__)


def extract_events_from_json_ld(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from JSON-LD schema.org data embedded in HTML."""
    events = []
    try:
        # Find all JSON-LD script tags
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string)

                # Handle @graph wrapper
                if "@graph" in data:
                    items = data["@graph"]
                elif isinstance(data, list):
                    items = data
                else:
                    items = [data]

                # Extract events from the structure
                for item in items:
                    # Check if it's an Event or contains Events
                    if item.get("@type") == "Event":
                        event_data = item
                    elif item.get("@type") == "Place" and "Events" in item:
                        # Handle Place with Events array
                        for event_data in item.get("Events", []):
                            if event_data.get("@type") != "Event":
                                continue

                            name = event_data.get("name", "").strip()
                            if not name or len(name) < 2:
                                continue

                            # Parse ISO datetime: "2026-10-06T04:59:00Z"
                            start_date = None
                            end_date = None

                            if "startDate" in event_data:
                                try:
                                    start_date = to_chicago_naive(
                                        datetime.fromisoformat(event_data["startDate"])
                                    )
                                except ValueError, AttributeError:
                                    pass

                            if "endDate" in event_data:
                                try:
                                    end_date = to_chicago_naive(
                                        datetime.fromisoformat(event_data["endDate"])
                                    )
                                except ValueError, AttributeError:
                                    pass

                            url = event_data.get("url", config.website_url)

                            events.append(
                                VenueEvent(
                                    name=name,
                                    date=start_date.isoformat() if start_date else None,
                                    date_end=end_date.isoformat() if end_date else None,
                                    time=None,
                                    location=f"{config.name}, {config.address}",
                                    url=url,
                                    venue_name=config.name,
                                    category=config.category,
                                    cost=jsonld_offer_cost(event_data),
                                )
                            )
                        continue
                    else:
                        continue

                    # Handle single Event item
                    name = event_data.get("name", "").strip()
                    if not name or len(name) < 2:
                        continue

                    start_date = None
                    end_date = None

                    if "startDate" in event_data:
                        try:
                            start_date = to_chicago_naive(
                                datetime.fromisoformat(event_data["startDate"])
                            )
                        except ValueError, AttributeError:
                            pass

                    if "endDate" in event_data:
                        try:
                            end_date = to_chicago_naive(
                                datetime.fromisoformat(event_data["endDate"])
                            )
                        except ValueError, AttributeError:
                            pass

                    url = event_data.get("url")
                    if not url:
                        slug = re.sub(r"[^\w\s-]", "", name).replace(" ", "-").lower()
                        url = f"{config.website_url.rstrip('/')}#{slug}"

                    events.append(
                        VenueEvent(
                            name=name,
                            date=start_date.isoformat() if start_date else None,
                            date_end=end_date.isoformat() if end_date else None,
                            time=None,
                            location=f"{config.name}, {config.address}",
                            url=url,
                            venue_name=config.name,
                            category=config.category,
                            cost=jsonld_offer_cost(event_data),
                        )
                    )

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
            ticket_url = (
                ticket_link.get("href", config.website_url) if ticket_link else config.website_url
            )

            events.append(
                VenueEvent(
                    name=event_name,
                    date=None,
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=ticket_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(article.get_text(" ", strip=True)),
                )
            )
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
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            if not lines:
                continue

            event_name = None
            event_date = None

            for line in lines:
                if line == "Selling Fast" or not event_name:
                    if line != "Selling Fast" and len(line) > 3:
                        if not any(x in line for x in ["Doors", "doors", "age"]):
                            event_name = line
                            break

            for line in lines:
                if re.search(r"\d{1,2}/\d{1,2}", line):
                    event_date = line
                    break

            if event_name and len(event_name) > 3:
                # Extract event URL: look for link in container, fall back to generated URL
                event_url = config.website_url
                link = container.find("a", href=True)
                if link and link.get("href"):
                    href = link.get("href")
                    if href.startswith("/"):
                        event_url = config.website_url.rstrip("/") + href
                    elif href.startswith("http"):
                        event_url = href
                else:
                    slug = re.sub(r"[^\w\s-]", "", event_name).replace(" ", "-").lower()
                    event_url = f"{config.website_url.rstrip('/')}#{slug}-{idx}"

                events.append(
                    VenueEvent(
                        name=event_name,
                        date=event_date,
                        time=None,
                        location=f"{config.name}, {config.address}",
                        url=event_url,
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(container.get_text(" ", strip=True)),
                    )
                )

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
            skip_terms = ["Home", "Login", "Sign up", "back", "next", "cart", "search", "checkout"]
            if any(term in text for term in skip_terms):
                continue

            # Extract URL if available
            url = link.get("href", config.website_url)
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            # This is an event name
            events.append(
                VenueEvent(
                    name=text,
                    date=None,  # Dates not exposed in static calendar
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=url if url != config.website_url else config.website_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(link.get_text(" ", strip=True)),
                )
            )

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
            link = item.find("a", href=True)
            if link and link.get("href"):
                href = link.get("href")
                if href.startswith("/"):
                    event_url = config.website_url.rstrip("/") + href
                elif href.startswith("http"):
                    event_url = href
            else:
                slug = re.sub(r"[^\w\s-]", "", name).replace(" ", "-").lower()
                event_url = f"{config.website_url.rstrip('/')}#{slug}-{idx}"

            events.append(
                VenueEvent(
                    name=name,
                    date=date_str,  # "October 3, 2026" format
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=event_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(item.get_text(" ", strip=True)),
                )
            )

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
        pattern = r"(\d{1,2}):(\d{2})\s*([ap])\s+([A-Za-z0-9\s\-:&]+?)(?=\d{1,2}:|Oct|Day|SUN|$)"
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)

        # Don't deduplicate - each time entry is a separate show
        for hour, minute, ampm, event_name in matches:
            title = event_name.strip()
            if len(title) > 3:
                # Map time to approximate date (Oct 15-17 visible in calendar)
                events.append(
                    VenueEvent(
                        name=title,
                        date="Oct 15, 2026",
                        time=f"{hour}:{minute}{ampm}",
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,
                        venue_name=config.name,
                        category=config.category,
                    )
                )

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
        await page.wait_for_selector("div[data-venue-events]", timeout=30000)

        # Scroll and load all cards
        for _ in range(20):
            try:
                # Try to click "load more" button
                more = page.locator("text=/load more|show more|see more/i")
                if await more.count():
                    await more.first.click()
                    await page.wait_for_timeout(1200)
                else:
                    # Scroll if no button
                    await page.mouse.wheel(0, 4000)
                    await page.wait_for_timeout(1000)
            except Exception:
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
            if card["date"] and card["title"]:
                # Parse date like "TUE, OCT 6"
                date_match = re.search(
                    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})",
                    card["date"],
                    re.IGNORECASE,
                )
                if date_match:
                    month = date_match.group(1)
                    day = date_match.group(2)

                    events.append(
                        VenueEvent(
                            name=card["title"],
                            date=f"{month} {day}, {infer_event_year(month)}",
                            time=card["doors"],
                            location=f"{config.name}, {config.address}",
                            url=card.get("url") or config.website_url,
                            venue_name=config.name,
                            category=config.category,
                        )
                    )

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
        articles = soup.select("article.ve-events__card")

        for article in articles:
            text = article.get_text(strip=True)

            # Look for date pattern: "Sat, Feb 20" or similar
            date_match = re.search(
                r"(\w{3}),?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", text
            )
            if not date_match:
                continue

            month = date_match.group(2)
            day = date_match.group(3)

            # Look for time pattern: "Doors: 6:00 PM"
            time_match = re.search(r"Doors:\s*(\d{1,2}):(\d{2})\s*([AP]M)", text, re.IGNORECASE)
            time_str = (
                f"{time_match.group(1)}:{time_match.group(2)}{time_match.group(3)}"
                if time_match
                else None
            )

            # Extract title - text after PM until age restriction or venue name (non-greedy)
            title_match = re.search(
                r"[AP]M\s+(.+?)(?:17 & Over|All Ages|The Salt Shed|Shed)", text, re.IGNORECASE
            )
            title = title_match.group(1).strip() if title_match else None

            if title and len(title) > 3:
                events.append(
                    VenueEvent(
                        name=title,
                        date=f"{month} {day}, 2026",
                        time=time_str,
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(article.get_text(" ", strip=True)),
                    )
                )

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
        for item in soup.select(".eb-item"):
            title_elem = item.select_one(".title")
            title = title_elem.get_text(" ", strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            date_elem = item.select_one(".date")
            date_text = date_elem.get_text(" ", strip=True) if date_elem else ""
            match = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})",
                date_text,
                re.IGNORECASE,
            )
            if not match:
                continue
            month = match.group(1).title()[:3]
            day = match.group(2)

            time_elem = item.select_one(".start-time")
            time_str = time_elem.get_text(" ", strip=True) if time_elem else None

            link = item.select_one('a[href*="ticketweb"]') or item.select_one("a[href]")
            url = link.get("href", config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            venue_elem = item.select_one(".venue")
            venue_name = venue_elem.get_text(" ", strip=True) if venue_elem else config.name

            events.append(
                VenueEvent(
                    name=title,
                    date=f"{month} {day}, {infer_event_year(month)}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=venue_name or config.name,
                    category=config.category,
                    cost=parse_cost(item.get_text(" ", strip=True)),
                )
            )

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

        for card in soup.select(".card"):
            title_elem = card.select_one(".card-title")
            title = title_elem.get_text(" ", strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            text = card.get_text(" ", strip=True)
            if wanted not in text.lower():
                continue

            # "OCT 07"
            match = re.search(
                r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{1,2})\b",
                text,
                re.IGNORECASE,
            )
            if not match:
                continue
            month = match.group(1).title()
            day = match.group(2)

            time_elem = card.select_one(".tessera-showTime")
            time_str = time_elem.get_text(" ", strip=True) if time_elem else None

            card.select_one(".showAges")
            link = card.select_one("a[href]")
            url = link.get("href", config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            events.append(
                VenueEvent(
                    name=title,
                    date=f"{month} {day}, {infer_event_year(month)}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(card.get_text(" ", strip=True)),
                )
            )

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
        for schedule in soup.select(".views-field-field-show-schedule-value"):
            line = schedule.get_text(" ", strip=True)
            match = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})",
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
                bands = row.select_one(".views-field-field-show-bands-nid")
                if bands:
                    break
            title = bands.get_text(" ", strip=True) if bands else None
            if not title or len(title) < 3:
                continue

            # "Doors 6:30PM - Show 7:30PM" -> keep the show time where given
            show = re.search(r"Show\s*(\d{1,2}(?::\d{2})?\s*[APap]\.?[Mm])", line)
            doors = re.search(r"Doors\s*(\d{1,2}(?::\d{2})?\s*[APap]\.?[Mm])", line)
            time_str = (
                (show or doors).group(1).upper().replace(" ", "") if (show or doors) else None
            )

            cost = None
            if re.search(r"no cover|free", line, re.IGNORECASE):
                cost = "Free"
            else:
                price = re.search(r"\$(\d+)", line)
                if price:
                    cost = f"${price.group(1)}"

            events.append(
                VenueEvent(
                    name=title[:200],
                    date=f"{month} {day}, {infer_event_year(month)}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=config.event_page_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=cost,
                )
            )

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
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2})\s+(\d{4})(?:.*?(\d{1,2}:\d{2}\s*[AP]M))?",
            re.IGNORECASE,
        )
        for row in soup.select(".concertListing"):
            text = row.get_text(" ", strip=True)
            match = line_pattern.search(text)
            if not match:
                continue
            month, day, year, time_str = match.groups()

            # The billing is the first heading in the row.
            heading = row.find(["h2", "h3", "h4"])
            title = heading.get_text(" ", strip=True) if heading else None
            if not title:
                # Fall back to the longest link text, which is the show name.
                links = [a.get_text(" ", strip=True) for a in row.select("a")]
                links = [t for t in links if t and "ticket" not in t.lower()]
                title = max(links, key=len) if links else None
            if not title or len(title) < 3:
                continue

            link = row.select_one("a[href]")
            url = link.get("href", config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            events.append(
                VenueEvent(
                    name=title[:200],
                    date=f"{month[:3].title()} {day}, {year}",
                    time=time_str.upper() if time_str else None,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(row.get_text(" ", strip=True)),
                )
            )

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
        for item in soup.select(".eventlist-event"):
            classes = " ".join(item.get("class", []))
            if "past" in classes:
                continue

            title_elem = item.select_one(".eventlist-title, .eventlist-title-link")
            title = title_elem.get_text(" ", strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            stamp = item.select_one("time[datetime]")
            iso = stamp.get("datetime") if stamp else None
            if not iso:
                continue
            try:
                parsed = datetime.strptime(iso[:10], "%Y-%m-%d")
            except ValueError:
                continue

            time_elem = item.select_one(".event-time-12hr")
            # Squarespace uses a narrow no-break space inside times.
            time_str = time_elem.get_text(" ", strip=True).replace(" ", " ") if time_elem else None

            link = item.select_one("a[href]")
            url = link.get("href", config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            events.append(
                VenueEvent(
                    name=title[:200],
                    date=f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(item.get_text(" ", strip=True)),
                )
            )

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
            if not any(
                part in response.url for part in ("/data/public/events", "/eventbrite/events")
            ):
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
                except TypeError, ValueError, OSError:
                    continue

                key = (when.date(), title.lower())
                if key in seen:
                    continue
                seen.add(key)

                events.append(
                    VenueEvent(
                        name=title[:200],
                        date=f"{when.strftime('%b')} {when.day}, {when.year}",
                        time=when.strftime("%-I:%M %p") if (when.hour or when.minute) else None,
                        location=f"{config.name}, {config.address}",
                        url=config.event_page_url,
                        venue_name=config.name,
                        category=config.category,
                    )
                )

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
            r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            re.IGNORECASE,
        )
        for cell in soup.select(".tn-events-calendar__day"):
            items = cell.select(".tn-events-calendar__day-event-list-item")
            if not items:
                continue

            label = cell.select_one(".sr-only")
            match = full_date.search(label.get_text(" ", strip=True)) if label else None
            if not match:
                continue
            day, month, year = match.group(1), match.group(2)[:3].title(), match.group(3)

            for item in items:
                name_elem = item.select_one(".tn-events-calendar__event-name")
                title = name_elem.get_text(" ", strip=True) if name_elem else None
                if not title or len(title) < 3:
                    continue

                time_elem = item.select_one(".tn-events-calendar__event-time")
                raw_time = time_elem.get_text(" ", strip=True) if time_elem else ""
                stamp = re.search(r"(\d{1,2}:\d{2}\s*[APap]\.?[Mm])", raw_time)

                link = item.select_one("a[href]")
                url = link.get("href", config.event_page_url) if link else config.event_page_url
                if not url.startswith("http"):
                    url = f"{config.website_url}{url}"

                events.append(
                    VenueEvent(
                        name=title[:200],
                        date=f"{month} {day}, {year}",
                        time=stamp.group(1).upper().replace(" ", "") if stamp else None,
                        location=f"{config.name}, {config.address}",
                        url=url,
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(item.get_text(" ", strip=True)),
                    )
                )

        logger.info(f"{config.name}: extracted {len(events)} events from Tessitura calendar")
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_dated_links(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events whose date is in the URL, as /events/YYYY/MM/DD/slug.

    Common on Jekyll-built sites - Chi Hack Night publishes one page per
    meeting that way. Reading the date from the href rather than the page text
    is both simpler and safer: there is no year to infer and no date-like
    string in a description to trip over.

    Past meetings stay linked forever on these sites, so anything older than
    yesterday is dropped rather than filling the database with history.
    """
    cutoff = datetime.now() - timedelta(days=1)
    events = []
    seen = set()

    for link in soup.select('a[href*="/20"]'):
        href = link.get("href") or ""
        match = re.search(r"/(?P<y>20\d{2})/(?P<m>\d{1,2})/(?P<d>\d{1,2})/", href)
        if not match:
            continue
        try:
            when = datetime(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        except ValueError:
            continue
        if when < cutoff:
            continue

        title = link.get_text(" ", strip=True)
        # The same event is linked several times per card (image, title,
        # "Details"), and only one of those carries the name.
        if not title or len(title) < 4 or title.lower() in ("details", "more", "read more"):
            continue

        key = (when.date(), title.lower())
        if key in seen:
            continue
        seen.add(key)

        url = href if href.startswith("http") else f"{config.website_url.rstrip('/')}{href}"
        events.append(
            VenueEvent(
                name=title[:200],
                date=f"{when.strftime('%b')} {when.day}, {when.year}",
                time=None,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
            )
        )

    logger.info(f"{config.name}: extracted {len(events)} events from dated links")
    return events


def extract_labelled_meeting(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract a single recurring meeting from a long-form page.

    A user group's homepage is not a calendar: ChiPy publishes its next
    meeting as prose with labelled fields - "When: Oct. 8, 2026, 6 p.m." and
    "Where: AlphaSense, 200 N. LaSalle Street" - so there is one event to
    find, not a list of cards. The card-shaped extractors see nothing here.

    The venue moves monthly (these groups meet at whichever company is
    hosting), so the address comes off the page rather than from the config.
    """
    lines = [ln.strip() for ln in soup.get_text("\n", strip=True).split("\n") if ln.strip()]

    def after(label: str, limit: int = 6) -> list[str]:
        """The lines following a label, up to the next label or `limit`."""
        for i, line in enumerate(lines):
            if line.rstrip(":").strip().lower() == label.lower().rstrip(":"):
                out = []
                for nxt in lines[i + 1 : i + 1 + limit]:
                    if nxt.endswith(":") and len(nxt) < 24:
                        break
                    out.append(nxt)
                return out
        return []

    when = after("When", limit=1)
    if not when:
        logger.info(f"{config.name}: no 'When:' block on the page")
        return []

    # "Oct. 8, 2026, 6 p.m."
    match = re.search(
        rf"(?P<m>{_MONTH})\s*(?P<d>\d{{1,2}}),\s*(?P<y>\d{{4}})", when[0], re.IGNORECASE
    )
    if not match:
        logger.info(f"{config.name}: could not read a date from {when[0]!r}")
        return []
    clock = re.search(r"(\d{1,2}(?::\d{2})?)\s*([apAP])\.?[mM]\.?", when[0])

    where = after("Where", limit=5)
    venue = where[0] if where else config.name
    street = " ".join(where[1:]) if len(where) > 1 else config.address

    # "NEXT EVENT CHIPY __MAIN__ MEETING" - drop the kicker.
    heading = next(
        (
            h.get_text(" ", strip=True)
            for h in soup.find_all(["h1", "h2", "h3"])
            if "meeting" in h.get_text(" ", strip=True).lower()
        ),
        config.name,
    )
    title = re.sub(r"^\s*(next event|upcoming event)\s*", "", heading, flags=re.IGNORECASE).strip()

    return [
        VenueEvent(
            name=(title or config.name)[:200],
            date=f"{match.group('m')[:3].title()} {int(match.group('d'))}, {match.group('y')}",
            time=(f"{clock.group(1)} {clock.group(2).upper()}M" if clock else None),
            # The host venue, which changes month to month.
            location=f"{venue}, {street}".strip(", "),
            url=config.event_page_url,
            venue_name=venue,
            category=config.category,
        )
    ]


def extract_aeg_showtime(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from an AEG "Showtime"/carbonhouse venue site.

    The markup is semantic, so this reads the real elements rather than
    guessing from text: the title lives in its own heading, separate from the
    promoter line. That distinction matters - the generic extractor read
    Radius's promoter credit ("Auris Presents") as the name of three shows,
    because it sits above the title in the card.
    """
    events = []
    seen = set()

    for card in soup.select("#eventsList .entry, .event_list .entry"):
        link = card.select_one("h3.carousel_item_title_small a, .title h3 a")
        title = link.get_text(" ", strip=True) if link else None
        if not title:
            continue

        date_elem = card.select_one("span.date")
        if not date_elem:
            continue
        # "Thu, Oct 8, 2026"
        match = _ONE_RE.search(date_elem.get_text(" ", strip=True))
        if not match:
            continue
        year = match.group("y") or infer_event_year(match.group("m"))
        date_str = f"{match.group('m')[:3].title()} {int(match.group('d'))}, {year}"

        key = (date_str, title.lower())
        if key in seen:
            continue
        seen.add(key)

        time_elem = card.select_one("span.time")
        clock = re.search(
            r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)",
            time_elem.get_text(" ", strip=True) if time_elem else "",
        )

        href = link.get("href") or config.event_page_url
        if not href.startswith("http"):
            href = f"{config.website_url.rstrip('/')}{href}"

        # The support acts are worth keeping, since a bill is often why
        # someone goes, but they do not belong in the title.
        support = card.select_one("h4.supporting")
        support.get_text(" ", strip=True) if support else None

        events.append(
            VenueEvent(
                name=title[:200],
                date=date_str,
                time=clock.group(1).upper().replace(".", "") if clock else None,
                location=f"{config.name}, {config.address}",
                url=href,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(card.get_text(" ", strip=True)),
            )
        )

    logger.info(f"{config.name}: extracted {len(events)} events from AEG Showtime")
    return events


def extract_tickeri_venue(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract a venue's events from its Tickeri page.

    Tickeri is the ticketing platform behind much of Chicago's Latin music
    circuit, and several of those venues have no website of their own. It is a
    Next.js app, so the page ships its data in a __NEXT_DATA__ script tag:
    structured events with an ISO timestamp and, unusually, a ticket price.
    That makes it better than scraping the rendered page and better than
    Songkick, which carries no prices at all.
    """
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        logger.warning(f"{config.name}: no __NEXT_DATA__ on the page")
        return []

    try:
        payload = json.loads(script.string)
    except ValueError:
        logger.warning(f"{config.name}: __NEXT_DATA__ is not valid JSON")
        return []

    # The events sit at an unstable depth under pageProps, so collect every
    # Event object rather than relying on a fixed path.
    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 10:
            return
        if isinstance(node, dict):
            if node.get("__typename") == "Event" and node.get("name"):
                found.append(node)
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)

    walk(payload)

    events = []
    seen = set()
    for item in found:
        # Tickeri keeps canceled shows in the feed, flagged by status.
        if (item.get("status") or "").upper() not in ("LIVE", "", "ACTIVE"):
            continue

        date_info = (item.get("eventDate") or {}).get("date") or {}
        iso = date_info.get("isoDateTime") or date_info.get("localDate")
        if not iso:
            continue
        try:
            when = datetime.fromisoformat(iso)
        except ValueError:
            continue

        title = (item.get("name") or "").strip()
        key = (when.date(), title.lower())
        if not title or key in seen:
            continue
        seen.add(key)

        price_range = item.get("ticketPriceRange") or {}
        low = (price_range.get("min") or {}).get("major")
        high = (price_range.get("max") or {}).get("major")
        cost = None
        if low is not None:
            if high is not None and high != low:
                cost = f"${low:g}-${high:g}"
            else:
                # Only a floor is published, so say so rather than implying
                # it is the whole price.
                cost = f"From ${low:g}" if low else "Free"

        events.append(
            VenueEvent(
                name=title[:200],
                date=f"{when.strftime('%b')} {when.day}, {when.year}",
                time=when.strftime("%-I:%M %p") if (when.hour or when.minute) else None,
                location=f"{config.name}, {config.address}",
                url=item.get("url") or config.event_page_url,
                venue_name=config.name,
                category=config.category,
                cost=cost,
            )
        )

    logger.info(f"{config.name}: extracted {len(events)} events from Tickeri")
    return events


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
            if low.startswith(
                ("buy tickets", "interested", "going", "don't miss", "dont miss", "tickets")
            ):
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

        events.append(
            VenueEvent(
                name=title[:200],
                date=f"{when.strftime('%b')} {when.day}, {when.year}",
                time=when.strftime("%-I:%M %p") if (when.hour or when.minute) else None,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
            )
        )

    logger.info(f"{config.name}: extracted {len(events)} events from Songkick")
    return events


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
    # Where a venue's markup is semantic, name the elements instead of
    # guessing. The heuristic reads the first plausible line as the title,
    # which on these sites is a kicker label ("EVENT-EXHIBITION") or a photo
    # credit ("THEMBA HADEBE / AP") sitting above the real one.
    container_selector = config.selectors.get("event_container")
    title_selector = config.selectors.get("title")
    date_selector = config.selectors.get("date")

    if container_selector:
        events = []
        seen = set()
        for card in soup.select(container_selector):
            title_el = card.select_one(title_selector) if title_selector else None
            title = (
                title_el.get_text(" ", strip=True)
                if title_el
                else _title_from(_card_lines(card), config.name)
            )
            if not title:
                continue

            date_el = card.select_one(date_selector) if date_selector else None
            date_text = (
                date_el.get_text(" ", strip=True) if date_el else card.get_text(" ", strip=True)
            )
            date_str, date_end_str = _dates_from_text(date_text)
            if not date_str:
                continue

            key = (date_str, title.lower())
            if key in seen:
                continue
            seen.add(key)

            clock = re.search(
                r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)", card.get_text(" ", strip=True)
            )
            link = card.select_one("a[href]")
            url = link["href"] if link else config.event_page_url
            if not url.startswith("http"):
                url = f"{config.website_url.rstrip('/')}{url if url.startswith('/') else '/' + url}"

            events.append(
                VenueEvent(
                    name=title[:200],
                    date=date_str,
                    date_end=date_end_str,
                    time=clock.group(1).upper().replace(".", "") if clock else None,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(card.get_text(" ", strip=True)),
                )
            )
        logger.info(f"{config.name}: extracted {len(events)} events from named selectors")
        return events

    # Where a venue's markup is semantic, name the elements instead of
    # guessing. The heuristic reads the first plausible line as the title,
    # which on these sites is a kicker label ("EVENT-EXHIBITION") or a photo
    # credit ("THEMBA HADEBE / AP") sitting above the real one.
    container_selector = config.selectors.get("event_container")
    title_selector = config.selectors.get("title")
    date_selector = config.selectors.get("date")

    if container_selector:
        events = []
        seen = set()
        for card in soup.select(container_selector):
            title_el = card.select_one(title_selector) if title_selector else None
            title = (
                title_el.get_text(" ", strip=True)
                if title_el
                else _title_from(_card_lines(card), config.name)
            )
            if not title:
                continue

            date_el = card.select_one(date_selector) if date_selector else None
            date_text = (
                date_el.get_text(" ", strip=True) if date_el else card.get_text(" ", strip=True)
            )
            date_str, date_end_str = _dates_from_text(date_text)
            if not date_str:
                continue

            key = (date_str, title.lower())
            if key in seen:
                continue
            seen.add(key)

            clock = re.search(
                r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)", card.get_text(" ", strip=True)
            )
            link = card.select_one("a[href]")
            url = link["href"] if link else config.event_page_url
            if not url.startswith("http"):
                url = f"{config.website_url.rstrip('/')}{url if url.startswith('/') else '/' + url}"

            events.append(
                VenueEvent(
                    name=title[:200],
                    date=date_str,
                    date_end=date_end_str,
                    time=clock.group(1).upper().replace(".", "") if clock else None,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(card.get_text(" ", strip=True)),
                )
            )
        logger.info(f"{config.name}: extracted {len(events)} events from named selectors")
        return events

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
        # A datepicker or filter widget carries dates but is not an event.
        # Form controls are what separates it from a card: real event cards
        # almost never contain an <input> or <select>.
        if el.find(["input", "select", "textarea"]):
            continue
        if _title_from(_card_lines(el), config.name):
            candidates.append(el)

    # Of the nested candidates keep the innermost, so the list container isn't
    # reported as one giant event. Checked by identity against a set rather
    # than pairwise, which would be quadratic on a large page.
    qualified = {id(el) for el in candidates}
    chosen = [
        el
        for el in candidates
        if not any(id(d) in qualified for d in el.descendants if d is not el)
    ]

    events = []
    seen = set()
    for el in chosen:
        lines = _card_lines(el)

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

        title = _title_from(lines, config.name)
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

        events.append(
            VenueEvent(
                name=title[:200],
                date=date_str,
                date_end=date_end_str,
                time=clock.group(1).upper().replace(".", "") if clock else None,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(el.get_text(" ", strip=True)),
            )
        )

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
        time_text = (
            time_elem.get_text(" ", strip=True) if time_elem else item.get_text(" ", strip=True)
        )
        clock = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?)", time_text)

        link = item.select_one("a[href]")
        url = link["href"] if link else config.event_page_url
        if not url.startswith("http"):
            url = f"{config.website_url.rstrip('/')}{url}"

        events.append(
            VenueEvent(
                name=title[:200],
                date=f"{when.strftime('%b')} {when.day}, {when.year}",
                time=clock.group(1).upper().replace(".", "") if clock else None,
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
                cost=parse_cost(item.get_text(" ", strip=True)),
            )
        )

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
                except ValueError, OSError:
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

                    events.append(
                        VenueEvent(
                            name=title[:200],
                            date=f"{when.strftime('%b')} {when.day}, {when.year}",
                            time=time_str,
                            location=f"{config.name}, {config.address}",
                            url=url,
                            venue_name=config.name,
                            category=config.category,
                            cost=cost,
                        )
                    )

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


def _den_event_url(href: str, config: VenueConfig) -> str:
    """Absolute Den Theatre event URL, using the site's own path.

    The site exposes an event under both /calendar/<date>/<slug> and
    /performances/<date>/<slug>, but the slugs differ and the paths are NOT
    interchangeable: where the calendar slug carries a uniqueness suffix
    ("...-5ssy7-b4xks") only /calendar/ resolves, and where it does not, only
    /performances/ does. Rewriting the path therefore 404s for a subset, so
    the href the page gives us is used as-is - it is by definition the one
    that works.
    """
    if not href:
        return config.event_page_url
    return href if href.startswith("http") else f"{config.website_url.rstrip('/')}{href}"


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
        for item in soup.select(".item"):
            link = item.select_one("a[href]")
            href = link.get("href", "") if link else ""
            stamp = re.search(r"/calendar/(\d{4})/(\d{1,2})/(\d{1,2})", href)
            if not stamp:
                continue
            year, month, day = (int(g) for g in stamp.groups())

            time_elem = item.select_one(".item-time--12hr")
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
            title = re.sub(
                r"^\s*\d{1,2}:\d{2}\s*([AP]M)?\s*", "", title, flags=re.IGNORECASE
            ).strip()
            if not title or len(title) < 3:
                continue

            key = (year, month, day, title.lower())
            if key in seen:
                continue
            seen.add(key)

            when = datetime(year, month, day)
            events.append(
                VenueEvent(
                    name=title[:200],
                    date=f"{when.strftime('%b')} {when.day}, {when.year}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=_den_event_url(href, config),
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(item.get_text(" ", strip=True)),
                )
            )

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
            r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+"
            r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
            r"(?:\s*[‐-―\-—]\s*(\d{1,2}(?::\d{2})?\s*[ap]m))?",
            re.IGNORECASE,
        )
        seen = set()

        # Only ticket links. Matching every dice.fm link also caught the
        # widget's own footer - "https://dice.fm" and
        # "https://dice.fm/privacy_policy.html" - and because the climb below
        # looks upward for a date, each of those reached the nearest card and
        # was stored as a third copy of that event.
        for link in soup.select('a[href*="link.dice.fm/"]'):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            if re.search(r"/(privacy|terms|cookie|about|app|help)", href, re.IGNORECASE):
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

            lines = [ln.strip() for ln in card.get_text("\n", strip=True).split("\n") if ln.strip()]
            # The billing is the first line that is neither the date nor a button.
            title = next(
                (
                    ln
                    for ln in lines
                    if not when.search(ln)
                    and not re.fullmatch(
                        r"(buy now|join the waiting list|more info|sold out|\+)", ln, re.IGNORECASE
                    )
                    and len(ln) > 3
                ),
                None,
            )
            if not title:
                continue

            seen.add(href)
            day, month, time_str = match.group(1), match.group(2).title(), match.group(3)
            events.append(
                VenueEvent(
                    name=title[:200],
                    date=f"{month} {day}, {infer_event_year(month)}",
                    time=time_str.upper().replace(" ", "") if time_str else None,
                    location=f"{config.name}, {config.address}",
                    url=href,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(link.get_text(" ", strip=True)),
                )
            )

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
            href = link.get("href", "")
            stamp = re.search(r"/events/(\d{4})-(\d{2})-(\d{2})", href)
            if not stamp:
                continue
            year, month, day = stamp.groups()

            cell = link.find_parent(class_="eventful") or link.parent
            text = cell.get_text("\n", strip=True) if cell else link.get_text(strip=True)

            for line in text.split("\n"):
                line = line.strip()
                # "(8pm - midnight) ALAN GRESIK'S SWING ORCHESTRA"
                billing = re.match(r"^\(([^)]*)\)\s*(.+)$", line)
                if billing:
                    time_str, title = billing.group(1).strip(), billing.group(2).strip()
                elif len(line) > 4 and not line.isdigit():
                    time_str, title = None, line
                else:
                    continue
                # A bare time range is the set time, not the act.
                if re.fullmatch(r"[\d:apm\s–—.\-]+", title, re.IGNORECASE):
                    continue
                if len(title) < 4:
                    continue

                key = (year, month, day, title.lower())
                if key in seen:
                    continue
                seen.add(key)

                when = datetime(int(year), int(month), int(day))
                events.append(
                    VenueEvent(
                        name=title[:200],
                        date=f"{when.strftime('%b')} {when.day}, {when.year}",
                        time=time_str,
                        location=f"{config.name}, {config.address}",
                        url=href if href.startswith("http") else f"{config.website_url}{href}",
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(line),
                    )
                )

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
        containers = soup.select(".chakra-card") or soup.select(".show")
        month_day = re.compile(
            r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s*(\d{1,2})\b|"
            r"\b(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\b",
            re.IGNORECASE,
        )
        for card in containers:
            lines = [ln.strip() for ln in card.get_text("\n", strip=True).split("\n") if ln.strip()]
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
                r"^(MON|TUE|WED|THU|FRI|SAT|SUN)|^\d{1,2}$|doors|selling fast|sold out|"
                r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?$|presents?$|"
                # Button labels sit in the same card and are often the longest line.
                r"buy tickets?|get tickets?|more info|tickets available|on sale|waiting list|"
                r"^\s*(free|rsvp|learn more)\s*$",
                re.IGNORECASE,
            )
            candidates = [ln for ln in lines if not noise.search(ln) and len(ln) > 4]
            if not candidates:
                continue
            title = max(candidates, key=len)

            doors = re.search(r"(\d{1,2}(?::\d{2})?\s*[APap]\.?[Mm])", joined)
            link = card.select_one("a[href]")
            url = link.get("href", config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            events.append(
                VenueEvent(
                    name=title[:200],
                    date=f"{month} {day}, {infer_event_year(month)}",
                    time=doors.group(1).upper().replace(" ", "") if doors else None,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(card.get_text(" ", strip=True)),
                )
            )

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
        ticketing = re.compile(
            r"universe\.com|tickettailor\.com|eventbrite\.com|pointtheatreproject\.com",
            re.IGNORECASE,
        )

        for link in soup.select("a[href]"):
            href = link.get("href", "")
            if not ticketing.search(href):
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 3 or href in seen:
                continue
            seen.add(href)

            events.append(
                VenueEvent(
                    name=title,
                    date=None,
                    time=None,
                    location=f"{config.name}, {config.address}",
                    url=href,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(link.get_text(" ", strip=True)),
                )
            )

        logger.info(
            f"{config.name}: extracted {len(events)} events from ticket links (no dates published)"
        )
        return events

    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
        return []


def extract_outset(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Outset (listings block with "15 Oct • 6:30pm" meta)."""
    import re

    events = []
    try:
        for listing in soup.select(".listings-block-list__listing"):
            title_elem = listing.select_one(".listing__title")
            title = title_elem.get_text(strip=True) if title_elem else None
            if not title or len(title) < 3:
                continue

            meta_elem = listing.select_one(".listingDateTime")
            meta = meta_elem.get_text(" ", strip=True) if meta_elem else ""

            date_match = re.search(
                r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
                meta,
                re.IGNORECASE,
            )
            if not date_match:
                continue
            day, month = date_match.group(1), date_match.group(2).title()

            time_match = re.search(r"(\d{1,2}(?::\d{2})?\s*[ap]m)", meta, re.IGNORECASE)
            time_str = time_match.group(1).upper().replace(" ", "") if time_match else None

            link = listing.select_one(".listing__titleLink")
            url = link.get("href", config.website_url) if link else config.website_url
            if not url.startswith("http"):
                url = f"{config.website_url}{url}"

            events.append(
                VenueEvent(
                    name=title,
                    date=f"{month} {day}, {infer_event_year(month)}",
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(listing.get_text(" ", strip=True)),
                )
            )

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
        for link in soup.select("a.eventLink[href]"):
            href = link.get("href", "")
            date_match = re.search(r"/events/(\d{4})/(\d{2})/(\d{2})/", href)
            if not date_match:
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            url = href if href.startswith("http") else f"{config.website_url}{href}"
            if url in seen:
                continue
            seen.add(url)

            year, month, day = date_match.groups()
            event_date = datetime(int(year), int(month), int(day))
            date_str = f"{event_date.strftime('%b')} {event_date.day}, {event_date.year}"

            # Time appears next to the title in the row: "Gorillaz (07:30 PM)"
            row = link.find_parent("li") or link.parent
            time_match = re.search(
                r"\((\d{1,2}:\d{2}\s*[AP]M)\)", row.get_text(" ", strip=True), re.IGNORECASE
            )
            time_str = time_match.group(1).upper() if time_match else None

            events.append(
                VenueEvent(
                    name=title,
                    date=date_str,
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(link.get_text(" ", strip=True)),
                )
            )

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
        articles = soup.select("article")

        for article in articles:
            # Get img alt text (event title)
            img = article.find("img")
            if img and img.get("alt"):
                title = img.get("alt").strip()

                # Cobra events might not have visible dates, so use None
                # Extract any visible text that might be date-related
                text = article.get_text()
                import re

                date_match = re.search(
                    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", text
                )
                date_str = None
                if date_match:
                    date_str = f"{date_match.group(2)} {date_match.group(1)}, 2026"

                events.append(
                    VenueEvent(
                        name=title,
                        date=date_str,
                        time=None,
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(article.get_text(" ", strip=True)),
                    )
                )

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
        containers = soup.select("div.eventItem")

        for container in containers:
            # Get all text from container
            text = container.get_text(strip=True)

            # Skip if no content
            if len(text) < 10:
                continue

            # Date pattern: "Thu,Oct8, 2026" or similar
            date_match = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{1,2}),?\s*2026", text
            )
            if not date_match:
                continue

            month = date_match.group(1)
            day = date_match.group(2)

            # Title is usually first substantial text before date
            lines = (
                text.split("Buy Tickets")[0].split("More Info")[0].split(",")[1:]
                if "," in text
                else text.split()
            )
            title = None
            for line in lines:
                cleaned = line.strip()
                if 4 <= len(cleaned) <= 200 and not any(c.isdigit() for c in cleaned[:3]):
                    title = cleaned
                    break

            if title:
                events.append(
                    VenueEvent(
                        name=title,
                        date=f"{month} {day}, 2026",
                        time=None,
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(line),
                    )
                )

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
        containers = soup.select("div.eventItem")

        for container in containers:
            text = container.get_text(strip=True)

            # Date format: "Oct7Wed" or "Oct23Mon"
            date_match = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{1,2})\w{3}", text
            )
            if not date_match:
                continue

            month = date_match.group(1)
            day = date_match.group(2)

            # Extract title - look for artist name after "Jam Presents"
            title_match = re.search(r"Jam Presents(.+?)(?:with |Doors:|$)", text)
            if title_match:
                title = title_match.group(1).strip()
                if len(title) > 3 and len(title) < 200:
                    events.append(
                        VenueEvent(
                            name=title,
                            date=f"{month} {day}, 2026",
                            time=None,
                            location=f"{config.name}, {config.address}",
                            url=config.website_url,
                            venue_name=config.name,
                            category=config.category,
                            cost=parse_cost(container.get_text(" ", strip=True)),
                        )
                    )

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
        for selector in ["div", '[class*="event"]', "article", ".show", ".item", "li"]:
            containers = soup.select(selector)
            if not containers:
                continue

            for container in containers:
                text = container.get_text(strip=True)

                # Skip empty or very short text
                if len(text) < 20 or len(text) > 2000:
                    continue

                # Look for date pattern (month + day)
                date_match = re.search(
                    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", text
                )
                if not date_match:
                    continue

                # Extract title - take first substantial line
                lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                title = None
                for line in lines:
                    if 8 <= len(line) <= 200 and not line.startswith("http"):
                        title = line
                        break

                if title:
                    events.append(
                        VenueEvent(
                            name=title,
                            date=f"{date_match.group(1)} {date_match.group(2)}, 2026",
                            time=None,
                            location=f"{config.name}, {config.address}",
                            url=config.website_url,
                            venue_name=config.name,
                            category=config.category,
                            cost=parse_cost(line),
                        )
                    )

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
        day_cells = soup.select("[data-date]")

        for cell in day_cells:
            date_str = cell.get("data-date")

            # Get events in this cell
            event_titles = cell.select('[class*="event-title"], .fc-event-title')

            for event_el in event_titles:
                text = event_el.get_text(strip=True)
                if not text or "Timezone" in text:
                    continue

                # Parse title and time
                lines = text.split("\n")
                title = lines[0].strip()

                # Find time (HH:MM AM/PM pattern)
                time_str = None
                for line in lines:
                    if ":" in line and ("AM" in line.upper() or "PM" in line.upper()):
                        time_str = line.strip()
                        break

                # Parse date to datetime
                try:
                    parsed_date = datetime.fromisoformat(date_str)
                except Exception:
                    parsed_date = None

                events.append(
                    VenueEvent(
                        name=title,
                        date=parsed_date.isoformat() if parsed_date else None,
                        time=time_str,
                        location=f"{config.name}, {config.address}",
                        url=config.website_url,  # No individual event URLs, use venue URL
                        venue_name=config.name,
                        category=config.category,
                        cost=parse_cost(line),
                    )
                )

        logger.info(f"{config.name}: extracted {len(events)} events from calendar")
    except Exception as e:
        logger.error(f"{config.name} calendar extraction failed: {e}")

    return events


def extract_squarespace_calendar(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from a Squarespace (YUI) month-grid calendar.

    Replaces a selector-based read of li[class*='item'], which was wrong in
    three ways at once:

    * The grid renders each entry twice - once in ul.itemlist for the cell and
      again in ul.flyoutitemlist for the hover card - so every event was
      stored twice.
    * A multi-day run repeats in every day cell it spans, so a four-night
      booking became four more copies. Eight rows for one show.
    * get_text() with no separator glued the three sibling time spans
      ("8:00 PM", "20:00", "8:00 PM") onto the title, producing
      "20:008:00 PMChristopher McBride & The Whole Proof".

    Read the real elements instead: the day number from the cell's marker, the
    month and year from the grid header, and the title from its own span. A
    run collapses to one event dated from its first cell, with date_end taken
    from "(ends Oct 11)".
    """
    header = soup.select_one(".yui3-calendar-header, [class*=calendar-header]")
    header_text = header.get_text(" ", strip=True) if header else ""
    month_match = re.search(rf"({_MONTH})\s*(\d{{4}})", header_text, re.IGNORECASE)
    if not month_match:
        logger.warning(f"{config.name}: no month header on the calendar")
        return []
    month_name = month_match.group(1)[:3].title()
    year = int(month_match.group(2))
    month = _MONTHS.get(month_name)
    if not month:
        return []

    # Keyed by the event's own link, so a run spanning four cells is one event
    # and the earliest cell wins as its start date.
    found: dict[str, dict] = {}

    for cell in soup.select("td.yui3-calendar-day"):
        daynum = cell.select_one(".marker-daynum")
        if not daynum or not daynum.get_text(strip=True).isdigit():
            continue
        try:
            when = datetime(year, month, int(daynum.get_text(strip=True)))
        except ValueError:
            continue

        # ul.itemlist only - ul.flyoutitemlist is the same entries again.
        for item in cell.select("ul.itemlist li.item"):
            title_el = item.select_one("span.item-title")
            title = title_el.get_text(" ", strip=True) if title_el else None
            if not title:
                continue

            link = item.select_one("a[href]")
            href = link.get("href") if link else None
            key = href or f"{title.lower()}|{when:%Y-%m}"

            time_el = item.select_one("span.item-time--12hr")
            # Squarespace uses a narrow no-break space in times.
            time_str = time_el.get_text(" ", strip=True).replace("\u202f", " ") if time_el else None

            end_el = item.select_one("span.item-enddate")
            date_end = None
            if end_el:
                end_match = re.search(
                    rf"({_MONTH})\s*(\d{{1,2}})", end_el.get_text(" ", strip=True), re.IGNORECASE
                )
                if end_match:
                    end_month = _MONTHS.get(end_match.group(1)[:3].title())
                    if end_month:
                        # A run crossing into January belongs to the next year.
                        end_year = year + 1 if end_month < month else year
                        date_end = f"{end_match.group(1)[:3].title()} {int(end_match.group(2))}, {end_year}"

            existing = found.get(key)
            if existing and existing["when"] <= when:
                continue
            found[key] = {
                "when": when,
                "title": title,
                "time": time_str,
                "date_end": date_end,
                "href": href,
            }

    events = []
    for entry in found.values():
        url = entry["href"] or config.event_page_url
        if not url.startswith("http"):
            url = f"{config.website_url.rstrip('/')}{url if url.startswith('/') else '/' + url}"
        events.append(
            VenueEvent(
                name=entry["title"][:200],
                date=f"{entry['when']:%b} {entry['when'].day}, {entry['when'].year}",
                date_end=entry["date_end"],
                time=entry["time"],
                location=f"{config.name}, {config.address}",
                url=url,
                venue_name=config.name,
                category=config.category,
            )
        )

    logger.info(f"{config.name}: extracted {len(events)} events from the calendar grid")
    return events


def extract_squarespace_events(soup: BeautifulSoup, config: VenueConfig) -> list[VenueEvent]:
    """Extract events from Squarespace li[class*='item'] structure."""
    events = []
    try:
        event_items = soup.select("li[class*='item']")
        logger.info(f"{config.name}: found {len(event_items)} event items")

        for _idx, item in enumerate(event_items):
            text = item.get_text(strip=True)
            if not text or len(text) < 3:
                continue

            # Skip navigation and UI items
            skip_terms = [
                "home",
                "calendar",
                "faqs",
                "faq",
                "contact",
                "about",
                "menu",
                "search",
                "login",
                "signup",
                "cart",
                "checkout",
                "gallery",
                "photos",
                "videos",
                "news",
                "blog",
                "press",
                "instagram",
                "facebook",
                "twitter",
                "social",
            ]
            if any(term in text.lower() for term in skip_terms):
                continue

            # Also skip month names if very short (likely navigation)
            if (
                any(
                    month in text.lower()
                    for month in [
                        "january",
                        "february",
                        "march",
                        "april",
                        "may",
                        "june",
                        "july",
                        "august",
                        "september",
                        "october",
                        "november",
                        "december",
                    ]
                )
                and len(text) < 20
            ):
                continue

            # Extract time
            time_match = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))", text)
            time_str = time_match.group(1) if time_match else None
            event_name = re.sub(r"^\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)\s*", "", text).strip()

            # Extract date
            date_str = None
            ends_match = re.search(r"\(ends?\s+(.+?)\)", event_name, re.IGNORECASE)
            if ends_match:
                date_str = ends_match.group(1).strip()
                event_name = re.sub(r"\(ends?.+?\)", "", event_name).strip()

            if not event_name or len(event_name) < 2:
                continue

            # Extract event URL: look for link in item, fall back to website URL
            event_url = config.website_url
            link = item.find("a", href=True)
            if link and link.get("href"):
                href = link.get("href")
                # Convert relative URLs to absolute
                if href.startswith("/"):
                    event_url = config.website_url.rstrip("/") + href
                elif href.startswith("http"):
                    event_url = href

            events.append(
                VenueEvent(
                    name=event_name,
                    date=date_str,
                    time=time_str,
                    location=f"{config.name}, {config.address}",
                    url=event_url,
                    venue_name=config.name,
                    category=config.category,
                    cost=parse_cost(item.get_text(" ", strip=True)),
                )
            )

        logger.info(f"{config.name}: extracted {len(events)} events")
    except Exception as e:
        logger.error(f"{config.name} extraction failed: {e}")
    return events
