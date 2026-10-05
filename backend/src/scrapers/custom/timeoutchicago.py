import logging
import httpx
from datetime import datetime
from typing import Optional, Union
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from shared.models import EventCreate
from shared.database.models import EventModel
from app.ai.event_enrichment import extract_from_event_text

logger = logging.getLogger(__name__)


class TimeoutChicagoScraper:
    """
    Scraper for Timeout Chicago event listings using static HTML parsing.
    """

    BASE_URL = "https://www.timeout.com"
    CHICAGO_BASE = f"{BASE_URL}/chicago"
    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    async def fetch_events(self, months: list[str] | None = None) -> list[EventCreate]:
        """Fetch events from Timeout Chicago calendar pages"""
        if months is None:
            months = ["october", "november", "december"]

        try:
            events = []
            seen_urls = set()

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT, follow_redirects=True) as client:
                for month in months:
                    try:
                        calendar_url = f"{self.CHICAGO_BASE}/events-calendar/{month}-events-calendar"
                        logger.info(f"Fetching {month} events from {calendar_url}")

                        response = await client.get(
                            calendar_url,
                            headers={"User-Agent": self.USER_AGENT},
                        )
                        response.raise_for_status()

                        soup = BeautifulSoup(response.text, "html.parser")
                        month_events = self._parse_calendar_page(soup, month)

                        logger.info(f"Found {len(month_events)} events in {month}")

                        for event in month_events:
                            if event.origination_url not in seen_urls:
                                events.append(event)
                                seen_urls.add(event.origination_url)

                    except Exception as e:
                        logger.warning(f"Error fetching {month} events: {e}")
                        continue

            logger.info(f"Fetched {len(events)} total events from Timeout Chicago")
            return events

        except Exception as e:
            logger.error(f"Timeout Chicago fetch error: {type(e).__name__}: {e}")
            return []

    def _parse_calendar_page(self, soup: BeautifulSoup, month: str) -> list[EventCreate]:
        """Parse events from calendar page HTML"""
        events = []

        event_containers = soup.find_all("article")
        logger.debug(f"Found {len(event_containers)} article tags")

        for container in event_containers:
            try:
                event = self._parse_event_card(container, month)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug(f"Error parsing event card: {e}")
                continue

        return events

    def _parse_event_card(self, card, month: str) -> Optional[EventCreate]:
        """Parse a single event card from HTML"""
        try:
            title_elem = card.find("h3")
            if not title_elem:
                return None

            title = title_elem.get_text(strip=True)
            if not title or len(title) < 3:
                return None

            link_elem = card.find("a", attrs={"data-testid": "tile-link_testID"})
            if not link_elem or not link_elem.get("href"):
                link_elem = card.find("a", href=True)

            url = None
            if link_elem and link_elem.get("href"):
                url = link_elem["href"]
                if not url.startswith("http"):
                    url = f"{self.BASE_URL}{url}"

            if not url:
                return None

            date_text = self._extract_date_text(card)
            if not date_text:
                return None

            try:
                event_date = self._parse_date(date_text, month)
            except (ValueError, TypeError):
                logger.debug(f"Could not parse date: {date_text}")
                return None

            category = self._extract_category(card)
            venue = self._extract_venue(card)
            description = venue if venue else None

            # Extract cost and age_range from title and details
            cost, age_range = extract_from_event_text(title, description)

            event = EventCreate(
                name=title,
                date=event_date,
                category=category,
                details=description,
                origination_url=url,
            )

            # Add cost and age_range to the event if extracted
            if cost:
                event.cost = cost
            if age_range:
                event.age_range = age_range

            return event

        except Exception as e:
            logger.debug(f"Error parsing event card: {e}")
            return None

    def _extract_date_text(self, card) -> Optional[str]:
        """Extract date text from event card"""
        elem = card.find("time")
        if elem:
            return elem.get("datetime") or elem.get_text(strip=True)

        elem = card.find("span", {"data-testid": "event-date"})
        if elem:
            return elem.get_text(strip=True)

        for div in card.find_all("div"):
            div_class = div.get("class", [])
            if any("date" in cls.lower() for cls in div_class):
                return div.get_text(strip=True)

        for text_node in card.stripped_strings:
            if any(
                x in text_node.lower() for x in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "-"]
            ):
                return text_node

        return None

    def _extract_category(self, card) -> str:
        """Extract category/tags from event card"""
        for span in card.find_all("span"):
            span_class = span.get("class", [])
            if any("tag" in cls.lower() for cls in span_class):
                return span.get_text(strip=True)

        for div in card.find_all("div"):
            div_class = div.get("class", [])
            if any("category" in cls.lower() for cls in div_class):
                return div.get_text(strip=True)

        for a in card.find_all("a"):
            a_class = a.get("class", [])
            if any("genre" in cls.lower() for cls in a_class):
                return a.get_text(strip=True)

        return "Events"

    def _extract_venue(self, card) -> Optional[str]:
        """Extract venue/location from event card"""
        for div in card.find_all("div"):
            div_class = div.get("class", [])
            if any("venue" in cls.lower() for cls in div_class):
                return div.get_text(strip=True)

        for span in card.find_all("span"):
            span_class = span.get("class", [])
            if any("location" in cls.lower() for cls in span_class):
                return span.get_text(strip=True)

        for p in card.find_all("p"):
            p_class = p.get("class", [])
            if any("address" in cls.lower() for cls in p_class):
                return p.get_text(strip=True)

        return None

    def _parse_date(self, date_text: str, month: str) -> datetime:
        """Parse date from various formats"""
        date_text = date_text.strip()
        now = datetime.now()
        current_year = now.year

        try:
            parsed = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
            return parsed
        except (ValueError, AttributeError):
            pass

        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
        }
        month_num = month_map.get(month.lower(), now.month)

        formats = [
            "%B %d, %Y",
            "%b %d, %Y",
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%B %d",
            "%b %d",
        ]

        for fmt in formats:
            try:
                if "%" in fmt and fmt.count("%") == 2:
                    parsed = datetime.strptime(f"{date_text} {current_year}", f"{fmt} %Y")
                else:
                    parsed = datetime.strptime(date_text, fmt)
                    if parsed.year == 1900:
                        parsed = parsed.replace(year=current_year)

                return parsed
            except ValueError:
                continue

        try:
            parts = date_text.split()
            if len(parts) >= 2:
                day = int(parts[0])
                parsed = datetime(current_year, month_num, day)
                return parsed
        except (ValueError, IndexError):
            pass

        raise ValueError(f"Could not parse date: {date_text}")

    async def scrape_and_save(self, db: Union[Session, AsyncSession], days_ahead: int = 30, months: list[str] | None = None) -> int:
        """Fetch events and save new ones to database (sync or async)"""
        try:
            events = await self.fetch_events(months=months)
            saved_count = 0
            seen_urls = set()

            is_async = isinstance(db, AsyncSession)

            for event_data in events:
                url = event_data.origination_url
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if is_async:
                    # Async query
                    result = await db.execute(
                        select(EventModel).filter_by(origination_url=url)
                    )
                    existing = result.scalar_one_or_none()
                else:
                    # Sync query
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="timeoutchicago")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from Timeout Chicago")
            return saved_count

        except Exception as e:
            logger.error(f"Save error: {e}")
            if is_async:
                await db.rollback()
            else:
                db.rollback()
            return 0
