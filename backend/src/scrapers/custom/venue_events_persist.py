"""
Fetch and persist events from venue scrapers to the database.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scrapers.venue_scraper import scrape_all_venues
from shared.database.models import EventModel

logger = logging.getLogger(__name__)


async def fetch_and_persist_venue_events(session: AsyncSession) -> int:
    """
    Scrape events from all registered venues and persist to database.
    Returns count of new events added.
    """
    try:
        events = await scrape_all_venues()

        if not events:
            logger.info("No venue events scraped")
            return 0

        added_count = 0

        for event in events:
            try:
                # Parse date if available
                event_date = None
                if event.date:
                    try:
                        # Try parsing various date formats
                        from dateutil import parser

                        event_date = parser.parse(event.date)
                    except Exception:
                        logger.debug(f"Could not parse date: {event.date}")

                # Skip if no valid date found
                if not event_date:
                    logger.debug(f"Skipping event {event.name} - no valid date")
                    continue

                # Check if event already exists (by URL)
                existing = await session.execute(
                    select(EventModel).where(EventModel.origination_url == event.url)
                )
                if existing.scalars().first():
                    logger.debug(f"Event already exists: {event.url}")
                    continue

                # Create and insert new event
                db_event = EventModel(
                    name=event.name,
                    date=event_date,
                    category=event.category,
                    details=None,
                    origination_url=event.url,
                    date_retrieved=datetime.utcnow(),
                    source="venue_scraper",
                    venue_name=event.venue_name,
                )

                session.add(db_event)
                added_count += 1
                logger.debug(f"Added event: {event.name} ({event.venue_name})")

            except Exception as e:
                logger.error(f"Failed to persist event {event.name}: {e}")

        # Commit all at once
        if added_count > 0:
            await session.commit()
            logger.info(f"Persisted {added_count} new venue events")

        return added_count

    except Exception as e:
        logger.error(f"Failed to fetch and persist venue events: {e}")
        await session.rollback()
        return 0
