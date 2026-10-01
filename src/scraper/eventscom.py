import logging
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from pyppeteer import launch
from src.models import EventCreate
from src.database.models import EventModel

logger = logging.getLogger(__name__)


class EventsComScraper:
    """
    Scraper for Events.com Chicago events using Pyppeteer for JavaScript rendering.
    Pyppeteer is a Python port of Puppeteer and works with Python 3.15.
    """

    BASE_URL = "https://discover.events.com"
    CHICAGO_URL = f"{BASE_URL}/us/illinois/chicago"
    REQUEST_TIMEOUT = 30000  # 30 seconds in ms

    async def fetch_events(self) -> list[EventCreate]:
        """Fetch Events.com Chicago events using Pyppeteer with JavaScript extraction"""
        browser = None
        try:
            events = []

            # Launch browser
            browser = await launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
            page = await browser.newPage()

            # Set viewport and user agent
            await page.setViewport({'width': 1280, 'height': 1024})
            await page.setUserAgent(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # Navigate to Chicago events page
            logger.info(f"Loading {self.CHICAGO_URL}")
            await page.goto(self.CHICAGO_URL, {'waitUntil': 'networkidle2', 'timeout': self.REQUEST_TIMEOUT})

            # Wait and scroll to trigger lazy loading
            logger.info("Waiting for events to load...")
            await page.evaluate('() => new Promise(resolve => setTimeout(resolve, 3000))')

            # Scroll down to trigger lazy loading
            for i in range(3):
                await page.evaluate('window.scrollBy(0, window.innerHeight)')
                await page.evaluate('() => new Promise(resolve => setTimeout(resolve, 1000))')

            # Scroll back to top
            await page.evaluate('window.scrollTo(0, 0)')
            await page.evaluate('() => new Promise(resolve => setTimeout(resolve, 1000))')

            # Extract events via JavaScript
            event_data = await page.evaluate('''
                () => {
                    const events = [];
                    const eventElements = Array.from(document.querySelectorAll('div, article, li')).filter(el => {
                        const text = el.innerText || '';
                        return text.length > 20 && text.length < 1000;
                    });

                    eventElements.forEach(el => {
                        try {
                            const text = (el.innerText || el.textContent || '').trim();
                            const lines = text.split('\\n').filter(l => l.trim().length > 2);
                            if (lines.length < 2) return;

                            const title = lines[0].substring(0, 100).trim();
                            let dateText = '';

                            for (const line of lines) {
                                if (/\\d{1,2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|today|tonight|tomorrow/i.test(line)) {
                                    dateText = line.substring(0, 100).trim();
                                    break;
                                }
                            }

                            if (title && dateText && title.length > 3) {
                                const href = el.querySelector('a[href]')?.href || el.closest('a[href]')?.href || '';
                                if (title && dateText) {
                                    events.push({title, dateText, url: href});
                                }
                            }
                        } catch(e) {}
                    });

                    return events.slice(0, 200);
                }
            ''')

            logger.info(f"Extracted {len(event_data)} event records via JavaScript")

            # Parse the extracted data
            for item in event_data:
                try:
                    event = self._convert_to_event(item)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.debug(f"Error converting event: {e}")

            await browser.close()
            logger.info(f"Fetched {len(events)} events from Events.com")
            return events

        except Exception as e:
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            logger.error(f"Error fetching Events.com events: {e}")
            return []

    def _parse_events(self, soup: BeautifulSoup) -> list[EventCreate]:
        """Parse events from BeautifulSoup object"""
        events = []

        # Try multiple selectors for event containers
        selectors = [
            '[data-event]',
            '.event-item',
            '.event-card',
            '.event',
            '[class*="event"]',
        ]

        event_elements = []
        for selector in selectors:
            event_elements = soup.select(selector)
            if event_elements:
                logger.debug(f"Found {len(event_elements)} events with selector: {selector}")
                break

        for element in event_elements:
            try:
                event = self._parse_event_element(element)
                if event:
                    events.append(event)
            except Exception as e:
                logger.debug(f"Error parsing event: {e}")
                continue

        return events

    def _convert_to_event(self, data: dict) -> Optional[EventCreate]:
        """Convert extracted event data to EventCreate"""
        try:
            title = data.get('title', '').strip()
            if not title or len(title) < 3:
                return None

            date_text = data.get('dateText', '').strip()
            if not date_text:
                return None

            try:
                event_date = self._parse_date(date_text)
            except (ValueError, TypeError):
                logger.debug(f"Could not parse date: {date_text}")
                return None

            url = data.get('url', '').strip()
            if not url:
                url = self.CHICAGO_URL
            elif not url.startswith('http'):
                url = f"{self.BASE_URL}{url}"

            return EventCreate(
                name=title,
                date=event_date,
                category="Events",
                details=None,
                origination_url=url,
            )
        except Exception as e:
            logger.debug(f"Conversion error: {e}")
            return None

    def _parse_event_element(self, element) -> Optional[EventCreate]:
        """Parse a single event from HTML element"""
        try:
            # Extract title/name
            title_elem = element.select_one('h2, h3, h4, a, [class*="title"], [class*="name"]')
            title = title_elem.get_text(strip=True) if title_elem else None

            if not title or len(title) < 3:
                return None

            # Extract date
            date_elem = element.select_one('time, [class*="date"], [data-date], .date')
            date_text = None

            if date_elem:
                date_text = date_elem.get('datetime')
                if not date_text:
                    date_text = date_elem.get_text(strip=True)

            if not date_text:
                return None

            try:
                event_date = self._parse_date(date_text)
            except (ValueError, TypeError):
                logger.debug(f"Could not parse date: {date_text}")
                return None

            # Extract category
            category = "Events"
            category_elem = element.select_one('[class*="category"], .category, .tag, [class*="type"]')
            if category_elem:
                category = category_elem.get_text(strip=True)

            # Extract description/details
            details = None
            details_elem = element.select_one('[class*="description"], .description, .excerpt')
            if details_elem:
                details = details_elem.get_text(strip=True)[:300]

            # Extract URL
            url_elem = element.select_one('a[href]')
            origination_url = None

            if url_elem and url_elem.get('href'):
                href = url_elem['href']
                if href.startswith('http'):
                    origination_url = href
                else:
                    origination_url = f"{self.BASE_URL}{href}"

            if not origination_url:
                origination_url = self.CHICAGO_URL

            return EventCreate(
                name=title,
                date=event_date,
                category=category,
                details=details,
                origination_url=origination_url,
            )

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    def _parse_date(self, date_text: str) -> datetime:
        """Parse date from various formats"""
        date_text = date_text.strip()

        formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%B %d, %Y",
            "%b %d, %Y",
            "%m/%d/%Y",
            "%A, %B %d, %Y",
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(date_text, fmt)
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed
            except ValueError:
                continue

        raise ValueError(f"Could not parse date: {date_text}")

    async def scrape_and_save(self, db: Session) -> int:
        """Fetch events and save new ones to database"""
        try:
            events = await self.fetch_events()
            saved_count = 0
            seen_urls = set()

            for event_data in events:
                url = event_data.origination_url
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                existing = db.query(EventModel).filter_by(origination_url=url).first()
                if not existing:
                    event = EventModel(**event_data.model_dump(), source="eventscom")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()

            db.commit()
            logger.info(f"Saved {saved_count} new events from Events.com")
            return saved_count

        except Exception as e:
            logger.error(f"Error saving events: {e}")
            db.rollback()
            return 0
