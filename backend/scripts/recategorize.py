"""Recompute stored event categories.

This replaces five separate scripts - normalize_categories,
migrate_to_parent_categories, backfill_undefined_categories,
recategorize_from_venue_config and reclassify_generic_categories - which were
written one at a time as problems turned up and had grown to 737 lines of
largely the same code: load the events, work out better labels, print a diff,
write it behind --commit.

Only the middle step ever differed, so that is the only thing a pass defines
here. Everything else - reading, mapping to parents, computing subtags,
diffing, reporting, committing - happens once, in `run`.

The passes, and the problem each was written for:

  normalize   Settle casing and apply the current vocabulary. "music" from a
              venue scraper and "Music" from Ticketmaster are one category and
              should be one tile.
  venue       Realign with the category `CHICAGO_VENUES` declares, for when a
              declaration is corrected - the Chicago Council on Global Affairs
              was "Community", which put foreign-policy lectures next to ward
              meetings.
  undefined   Repair placeholder categories. Ticketmaster fills unknown
              classification levels with the literal string "Undefined", which
              went into the category and gave the UI a tile named after it.
  generic     Classify rows whose only label says nothing. Some sources send
              no category at all, so those events sat in "Other" having never
              been looked at rather than having been found hard.
  parents     Roll stored labels up to the parent taxonomy.

A pass returns the SOURCE labels for an event, or None to leave it alone. It
never touches the database and never thinks about parents or subtags.

Two rules hold across all of them, and the shared core is what guarantees it:

  A title rule always outranks a venue's category. A venue is mostly one kind
  of thing and not always - "SEWING FREAK" at Sleeping Village is Arts &
  Crafts - so a venue category is a fallback passed to `classify_all`, never
  an answer in its own right.

  Nothing is ever deleted, and only `category`, `categories` and
  `subcategories` are written.

Usage:
    python recategorize.py --pass venue              # dry run
    python recategorize.py --pass venue --commit
    python recategorize.py --pass all --commit
    python recategorize.py --pass generic --source timeoutchicago
"""

import argparse
import asyncio
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable

from sqlalchemy import select

sys.path.insert(0, "src")

from shared.categories import (
    GENERIC_CATEGORY,
    classify_all,
    informative_subtags,
    normalize_category,
    to_parents,
    unmapped_labels,
)
from shared.database import AsyncSessionLocal
from shared.database.models import EventModel

GENERIC_PARENT = "Other"
PLACEHOLDER = "undefined"

# Categories that say nothing, so they must not be learned as a venue's prior.
UNINFORMATIVE = {PLACEHOLDER, "other", GENERIC_CATEGORY.lower(), ""}

# Ticketmaster writes details as "Venue: Vic Theatre | Location: Chicago, IL".
_VENUE_IN_DETAILS = re.compile(r"Venue:\s*([^|]+)")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def source_labels(event: EventModel) -> list[str]:
    """Everything the row currently claims to be, primary first.

    `subcategories` is included, and must be: those are source labels too, and
    leaving them out made a re-run clear them. A row stored as Theater with
    the subtag "Theatre & Performing Arts" would be recomputed as Theater with
    no subtag, quietly discarding the finer label the taxonomy exists to keep.
    """
    labels = []
    for label in [event.category] + list(event.categories or []) + list(event.subcategories or []):
        if label and label not in labels:
            labels.append(label)
    return labels


def venue_of(event: EventModel) -> str:
    """The venue for an event, from its own column or out of its details."""
    if event.venue_name and event.venue_name.strip():
        return event.venue_name.strip()
    found = _VENUE_IN_DETAILS.search(event.details or "")
    return found.group(1).strip() if found else ""


def venue_key(name: str) -> str:
    """A venue name reduced to something two sources can agree on.

    Exact matching finds almost nothing: Ticketmaster says "Cole's Bar
    Chicago" and "Vic Theatre" where our own scrapers say "Cole's Bar" and
    "The Vic Theatre", and it appends a disambiguator to venues sharing a
    name ("Chop Shop - IL"). Theater/theatre is folded too.
    """
    key = (name or "").lower()
    key = re.sub(r"[^a-z0-9 ]+", "", key)
    key = re.sub(r"\btheatre\b", "theater", key)
    key = re.sub(r"^the\s+", "", key)
    for _ in range(2):
        key = re.sub(r"\s*\b(il|illinois|chicago)\s*$", "", key)
    return " ".join(key.split())


