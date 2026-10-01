"""
Populate neighborhoods and venues into database from master venue list
Run this script to initialize the database with all verified venues
"""

import asyncio
import sys
sys.path.insert(0, '/Users/lorenamesa/Workspace/python315')

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Base, NeighborhoodModel, VenueModel
from src.scrapers.chicago_venues_master import CHICAGO_VENUES_MASTER

# Database URL - using aiosqlite for async SQLite
DATABASE_URL = "sqlite+aiosqlite:////Users/lorenamesa/Workspace/python315/events.db"

# Entertainment level mapping
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
    "Rogers Park": "low",
    "North Center": "low",
    "Avondale": "low",
    "West Town": "low",
    "Pilsen": "low",
}

async def populate_database():
    """Populate neighborhoods and venues into database."""

    # Create async engine
    engine = create_async_engine(DATABASE_URL, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        print("Populating neighborhoods and venues...")

        neighborhoods_added = 0
        venues_added = 0

        for neighborhood_name, venues_list in sorted(CHICAGO_VENUES_MASTER.items()):
            # Check if neighborhood already exists
            from sqlalchemy import select
            stmt = select(NeighborhoodModel).where(NeighborhoodModel.name == neighborhood_name)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                neighborhood = existing
            else:
                # Create new neighborhood
                neighborhood = NeighborhoodModel(
                    name=neighborhood_name,
                    official_name=neighborhood_name,
                    entertainment_level=ENTERTAINMENT_LEVELS.get(neighborhood_name, "low"),
                    is_researched=True,
                )
                session.add(neighborhood)
                await session.flush()  # Flush to get ID
                neighborhoods_added += 1

            # Add venues
            for venue_data in venues_list:
                # Check if venue already exists
                stmt = select(VenueModel).where(
                    (VenueModel.name == venue_data["name"]) &
                    (VenueModel.neighborhood_id == neighborhood.id)
                )
                result = await session.execute(stmt)
                existing_venue = result.scalar_one_or_none()

                if not existing_venue:
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

        print(f"✓ Added {neighborhoods_added} neighborhoods")
        print(f"✓ Added {venues_added} venues")
        print(f"✓ Total neighborhoods: {len(CHICAGO_VENUES_MASTER)}")
        print(f"✓ Total venues configured: {sum(len(v) for v in CHICAGO_VENUES_MASTER.values())}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(populate_database())
