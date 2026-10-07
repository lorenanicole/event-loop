"""Resolve Chicago coordinates to a neighborhood name.

Sources like Ticketmaster give a venue's latitude and longitude but no
neighborhood, so events from them cannot be offered under the UI's "where"
tiles until the point is placed inside a boundary.

This does a point-in-polygon lookup against the City of Chicago's published
neighborhood boundaries rather than calling a geocoding API per event:
the boundaries are fetched once and cached on disk, after which lookups are
local, instant, deterministic and not subject to anyone's rate limit.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# City of Chicago open data: "Boundaries - Neighborhoods" (98 polygons).
BOUNDARIES_URL = "https://data.cityofchicago.org/resource/y6yq-dbs2.geojson?$limit=500"
BOUNDARIES_PATH = Path(__file__).resolve().parents[3] / "data" / "chicago_neighborhoods.geojson"

# The city's boundaries are finer-grained than the neighborhood names this app
# already uses, and a few are really venues rather than places. Fold those into
# the name events are already filed under so the UI does not grow a "United
# Center" tile sitting next to "Near West Side".
NEIGHBORHOOD_ALIASES = {
    "wrigleyville": "Lake View",
    "boystown": "Lake View",
    "sheffield & depaul": "Lincoln Park",
    "united center": "Near West Side",
    "old town": "Old Town",
    "river north": "River North",
    "west loop": "West Loop",
    "printers row": "Loop",
    "the loop": "Loop",
    "museum campus": "Loop",
    "millenium park": "Loop",
    "grant park": "Loop",
}


def _canonical(name: str | None) -> str | None:
    if not name:
        return None
    return NEIGHBORHOOD_ALIASES.get(name.strip().lower(), name.strip())


class ChicagoNeighborhoods:
    """Point-in-polygon lookup over the city's neighborhood boundaries."""

    def __init__(self, path: Path = BOUNDARIES_PATH, url: str = BOUNDARIES_URL):
        self._path = path
        self._url = url
        self._features: list | None = None

    def _load(self) -> list:
        """Load boundaries, downloading them once if they are not cached."""
        if self._features is not None:
            return self._features

        if not self._path.exists():
            logger.info(f"Downloading Chicago neighborhood boundaries to {self._path}")
            import urllib.request

            self._path.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(self._url, headers={"User-Agent": "eventloop/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                self._path.write_bytes(response.read())

        with self._path.open() as handle:
            self._features = json.load(handle).get("features", [])
        logger.info(f"Loaded {len(self._features)} Chicago neighborhood boundaries")
        return self._features

    @staticmethod
    def _polygons(geometry: dict):
        """Yield each polygon (outer ring first, then any holes)."""
        kind = geometry.get("type")
        if kind == "Polygon":
            yield geometry["coordinates"]
        elif kind == "MultiPolygon":
            yield from geometry["coordinates"]

    @staticmethod
    def _in_ring(x: float, y: float, ring: list) -> bool:
        """Ray casting: is (x, y) inside this ring?"""
        inside = False
        count = len(ring)
        for i in range(count):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % count][0], ring[(i + 1) % count][1]
            if (y1 > y) != (y2 > y):
                crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < crossing:
                    inside = not inside
        return inside

    def lookup(self, latitude: float, longitude: float) -> str | None:
        """Neighborhood containing this point, or None if outside Chicago."""
        if latitude is None or longitude is None:
            return None
        try:
            features = self._load()
        except Exception as e:
            logger.warning(f"Neighborhood boundaries unavailable: {e}")
            return None

        for feature in features:
            for polygon in self._polygons(feature.get("geometry") or {}):
                if not polygon:
                    continue
                # Inside the outer ring and not inside any hole.
                if self._in_ring(longitude, latitude, polygon[0]) and not any(
                    self._in_ring(longitude, latitude, hole) for hole in polygon[1:]
                ):
                    return _canonical(feature.get("properties", {}).get("pri_neigh"))
        return None

    def locate_in(self, latitude: float, longitude: float, boundaries: dict) -> str | None:
        """Place a point using boundaries already loaded from the database.

        `boundaries` maps neighborhood name -> parsed GeoJSON geometry, so this
        runs entirely on rows we store and never touches the network.
        """
        if latitude is None or longitude is None:
            return None
        for name, geometry in boundaries.items():
            for polygon in self._polygons(geometry or {}):
                if not polygon:
                    continue
                if self._in_ring(longitude, latitude, polygon[0]) and not any(
                    self._in_ring(longitude, latitude, hole) for hole in polygon[1:]
                ):
                    return name
        return None


chicago_neighborhoods = ChicagoNeighborhoods()


def neighborhood_for(latitude: float | None, longitude: float | None) -> str | None:
    """Neighborhood name for a coordinate, or None if it is outside the city."""
    if latitude is None or longitude is None:
        return None
    return chicago_neighborhoods.lookup(latitude, longitude)
