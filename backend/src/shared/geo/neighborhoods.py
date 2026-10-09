"""Attach events to rows in the neighborhoods table.

Neighborhood names reach us from two directions - the venue scraper knows them
from its own config, and external sources are placed by coordinates - so the
get-or-create lives here rather than in either scraper.
"""

import logging

from sqlalchemy import select

from shared.database.models import NeighborhoodModel

logger = logging.getLogger(__name__)

# A few neighborhoods are spelled more than one way across our sources; collapse
# them so one place does not end up as two tiles in the UI.
# frozendict (PEP 814, Python 3.15 built-in) — immutable at runtime, hashable,
# visible to type checkers. Silently mutating a global alias table between
# requests is now impossible rather than just unlikely.
NEIGHBORHOOD_ALIASES: frozendict[str, str] = frozendict(
    {
        # How people type it, versus how the city spells it.
        "lakeview": "Lake View",
        "wrigleyville": "Lake View",
        "boystown": "Lake View",
        "northalsted": "Lake View",
        "ukie village": "Ukrainian Village",
        "the loop": "Loop",
        "south loop": "Near South Side",
        "bronzeville/douglas": "Bronzeville",
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
)

# Broad local directions are useful query locations, not neighborhood rows.
# Resolve them to names that already exist in the database before building the
# neighborhood filter. These are intentionally explicit: side boundaries are
# colloquial and should not be guessed from coordinates at query time.
CHICAGO_REGION_ALIASES = {
    "northwest side": (
        "Albany Park",
        "Avondale",
        "Belmont Cragin",
        "Dunning",
        "Forest Glen",
        "Galewood",
        "Hermosa",
        "Irving Park",
        "Jefferson Park",
        "Logan Square",
        "Montclare",
        "North Park",
        "Norwood Park",
        "O'Hare",
        "Portage Park",
    ),
    "north side": (
        "Andersonville",
        "Edgewater",
        "Lake View",
        "Lincoln Park",
        "Lincoln Square",
        "North Center",
        "North Park",
        "Rogers Park",
        "Uptown",
        "West Ridge",
    ),
    "west side": (
        "Austin",
        "Garfield Park",
        "Humboldt Park",
        "Little Village",
        "Near West Side",
        "North Lawndale",
        "Ukrainian Village",
        "West Loop",
        "West Town",
    ),
    "south side": (
        "Armour Square",
        "Avalon Park",
        "Beverly",
        "Bridgeport",
        "Bronzeville",
        "Burnside",
        "Chatham",
        "Chicago Lawn",
        "East Side",
        "Englewood",
        "Fuller Park",
        "Greater Grand Crossing",
        "Hegewisch",
        "Hyde Park",
        "Kenwood",
        "New City",
        "Pullman",
        "Riverdale",
        "Roseland",
        "South Chicago",
        "South Deering",
        "South Shore",
        "Washington Heights",
        "Washington Park",
        "West Pullman",
        "Woodlawn",
    ),
    "downtown": ("Loop", "Near South Side", "River North", "Streeterville", "West Loop"),
}


def canonical_neighborhood(name: str | None) -> str | None:
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
        except TypeError, ValueError:
            logger.warning(f"Neighborhood {name!r} has an unreadable boundary")
    return boundaries


async def neighborhood_for_point(session, latitude, longitude) -> str | None:
    """Neighborhood containing a coordinate, using boundaries stored in the DB."""
    if latitude is None or longitude is None:
        return None
    from shared.geo import chicago_neighborhoods

    return chicago_neighborhoods.locate_in(latitude, longitude, await load_boundaries(session))


async def resolve_neighborhood_id(session, name: str | None) -> int | None:
    """Neighborhood row id for this name, creating the row if it is new."""
    name = canonical_neighborhood(name)
    if not name:
        return None

    result = await session.execute(select(NeighborhoodModel).where(NeighborhoodModel.name == name))
    row = result.scalars().first()
    if row:
        return row.id

    row = NeighborhoodModel(name=name)
    session.add(row)
    # Flush, not commit: the caller owns the transaction, but the id is needed
    # now so events can point at it.
    await session.flush()
    return row.id


def resolve_neighborhood_id_sync(session, name: str | None) -> int | None:
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
