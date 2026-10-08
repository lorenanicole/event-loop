#!/usr/bin/env python
"""Place events in a neighborhood from whatever location data they carry.

Works for any venue, not just the ones we scrape directly, by trying in order:

  1. coordinates on the event        -> point-in-polygon against our own tables
  2. a venue we scrape               -> the neighborhood from its config
  3. a street address                -> geocode once, cache it, then place it

Only step 3 touches the network, it is rate limited, and every result is stored
in geocode_cache so an address is never looked up twice.

    python backfill_neighborhoods.py            # cached + offline sources only
    python backfill_neighborhoods.py --geocode  # also geocode unknown addresses
"""

import asyncio
import sys

sys.path.insert(0, "src")

from shared.database.neighborhoods import load_boundaries, resolve_neighborhood_id
from sqlalchemy import select

from scrapers.venue.chicago_events_scraper import venue_to_neighborhood
from shared.database import AsyncSessionLocal, EventModel, init_db, upcoming_events_filter
from shared.geo import resolve_neighborhood


async def main(allow_network: bool) -> None:
    await init_db()

    async with AsyncSessionLocal() as session:
        boundaries = await load_boundaries(session)
        venue_map = venue_to_neighborhood()
        print(f"{len(boundaries)} neighborhood polygons, {len(venue_map)} known venues")
        if not boundaries:
            print("No boundaries stored. Run load_neighborhood_boundaries.py first.")
            return

        result = await session.execute(
            select(EventModel)
            .where(EventModel.neighborhood_id.is_(None))
            .where(upcoming_events_filter())
        )
        events = result.scalars().all()
        print(f"{len(events)} upcoming events without a neighborhood")
        if allow_network:
            print("geocoding enabled (about 1.5s per new address)\n")
        else:
            print("geocoding disabled - pass --geocode to look up new addresses\n")

        ids: dict[str, int] = {}
        placed = 0
        outside = 0

        for event in events:
            name, latitude, longitude = await resolve_neighborhood(
                session,
                boundaries,
                latitude=event.latitude,
                longitude=event.longitude,
                address=event.address,
                venue_name=event.venue_name,
                venue_map=venue_map,
                allow_network=allow_network,
            )

            # Keep coordinates even when the point falls outside the city, so
            # the lookup is not repeated on the next run.
            if latitude is not None and event.latitude is None:
                event.latitude, event.longitude = latitude, longitude

            if not name:
                if latitude is not None:
                    outside += 1
                continue

            if name not in ids:
                ids[name] = await resolve_neighborhood_id(session, name)
            event.neighborhood_id = ids[name]
            placed += 1

        await session.commit()
        print(f"placed {placed} events across {len(ids)} neighborhoods")
        print(f"{outside} events geolocated outside Chicago's boundaries")


if __name__ == "__main__":
    asyncio.run(main(allow_network="--geocode" in sys.argv))
