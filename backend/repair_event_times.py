"""Repair events stored as UTC instead of Chicago local time.

Ticketmaster publishes `dateTime` in UTC and Rosa's publishes a schema.org
offset; both were parsed into an aware datetime whose zone was then dropped
on the way into the column, leaving a UTC wall clock with nothing to say so.

The effect was not cosmetic. An 8pm show became 01:00 the following day, so
it answered "tomorrow" and never "tonight", and 430 events were sitting on
the wrong date.

Only the sources known to have stored UTC are touched. A venue page that
published a bare local time was always correct and must not be shifted, which
is why this works by source rather than by looking for suspicious times.

    python repair_event_times.py --dry-run
    python repair_event_times.py
"""

import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, "src")

from shared.localtime import utc_naive_to_chicago  # noqa: E402

DB_PATH = "data/events.db"

# Sources whose parser produced an aware UTC datetime. Everything else gave a
# naive local time and is already right.
UTC_SOURCES = ("ticketmaster", "chicago_venue_rosass_lounge")

STAMP = "%Y-%m-%d %H:%M:%S.%f"


def parse(value):
    if not value:
        return None
    for fmt in (STAMP, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = sqlite3.connect(DB_PATH)

    placeholders = ",".join("?" for _ in UTC_SOURCES)
    rows = db.execute(
        f"SELECT id, source, date, date_end, name FROM events WHERE source IN ({placeholders})",
        UTC_SOURCES,
    ).fetchall()

    changes = []
    day_moved = 0
    for event_id, source, date_raw, end_raw, name in rows:
        start, end = parse(date_raw), parse(end_raw)
        if start is None:
            continue
        # A bare date with no time carries no zone error to correct.
        if start.hour == 0 and start.minute == 0:
            continue
        fixed_start = utc_naive_to_chicago(start)
        fixed_end = utc_naive_to_chicago(end) if end else None
        if fixed_start == start:
            continue
        if fixed_start.date() != start.date():
            day_moved += 1
        changes.append((
            fixed_start.strftime(STAMP),
            fixed_end.strftime(STAMP) if fixed_end else None,
            event_id,
            name,
            start,
            fixed_start,
        ))

    print(f"{len(changes)} events to correct, of which {day_moved} move to a different day\n")
    for _, _, _, name, old, new in changes[:10]:
        marker = "  <- day changes" if old.date() != new.date() else ""
        print(f"   {old:%Y-%m-%d %H:%M} -> {new:%Y-%m-%d %H:%M}  {name[:40]}{marker}")
    if len(changes) > 10:
        print(f"   ... and {len(changes) - 10} more")

    if changes and not dry_run:
        db.executemany(
            "UPDATE events SET date = ?, date_end = ? WHERE id = ?",
            [(start, end, event_id) for start, end, event_id, *_ in changes],
        )
        db.commit()
        print(f"\ncorrected {len(changes)} events")
    elif changes:
        print("\n(dry run - nothing written)")


if __name__ == "__main__":
    main()
