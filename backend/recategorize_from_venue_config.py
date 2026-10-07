"""Realign stored categories with the venue categories the scraper declares.

A venue's category lives in `CHICAGO_VENUES`, and events are labelled from it
at scrape time. When that declaration is corrected - the Chicago Council on
Global Affairs was filed under "Community", which put its foreign-policy
lectures next to ward meetings - every event already in the database keeps the
old label until something goes back over them. This is that something.

It is not a blanket overwrite. Each row is recomputed with `classify_all`
against the venue's current category, which means:

  - A title rule still wins. "SEWING FREAK" at Sleeping Village stays
    Arts & Crafts, and a wine tasting at a lecture hall stays Food & Drink. A
    venue is mostly one kind of thing and not always, so the declared category
    is a default and never an override.
  - Secondary labels are recomputed too, so a row gains the multi-label
    treatment it predates.
  - Rows that already agree are left untouched.

Only `category` and `categories` are written. Nothing is deleted.

Usage:
    python recategorize_from_venue_config.py                      # dry run, all venues
    python recategorize_from_venue_config.py --commit
    python recategorize_from_venue_config.py --source chicago_venue_chicago_humanities
"""

import argparse
import asyncio
import sys
from collections import Counter

from sqlalchemy import select

sys.path.insert(0, "src")

from shared.categories import classify_all, normalize_category  # noqa: E402
from shared.database import AsyncSessionLocal  # noqa: E402
from shared.database.models import EventModel  # noqa: E402


def declared_categories() -> dict[str, str]:
    """Each venue scraper's source name mapped to its declared category.

    Keyed by `source`, which is how the rows are stamped, rather than by venue
    name - the two differ in punctuation and case and matching them by hand is
    what this avoids.
    """
    from scrapers.custom.venue.chicago_events_scraper import (
        CHICAGO_VENUES,
        venue_source_name,
    )

    declared = {}
    for configs in CHICAGO_VENUES.values():
        for config in configs:
            label = normalize_category(config.category)
            if label:
                declared[venue_source_name(config)] = label
    return declared


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the changes")
    parser.add_argument("--source", help="only this source")
    args = parser.parse_args()

    declared = declared_categories()
    if args.source:
        declared = {k: v for k, v in declared.items() if k == args.source}
        if not declared:
            print(f"No venue scraper is stamped with source {args.source!r}.")
            return
    print(f"{len(declared)} venue scrapers declare a category")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EventModel).filter(EventModel.source.in_(list(declared)))
        )
        events = list(result.scalars().all())
        print(f"{len(events)} stored events from those venues\n")

        changes = []
        for event in events:
            fallback = declared[event.source]
            labels = classify_all(event.name, fallback)
            if not labels:
                continue
            same_primary = (event.category or "") == labels[0]
            same_all = (event.categories or []) == labels
            if same_primary and same_all:
                continue
            changes.append((event, labels))

        if not changes:
            print("Everything already agrees with the config.")
            return

        moves = Counter(
            f"{e.category or '-'} -> {labels[0]}"
            for e, labels in changes
            if (e.category or "") != labels[0]
        )
        print(f"{len(changes)} rows to rewrite "
              f"({sum(moves.values())} of them a different primary)\n")
        print(f"{'primary change':52} {'n':>4}")
        for move, count in moves.most_common(20):
            print(f"{move[:52]:52} {count:4}")

        print("\nexamples:")
        for event, labels in changes[:12]:
            print(f"  {event.name[:40]:42} {str(event.category)[:18]:20} -> {labels}")

        # The interesting ones: a title rule kept the row off the venue's
        # default, which is the behaviour that must survive this script.
        overrides = [
            (e, labels) for e, labels in changes
            if labels[0] != declared[e.source]
        ]
        if overrides:
            print(f"\n{len(overrides)} kept a title-driven category instead of "
                  f"the venue default:")
            for event, labels in overrides[:8]:
                print(f"  {event.name[:40]:42} venue={declared[event.source][:16]:18} -> {labels}")

        if not args.commit:
            print("\nDRY RUN - nothing written. Re-run with --commit.")
            return

        for event, labels in changes:
            event.category = labels[0]
            event.categories = labels
        await session.commit()
        print(f"\nRewrote {len(changes)} rows. No rows deleted.")


if __name__ == "__main__":
    asyncio.run(main())
