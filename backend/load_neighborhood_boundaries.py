#!/usr/bin/env python
"""Load Chicago neighborhood boundaries into the database.

Run once (and again only if the city republishes the boundaries). After this,
placing a coordinate in a neighborhood is a local point-in-polygon test against
rows in our own database - no geocoding API, no rate limit, no network.

    python load_neighborhood_boundaries.py
"""

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "src")

from sqlalchemy import select

from shared.database import AsyncSessionLocal, init_db
from shared.database.models import NeighborhoodModel
from shared.database.neighborhoods import canonical_neighborhood

SOURCE_URL = "https://data.cityofchicago.org/resource/y6yq-dbs2.geojson?$limit=500"
CACHE_PATH = Path("data/chicago_neighborhoods.geojson")

# The city's boundaries are finer-grained than the neighborhood names this app
# already uses, and a few are venues rather than places. Fold those in so the UI
# does not grow a "United Center" tile next to "Near West Side".
BOUNDARY_ALIASES = {
    "wrigleyville": "Lake View",
    "boystown": "Lake View",
    "sheffield & depaul": "Lincoln Park",
    "united center": "Near West Side",
    "printers row": "Loop",
    "millenium park": "Loop",
    "grant park": "Loop",
    "museum campus": "Loop",
    # The city joins two areas into one polygon for these. Use the name a
    # person would actually recognise rather than the comma-joined pair:
    # UIC is a university campus, and Forest Glen is the community area that
    # contains Sauganash.
    "little italy, uic": "Little Italy",
    "sauganash,forest glen": "Forest Glen",
    # Community-area names nobody uses out loud. Pilsen sits inside the Lower
    # West Side community area, and the light posts there say Pilsen. Bronzeville
    # spans two community areas, Douglas and Grand Boulevard, so both fold into
    # it - and Douglas carries the name of a senator who argued for slavery.
    "lower west side": "Pilsen",
    "douglas": "Bronzeville",
    "grand boulevard": "Bronzeville",
}


def fetch_boundaries() -> list:
    if CACHE_PATH.exists():
        print(f"using cached {CACHE_PATH}")
        return json.loads(CACHE_PATH.read_text())["features"]

    print(f"downloading {SOURCE_URL}")
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "eventloop/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = response.read()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_bytes(payload)
    return json.loads(payload)["features"]


async def main() -> None:
    await init_db()
    features = fetch_boundaries()
    print(f"{len(features)} boundary polygons")

    # Several city polygons can fold into one of our neighborhoods, so collect
    # their geometries before writing.
    merged: dict[str, list] = {}
    for feature in features:
        raw = (feature.get("properties") or {}).get("pri_neigh")
        geometry = feature.get("geometry")
        if not raw or not geometry:
            continue
        name = canonical_neighborhood(BOUNDARY_ALIASES.get(raw.strip().lower(), raw.strip()))
        merged.setdefault(name, []).append(geometry)

    async with AsyncSessionLocal() as session:
        existing = {
            row.name: row
            for row in (await session.execute(select(NeighborhoodModel))).scalars().all()
        }

        created = updated = 0
        for name, geometries in sorted(merged.items()):
            # One row per neighborhood; several polygons become a MultiPolygon.
            polygons = []
            for geometry in geometries:
                if geometry["type"] == "Polygon":
                    polygons.append(geometry["coordinates"])
                elif geometry["type"] == "MultiPolygon":
                    polygons.extend(geometry["coordinates"])
            boundary = json.dumps({"type": "MultiPolygon", "coordinates": polygons})

            row = existing.get(name)
            if row is None:
                row = NeighborhoodModel(name=name)
                session.add(row)
                created += 1
            else:
                updated += 1
            row.boundary = boundary

        await session.commit()
        print(f"neighborhoods: {created} created, {updated} updated with boundaries")


if __name__ == "__main__":
    asyncio.run(main())
