"""Place Chicago Park District events in neighborhoods without geocoding.

The geocoder is rate limited to one request a minute, which would take hours
for a few hundred park addresses. The city's open data portal publishes every
Park District park with its boundary polygon, so one request gets all 617
parks; their centroids are then placed against the neighborhood boundaries
already in our database. Exact, offline, and polite.

    python place_park_district.py          # place what is unplaced
    python place_park_district.py --all    # re-place everything from this source
"""

import asyncio
import json
import re
import sys

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, "src")

from shared.database.models import EventModel  # noqa: E402
from shared.database.neighborhoods import load_boundaries, resolve_neighborhood_id  # noqa: E402
from shared.geo import chicago_neighborhoods  # noqa: E402

DB_URL = "sqlite+aiosqlite:///data/events.db"
PARKS_URL = "https://data.cityofchicago.org/resource/ejsh-fztr.json"

# "2901 S POPLAR AVE" and "2901 S. Poplar Ave. Chicago, IL 60608" must match.
_SUFFIXES = {
    "ave": "av", "avenue": "av", "av": "av", "st": "st", "street": "st",
    "rd": "rd", "road": "rd", "dr": "dr", "drive": "dr", "blvd": "bl",
    "boulevard": "bl", "pl": "pl", "place": "pl", "pkwy": "pk", "parkway": "pk",
    "ct": "ct", "court": "ct", "ter": "te", "terrace": "te", "ln": "ln",
    "lane": "ln", "hwy": "hw", "highway": "hw",
}


def normalize_address(value: str) -> str:
    """Reduce a street address to a comparable key."""
    if not value:
        return ""
    text = value.lower()
    # Drop everything from the city onwards, plus any ZIP.
    text = re.split(r",?\s*chicago\b", text)[0]
    text = re.sub(r"\b\d{5}(?:-\d{4})?\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    words = [w for w in text.split() if w]
    return " ".join(_SUFFIXES.get(w, w) for w in words)


def normalize_name(value: str) -> str:
    """Reduce a park name to a comparable key.

    The dataset writes "MCGUANE (JOHN)" where an event title says "McGuane",
    so the parenthetical and any "Park"/"Playlot" suffix come off.
    """
    if not value:
        return ""
    text = re.sub(r"\(.*?\)", " ", value.lower())
    text = re.sub(r"\b(park|playlot|playground|field ?house|th)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(text.split())


def centroid(geometry: dict):
    """Mean of a MultiPolygon's outer-ring points.

    A park is small and convex enough that its mean point lies inside it, and
    all that matters here is which neighborhood polygon contains it.
    """
    coordinates = (geometry or {}).get("coordinates") or []
    points = []

    def walk(node):
        if (isinstance(node, list) and len(node) == 2
                and all(isinstance(v, (int, float)) for v in node)):
            points.append(node)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)

    walk(coordinates)
    if not points:
        return None, None
    longitude = sum(p[0] for p in points) / len(points)
    latitude = sum(p[1] for p in points) / len(points)
    return latitude, longitude


async def fetch_parks() -> tuple[dict, dict]:
    """Build address -> point and name -> point lookups for every park."""
    by_address, by_name = {}, {}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            PARKS_URL,
            params={"$limit": 1000, "$select": "label,park,location,the_geom"},
        )
        response.raise_for_status()
        rows = response.json()

    for row in rows:
        geometry = row.get("the_geom")
        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except ValueError:
                continue
        latitude, longitude = centroid(geometry)
        if latitude is None:
            continue
        point = (latitude, longitude)
        if row.get("location"):
            by_address.setdefault(normalize_address(row["location"]), point)
        for field in ("label", "park"):
            if row.get(field):
                by_name.setdefault(normalize_name(row[field]), point)

    print(f"parks dataset: {len(rows)} parks, "
          f"{len(by_address)} addresses, {len(by_name)} names")
    return by_address, by_name


async def main():
    place_all = "--all" in sys.argv
    by_address, by_name = await fetch_parks()

    engine = create_async_engine(DB_URL)
    session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        boundaries = await load_boundaries(session)
        print(f"boundaries loaded: {len(boundaries)} neighborhoods")

        query = select(EventModel).where(EventModel.source == "chicago_park_district")
        if not place_all:
            query = query.where(EventModel.neighborhood_id.is_(None))
        events = (await session.execute(query)).scalars().all()
        print(f"events to place: {len(events)}")

        ids: dict[str, int] = {}
        placed = unmatched = outside = 0

        for event in events:
            point = by_address.get(normalize_address(event.address or ""))
            if not point and event.venue_name:
                point = by_name.get(normalize_name(event.venue_name))
            if not point:
                unmatched += 1
                continue

            latitude, longitude = point
            name = chicago_neighborhoods.locate_in(latitude, longitude, boundaries)
            if not name:
                outside += 1
                continue

            if name not in ids:
                ids[name] = await resolve_neighborhood_id(session, name)
            event.neighborhood_id = ids[name]
            if event.latitude is None:
                event.latitude, event.longitude = latitude, longitude
            placed += 1

        await session.commit()

    print(f"\nplaced {placed} | no park matched {unmatched} | "
          f"matched but outside every boundary {outside}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
