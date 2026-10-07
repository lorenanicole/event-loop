"""Merge neighborhood rows that are two names for one place.

The city publishes a 98-entry neighborhood layer and a 77-entry community-area
list, and they disagree in three places. Each disagreement left us holding two
rows for the same ground - typically one carrying the boundary polygon and the
other carrying the events - so neither could be placed or filtered properly:

    Grand Crossing      -> Greater Grand Crossing   (community-area name)
    Mckinley Park       -> McKinley Park            (the president's spelling)
    Near North Side     -> Streeterville            (not in the city's layer)

Events move to the surviving row, the boundary follows if the survivor lacks
one, and only the emptied duplicate is deleted. Nothing else is touched.

    python merge_duplicate_neighborhoods.py --dry-run
    python merge_duplicate_neighborhoods.py
"""

import sqlite3
import sys

DB_PATH = "data/events.db"

# (duplicate to retire, row to keep)
MERGES = [
    ("Grand Crossing", "Greater Grand Crossing"),
    ("Mckinley Park", "McKinley Park"),
    ("Near North Side", "Streeterville"),
]


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = sqlite3.connect(DB_PATH)

    for duplicate, keeper in MERGES:
        rows = {
            name: (rid, boundary is not None)
            for name, rid, boundary in db.execute(
                "SELECT name, id, boundary FROM neighborhoods WHERE name IN (?, ?)",
                (duplicate, keeper),
            ).fetchall()
        }
        if duplicate not in rows:
            print(f"{duplicate!r}: already gone, nothing to do")
            continue
        dup_id, dup_has_boundary = rows[duplicate]

        if keeper not in rows:
            # No survivor to merge into: just rename the duplicate.
            print(f"{duplicate!r} -> rename to {keeper!r}")
            if not dry_run:
                db.execute("UPDATE neighborhoods SET name = ? WHERE id = ?", (keeper, dup_id))
            continue

        keep_id, keep_has_boundary = rows[keeper]
        moved = db.execute(
            "SELECT COUNT(*) FROM events WHERE neighborhood_id = ?", (dup_id,)
        ).fetchone()[0]
        print(f"{duplicate!r} (id {dup_id}, {moved} events) -> {keeper!r} (id {keep_id})"
              + ("  [carrying boundary across]" if dup_has_boundary and not keep_has_boundary else ""))

        if dry_run:
            continue

        if dup_has_boundary and not keep_has_boundary:
            db.execute(
                "UPDATE neighborhoods SET boundary = (SELECT boundary FROM neighborhoods "
                "WHERE id = ?) WHERE id = ?", (dup_id, keep_id)
            )
        db.execute("UPDATE events SET neighborhood_id = ? WHERE neighborhood_id = ?",
                   (keep_id, dup_id))
        remaining = db.execute(
            "SELECT COUNT(*) FROM events WHERE neighborhood_id = ?", (dup_id,)
        ).fetchone()[0]
        assert remaining == 0, f"{duplicate!r} still has {remaining} events; not deleting"
        db.execute("DELETE FROM neighborhoods WHERE id = ?", (dup_id,))

    if not dry_run:
        db.commit()

    total, = db.execute("SELECT COUNT(*) FROM neighborhoods").fetchone()
    without, = db.execute("SELECT COUNT(*) FROM neighborhoods WHERE boundary IS NULL").fetchone()
    print(f"\n{'(dry run) ' if dry_run else ''}{total} neighborhood rows, "
          f"{without} without a boundary")


if __name__ == "__main__":
    main()
