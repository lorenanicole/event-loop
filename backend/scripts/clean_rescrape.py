#!/usr/bin/env python
"""Full clean rescrape with updated extractors."""

import asyncio
import sys

sys.path.insert(0, "src")

from scrapers.venue.chicago_events_scraper import scrape_chicago_events


async def main():
    """Run fresh scrape."""
    print("🔄 Starting clean rescrape with updated extractors...")
    print("   (Rosa's, Hideout, Jazz Showcase, Green Mill, Den Theatre, etc.)")
    print()

    results = await scrape_chicago_events()

    total_events = sum(len(events) for events in results.values())

    print("\n" + "=" * 60)
    print("✅ Clean rescrape complete!")
    print(f"   Total events extracted: {total_events}")
    print(f"   Neighborhoods: {len(results)}")
    print()

    # Check database results
    import sqlite3

    db_path = "data/events.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check total events
    cursor.execute("SELECT COUNT(*) FROM events")
    total = cursor.fetchone()[0]

    # Check future events
    cursor.execute("SELECT COUNT(*) FROM events WHERE date >= '2026-10-05'")
    future = cursor.fetchone()[0]

    # Check events with dates
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE date IS NOT NULL
        AND source LIKE 'chicago_venue_%' OR source = 'chicago_venues'
    """)
    with_dates = cursor.fetchone()[0]

    # Show by source
    cursor.execute("""
        SELECT source, COUNT(*) as count,
               COUNT(CASE WHEN date IS NOT NULL THEN 1 END) as with_dates
        FROM events
        WHERE source LIKE 'chicago_venue_%' OR source = 'chicago_venues'
        GROUP BY source
        ORDER BY count DESC
        LIMIT 15
    """)

    venues = cursor.fetchall()

    print("Database results:")
    print(f"  Total events: {total}")
    print(f"  Future events (2026-10-05+): {future}")
    print(f"  Chicago venue events: {with_dates}")
    print()
    print("Top venues:")
    for source, count, dates in venues:
        pct = (dates / count * 100) if count > 0 else 0
        print(f"  {source}: {count} events, {dates} with dates ({pct:.0f}%)")

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
