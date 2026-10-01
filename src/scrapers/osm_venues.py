"""
Fetch entertainment venues from OpenStreetMap using Nominatim API.
Returns venue data (name, coordinates, type) for Chicago.
"""

import httpx
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RATE_LIMIT_DELAY = 1.1  # Nominatim: 1 req/sec, +100ms buffer


@dataclass
class Venue:
    """Entertainment venue from OpenStreetMap."""
    name: str
    lat: float
    lon: float
    venue_type: str
    website: Optional[str] = None
    phone: Optional[str] = None


async def fetch_chicago_venues() -> list[Venue]:
    """
    Query OpenStreetMap Nominatim for Chicago entertainment venues.
    Uses multiple search queries to find different venue types.
    """
    venues = []
    queries = [
        "theater Chicago",
        "theatre Chicago",
        "comedy club Chicago",
        "concert hall Chicago",
        "music venue Chicago",
        "nightclub Chicago",
    ]

    seen_names = set()
    headers = {"User-Agent": "EventLoop/1.0 (Chicago event discovery)"}

    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        for query in queries:
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)  # Respect rate limit

                response = await client.get(
                    NOMINATIM_URL,
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 10,
                        "viewbox": "-87.9,41.6,-87.5,42.0",  # Chicago bbox
                        "bounded": 1,
                    }
                )
                response.raise_for_status()

                results = response.json()
                for result in results:
                    venue = _parse_nominatim_result(result)
                    if venue and venue.name not in seen_names:
                        venues.append(venue)
                        seen_names.add(venue.name)

            except Exception as e:
                logger.error(f"Failed to search for '{query}': {e}")

    logger.info(f"Fetched {len(venues)} venues from Nominatim")
    return venues


def _parse_nominatim_result(result: dict) -> Optional[Venue]:
    """Parse Nominatim search result into a Venue."""
    try:
        name = result.get("name", "").strip()
        if not name:
            return None

        lat = float(result.get("lat", 0))
        lon = float(result.get("lon", 0))

        if lat == 0 or lon == 0:
            return None

        # Categorize venue type from OSM tags
        venue_type = "venue"
        osm_class = result.get("class", "")
        osm_type = result.get("type", "")

        if osm_class == "amenity":
            if osm_type in ("theatre", "concert_hall", "nightclub", "bar"):
                venue_type = osm_type
            else:
                venue_type = "amenity"
        elif "theater" in name.lower() or "theatre" in name.lower():
            venue_type = "theatre"
        elif "comedy" in name.lower():
            venue_type = "comedy"
        elif "concert" in name.lower() or "hall" in name.lower():
            venue_type = "concert_hall"

        return Venue(
            name=name,
            lat=lat,
            lon=lon,
            venue_type=venue_type,
            website=None,  # Nominatim doesn't provide website
            phone=None,    # Nominatim doesn't provide phone
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.debug(f"Failed to parse Nominatim result: {e}")

    return None
