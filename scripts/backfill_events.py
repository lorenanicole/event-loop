"""
Backfill script to extract cost and age_range for existing events in the database.
Run this to populate cost/age_range fields for events that were created before this feature.
"""

import asyncio
import logging
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from src.database import init_db, AsyncSessionLocal
from src.database.models import EventModel
from src.ai.event_enrichment import extract_from_event_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def backfill_cost_and_age_range() -> dict:
    """
    Scan all events in DB with NULL cost or age_range fields.
    Extract these values from name + details.
    Update events where extraction was successful.

    Returns: dict with stats about the backfill
    """
    await init_db()
    logger.info("Starting backfill of cost and age_range fields...")

    stats = {
        "total_processed": 0,
        "cost_updated": 0,
        "age_range_updated": 0,
        "both_updated": 0,
        "errors": 0,
    }

    async with AsyncSessionLocal() as session:
        try:
            # Query events where cost OR age_range is NULL
            result = await session.execute(
                select(EventModel).filter(
                    (EventModel.cost.is_(None)) | (EventModel.age_range.is_(None))
                )
            )
            events_to_update = result.scalars().all()
            stats["total_processed"] = len(events_to_update)

            if not events_to_update:
                logger.info("No events to backfill (all cost and age_range fields are populated)")
                return stats

            logger.info(f"Found {len(events_to_update)} events to backfill")

            for i, event in enumerate(events_to_update, 1):
                try:
                    # Extract cost and age_range
                    cost, age_range = extract_from_event_text(
                        event_name=event.name,
                        details=event.details,
                    )

                    # Update only if extraction was successful and field is NULL
                    updated = False

                    if cost and event.cost is None:
                        event.cost = cost
                        updated = True
                        stats["cost_updated"] += 1

                    if age_range and event.age_range is None:
                        event.age_range = age_range
                        updated = True
                        stats["age_range_updated"] += 1

                    if updated and cost and age_range:
                        stats["both_updated"] += 1

                    # Log progress every 10 events
                    if i % 10 == 0:
                        logger.info(f"Processed {i}/{len(events_to_update)} events")

                except Exception as e:
                    logger.error(f"Error processing event {event.id}: {e}")
                    stats["errors"] += 1

            # Commit all updates
            await session.commit()
            logger.info(f"Backfill complete. Stats: {stats}")

        except Exception as e:
            logger.error(f"Backfill failed: {e}")
            stats["errors"] += 1
            await session.rollback()

    return stats


async def main():
    """Run backfill from command line"""
    stats = await backfill_cost_and_age_range()

    print("\n" + "=" * 60)
    print("BACKFILL RESULTS")
    print("=" * 60)
    print(f"Total Processed: {stats['total_processed']}")
    print(f"Cost Updated: {stats['cost_updated']}")
    print(f"Age Range Updated: {stats['age_range_updated']}")
    print(f"Both Fields Updated: {stats['both_updated']}")
    print(f"Errors: {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