def is_placeholder(event: EventModel) -> bool:
    return any((label or "").strip().lower() == PLACEHOLDER for label in source_labels(event))


def only_generic(event: EventModel) -> bool:
    """No real category, only a placeholder."""
    return not [
        label for label in source_labels(event) if label not in (GENERIC_PARENT, GENERIC_CATEGORY)
    ]


class Context:
    """Everything the passes need that is expensive to work out once.

    Built lazily, so a pass that does not need venue priors does not pay for
    a full table scan to compute them.
    """

    def __init__(self, events: list[EventModel]):
        self.events = events
        self._priors: dict[str, str] | None = None
        self._declared: dict[str, str] | None = None

    @property
    def declared(self) -> dict[str, str]:
        """Each venue scraper's source name -> the category it declares."""
        if self._declared is None:
            from scrapers.venue.chicago_events_scraper import (
                CHICAGO_VENUES,
                venue_source_name,
            )

            self._declared = {}
            for configs in CHICAGO_VENUES.values():
                for config in configs:
                    label = normalize_category(config.category)
                    if label:
                        self._declared[venue_source_name(config)] = label
        return self._declared

    @property
    def priors(self) -> dict[str, str]:
        """The category events at each venue usually carry.

        From the config first - somebody chose those deliberately - then from
        what the rest of the database shows. Ticketmaster is excluded when
        tallying, because its rows are the ones being repaired and letting
        them vote would have "Undefined" elect itself.
        """
        if self._priors is None:
            tally: dict[str, Counter] = defaultdict(Counter)
            for event in self.events:
                if event.source == "ticketmaster":
                    continue
                venue = venue_of(event)
                category = (event.category or "").strip()
                if not venue or category.lower() in UNINFORMATIVE:
                    continue
                tally[venue_key(venue)][category] += 1
            self._priors = {v: c.most_common(1)[0][0] for v, c in tally.items()}

            from scrapers.venue.chicago_events_scraper import CHICAGO_VENUES

            for configs in CHICAGO_VENUES.values():
                for config in configs:
                    label = normalize_category(config.category)
                    if label and label.lower() not in UNINFORMATIVE:
                        self._priors[venue_key(config.name)] = label
        return self._priors

    def prior_for(self, event: EventModel) -> str:
        """The best default category for this event's venue.

        A prior, never an answer: it is handed to `classify_all` as the
        fallback, where any title rule outranks it.
        """
        venue = venue_of(event)
        found = self.priors.get(venue_key(venue))
        if not found and venue:
            # Weakest source: what the venue's own name says it is.
            # "Athenaeum Theatre" is a theater. Deliberately not passed to the
            # classifier as a hint - the concept matcher finds "Theatre" inside
            # "Vic Theatre" and files a live podcast as Theater.
            from shared.categories import classify_from_title

            guessed = classify_from_title(venue, GENERIC_CATEGORY)
            found = guessed if guessed != GENERIC_CATEGORY else None
        return found or GENERIC_CATEGORY


# --------------------------------------------------------------------------
# Passes: each returns the source labels for an event, or None to skip it
# --------------------------------------------------------------------------


def pass_normalize(event: EventModel, ctx: Context) -> list[str] | None:
    """Apply the current vocabulary to whatever the row already claims.

    Existing subtags are carried through rather than recomputed away: the
    classifier works from the title and the fallback, so it has no way to
    rediscover that Ticketmaster called this "Arts & Theatre".
    """
    fallback = normalize_category(event.category) or GENERIC_CATEGORY
    labels = classify_all(event.name, fallback)
    for subtag in event.subcategories or []:
        if subtag not in labels:
            labels.append(subtag)
    return labels


def pass_venue(event: EventModel, ctx: Context) -> list[str] | None:
    """Realign with the category the scraper config declares for this venue."""
    declared = ctx.declared.get(event.source)
    if not declared:
        return None
    return classify_all(event.name, declared)


