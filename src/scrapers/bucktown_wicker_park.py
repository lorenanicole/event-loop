"""
Bucktown/Wicker Park venue event discovery via SerpAPI.
Uses Google search to reliably find upcoming events at venues.
More robust than HTML scraping since venues use external ticketing platforms.
"""

import httpx
import logging
import os
import asyncio
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

SERP_API_URL = "https://serpapi.com/search"
RATE_LIMIT_DELAY = 0.5


@dataclass
class VenueEvent:
    """Event discovered via search."""
    name: str
    date: Optional[str]
    time: Optional[str]
    location: str
    url: str
    venue_name: str
    category: str


# Bucktown/Wicker Park venues with addresses
BUCKTOWN_WICKER_PARK_VENUES = [
    {
        "name": "Subterranean",
        "address": "2011 W North Ave, Chicago",
        "category": "music",
        "neighborhood": "Wicker Park"
    },
    {
        "name": "Chop Shop",
        "address": "2033 W North Ave, Chicago",
        "category": "music",
        "neighborhood": "Wicker Park"
    },
    {
        "name": "Schubas Tavern",
        "address": "3159 N Southport Ave, Chicago",
        "category": "music",
        "neighborhood": "Lakeview (near Bucktown)"
    },
    {
        "name": "The Hideout",
        "address": "1354 W Wabansia Ave, Chicago",
        "category": "music",
        "neighborhood": "Bucktown"
    },
    {
        "name": "Empty Bottle",
        "address": "1035 N Western Ave, Chicago",
        "category": "music",
        "neighborhood": "Wicker Park"
    },
    {
        "name": "Concord Music Hall",
        "address": "2047 N Milwaukee Ave, Chicago",
        "category": "music",
        "neighborhood": "Bucktown"
    },
]


async def _search_venue_events(client: httpx.AsyncClient, venue_name: str, api_key: str) -> list[VenueEvent]:
    """Search for upcoming events at a venue via SerpAPI."""
    events = []

    try:
        await asyncio.sleep(RATE_LIMIT_DELAY)

        # Search for events at this venue
        response = await client.get(
            SERP_API_URL,
            params={
                "q": f"{venue_name} Chicago events 2026",
                "api_key": api_key,
                "engine": "google",
                "num": 10,
            }
        )
        response.raise_for_status()

        results = response.json()

        # Parse knowledge graph / organic results for event info
        if "knowledge_graph" in results:
            kg = results["knowledge_graph"]
            if "events" in kg:
                for event_data in kg["events"][:5]:
                    try:
                        events.append(VenueEvent(
                            name=event_data.get("title", "Unknown"),
                            date=event_data.get("date", None),
                            time=None,
                            location=venue_name,
                            url=event_data.get("link", ""),
                            venue_name=venue_name,
                            category="music"
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to parse event: {e}")

        # Also parse organic results for event links
        if "organic_results" in results:
            for result in results["organic_results"][:5]:
                try:
                    title = result.get("title", "")
                    link = result.get("link", "")
                    snippet = result.get("snippet", "")

                    # Look for event keywords in title/snippet
                    if any(x in title.lower() or x in snippet.lower() for x in ["event", "concert", "show", "ticket", "buy tickets"]):
                        events.append(VenueEvent(
                            name=title[:100],
                            date=None,  # Would need parsing from snippet
                            time=None,
                            location=venue_name,
                            url=link,
                            venue_name=venue_name,
                            category="music"
                        ))
                except Exception as e:
                    logger.debug(f"Failed to parse result: {e}")

    except Exception as e:
        logger.error(f"SerpAPI search failed for {venue_name}: {e}")

    return events


async def scrape_bucktown_wicker_park() -> list[VenueEvent]:
    """Discover events at all Bucktown/Wicker Park venues via SerpAPI."""
    all_events = []
    api_key = os.environ.get("SERP_API_KEY")

    if not api_key:
        logger.warning("SERP_API_KEY not set - skipping event discovery")
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        for venue in BUCKTOWN_WICKER_PARK_VENUES:
            try:
                logger.debug(f"Searching events for {venue['name']}...")
                events = await _search_venue_events(client, venue["name"], api_key)
                all_events.extend(events)
                logger.info(f"{venue['name']}: found {len(events)} events")
            except Exception as e:
                logger.error(f"Error searching {venue['name']}: {e}")

    logger.info(f"Total Bucktown/Wicker Park events discovered: {len(all_events)}")
    return all_events
