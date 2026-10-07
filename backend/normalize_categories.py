"""Normalize stored category casing, leaving the wording alone.

A dozen sources each label their own events, so the same category arrives in
different cases: "music" from the venue scrapers, "Music" from Ticketmaster.
Those are one category and should be one tile. "Arts & Crafts" and "Arts &
Culture" are not, and are left as they are - collapsing them would throw away a
real distinction, and `shared.categories.category_filter` already matches a
search for "art" across every Arts* label by prefix.

    python normalize_categories.py --dry-run
    python normalize_categories.py
"""

import sqlite3
import sys
from collections import Counter

sys.path.insert(0, "src")

from shared.categories import normalize_category  # noqa: E402

DB_PATH = "data/events.db"


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = sqlite3.connect(DB_PATH)

    rows = db.execute(
        "SELECT id, category FROM events WHERE category IS NOT NULL"
    ).fetchall()

    changes = []
    for event_id, current in rows:
        wanted = normalize_category(current)
        if wanted and wanted != current:
            changes.append((event_id, current, wanted))

    before = {r[0] for r in db.execute(
        "SELECT DISTINCT category FROM events WHERE category IS NOT NULL")}

    moves = Counter((old, new) for _, old, new in changes)
    print(f"{len(changes)} rows to update across {len(moves)} distinct values:")
    for (old, new), count in moves.most_common():
        merges_into_existing = new in before
        note = "  (merges with existing)" if merges_into_existing else ""
        print(f"   {old!r:34} -> {new!r:28} {count:5} rows{note}")

    if not dry_run and changes:
        db.executemany(
            "UPDATE events SET category = ? WHERE id = ?",
            [(new, event_id) for event_id, _, new in changes],
        )
        db.commit()

    after = {r[0] for r in db.execute(
        "SELECT DISTINCT category FROM events WHERE category IS NOT NULL")}
    print(f"\n{'(dry run) ' if dry_run else ''}distinct categories: "
          f"{len(before)} -> {len(after)}")
    if not dry_run:
        print("values:", ", ".join(sorted(after)))


if __name__ == "__main__":
    main()
