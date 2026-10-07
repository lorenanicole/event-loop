"""Roll stored categories up to the parent taxonomy.

Events were labelled with whatever each source calls things, which left 24
distinct categories, four spellings of theater, and a do312 bucket named
"Activism & Community Events" that filed a library's Teen Anime Night under
activism. `CATEGORY_TAXONOMY` maps each of those source labels to a parent;
this rewrites the stored rows to match.

For every event:

    category       <- the primary parent
    categories     <- every parent it rolls up to
    subcategories  <- the source's own labels, where they say more

Nothing is dropped. A label like "Arts & Crafts" moves from `category` to
`subcategories`, so the distinction between making something and going to look
at something survives - it is just no longer competing for a filter tile.

Ticketmaster's "Arts & Theatre" maps to two parents, Theater and Arts. It is
one segment covering both and holds a quarter of the theater data, so forcing
it either way mislabels the other half.

Also reports any label the taxonomy does not know, which is the one job
similarity scoring is good for here: not deciding where a label belongs, but
noticing that a source has started sending one nobody has placed.

Usage:
    python migrate_to_parent_categories.py            # dry run
    python migrate_to_parent_categories.py --commit
"""

import argparse
import asyncio
import sys
from collections import Counter

from sqlalchemy import select

sys.path.insert(0, "src")

from shared.categories import (  # noqa: E402
    CATEGORY_TAXONOMY,
    PARENT_CATEGORIES,
    informative_subtags,
    to_parents,
    unmapped_labels,
)
from shared.database import AsyncSessionLocal  # noqa: E402
from shared.database.models import EventModel  # noqa: E402


def source_labels(event: EventModel) -> list[str]:
    """Everything the row currently claims to be, primary first."""
    labels = []
    for label in [event.category] + list(event.categories or []):
        if label and label not in labels:
            labels.append(label)
    return labels


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    print(f"{len(PARENT_CATEGORIES)} parents, "
          f"{sum(len(v) for v in CATEGORY_TAXONOMY.values())} mapped source labels\n")

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(EventModel))
        events = list(result.scalars().all())
        print(f"{len(events)} events\n")

        # Report gaps before touching anything: a label nobody mapped would
        # otherwise become its own parent and quietly grow a filter tile.
        seen = []
        for event in events:
            for label in source_labels(event):
                if label not in seen:
                    seen.append(label)
        gaps = unmapped_labels(seen)
        if gaps:
            counts = Counter(
                label for e in events for label in source_labels(e) if label in gaps
            )
            print("NOT IN THE TAXONOMY - these keep their own name as a parent, "
                  "and should be mapped:")
            for label, count in counts.most_common():
                print(f"  {label!r}  ({count} events)")
            print()

        changes = []
        for event in events:
            labels = source_labels(event)
            parents = to_parents(labels)
            if not parents:
                continue
            finer = informative_subtags(labels, parents) or None
            if (event.category == parents[0]
                    and (event.categories or []) == parents
                    and (event.subcategories or None) == finer):
                continue
            changes.append((event, parents, finer))

        if not changes:
            print("Already rolled up.")
            return

        moves = Counter(
            f"{e.category} -> {parents[0]}"
            for e, parents, _ in changes if e.category != parents[0]
        )
        print(f"{len(changes)} rows to rewrite, "
              f"{sum(moves.values())} changing their primary\n")
        print(f"{'primary change':56} {'n':>5}")
        for move, count in moves.most_common():
            print(f"{move[:56]:56} {count:5}")

        kept = Counter(
            label for _, _, finer in changes for label in (finer or [])
        )
        if kept:
            print(f"\nsubtags preserved (shown on a card, not filtered on):")
            for label, count in kept.most_common():
                print(f"  {label:34} {count:5}")

        multi = [c for c in changes if len(c[1]) > 1]
        print(f"\n{len(multi)} rows end up with more than one parent, e.g.:")
        for event, parents, finer in multi[:6]:
            print(f"  {event.name[:38]:40} {parents}  sub={finer}")

        if not args.commit:
            print("\nDRY RUN - nothing written. Re-run with --commit.")
            return

        for event, parents, finer in changes:
            event.category = parents[0]
            event.categories = parents
            event.subcategories = finer
        await session.commit()
        print(f"\nRewrote {len(changes)} rows. No rows deleted.")


if __name__ == "__main__":
    asyncio.run(main())
