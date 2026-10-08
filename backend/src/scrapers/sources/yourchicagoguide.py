import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from shared.database.models import EventModel
from shared.enrichment import extract_from_event_text
from shared.schemas import EventCreate

logger = logging.getLogger(__name__)

# Rows written before the lock is released. SQLite serializes writers, and
# these scrapers used to add several hundred events inside one transaction -
# which held the write lock for minutes and failed every `INSERT INTO
# chat_threads` a chat tried to make meanwhile, with "database is locked".
# Raising busy_timeout to 30s did not help: no wait beats a transaction held
# that long. Committing in batches does, by letting go between them.
WRITE_BATCH = 50


class YourChicagoGuideScraper:
    """
    Scraper for Your Chicago Guide events using WordPress REST API.
    Their events are published as blog posts in category 48.
    """

    BASE_URL = "https://yourchicagoguide.com"
    WP_API_URL = f"{BASE_URL}/wp-json/wp/v2/posts"
    EVENTS_CATEGORY_ID = 48
    REQUEST_TIMEOUT = 10
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    async def fetch_events(self, days_ahead: int = 30) -> list[EventCreate]:
        """Fetch events from Your Chicago Guide WordPress REST API"""
        try:
            events = []
            page = 1

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                while True:
                    params = {
                        "categories": self.EVENTS_CATEGORY_ID,
                        "per_page": 100,
                        "page": page,
                        "orderby": "date",
                        "order": "desc",
                    }

                    response = await client.get(
                        self.WP_API_URL,
                        params=params,
                        headers={"User-Agent": self.USER_AGENT},
                    )
                    response.raise_for_status()

                    posts = response.json()

                    if not posts:
                        break

                    for post in posts:
                        try:
                            event = self._parse_post(post)
                            if event:
                                events.append(event)
                        except Exception as e:
                            logger.debug(f"Error parsing post: {e}")
                            continue

                    # Check if there are more pages
                    if len(posts) < 100:
                        break

                    page += 1

            logger.info(f"Fetched {len(events)} events from Your Chicago Guide")
            return events

        except Exception as e:
            logger.error(f"Error fetching Your Chicago Guide events: {e}")
            return []

    def _parse_post(self, post: dict) -> EventCreate | None:
        """Parse a WordPress post into an event"""
        try:
            title = post.get("title", {})
            if isinstance(title, dict):
                title = title.get("rendered", "").strip()
            else:
                title = str(title).strip()

            if not title or len(title) < 3:
                return None

            # Get date
            date_str = post.get("date")
            if not date_str:
                return None

            try:
                event_date = datetime.fromisoformat(date_str)
            except ValueError, TypeError:
                return None

            # Extract event details from content/excerpt
            post.get("content", {})
            excerpt = post.get("excerpt", {})

            details = None
            if isinstance(excerpt, dict):
                details = excerpt.get("rendered", "").strip()
            elif excerpt:
                details = str(excerpt).strip()

            # Remove HTML tags if present
            if details:
                details = details.replace("<p>", "").replace("</p>", "").replace("&nbsp;", " ")
                details = details[:500].strip()

            # Category - events from Your Chicago Guide
            category = "Events"

            # URL
            origination_url = post.get("link")
            if not origination_url:
                return None

            # Extract cost and age_range from title and details
            cost, age_range = extract_from_event_text(title, details)

            event = EventCreate(
                name=title,
                date=event_date,
                category=category,
                details=details,
                origination_url=origination_url,
            )

            # Add cost and age_range to the event if extracted
            if cost:
                event.cost = cost
            if age_range:
                event.age_range = age_range

            return event

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    async def scrape_and_save(self, db: Session | AsyncSession, days_ahead: int = 30) -> int:
        """Fetch events and save new ones to database (sync or async)"""
        try:
            events = await self.fetch_events(days_ahead=days_ahead)
            saved_count = 0
            seen_urls = set()

            is_async = isinstance(db, AsyncSession)

            processed = 0
            for event_data in events:
                processed += 1
                if processed % WRITE_BATCH == 0:
                    # Release the write lock so an
                    # interactive write can get in.
                    if is_async:
                        await db.commit()
                    else:
                        db.commit()
                url = event_data.origination_url
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if is_async:
                    # Async query
                    result = await db.execute(select(EventModel).filter_by(origination_url=url))
                    existing = result.scalar_one_or_none()
                else:
                    # Sync query
                    existing = db.query(EventModel).filter_by(origination_url=url).first()

                if not existing:
                    event = EventModel(**event_data.model_dump(), source="yourchicagoguide")
                    db.add(event)
                    saved_count += 1
                else:
                    existing.date_retrieved = datetime.utcnow()

            if is_async:
                await db.commit()
            else:
                db.commit()

            logger.info(f"Saved {saved_count} new events from Your Chicago Guide")
            return saved_count

        except Exception as e:
            logger.error(f"Error saving events: {e}")
            if is_async:
                await db.rollback()
            else:
                db.rollback()
            return 0
