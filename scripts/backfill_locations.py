"""
Backfill event location data: is_outdoor, address, venue_name.
Populates existing events with extracted location information.
"""

import asyncio
import logging
from sqlalchemy import select, and_
from src.database import AsyncSessionLocal
from src.database.models import EventModel
from src.ai.event_enrichment import extract_is_outdoor, extract_address, extract_venue_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_event_locations() -> None:
    """Extract and update location data for existing events."""
    async with AsyncSessionLocal() as db:
        # Find events missing location data
        result = await db.execute(
            select(EventModel).filter(
                and_(
                    EventModel.is_outdoor.is_(None),
                    EventModel.address.is_(None),
                    EventModel.venue_name.is_(None),
                )
            )
        )
        events = result.scalars().all()

        if not events:
            logger.info("✅ All events already have location data")
            return

        logger.info(f"🔄 Backfilling location data for {len(events)} events")

        updated = 0
        for event in events:
            # Extract from event name and details
            full_text = f"{event.name} {event.details or ''}".strip()

            # Extract outdoor/indoor
            is_outdoor = extract_is_outdoor(full_text)
            if is_outdoor:
                event.is_outdoor = is_outdoor
                updated += 1

            # Extract address
            address = extract_address(full_text)
            if address:
                event.address = address

            # Extract venue name
            venue_name = extract_venue_name(event.name)
            if venue_name:
                event.venue_name = venue_name

        # Commit all updates
        await db.commit()
        logger.info(f"✅ Backfill complete: {updated} events updated with outdoor/indoor data")


async def main() -> None:
    """Run backfill."""
    await backfill_event_locations()


if __name__ == "__main__":
    asyncio.run(main())
