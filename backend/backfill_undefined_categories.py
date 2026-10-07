"""Reclassify events stored under the category "Undefined".

Where they came from: Ticketmaster's Discovery API describes an event at three
widths - segment, genre, subGenre - and fills any it does not know with the
literal string "Undefined". The scraper read `segment.name` straight into the
category, so 128 events arrived labelled "Undefined" and the UI grew a filter
tile with that name. All 128 are from that one source; no other source
produces it. The scraper now treats "Undefined" as absent at every level, so
this backfill is a one-off repair rather than a recurring chore.

Nothing is deleted. Each row keeps its name, date, venue and URL, and only
`category` and `categories` are rewritten.

How a replacement is chosen, in order of how much it can be trusted:

1. The narrow title rules - "SEWING FREAK" is Arts & Crafts wherever it
   happens.
2. The concept vocabulary, over the title plus the venue name as a hint.
   Discovery's `details` are no help here, being only "Venue: X | Location:
   Chicago", but the venue name itself carries real signal: ChiTown Movies
   says film, Chicago Shakespeare Theater says theater.
3. Only if both are silent, the category that other events at the same venue
   usually have.

Step 3 is a prior and never an override, which matters: a venue is mostly one
kind of thing and not always. Sleeping Village is a music venue that hosts
"SEWING FREAK", and that event is Arts & Crafts. The ordering above is what
keeps it that way - `classify_all` applies the title rules before it will look
at the fallback. Ticketmaster rows are left out when computing the prior, or
"Undefined" would vote for itself.

Usage:
    python backfill_undefined_categories.py            # dry run
    python backfill_undefined_categories.py --commit   # write
"""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict

from sqlalchemy import String, cast, or_, select

sys.path.insert(0, "src")

from shared.categories import (  # noqa: E402
    GENERIC_CATEGORY,
    classify_all,
    classify_from_title,
)
from shared.database import AsyncSessionLocal  # noqa: E402
from shared.database.models import EventModel  # noqa: E402

PLACEHOLDER = "undefined"

# Discovery writes details as "Venue: Vic Theatre | Location: Chicago, Illinois"
_VENUE_IN_DETAILS = re.compile(r"Venue:\s*([^|]+)")

# Categories that say nothing, so they must not be learned as a venue's prior.
_UNINFORMATIVE = {PLACEHOLDER, "other", GENERIC_CATEGORY.lower(), ""}


def venue_of(event: EventModel) -> str:
    """The venue for an event, from its own column or out of its details."""
    if event.venue_name and event.venue_name.strip():
        return event.venue_name.strip()
    found = _VENUE_IN_DETAILS.search(event.details or "")
    return found.group(1).strip() if found else ""


def venue_key(name: str) -> str:
    """A venue name reduced to something two sources can agree on.

    Exact matching finds almost nothing, because each source writes the same
    room differently: Ticketmaster says "Cole's Bar Chicago" and "Vic Theatre"
    where our own scrapers say "Cole's Bar" and "The Vic Theatre". Dropping
    punctuation, a leading "the" and a trailing "chicago" makes those meet.

    Theater/theatre is folded too - the same building is spelled both ways by
    different sources.
    """
    key = (name or "").lower()
    key = re.sub(r"[^a-z0-9 ]+", "", key)
    key = re.sub(r"\btheatre\b", "theater", key)
    key = re.sub(r"^the\s+", "", key)
    # Ticketmaster appends a disambiguator to venues that share a name:
    # "Chop Shop - IL", "Riviera Theatre- IL". Stripped repeatedly, because a
    # name can carry both ("... Chicago IL").
    for _ in range(2):
        key = re.sub(r"\s*\b(il|illinois|chicago)\s*$", "", key)
    return " ".join(key.split())


def config_priors() -> dict[str, str]:
    """Each venue's category as the scraper config declares it.

    Authoritative where it exists - somebody wrote it down deliberately - and
    independent of whatever happens to be in the database this week, so a
    venue with no other events on record still gets a sensible default.
    """
    from shared.categories import normalize_category
    from scrapers.custom.venue.chicago_events_scraper import CHICAGO_VENUES

    priors = {}
    for configs in CHICAGO_VENUES.values():
        for config in configs:
            label = normalize_category(config.category)
            if label and label.lower() not in _UNINFORMATIVE:
                priors[venue_key(config.name)] = label
    return priors


