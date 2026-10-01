"""
Fetch entertainment venues from OpenStreetMap using Overpass API.
Returns venue data (name, coordinates, type) for Chicago.
"""

import httpx
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

CHICAGO_BBOX = "41.6,-87.9,42.0,-87.5"  # (south, west, north, east)

OVERPASS_QUERY = f"""
[bbox:{CHICAGO_BBOX}];
(
  node["amenity"="theatre"];
  node["amenity"="nightclub"];
  node["amenity"="concert_hall"];
  node["amenity"="music_venue"];
  node["name"~"comedy|theater|theatre|live"];
);
out center;
"""


@dataclass
class Venue:
    """Entertainment venue from OpenStreetMap."""
    name: str
    lat: float
    lon: float
    venue_type: str  # "theatre", "nightclub", "concert_hall", etc.
    website: Optional[str] = None
    phone: Optional[str] = None


async def fetch_chicago_venues() -> list[Venue]:
    """
    Query OpenStreetMap for Chicago entertainment venues.
    Returns list of venues with coordinates and metadata.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://overpass-api.de/api/interpreter",
                params={"data": OVERPASS_QUERY}
            )
            response.raise_for_status()

            venues = _parse_overpass_response(response.text)
            logger.info(f"Fetched {len(venues)} venues from OpenStreetMap")
            return venues

    except Exception as e:
        logger.error(f"Failed to fetch venues from Overpass API: {e}")
        return []


def _parse_overpass_response(xml_text: str) -> list[Venue]:
    """Parse XML response from Overpass API into Venue objects."""
    venues = []

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)

        for node in root.findall(".//node"):
            venue = _parse_node(node)
            if venue:
                venues.append(venue)

    except Exception as e:
        logger.error(f"Failed to parse Overpass XML: {e}")

    return venues


def _parse_node(node_elem) -> Optional[Venue]:
    """Parse a single OSM node element into a Venue."""
    try:
        lat = float(node_elem.get("lat"))
        lon = float(node_elem.get("lon"))

        name = None
        venue_type = None
        website = None
        phone = None

        for tag in node_elem.findall("tag"):
            key = tag.get("k")
            val = tag.get("v")

            if key == "name":
                name = val
            elif key == "amenity":
                venue_type = val
            elif key == "website":
                website = val
            elif key == "phone":
                phone = val

        if name and (venue_type or name):
            return Venue(
                name=name,
                lat=lat,
                lon=lon,
                venue_type=venue_type or "venue",
                website=website,
                phone=phone,
            )
    except (ValueError, AttributeError) as e:
        logger.debug(f"Failed to parse node: {e}")

    return None
