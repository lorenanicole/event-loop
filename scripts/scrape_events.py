"""
Scrape events from all sources and populate the database.
Sources: DO312, BandsinTown, EventBrite, Ticketmaster, TimeoutChicago, YourChicagoGuide
Run with: uv run python scripts/scrape_events.py
"""

import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file BEFORE importing scrapers
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from src.scraper import (
    DO312Scraper,
    BandsinTownScraper,
    EventbriteScraper,
    TicketmasterScraper,
    TimeoutChicagoScraper,
    YourChicagoGuideScraper,
)
from src.database import AsyncSessionLocal
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

# Use sync engine for scraper (scrapers use sync session)
DATABASE_URL = "sqlite:///./data/events.db"


async def scrape_all_sources():
    """Scrape from all event sources, skip those missing credentials."""
    print("🔍 Scraping events from all Chicago sources...\n")

    # Create sync engine for scrapers
    sync_engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    scrapers_config = [
        ("DO312", DO312Scraper),
        ("BandsinTown", BandsinTownScraper),
        ("EventBrite", EventbriteScraper),
        ("Ticketmaster", TicketmasterScraper),
        ("TimeoutChicago", TimeoutChicagoScraper),
        ("YourChicagoGuide", YourChicagoGuideScraper),
    ]

    total_events = 0
    skipped = []

    for source_name, scraper_class in scrapers_config:
        # Try to instantiate - will fail if credentials missing
        try:
            scraper = scraper_class()
        except ValueError as e:
            print(f"⏭️  Skipped {source_name}: {str(e)[:50]}")
            skipped.append(source_name)
            continue
        except Exception as e:
            print(f"⏭️  Skipped {source_name}: {str(e)[:50]}")
            skipped.append(source_name)
            continue

        # Scrape with this source (using sync session)
        try:
            with Session(sync_engine) as db:
                print(f"⏳ Scraping {source_name}...", end=" ", flush=True)
                count = await scraper.scrape_and_save(db, days_ahead=60)
                total_events += count
                print(f"✅ {count} events")
        except Exception as e:
            print(f"⚠️  Error: {str(e)[:60]}...")

    print(f"\n{'='*60}")
    print(f"📊 Total events scraped: {total_events}")
    if skipped:
        print(f"⏭️  Skipped sources: {', '.join(skipped)}")
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