def is_placeholder(event: EventModel) -> bool:
    if (event.category or "").strip().lower() == PLACEHOLDER:
        return True
    return any(
        (label or "").strip().lower() == PLACEHOLDER
        for label in (event.categories or [])
    )


async def venue_priors(session) -> dict[str, str]:
    """The category events at each venue usually carry.

    Built from every source except Ticketmaster: its rows are the ones being
    repaired, so letting them vote would have "Undefined" elect itself.
    """
    result = await session.execute(
        select(EventModel).filter(EventModel.source != "ticketmaster")
    )
    tally: dict[str, Counter] = defaultdict(Counter)
    for event in result.scalars().all():
        venue = venue_of(event)
        category = (event.category or "").strip()
        if not venue or category.lower() in _UNINFORMATIVE:
            continue
        tally[venue_key(venue)][category] += 1

    return {venue: counts.most_common(1)[0][0] for venue, counts in tally.items()}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EventModel).filter(
                or_(
                    EventModel.category.ilike(PLACEHOLDER),
                    cast(EventModel.categories, String).ilike(f'%"{PLACEHOLDER}"%'),
                )
            )
        )
        broken = [e for e in result.scalars().all() if is_placeholder(e)]
        print(f"{len(broken)} events stored under a placeholder category")
        if not broken:
            return

        by_source = Counter(e.source for e in broken)
        print("by source: " + ", ".join(f"{s}={n}" for s, n in by_source.most_common()))

        # The config first, because somebody chose those deliberately; then
        # whatever the rest of the database shows, for venues not in it.
        priors = await venue_priors(session)
        declared = config_priors()
        priors.update(declared)
        print(f"{len(priors)} venues have a usable category prior "
              f"({len(declared)} declared in the scraper config)\n")

        changes = []
        for event in broken:
            venue = venue_of(event)
            prior = priors.get(venue_key(venue))
            if not prior and venue:
                # Weakest source, and still only a prior: what the venue's own
                # name says it is. "Athenaeum Theatre" is a theater and
                # "ChiTown Movies" shows films, which is worth more than the
                # generic bucket for a venue we have never scraped.
                #
                # Note this is the venue's category, not the event's - it goes
                # into `prior`, where any title rule outranks it. Feeding the
                # venue name to the classifier as a hint instead was tried and
                # filed a live podcast at Vic Theatre as Theater.
                guessed = classify_from_title(venue, GENERIC_CATEGORY)
                prior = guessed if guessed != GENERIC_CATEGORY else None
            prior = prior or GENERIC_CATEGORY
            # Deliberately no hint. Passing the venue name was tried and is
            # wrong: the concept matcher sees "Theatre" inside "Vic Theatre"
            # and files a live podcast recording as Theater, which is the venue
            # asserting a category for an event that is not that category. The
            # venue belongs in `prior`, where the title rules outrank it.
            labels = classify_all(event.name, prior)
            if not labels:
                continue
            changes.append((event, labels, venue, prior))

        outcome = Counter(labels[0] for _, labels, _, _ in changes)
        print(f"{'new primary':26} {'n':>4}")
        for category, count in outcome.most_common():
            print(f"{category:26} {count:4}")

        print("\nexamples:")
        for event, labels, venue, prior in changes[:14]:
            print(f"  {event.name[:38]:40} @ {venue[:24]:26} prior={prior[:14]:16} -> {labels}")

        still_generic = [c for c in changes if c[1][0] == GENERIC_CATEGORY]
        if still_generic:
            print(f"\n{len(still_generic)} could not be classified beyond "
                  f"'{GENERIC_CATEGORY}'. Kept, not dropped - the name, date, "
                  f"venue and link are all still there:")
            for event, _, venue, _ in still_generic[:8]:
                print(f"  {event.name[:44]:46} @ {venue[:28]}")

        if not args.commit:
            print("\nDRY RUN - nothing written. Re-run with --commit.")
            return

        for event, labels, _, _ in changes:
            event.category = labels[0]
            event.categories = labels
        await session.commit()
        print(f"\nRewrote the category on {len(changes)} events. "
              f"No rows deleted, no other column touched.")


if __name__ == "__main__":
    asyncio.run(main())
