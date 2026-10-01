"""
Migrate database schema: preserve existing events and add new location columns.
Exports events from old DB, recreates with new schema, re-imports.
"""

import asyncio
import os
import shutil
from datetime import datetime
from sqlalchemy import select, create_engine, text
from sqlalchemy.orm import Session
from src.database import AsyncSessionLocal, init_db
from src.database.models import EventModel, Base
from src.ai.event_enrichment import extract_is_outdoor, extract_address, extract_venue_name

DB_FILE = "data/events.db"
BACKUP_FILE = "data/events.db.backup"


async def migrate_database():
    """Migrate database: preserve events and add new columns."""

    # Step 1: Backup old database
    if os.path.exists(DB_FILE):
        print(f"📦 Backing up old database to {BACKUP_FILE}...")
        shutil.copy(DB_FILE, BACKUP_FILE)
    else:
        print("ℹ️  No existing database found, skipping backup")
        await init_db()
        print("✅ New database created with all columns")
        return

    # Step 2: Extract events from old database
    print("📤 Exporting events from old database...")
    old_engine = create_engine(f"sqlite:///{DB_FILE}")
    events_data = []

    try:
        with Session(old_engine) as session:
            result = session.query(EventModel).all()
            for event in result:
                events_data.append({
                    "id": event.id,
                    "name": event.name,
                    "date": event.date,
                    "category": event.category,
                    "details": event.details,
                    "origination_url": event.origination_url,
                    "date_retrieved": event.date_retrieved,
                    "source": event.source,
                    "cost": getattr(event, "cost", None),
                    "age_range": getattr(event, "age_range", None),
                })
        print(f"✅ Exported {len(events_data)} events")
    except Exception as e:
        print(f"❌ Error exporting events: {e}")
        return

    # Step 3: Delete old database
    print(f"🗑️  Deleting old database file...")
    os.remove(DB_FILE)

    # Step 4: Create new database with new schema
    print("🆕 Creating new database with updated schema...")
    await init_db()
    print("✅ New database created")

    # Step 5: Re-import events with location enrichment
    print("📥 Re-importing events with location enrichment...")
    async with AsyncSessionLocal() as db:
        for event_data in events_data:
            # Extract location info from existing data
            full_text = f"{event_data['name']} {event_data['details'] or ''}".strip()
            is_outdoor = extract_is_outdoor(full_text)
            address = extract_address(full_text)
            venue_name = extract_venue_name(event_data['name'])

            new_event = EventModel(
                name=event_data['name'],
                date=event_data['date'],
                category=event_data['category'],
                details=event_data['details'],
                origination_url=event_data['origination_url'],
                date_retrieved=event_data['date_retrieved'],
                source=event_data['source'],
                cost=event_data['cost'],
                age_range=event_data['age_range'],
                is_outdoor=is_outdoor,
                address=address,
                venue_name=venue_name,
            )
            db.add(new_event)

        await db.commit()
        print(f"✅ Re-imported {len(events_data)} events with location enrichment")

    print("\n🎉 Migration complete!")
    print(f"📋 Old database backed up to: {BACKUP_FILE}")
    print(f"✨ New database with location data ready at: {DB_FILE}")


async def main():
    """Run migration."""
    await migrate_database()


if __name__ == "__main__":
    asyncio.run(main())
