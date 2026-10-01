"""
Venue Implementation Sprint: Systematic neighborhood-by-neighborhood venue addition

Strategy:
1. Render venue event page with Playwright
2. Identify if events are on main page or nested sub-page
3. Extract CSS/DOM selectors matching event patterns
4. Save selectors to database for reuse
5. Generate VenueConfig for scraper
6. Test extraction and validate event count
7. Mark venue as "working" in database
"""

import asyncio
import sys
import json
sys.path.insert(0, '/Users/lorenamesa/Workspace/python315')

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, selectinload
from sqlalchemy import select, update
from src.database.models import NeighborhoodModel, VenueModel
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

DATABASE_URL = "sqlite+aiosqlite:////Users/lorenamesa/Workspace/python315/events.db"

async def analyze_venue_page(venue: VenueModel) -> dict:
    """
    1. Render event page with Playwright
    2. Identify event location (main/nested)
    3. Extract CSS selectors
    4. Return analysis for scraper configuration
    """

    if not venue.event_page_url:
        return {"status": "no_url", "venue_id": venue.id}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage']
            )
            page = await browser.new_page(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            print(f"  Loading {venue.event_page_url}")
            await page.goto(venue.event_page_url, timeout=10000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            html = await page.content()
            url = page.url
            await browser.close()

            soup = BeautifulSoup(html, "html.parser")

            # Analyze for event patterns
            analysis = {
                "venue_id": venue.id,
                "venue_name": venue.name,
                "requested_url": venue.event_page_url,
                "loaded_url": url,
                "url_changed": url != venue.event_page_url,
                "html_size": len(html),
            }

            # Find potential event containers and count
            selectors_to_test = {
                "[class*='event']": "Elements with 'event' in class",
                "[class*='show']": "Elements with 'show' in class",
                "[class*='performance']": "Elements with 'performance' in class",
                "[class*='item']": "Elements with 'item' in class",
                "li": "List items",
                "article": "Article elements",
                "[data-event]": "Elements with data-event attribute",
                ".event-card": "Event card class",
                ".show-item": "Show item class",
                "tr[class*='event']": "Table rows with event",
            }

            selector_results = {}
            for selector, description in selectors_to_test.items():
                try:
                    elements = soup.select(selector)
                    if elements:
                        sample_texts = []
                        for elem in elements[:3]:
                            text = elem.get_text(strip=True)
                            if len(text) > 3 and len(text) < 200:
                                sample_texts.append(text[:60])

                        if sample_texts:
                            selector_results[selector] = {
                                "count": len(elements),
                                "samples": sample_texts,
                                "description": description
                            }
                except:
                    pass

            analysis["selectors_found"] = selector_results

            # Identify best selector (most matches, reasonable sample count)
            if selector_results:
                best = max(selector_results.items(), key=lambda x: x[1]["count"])
                analysis["recommended_selector"] = best[0]
                analysis["recommended_selector_matches"] = best[1]["count"]
                analysis["status"] = "selectors_found"
            else:
                analysis["status"] = "no_events_found"

            return analysis

    except asyncio.TimeoutError:
        return {
            "venue_id": venue.id,
            "venue_name": venue.name,
            "status": "timeout",
            "message": "Page loading timed out"
        }
    except Exception as e:
        return {
            "venue_id": venue.id,
            "venue_name": venue.name,
            "status": "error",
            "message": str(e)
        }

async def sprint_neighborhood(neighborhood_name: str, max_venues: int = 5):
    """
    Execute sprint on one neighborhood:
    1. Load venues from neighborhood
    2. Analyze each venue's event page
    3. Save selector findings to database
    4. Generate scraper config
    """

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get venues for this neighborhood that haven't been tested yet
        stmt = (
            select(VenueModel)
            .join(NeighborhoodModel)
            .where(NeighborhoodModel.name == neighborhood_name)
            .where(VenueModel.scraper_status == "not_started")
            .limit(max_venues)
        )
        result = await session.execute(stmt)
        venues = result.scalars().all()

        if not venues:
            print(f"\n✓ No untested venues in {neighborhood_name}")
            return

        print(f"\n{'='*70}")
        print(f"SPRINT: {neighborhood_name} ({len(venues)} venues to test)")
        print(f"{'='*70}\n")

        sprint_results = []

        for venue in venues:
            print(f"Testing: {venue.name}")

            analysis = await analyze_venue_page(venue)
            sprint_results.append(analysis)

            if analysis["status"] == "selectors_found":
                print(f"  ✓ Found selectors!")
                print(f"    Recommended: {analysis['recommended_selector']}")
                print(f"    Matches: {analysis['recommended_selector_matches']} elements")

                # Update venue in database
                stmt = (
                    update(VenueModel)
                    .where(VenueModel.id == venue.id)
                    .values(
                        scraper_status="in_progress",
                        description=json.dumps(analysis["selectors_found"])
                    )
                )
                await session.execute(stmt)

                print(f"  → Saved to database, ready for scraper implementation\n")

            elif analysis["status"] == "no_events_found":
                print(f"  ✗ No events found on page")
                stmt = (
                    update(VenueModel)
                    .where(VenueModel.id == venue.id)
                    .values(scraper_status="failed")
                )
                await session.execute(stmt)
                print()
            else:
                print(f"  ✗ {analysis['status']}: {analysis.get('message', 'Unknown')}")
                stmt = (
                    update(VenueModel)
                    .where(VenueModel.id == venue.id)
                    .values(scraper_status="failed")
                )
                await session.execute(stmt)
                print()

        await session.commit()

        # Summary
        working = sum(1 for r in sprint_results if r["status"] == "selectors_found")
        print(f"{'='*70}")
        print(f"Sprint Summary: {working}/{len(sprint_results)} venues have viable selectors")
        print(f"{'='*70}\n")

    await engine.dispose()

async def main():
    """Run sprints on priority neighborhoods."""

    # Priority neighborhoods with researched event page URLs
    priority_neighborhoods = [
        "Loop",      # 3 venues, major theaters
        "Uptown",    # 3 venues, jazz/music venues
        "Lincoln Park",  # 5 venues, major entertainment district
    ]

    for neighborhood in priority_neighborhoods:
        await sprint_neighborhood(neighborhood, max_venues=10)

if __name__ == "__main__":
    asyncio.run(main())
