"""
Fetch entertainment venues from OpenStreetMap using Nominatim API.
Geocodes known Chicago venues and discovers their websites via SerpAPI.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx

from .chicago_venues import get_all_venue_names

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
SERP_API_URL = "https://serpapi.com/search"
RATE_LIMIT_DELAY = 1.1  # Nominatim: 1 req/sec, +100ms buffer

# Chicago neighborhoods for venue organization (30+ neighborhoods)
CHICAGO_NEIGHBORHOODS = {
    # Downtown & Loop Area
    "Loop": (41.8837, -87.6453),
    "River North": (41.8910, -87.6249),
    "West Loop": (41.8833, -87.6544),
    "South Loop": (41.8666, -87.6243),
    "Near South Side": (41.8500, -87.6250),
    "Printer's Row": (41.8689, -87.6386),
    # North Gold Coast
    "Gold Coast": (41.8980, -87.6244),
    "Old Town": (41.9061, -87.6137),
    "Lincoln Park": (41.9214, -87.6471),
    "Clybourn Corridor": (41.9080, -87.6490),
    # North Side
    "Lakeview": (41.9380, -87.6455),
    "Boystown": (41.9440, -87.6443),
    "Uptown": (41.9647, -87.6577),
    "Andersonville": (41.9709, -87.6707),
    "Edgewater": (41.9730, -87.6570),
    "Rogers Park": (41.9978, -87.6752),
    # Northwest Side
    "Wicker Park": (41.9086, -87.6751),
    "Bucktown": (41.9189, -87.6899),
    "Logan Square": (41.9331, -87.6764),
    "Humboldt Park": (41.8993, -87.7130),
    "Ukrainian Village": (41.8976, -87.6841),
    "Avondale": (41.9524, -87.7048),
    "Ravenswood": (41.9626, -87.6933),
    "Kilbourn Park": (41.9474, -87.7095),
    # West & Southwest
    "Pilsen": (41.8534, -87.6426),
    "Little Italy": (41.8715, -87.6475),
    "University Village": (41.8058, -87.6258),
    "Bridgeport": (41.8311, -87.6427),
    "Bronzeville": (41.8170, -87.6155),
    # Central/South
    "Oak Park": (41.8763, -87.7839),
    "Lincoln Square": (41.9748, -87.6954),
    "North Center": (41.9503, -87.6995),
    # Lakefront
    "Streeterville": (41.8867, -87.6066),
}


@dataclass
class Venue:
    """Entertainment venue from OpenStreetMap."""

    name: str
    lat: float
    lon: float
    venue_type: str
    website: str | None = None
    phone: str | None = None
    neighborhood: str | None = field(default=None)

    def get_neighborhood(self) -> str:
        """Find nearest Chicago neighborhood."""
        if self.neighborhood:
            return self.neighborhood

        # Simple distance check to nearest neighborhood
        min_distance = float("inf")
        nearest = "Chicago"

        for nbhd, (lat, lon) in CHICAGO_NEIGHBORHOODS.items():
            distance = ((self.lat - lat) ** 2 + (self.lon - lon) ** 2) ** 0.5
            if distance < min_distance:
                min_distance = distance
                nearest = nbhd

        self.neighborhood = nearest
        return nearest


async def fetch_chicago_venues() -> list[Venue]:
    """
    Geocode known Chicago entertainment venues via Nominatim.
    Optionally discovers websites via SerpAPI if API key available.
    Organizes venues by Chicago neighborhood.
    """
    venues = []
    venue_names = get_all_venue_names()

    headers = {"User-Agent": "EventLoop/1.0 (Chicago event discovery)"}
    serp_api_key = os.environ.get("SERP_API_KEY")

    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        for venue_name in venue_names:
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)  # Respect rate limit

                # Geocode venue
                response = await client.get(
                    NOMINATIM_URL,
                    params={
                        "q": f"{venue_name}, Chicago",
                        "format": "json",
                        "limit": 1,
                    },
                )
                response.raise_for_status()
                results = response.json()

                if not results:
                    logger.debug(f"No Nominatim results for: {venue_name}")
                    continue

                venue = _parse_nominatim_result(results[0])
                if not venue:
                    continue

                # Assign neighborhood
                venue.get_neighborhood()

                # Discover website via SerpAPI if available
                if serp_api_key:
                    try:
                        website = await _get_venue_website(client, venue_name, serp_api_key)
                        if website:
                            venue.website = website
                    except Exception as e:
                        logger.debug(f"Failed to get website for {venue_name}: {e}")

                venues.append(venue)
                logger.debug(
                    f"Added: {venue_name} ({venue.neighborhood}) - {venue.lat:.4f}, {venue.lon:.4f}"
                )

            except Exception as e:
                logger.debug(f"Failed to geocode '{venue_name}': {e}")

    logger.info(f"Geocoded {len(venues)} venues from Nominatim (with neighborhoods)")
    return venues


async def _get_venue_website(
    client: httpx.AsyncClient, venue_name: str, api_key: str
) -> str | None:
    """Discover venue website using SerpAPI."""
    try:
        await asyncio.sleep(0.5)  # SerpAPI rate limiting

        response = await client.get(
            SERP_API_URL,
            params={
                "q": f"{venue_name} Chicago website",
                "api_key": api_key,
                "engine": "google",
                "num": 3,
            },
        )
        response.raise_for_status()

        results = response.json()
        if results.get("organic_results"):
            # Return first result's link
            first_result = results["organic_results"][0]
            link = first_result.get("link")
            if link and "www" in link:
                return link
    except Exception as e:
        logger.debug(f"SerpAPI error for {venue_name}: {e}")

    return None


def _parse_nominatim_result(result: dict) -> Venue | None:
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
            phone=None,  # Nominatim doesn't provide phone
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.debug(f"Failed to parse Nominatim result: {e}")

    return None
