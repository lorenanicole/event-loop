"""Place an event in a neighborhood from whatever location data a source gave us.

Sources differ in what they provide:

* Ticketmaster returns venue coordinates.
* do312 and the SerpAPI cache return a street address and nothing else.
* The venue scrapers know the neighborhood outright, from their own config.

Any venue can appear, not just the ones we scrape directly, so the fallbacks
below are ordered cheapest-first. Coordinates are resolved locally against the
boundary polygons stored in our database. Only an address with no coordinates
anywhere reaches an external geocoder, and the result of that is written back to
the cache so the same address is never looked up twice.
"""

import asyncio
import logging
import re
import time
from typing import Optional

from sqlalchemy import select

from shared.database.models import GeocodeCacheModel
from .chicago_neighborhoods import chicago_neighborhoods

logger = logging.getLogger(__name__)

# Nominatim's usage policy allows at most one request per second, and asks for
# an identifying User-Agent. We stay a comfortable margin under it.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "eventloop/1.0 (chicago events discovery)"
NOMINATIM_MIN_INTERVAL = 1.5  # seconds between calls

_last_nominatim_call = 0.0
_nominatim_lock = asyncio.Lock()


# Addresses reaching us from text extraction are sometimes a sentence from the
# event blurb rather than a place. Geocoding those wastes a rate-limited call
# and can only ever fail, so they are rejected before the request is made.
MAX_ADDRESS_WORDS = 12
MAX_ADDRESS_CHARS = 120


def looks_like_address(text: str) -> bool:
    """Cheap plausibility check before spending a geocoding request."""
    if not text or len(text) > MAX_ADDRESS_CHARS:
        return False
    if len(text.split()) > MAX_ADDRESS_WORDS:
        return False
    # Prose gives itself away with sentence punctuation.
    if any(mark in text for mark in ("?", "!", ";")) or text.count(".") > 2:
        return False
    return True


def normalise_address(address: Optional[str], venue_name: Optional[str] = None) -> Optional[str]:
    """Cache key for a location: lowercase, collapsed whitespace, Chicago implied.

    Returns None when the text is not plausibly a place.
    """
    for candidate in ((address or "").strip(), (venue_name or "").strip()):
        if not candidate:
            continue
        text = re.sub(r"\s+", " ", candidate).lower()
        if not looks_like_address(text):
            continue
        if "chicago" not in text:
            text = f"{text}, chicago, il"
        return text[:400]
    return None


async def _cached_coordinates(session, key: str):
    result = await session.execute(
        select(GeocodeCacheModel).where(GeocodeCacheModel.query == key)
    )
    return result.scalars().first()


async def _geocode_with_nominatim(key: str):
    """Address -> (lat, lon) via OpenStreetMap, rate limited. None when unknown."""
    global _last_nominatim_call

    import httpx

    async with _nominatim_lock:
        # Serialise calls and space them out, so concurrent scrapers cannot
        # burst past the published limit.
        wait = NOMINATIM_MIN_INTERVAL - (time.monotonic() - _last_nominatim_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    NOMINATIM_URL,
                    params={"q": key, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
                    headers={"User-Agent": NOMINATIM_USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as e:
            logger.warning(f"Geocoding failed for {key!r}: {e}")
            return None
        finally:
            _last_nominatim_call = time.monotonic()

    if not payload:
        return None
    try:
        return float(payload[0]["lat"]), float(payload[0]["lon"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def coordinates_for_address(
    session, address: Optional[str], venue_name: Optional[str] = None, allow_network: bool = True
):
    """Coordinates for a free-text address, from cache or the geocoder."""
    key = normalise_address(address, venue_name)
    if not key:
        return None

    cached = await _cached_coordinates(session, key)
    if cached:
        # A cached miss counts: do not ask again for an address we know fails.
        if cached.resolved and cached.latitude is not None:
            return cached.latitude, cached.longitude
        return None

    if not allow_network:
        return None

    found = await _geocode_with_nominatim(key)
    session.add(
        GeocodeCacheModel(
            query=key,
            latitude=found[0] if found else None,
            longitude=found[1] if found else None,
            provider="nominatim",
            resolved=bool(found),
        )
    )
    await session.flush()
    return found


async def resolve_neighborhood(
    session,
    boundaries: dict,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    address: Optional[str] = None,
    venue_name: Optional[str] = None,
    venue_map: Optional[dict] = None,
    allow_network: bool = True,
) -> tuple[Optional[str], Optional[float], Optional[float]]:
    """Best-effort neighborhood for an event.

    Returns (neighborhood, latitude, longitude) - the coordinates come back too
    so the caller can store them and skip the lookup next time.
    """
    # 1. Coordinates we already have: a local polygon test, no network.
    if latitude is not None and longitude is not None:
        name = chicago_neighborhoods.locate_in(latitude, longitude, boundaries)
        if name:
            return name, latitude, longitude

    # 2. A venue we scrape directly already tells us its neighborhood.
    if venue_map and venue_name:
        known = venue_map.get(venue_name.strip().lower())
        if known:
            return known, latitude, longitude

    # 3. Otherwise geocode the address, once ever, and place that point.
    if address or venue_name:
        found = await coordinates_for_address(
            session, address, venue_name, allow_network=allow_network
        )
        if found:
            name = chicago_neighborhoods.locate_in(found[0], found[1], boundaries)
            return name, found[0], found[1]

    return None, latitude, longitude
