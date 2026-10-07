"""
Venue Discovery Worker: Systematically test venues and add to scraper
1. Query database for venues with scraper_status = "not_started"
2. Test with Playwright to find selector patterns
3. Generate scraper config
4. Update venue status in database
"""

import asyncio
import sys

sys.path.insert(0, "/Users/lorenamesa/Workspace/python315")

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload, sessionmaker

from shared.database.models import VenueModel

DATABASE_URL = "sqlite+aiosqlite:////Users/lorenamesa/Workspace/python315/events.db"


async def test_venue(venue: VenueModel) -> dict:
    """Test a venue's event page with Playwright and find selectors."""

    if not venue.event_page_url:
        return {
            "venue_id": venue.id,
            "name": venue.name,
            "status": "no_event_url",
            "message": "No event_page_url defined",
        }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            await page.goto(venue.event_page_url, timeout=8000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Find potential event selectors
            selectors_found = {}
            for selector in [
                "[class*='event']",
                "[class*='show']",
                "[class*='item']",
                "li",
                "article",
                "a",
            ]:
                elements = soup.select(selector)
                if elements and len(elements) > 0:
                    sample = elements[0].get_text(strip=True)[:60]
                    selectors_found[selector] = {"count": len(elements), "sample": sample}

            await browser.close()

            return {
                "venue_id": venue.id,
                "name": venue.name,
                "status": "tested",
                "selectors_found": selectors_found,
                "html_size": len(html),
            }

    except TimeoutError:
        return {
            "venue_id": venue.id,
            "name": venue.name,
            "status": "timeout",
            "message": "Page took too long to load",
        }
    except Exception as e:
        return {
            "venue_id": venue.id,
            "name": venue.name,
            "status": "error",
            "message": str(e),
        }


async def discover_venues():
    """Test venues and report findings."""

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get venues with "not_started" status, limit to 10 for initial discovery
        stmt = (
            select(VenueModel)
            .where(VenueModel.scraper_status == "not_started")
            .options(selectinload(VenueModel.neighborhood))
            .limit(10)
        )
        result = await session.execute(stmt)
        venues = result.scalars().all()

        print(f"\nTesting {len(venues)} venues for event page patterns...\n")

        for venue in venues:
            print(f"Testing: {venue.neighborhood.name} → {venue.name}")
            print(f"  URL: {venue.event_page_url}")

            test_result = await test_venue(venue)

            if test_result["status"] == "tested":
                selectors = test_result.get("selectors_found", {})
                print(f"  ✓ Found {len(selectors)} potential selectors")
                for selector, info in list(selectors.items())[:3]:
                    print(f"    • {selector}: {info['count']} elements")

                # Update venue status
                venue.scraper_status = "in_progress"
                venue.last_scraped_at = None
            else:
                print(f"  ✗ {test_result['status']}: {test_result.get('message', 'Unknown error')}")
                venue.scraper_status = "failed"

            session.add(venue)
            await session.flush()

        await session.commit()
        print("\n✓ Venue discovery complete. Status updated in database.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(discover_venues())
