"""Database utility helpers shared across scrapers and the API."""

from datetime import datetime, timezone


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """Convert a datetime to a naive UTC datetime, stripping tzinfo.

    Postgres ``TIMESTAMP WITHOUT TIME ZONE`` columns reject tz-aware objects.
    Scraper sources return datetimes that may or may not carry a UTC offset
    depending on the API. This helper normalises both cases to naive UTC so
    inserts never fail on the timezone check.

    - Aware datetime  → converted to UTC, tzinfo stripped
    - Naive datetime  → assumed UTC, returned unchanged
    - None            → returned as-is
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
