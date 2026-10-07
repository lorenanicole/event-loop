"""Attach events to rows in the neighborhoods table.

Neighborhood names reach us from two directions - the venue scraper knows them
from its own config, and external sources are placed by coordinates - so the
get-or-create lives here rather than in either scraper.
"""

import logging
from typing import Optional

from sqlalchemy import select

from .models import NeighborhoodModel

logger = logging.getLogger(__name__)

# A few neighborhoods are spelled more than one way across our sources; collapse
# them so one place does not end up as two tiles in the UI.
NEIGHBORHOOD_ALIASES = {
    "lakeview": "Lake View",
    # The city's neighborhood layer and its community-area list disagree on
    # these, which left us holding two rows for one place - one with the
    # boundary, one with the events. Fold each onto the community-area name,
    # matching how Pilsen and Bronzeville are handled in the boundary loader.
    "grand crossing": "Greater Grand Crossing",
    # The city's data has "Mckinley Park"; the park and the president are
    # McKinley.
    "mckinley park": "McKinley Park",
    # Not a neighborhood in the city's layer at all: that area is published as
    # Streeterville, Gold Coast, River North and Old Town. Anything still
    # labelled with the community area resolves to where it actually sits.
    "near north side": "Streeterville",
}


def canonical_neighborhood(name: Optional[str]) -> Optional[str]:
    """Normalize a neighborhood name to the single spelling we store."""
    if not name or not name.strip():
        return None
    cleaned = name.strip()
    return NEIGHBORHOOD_ALIASES.get(cleaned.lower(), cleaned)


async def load_boundaries(session) -> dict:
    """Neighborhood name -> parsed boundary geometry, for point-in-polygon.

    Read once per scrape and reused; placing a coordinate then costs no
    network calls at all.
    """
    import json

    result = await session.execute(
        select(NeighborhoodModel.name, NeighborhoodModel.boundary).where(
            NeighborhoodModel.boundary.isnot(None)
        )
    )
    boundaries = {}
    for name, raw in result.all():
        try:
            boundaries[name] = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning(f"Neighborhood {name!r} has an unreadable boundary")
    return boundaries


async def neighborhood_for_point(session, latitude, longitude) -> Optional[str]:
    """Neighborhood containing a coordinate, using boundaries stored in the DB."""
    if latitude is None or longitude is None:
        return None
    from shared.geo import chicago_neighborhoods

    return chicago_neighborhoods.locate_in(latitude, longitude, await load_boundaries(session))


async def resolve_neighborhood_id(session, name: Optional[str]) -> Optional[int]:
    """Neighborhood row id for this name, creating the row if it is new."""
    name = canonical_neighborhood(name)
    if not name:
        return None

    result = await session.execute(
        select(NeighborhoodModel).where(NeighborhoodModel.name == name)
    )
    row = result.scalars().first()
    if row:
        return row.id

    row = NeighborhoodModel(name=name)
    session.add(row)
    # Flush, not commit: the caller owns the transaction, but the id is needed
    # now so events can point at it.
    await session.flush()
    return row.id


def resolve_neighborhood_id_sync(session, name: Optional[str]) -> Optional[int]:
    """Synchronous counterpart, for scrapers given a plain Session."""
    name = canonical_neighborhood(name)
    if not name:
        return None

    row = session.query(NeighborhoodModel).filter_by(name=name).first()
    if row:
        return row.id

    row = NeighborhoodModel(name=name)
    session.add(row)
    session.flush()
    return row.id
