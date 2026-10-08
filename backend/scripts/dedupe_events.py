"""Collapse rows that are the same event stored more than once.

Several extractors yielded each event twice - the same card reached through
two overlapping selectors, or a nested container matched alongside its
parent - and save_events_to_db made that permanent: its collision handling
invented a unique URL for the second copy, which preserved the duplicate
instead of recognising it. Kingston Mines stored every show twice, nightly.

That is now collapsed at save time, but rows written before the fix remain.

Identity is source + name + date + time. Time matters: Kingston Mines runs
several sets a night and Jazz Showcase two houses, so two rows sharing a
title and a date are only duplicates if they also share a start time.

Only duplicates *within one source* are touched. The same show listed by both
Ticketmaster and its venue is not the same row: the URLs and details differ,
and choosing which to keep is a judgment this script should not make. Those
are reported and left alone.

    python dedupe_events.py --dry-run
    python dedupe_events.py
"""

import sqlite3
import sys

DB_PATH = "data/events.db"


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = sqlite3.connect(DB_PATH)

    # Undated rows are excluded. Six "JW Jones" rows at Buddy Guy's with a
    # NULL date are six nights whose date failed to parse, not six copies of
    # one night - there is nothing to tell them apart by, so collapsing them
    # would delete five real events. They are reported separately instead.
    groups = db.execute(
        """SELECT source, LOWER(TRIM(name)), date, IFNULL(time, ''),
                  COUNT(*), GROUP_CONCAT(id)
           FROM events
           WHERE date IS NOT NULL
           GROUP BY source, LOWER(TRIM(name)), date, IFNULL(time, '')
           HAVING COUNT(*) > 1"""
    ).fetchall()

    # Keep the lowest id - the first time the event was seen - so whatever
    # else references it keeps working.
    doomed = []
    for source, name, date, time, count, ids in groups:
        _keep, *rest = sorted(int(i) for i in ids.split(","))
        doomed.extend(rest)

    print(f"{len(groups)} duplicated events within a single source, {len(doomed)} redundant rows\n")
    for source, name, date, time, count, _ in sorted(groups, key=lambda g: -g[4])[:12]:
        print(f"   x{count}  {str(date)[:10]} {time or '-':9} {name[:32]:34} {source[:34]}")
    if len(groups) > 12:
        print(f"   ... and {len(groups) - 12} more")

    (undated,) = db.execute("SELECT COUNT(*) FROM events WHERE date IS NULL").fetchone()
    if undated:
        print(
            f"\n{undated} rows have no date at all and are skipped. They cannot be "
            f"told apart, and are already invisible to the UI, which requires a date."
        )

    cross = db.execute(
        """SELECT LOWER(TRIM(name)), date, COUNT(DISTINCT source)
           FROM events GROUP BY LOWER(TRIM(name)), date
           HAVING COUNT(DISTINCT source) > 1"""
    ).fetchall()
    print(
        f"\n{len(cross)} events appear under more than one source - left alone, "
        f"since the rows differ in URL and detail."
    )

    if doomed and not dry_run:
        db.executemany("DELETE FROM events WHERE id = ?", [(i,) for i in doomed])
        db.commit()
        print(f"\ndeleted {len(doomed)} rows")
    elif doomed:
        print("\n(dry run - nothing deleted)")

    (total,) = db.execute("SELECT COUNT(*) FROM events").fetchone()
    print(f"events remaining: {total}")


if __name__ == "__main__":
    main()