def pass_undefined(event: EventModel, ctx: Context) -> list[str] | None:
    """Repair rows stored under a placeholder category."""
    if not is_placeholder(event):
        return None
    return classify_all(event.name, ctx.prior_for(event))


def pass_generic(event: EventModel, ctx: Context) -> list[str] | None:
    """Classify rows whose only label says nothing about what they are.

    No venue fallback: these come from sources that send no category, which is
    why they are here. The title has to carry it, and where the keyword rules
    are silent the model gets a turn - above its floor only, because below it
    the model is still confident and still wrong.
    """
    if not only_generic(event):
        return None
    labels = classify_all(event.name, GENERIC_CATEGORY)
    if [p for p in to_parents(labels) if p != GENERIC_PARENT]:
        return labels

    from shared.semantic_categories import semantic_category

    guess = semantic_category(event.name)
    return [guess[0]] if guess else None


def pass_parents(event: EventModel, ctx: Context) -> list[str] | None:
    """Roll whatever is stored up to the parent taxonomy, unchanged."""
    return source_labels(event) or None


PASSES: dict[str, Callable[[EventModel, Context], list[str] | None]] = {
    "normalize": pass_normalize,
    "venue": pass_venue,
    "undefined": pass_undefined,
    "generic": pass_generic,
    "parents": pass_parents,
}

# Order matters when running everything: settle the vocabulary, then the venue
# declarations, then repair placeholders, then give the leftovers to the
# model, and roll up last so nothing is left below the parent level.
ALL_PASSES = ["normalize", "venue", "undefined", "generic", "parents"]


# --------------------------------------------------------------------------
# The shared engine
# --------------------------------------------------------------------------


async def run(session, name: str, events: list[EventModel], ctx: Context, commit: bool) -> int:
    """Apply one pass: compute, diff, report, optionally write."""
    strategy = PASSES[name]
    changes = []
    for event in events:
        labels = strategy(event, ctx)
        if not labels:
            continue
        parents = to_parents(labels)
        if not parents:
            continue
        # A pass that can only produce the generic bucket has found nothing.
        if name == "generic" and parents == [GENERIC_PARENT]:
            continue
        finer = informative_subtags(labels, parents) or None
        if (
            event.category == parents[0]
            and (event.categories or []) == parents
            and (event.subcategories or None) == finer
        ):
            continue
        changes.append((event, parents, finer))

    print(f"\n=== {name}: {len(changes)} of {len(events)} rows to rewrite")
    if not changes:
        print("    nothing to do")
        return 0

    moves = Counter(f"{e.category or '-'} -> {p[0]}" for e, p, _ in changes if e.category != p[0])
    for move, count in moves.most_common(12):
        print(f"    {move[:56]:56} {count:5}")
    if not moves:
        print("    (secondary labels only, primaries unchanged)")

    for event, parents, finer in changes[:6]:
        print(f"    e.g. {event.name[:38]:40} -> {parents}{'  sub=' + str(finer) if finer else ''}")

    if commit:
        for event, parents, finer in changes:
            event.category = parents[0]
            event.categories = parents
            event.subcategories = finer
        await session.commit()
        print("    written")
    return len(changes)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pass",
        dest="which",
        default="all",
        choices=list(PASSES) + ["all"],
        help="which pass to run (default: all)",
    )
    parser.add_argument("--source", help="only events from this source")
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        query = select(EventModel)
        if args.source:
            query = query.filter(EventModel.source == args.source)
        events = list((await session.execute(query)).scalars().all())
        print(f"{len(events)} events" + (f" from {args.source}" if args.source else ""))

        # A label nobody has mapped would silently become its own parent and
        # grow a filter tile, so it is reported before anything is written.
        gaps = unmapped_labels(label for event in events for label in source_labels(event))
        if gaps:
            print(f"\nNOT IN THE TAXONOMY - add these to CATEGORY_TAXONOMY: {gaps}")

        ctx = Context(events)
        names = ALL_PASSES if args.which == "all" else [args.which]
        total = 0
        for name in names:
            total += await run(session, name, events, ctx, args.commit)

        print(
            f"\n{total} rows rewritten"
            if args.commit
            else f"\n{total} rows would change - DRY RUN, re-run with --commit"
        )


if __name__ == "__main__":
    asyncio.run(main())
