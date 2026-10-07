"""Give a real category to events whose source never supplied one.

Some sources send no category at all - TimeOut sends a title, a date and a
link - and those events were stored as "Events", then renamed to "Other" when
the parent taxonomy landed. Renaming is not classifying, so "Other" stayed
inflated: 85 upcoming events, 69 of them from TimeOut, including "Chicago Art
Fair", "Bank of America Chicago Marathon" and a dozen Halloween events.

This runs the title classifier over exactly those rows - the ones whose only
label is a generic placeholder - and keeps whatever it can justify. A row it
cannot classify stays in the generic bucket, which is the honest answer; the
goal is an accurate "Other", not an empty one.

Only `category`, `categories` and `subcategories` are written. Nothing is
deleted, and a row that already has a real category is never touched.

Usage:
    python reclassify_generic_categories.py            # dry run
    python reclassify_generic_categories.py --commit
"""

import argparse
import asyncio
import sys
from collections import Counter

from sqlalchemy import select

sys.path.insert(0, "src")

from shared.categories import (  # noqa: E402
    GENERIC_CATEGORY,
    classify_all,
    informative_subtags,
    to_parents,
)
from shared.database import AsyncSessionLocal  # noqa: E402
from shared.database.models import EventModel  # noqa: E402
from shared.semantic_categories import semantic_category  # noqa: E402

# The parent a placeholder label rolls up to.
GENERIC_PARENT = "Other"


def only_generic(event: EventModel) -> bool:
    """Whether this row has no real category, only a placeholder."""
    labels = [event.category] + list(event.categories or [])
    real = [
        label for label in labels
        if label and label not in (GENERIC_PARENT, GENERIC_CATEGORY)
    ]
    return not real


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(EventModel))
        events = [e for e in result.scalars().all() if only_generic(e)]
        print(f"{len(events)} events carry no category but a placeholder")
        by_source = Counter(e.source for e in events)
        print("by source: " + ", ".join(f"{s}={n}" for s, n in by_source.most_common(6)))
        print()

        changes = []
        from_rules = from_model = 0
        for event in events:
            # No fallback: there is no venue category to inherit, which is the
            # whole reason these rows are here. The title has to carry it.
            subtags = classify_all(event.name, GENERIC_CATEGORY)
            parents = to_parents(subtags)
            parents = [p for p in parents if p != GENERIC_PARENT]

            if parents:
                from_rules += 1
                finer = informative_subtags(subtags, parents) or None
            else:
                # The rules said nothing, so ask the model - which is measured
                # to beat the rules alone on coverage and precision together,
                # but only above its floor. Below that it is still confident
                # and still wrong, so it returns nothing and the row stays
                # generic. See `shared.semantic_categories`.
                guess = semantic_category(event.name)
                if not guess:
                    continue
                parents = [guess[0]]
                finer = None
                from_model += 1

            changes.append((event, parents, finer))

        gained = Counter(parents[0] for _, parents, _ in changes)
        print(f"{len(changes)} of {len(events)} can be classified "
              f"({from_rules} by keyword rules, {from_model} by the model)\n")
        print(f"{'new primary':26} {'n':>4}")
        for category, count in gained.most_common():
            print(f"{category:26} {count:4}")

        print("\nexamples:")
        for event, parents, finer in changes[:16]:
            print(f"  {event.name[:46]:48} -> {parents}{'  sub=' + str(finer) if finer else ''}")

        remaining = len(events) - len(changes)
        print(f"\n{remaining} stay in '{GENERIC_PARENT}', which is the honest "
              f"answer for them:")
        unclassified = [e for e in events if e not in {c[0] for c in changes}]
        for event in unclassified[:10]:
            print(f"  {event.name[:52]:54} ({event.source})")

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
