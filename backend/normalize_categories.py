"""Bring stored categories in line with what the ingest path now produces.

Two steps, the same ones EventCreate and save_events_to_db apply:

1. Settle casing, leaving wording alone.

   A dozen sources each label their own events, so the same category arrives
   in different cases: "music" from the venue scrapers, "Music" from
   Ticketmaster. Those are one category and should be one tile. "Arts &
   Crafts" and "Arts & Culture" are not, and are left as they are.

2. Override a venue's blanket category where the title is unambiguous.

   A venue scraper labels everything with the venue's own category, so a wine
   special at a music pub arrives as "Music". See infer_category.

3. Fill in every applicable label, not just the primary.

   A trans pride festival is both Community and LGBTQ; a drag show at a music
   venue is both Music and LGBTQ. See classify_all.

    python normalize_categories.py --dry-run
    python normalize_categories.py
"""

import json
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, "src")

from shared.categories import (  # noqa: E402
    classify_all,
    infer_category,
    normalize_category,
)

DB_PATH = "data/events.db"


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = sqlite3.connect(DB_PATH)

    rows = db.execute(
        "SELECT id, name, category FROM events WHERE category IS NOT NULL"
    ).fetchall()

    changes = []
    for event_id, name, current in rows:
        # Same two steps the ingest path applies: settle the casing, then let
        # an unambiguous title override the venue's blanket category.
        wanted = normalize_category(infer_category(name, current))
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

    # Step 3: every applicable label, not just the primary. One event often
    # belongs to several, and storing one made it invisible under the others.
    labelled = [
        (json.dumps(classify_all(name, normalize_category(current) or current)), event_id)
        for event_id, name, current in rows
    ]
    multi = sum(1 for payload, _ in labelled if len(json.loads(payload)) > 1)
    print(f"\n{multi} of {len(labelled)} events carry more than one label")
    if not dry_run:
        db.executemany("UPDATE events SET categories = ? WHERE id = ?", labelled)
        db.commit()

    after = {r[0] for r in db.execute(
        "SELECT DISTINCT category FROM events WHERE category IS NOT NULL")}
    print(f"\n{'(dry run) ' if dry_run else ''}distinct categories: "
          f"{len(before)} -> {len(after)}")
    if not dry_run:
        print("values:", ", ".join(sorted(after)))


if __name__ == "__main__":
    main()
