"""
Scrape events from DO312 and populate the database.
Run with: uv run python scripts/scrape_events.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scraper import DO312Scraper
from src.database import AsyncSessionLocal
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

DATABASE_URL = "sqlite:///./data/events.db"


async def scrape_events():
    """Scrape events and save to database."""
    print("🔍 Scraping events from DO312...")

    scraper = DO312Scraper()

    # Use sync session for scraper
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    with Session(engine) as db:
        try:
            count = await scraper.scrape_and_save(db, days_ahead=60)
            print(f"✅ Scraped and saved {count} new events")
            print("📊 Database now populated with event data")
            print("🚀 Ready to query! Try: 'invoke dev' then open http://localhost:5173")
        except Exception as e:
            print(f"❌ Scrape error: {e}")
            return False

    return True


async def main():
    """Run scraper."""
    success = await scrape_events()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
