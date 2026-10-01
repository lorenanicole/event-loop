"""
Scrape events from all sources and populate the database.
Sources: DO312, Bandsintown, EventBrite, Ticketmaster, TimeoutChicago, YourChicagoGuide, EventsCom
Run with: uv run python scripts/scrape_events.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scraper import (
    DO312Scraper,
    BandsintownScraper,
    EventBriteScraper,
    TicketmasterScraper,
    TimeoutChicagoScraper,
    YourChicagoGuideScraper,
    EventsComScraper,
)
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

DATABASE_URL = "sqlite:///./data/events.db"


async def scrape_all_sources():
    """Scrape from all event sources in parallel."""
    print("🔍 Scraping events from all Chicago sources...\n")

    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    scrapers = [
        ("DO312", DO312Scraper()),
        ("Bandsintown", BandsintownScraper()),
        ("EventBrite", EventBriteScraper()),
        ("Ticketmaster", TicketmasterScraper()),
        ("TimeoutChicago", TimeoutChicagoScraper()),
        ("YourChicagoGuide", YourChicagoGuideScraper()),
        ("EventsCom", EventsComScraper()),
    ]

    total_events = 0

    for source_name, scraper in scrapers:
        try:
            with Session(engine) as db:
                print(f"⏳ Scraping {source_name}...", end=" ", flush=True)
                count = await scraper.scrape_and_save(db, days_ahead=60)
                total_events += count
                print(f"✅ {count} events")
        except Exception as e:
            print(f"⚠️  Error: {str(e)[:60]}...")

    print(f"\n{'='*60}")
    print(f"📊 Total events scraped: {total_events}")
    print(f"{'='*60}")
    print("\n🚀 Database populated and ready!")
    print("Next steps:")
    print("  1. invoke dev       # Start backend")
    print("  2. invoke frontend  # Start frontend")
    print("  3. Visit http://localhost:5173")

    return True


async def main():
    """Run all scrapers."""
    success = await scrape_all_sources()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
