#!/usr/bin/env python3
"""
CLI tool to scrape events from a specific Chicago neighborhood.

Usage:
    python scrape_neighborhood.py Bucktown
    python scrape_neighborhood.py "Wicker Park"
    python scrape_neighborhood.py --list              # Show available neighborhoods
    python scrape_neighborhood.py --venues Bucktown   # Show venues in neighborhood
"""

import asyncio
import sys
import logging
from neighborhood_scraper import (
    scrape_neighborhood,
    list_neighborhoods,
    list_venues_in_neighborhood
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    # Show available neighborhoods
    if command == "--list":
        neighborhoods = list_neighborhoods()
        print(f"\n📍 Available neighborhoods ({len(neighborhoods)}):\n")
        for nbhd in neighborhoods:
            venues = list_venues_in_neighborhood(nbhd)
            print(f"  {nbhd:20} ({len(venues)} venues)")
        print()
        return

    # Show venues in neighborhood
    if command == "--venues":
        if len(sys.argv) < 3:
            print("Usage: python scrape_neighborhood.py --venues <neighborhood>")
            return

        neighborhood = sys.argv[2]
        try:
            venues = list_venues_in_neighborhood(neighborhood)
            print(f"\n🎵 Venues in {neighborhood}:\n")
            for venue in venues:
                print(f"  - {venue}")
            print()
        except ValueError as e:
            print(f"❌ Error: {e}\n")
        return

    # Scrape neighborhood
    neighborhood = command
    try:
        print(f"\n🏘️  Scraping {neighborhood} neighborhoods...")
        events = await scrape_neighborhood(neighborhood)

        print(f"\n✅ Found {len(events)} events\n")

        if events:
            print("📋 Events:\n")
            for i, event in enumerate(events[:10], 1):
                print(f"{i}. {event.name}")
                print(f"   Venue: {event.venue_name}")
                print(f"   Location: {event.location}")
                if event.date:
                    print(f"   Date: {event.date}")
                print(f"   URL: {event.url}\n")

            if len(events) > 10:
                print(f"... and {len(events) - 10} more events\n")
        else:
            print("💡 No events found. Try setting SERP_API_KEY for fallback search:")
            print("   export SERP_API_KEY=<your-key>")
            print()

    except ValueError as e:
        print(f"❌ Error: {e}\n")
        print("Use --list to see available neighborhoods\n")


if __name__ == "__main__":
    asyncio.run(main())
