"""Chicago-local event times.

Sources publish start times in three different shapes and the difference is
not cosmetic. Ticketmaster gives `dateTime` in UTC alongside `localDate` and
`localTime`; schema.org JSON-LD gives an offset ("2026-10-06T21:30:00-05:00");
venue pages give a bare local time with no zone at all.

Storing a UTC instant as if it were local moves every evening show forward a
day: a 9:30pm set at Rosa's was stored as 02:30 the next morning, so it
answered "tomorrow" and not "tonight". 430 events were sitting on the wrong
day because of this.

Everything is therefore normalized to naive Chicago local time on the way in,
which is what the date filters and the "tonight" window already assume.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")


def to_chicago_naive(value: datetime | None) -> datetime | None:
    """Convert an aware datetime to naive Chicago local time.

    A naive value is passed through untouched: it came from a venue page that
    published a local time without a zone, which is already what we want.
    Using zoneinfo rather than a fixed offset so the switch between CDT and
    CST is handled - a November event is -6, an October one -5.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(CHICAGO).replace(tzinfo=None)


def utc_naive_to_chicago(value: datetime | None) -> datetime | None:
    """Reinterpret a naive value that is really UTC, and convert it.

    For repairing rows already stored: the offset was dropped on the way in,
    so the wall clock in the database is UTC but carries no zone to say so.
    """
    if value is None:
        return None
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(CHICAGO).replace(tzinfo=None)
