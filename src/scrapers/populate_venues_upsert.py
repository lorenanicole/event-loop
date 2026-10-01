"""
Populate and UPDATE neighborhoods and venues - preserves events, updates venue data
"""

import asyncio
import sys
sys.path.insert(0, '/Users/lorenamesa/Workspace/python315')

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update
from src.database.models import Base, NeighborhoodModel, VenueModel
from src.scrapers.chicago_venues_master import CHICAGO_VENUES_MASTER

DATABASE_URL = "sqlite+aiosqlite:////Users/lorenamesa/Workspace/python315/events.db"

ENTERTAINMENT_LEVELS = {
    "Loop": "high",
    "Uptown": "high",
    "Lincoln Park": "high",
    "Lake View": "high",
    "Wicker Park": "high",
    "Near North Side": "high",
    "Hyde Park": "medium",
    "South Shore": "medium",
    "Lincoln Square": "medium",
    "Bucktown": "medium",
    "Logan Square": "medium",
    "Humboldt Park": "medium",
    "Bridgeport": "medium",
}

async def upsert_database():
    """Populate and UPDATE neighborhoods and venues (non-destructive upsert)."""

    engine = create_async_engine(DATABASE_URL, echo=False)

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        print("Upserting neighborhoods and venues...\n")

        neighborhoods_added = 0
        neighborhoods_updated = 0
        venues_added = 0
        venues_updated = 0

        for neighborhood_name, venues_list in sorted(CHICAGO_VENUES_MASTER.items()):
            # Check if neighborhood exists
            stmt = select(NeighborhoodModel).where(NeighborhoodModel.name == neighborhood_name)
            result = await session.execute(stmt)
            existing_neighborhood = result.scalar_one_or_none()

            if existing_neighborhood:
                neighborhood = existing_neighborhood
                # Update if needed
                stmt = (
                    update(NeighborhoodModel)
                    .where(NeighborhoodModel.id == neighborhood.id)
                    .values(
                        entertainment_level=ENTERTAINMENT_LEVELS.get(neighborhood_name, "low"),
                        is_researched=True,
                    )
                )
                await session.execute(stmt)
                neighborhoods_updated += 1
            else:
                # Create new neighborhood
                neighborhood = NeighborhoodModel(
                    name=neighborhood_name,
                    official_name=neighborhood_name,
                    entertainment_level=ENTERTAINMENT_LEVELS.get(neighborhood_name, "low"),
                    is_researched=True,
                )
                session.add(neighborhood)
                await session.flush()
                neighborhoods_added += 1

            # Upsert venues
            for venue_data in venues_list:
                stmt = select(VenueModel).where(
                    (VenueModel.name == venue_data["name"]) &
                    (VenueModel.neighborhood_id == neighborhood.id)
                )
                result = await session.execute(stmt)
                existing_venue = result.scalar_one_or_none()

                if existing_venue:
                    # UPDATE existing venue with new data
                    stmt = (
                        update(VenueModel)
                        .where(VenueModel.id == existing_venue.id)
                        .values(
                            category=venue_data.get("category", existing_venue.category),
                            address=venue_data.get("address", existing_venue.address),
                            website_url=venue_data.get("website", existing_venue.website_url),
                            event_page_url=venue_data.get("event_page_url", existing_venue.event_page_url),
                        )
                    )
                    await session.execute(stmt)
                    venues_updated += 1
                else:
                    # INSERT new venue
                    venue = VenueModel(
                        neighborhood_id=neighborhood.id,
                        name=venue_data["name"],
                        category=venue_data.get("category", "other"),
                        address=venue_data.get("address"),
                        website_url=venue_data.get("website"),
                        event_page_url=venue_data.get("event_page_url"),
                        is_active=True,
                        scraper_status="not_started",
                    )
                    session.add(venue)
                    venues_added += 1

        # Commit all changes
        await session.commit()

        print(f"✓ Neighborhoods: +{neighborhoods_added} added, ~{neighborhoods_updated} updated")
        print(f"✓ Venues: +{venues_added} added, ~{venues_updated} updated")
        print(f"✓ Total neighborhoods: {len(CHICAGO_VENUES_MASTER)}")
        print(f"✓ Total venues: {sum(len(v) for v in CHICAGO_VENUES_MASTER.values())}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(upsert_database())
