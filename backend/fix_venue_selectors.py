#!/usr/bin/env python3
"""
Diagnostic tool to identify correct CSS selectors for problem venues.
Inspects actual HTML structure to find date elements.
"""

import sys
import asyncio
sys.path.insert(0, '/Users/lorenamesa/Workspace/python315/backend/src')

from scrapers.custom.venue.venue_scraper import VenueScraper, VenueConfig
from bs4 import BeautifulSoup
import json
import re

# Problem venues we need to fix
PROBLEM_VENUES = [
    {
        "name": "Zanies Comedy Club",
        "url": "https://chicago.zanies.com/chicago",
        "venue_name": "chicago_venue_zanies_comedy_club",
        "missing_events": 184,
    },
    {
        "name": "The Lincoln Lodge",
        "url": "https://www.lincolnlodgechicago.com/",
        "venue_name": "chicago_venue_the_lincoln_lodge",
        "missing_events": 68,
    },
    {
        "name": "Empty Bottle",
        "url": "https://www.emptybottle.com/",
        "venue_name": "chicago_venue_empty_bottle",
        "missing_events": 85,  # 86-1 with existing date
    },
]

async def inspect_venue(venue_info):
    """Load venue with Playwright and identify date elements."""
    print(f"\n{'='*70}")
    print(f"Inspecting: {venue_info['name']}")
    print(f"URL: {venue_info['url']}")
    print(f"Missing dates: {venue_info['missing_events']} events")
    print('='*70)

    # Create minimal config for this venue
    config = VenueConfig(
        name=venue_info['name'],
        website_url=venue_info['url'].split('/')[2],
        event_page_url=venue_info['url'],
        category='unknown',
        address='',
        selectors={},
        use_playwright=True,
    )

    try:
        scraper = VenueScraper(config)
        html = await scraper._scrape_with_playwright()
        soup = BeautifulSoup(html, 'html.parser')

        # Look for all potential date-related elements
        print("\n📅 POTENTIAL DATE ELEMENTS (in page order):")
        print("-" * 70)

        # Find text nodes that look like dates
        date_pattern = re.compile(
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|'
            r'January|February|March|April|May|June|July|August|September|October|November|December|\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2})',
            re.IGNORECASE
        )

        date_elements = []

        # Check common selectors
        selectors_to_check = [
            '.date', '.time', '.start-time', '.end-time',
            '[class*="date"]', '[class*="time"]', '[class*="event"]',
            'time', '.event-date', '.show-date',
            '[data-date]', '[data-time]',
            '.datetime', '.event-time',
            'p', 'span', 'div'
        ]

        for selector in selectors_to_check:
            elements = soup.select(selector)[:3]  # Just first 3 of each
            for elem in elements:
                text = elem.get_text(strip=True)
                if date_pattern.search(text):
                    date_elements.append({
                        'selector': selector,
                        'tag': elem.name,
                        'class': elem.get('class', []),
                        'id': elem.get('id', ''),
                        'text': text[:100],
                    })

        # Deduplicate and print
        seen = set()
        for elem in date_elements:
            key = (elem['selector'], elem['text'])
            if key not in seen:
                seen.add(key)
                print(f"  Selector: {elem['selector']:<30} | Tag: {elem['tag']:<6} | Text: {elem['text']}")

        # Look for event containers
        print("\n🎪 POTENTIAL EVENT CONTAINERS:")
        print("-" * 70)
        container_selectors = [
            'li', 'article', 'div[class*="event"]', 'div[class*="item"]',
            '.event', '.listing', '.show', 'div.card', 'tr', '.row'
        ]

        for selector in container_selectors:
            containers = soup.select(selector)
            if containers and len(containers) > 1:
                print(f"  {selector:<30} | Found: {len(containers)} elements")
                first = containers[0]
                # Show first container's HTML (truncated)
                html_str = str(first)[:200]
                print(f"    First element: {html_str}...")

        print("\n💾 Full HTML Sample (first 1000 chars):")
        print("-" * 70)
        print(html[:1000])

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    for venue in PROBLEM_VENUES:
        try:
            await inspect_venue(venue)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR inspecting {venue['name']}: {e}")

    print("\n" + "="*70)
    print("✅ Inspection complete. Use findings to update VenueConfig selectors.")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(main())
