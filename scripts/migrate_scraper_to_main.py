#!/usr/bin/env python3
"""
Migrate Chicago venue scraper data from events.db to main data/events.db.
Safely merges venue/neighborhood/event data from scraper into main database.
"""

import asyncio
import sqlite3
from pathlib import Path
from datetime import datetime

SCRAPER_DB = "events.db"
MAIN_DB = "data/events.db"


def backup_main_db():
    """Backup main database before migration."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"data/events.db.pre-migration-{timestamp}.backup"
    import shutil
    shutil.copy(MAIN_DB, backup_file)
    print(f"✅ Main database backed up to: {backup_file}")
    return backup_file


def check_scraper_db():
    """Check scraper database has expected data."""
    conn = sqlite3.connect(SCRAPER_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM events")
    events_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM venues")
    venues_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM neighborhoods")
    neighborhoods_count = cursor.fetchone()[0]

    conn.close()

    print(f"\n📊 Scraper database ({SCRAPER_DB}):")
    print(f"   Events: {events_count}")
    print(f"   Venues: {venues_count}")
    print(f"   Neighborhoods: {neighborhoods_count}")

    return events_count, venues_count, neighborhoods_count


async def init_main_db_schema():
    """Ensure main database has all tables via SQLAlchemy."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.database import init_db
    await init_db()
    print("✅ Main database schema initialized with all tables")

    # Add missing columns if they don't exist
    conn = sqlite3.connect(MAIN_DB)
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE events ADD COLUMN neighborhood_id INTEGER")
        print("   ✓ Added neighborhood_id column")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE events ADD COLUMN venue_id INTEGER")
        print("   ✓ Added venue_id column")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.commit()
    conn.close()


def migrate_neighborhoods():
    """Migrate neighborhoods from scraper to main database."""
    scraper_conn = sqlite3.connect(SCRAPER_DB)
    main_conn = sqlite3.connect(MAIN_DB)

    scraper_cursor = scraper_conn.cursor()
    main_cursor = main_conn.cursor()

    # Get neighborhoods from scraper
    scraper_cursor.execute("SELECT id, name FROM neighborhoods")
    neighborhoods = scraper_cursor.fetchall()

    # Insert into main database (skip if exists)
    inserted = 0
    for neighborhood_id, name in neighborhoods:
        try:
            main_cursor.execute(
                "INSERT OR IGNORE INTO neighborhoods (id, name) VALUES (?, ?)",
                (neighborhood_id, name)
            )
            if main_cursor.rowcount > 0:
                inserted += 1
        except sqlite3.IntegrityError:
            pass

    main_conn.commit()
    main_conn.close()
    scraper_conn.close()

    print(f"✅ Migrated {inserted} neighborhoods")


def migrate_venues():
    """Migrate venues from scraper to main database."""
    scraper_conn = sqlite3.connect(SCRAPER_DB)
    main_conn = sqlite3.connect(MAIN_DB)

    scraper_cursor = scraper_conn.cursor()
    main_cursor = main_conn.cursor()

    # Get venues from scraper (with all columns)
    scraper_cursor.execute("""
        SELECT id, name, neighborhood_id, website_url, events_count
        FROM venues
    """)
    venues = scraper_cursor.fetchall()

    # Insert into main database
    inserted = 0
    for venue_id, name, neighborhood_id, website_url, events_count in venues:
        try:
            main_cursor.execute("""
                INSERT OR IGNORE INTO venues
                (id, name, neighborhood_id, website_url, events_count)
                VALUES (?, ?, ?, ?, ?)
            """, (venue_id, name, neighborhood_id, website_url, events_count))
            if main_cursor.rowcount > 0:
                inserted += 1
        except sqlite3.IntegrityError:
            pass

    main_conn.commit()
    main_conn.close()
    scraper_conn.close()

    print(f"✅ Migrated {inserted} venues")


def migrate_events():
    """Migrate events from scraper to main database."""
    scraper_conn = sqlite3.connect(SCRAPER_DB)
    main_conn = sqlite3.connect(MAIN_DB)

    scraper_cursor = scraper_conn.cursor()
    main_cursor = main_conn.cursor()

    # Get events from scraper
    scraper_cursor.execute("""
        SELECT id, name, date, category, details, origination_url,
               venue_id, neighborhood_id, source, venue_name
        FROM events
    """)
    events = scraper_cursor.fetchall()

    # Insert into main database (skip duplicates by URL)
    inserted = 0
    skipped = 0

    for event_data in events:
        event_id, name, date, category, details, url, venue_id, neighborhood_id, source, venue_name = event_data

        # Check if event already exists (by URL)
        main_cursor.execute(
            "SELECT id FROM events WHERE origination_url = ?",
            (url,)
        )

        if main_cursor.fetchone():
            skipped += 1
            continue

        try:
            main_cursor.execute("""
                INSERT INTO events
                (name, date, category, details, origination_url,
                 venue_id, neighborhood_id, source, venue_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, date, category, details, url,
                  venue_id, neighborhood_id, source, venue_name))
            inserted += 1
        except sqlite3.IntegrityError as e:
            skipped += 1

    main_conn.commit()
    main_conn.close()
    scraper_conn.close()

    print(f"✅ Migrated {inserted} events (skipped {skipped} duplicates)")


def verify_migration():
    """Verify migration was successful."""
    main_conn = sqlite3.connect(MAIN_DB)
    cursor = main_conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM events")
    events = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM venues")
    venues = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM neighborhoods")
    neighborhoods = cursor.fetchone()[0]

    main_conn.close()

    print(f"\n📊 Main database after migration:")
    print(f"   Events: {events}")
    print(f"   Venues: {venues}")
    print(f"   Neighborhoods: {neighborhoods}")


async def main():
    """Run migration."""
    print("\n" + "="*70)
    print("MIGRATING CHICAGO VENUE SCRAPER DATA TO MAIN DATABASE")
    print("="*70)

    # Check scraper database
    check_scraper_db()

    # Backup main database
    backup_main_db()

    # Initialize main database schema
    await init_main_db_schema()

    # Migrate data
    print("\n📤 Starting data migration...")
    migrate_neighborhoods()
    migrate_venues()
    migrate_events()

    # Verify
    verify_migration()

    print("\n✅ Migration complete!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
