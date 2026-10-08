"""Fill in missing event prices from each event's own page.

Why this is a fetch and not a pure migration: there is nothing in the database
to migrate from. Of 2,498 unpriced upcoming events, re-scanning every stored
`details` and `name` recovered zero prices, because almost every venue source
stores no details text at all and the venue listing pages the scrapers read do
not show a price. Reggies, United Center, Goodman, Old Town and Rosa's listing
pages contain no dollar amount anywhere.

What they do have is a link. Every row already stores `origination_url`, so
this walks the unpriced rows, fetches each event's own page once, and reads the
price off it with `shared.pricing` - schema.org `offers` where published, a
per-source pattern otherwise.

Safety:
  - Dry run unless `--commit` is passed. The dry run prints exactly what it
    would write.
  - Only ever fills a blank `cost`. An existing price is never overwritten,
    so re-running cannot degrade what is already there.
  - Only touches `cost`. Nothing else on the row is read or written.
  - Skips sources with no reliable pattern rather than guessing (see
    `shared.pricing` for which, and why each was rejected).

Usage:
    python backfill_event_costs.py                    # dry run, all sources
    python backfill_event_costs.py --commit           # write
    python backfill_event_costs.py --source do312     # one source
    python backfill_event_costs.py --limit 50         # first 50 rows
"""

import argparse
import asyncio
import logging
import sys
from collections import Counter, defaultdict

import httpx
from sqlalchemy import or_, select

sys.path.insert(0, "src")

from shared.database import AsyncSessionLocal, upcoming_events_filter
from shared.database.models import EventModel
from shared.pricing import SOURCE_PRICE_RULES, cost_from_page

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# A real browser's header set. Several venues return a bot page to anything
# that looks automated, and a bot page has no price on it.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Polite enough not to look like an attack, fast enough to finish.
CONCURRENCY = 10
TIMEOUT = 20


async def candidate_rows(session, source=None, limit=None):
    """Unpriced upcoming events that link to a page worth fetching."""
    query = (
        select(EventModel)
        .filter(upcoming_events_filter())
        .filter(or_(EventModel.cost.is_(None), EventModel.cost == ""))
        .filter(EventModel.origination_url.like("http%"))
    )
    if source:
        query = query.filter(EventModel.source == source)
    if limit:
        query = query.limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def read_price(client, event, semaphore, stats):
    """Fetch one event's page and read a price off it, or give up quietly."""
    async with semaphore:
        try:
            response = await client.get(
                event.origination_url,
                headers=HEADERS,
                follow_redirects=True,
                timeout=TIMEOUT,
            )
        except httpx.HTTPError, httpx.InvalidURL:
            stats["unreachable"] += 1
            return None
        if response.status_code != 200:
            stats[f"http {response.status_code}"] += 1
            return None
        stats["fetched"] += 1
        try:
            return cost_from_page(response.text, event.source)
        except Exception as exc:  # a malformed page must not stop the run
            logging.debug("parse failed for %s: %s", event.origination_url, exc)
            stats["parse failed"] += 1
            return None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit", action="store_true", help="write the prices (otherwise dry run)"
    )
    parser.add_argument("--source", help="only this source")
    parser.add_argument("--limit", type=int, help="only this many rows")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        events = await candidate_rows(session, args.source, args.limit)
        print(f"{len(events)} unpriced upcoming events with a link")

        # A source with neither structured data nor a pattern cannot be read,
        # and fetching thousands of its pages to learn that again is rude.
        # The Ticketmaster rows are the clearest case: its pages answer 401 to
        # anything but a browser, and the price already comes from its API.
        Counter(e.source for e in events)
        readable = [
            e for e in events if e.source in SOURCE_PRICE_RULES or _may_have_jsonld(e.source)
        ]
        skipped = len(events) - len(readable)
        if skipped:
            print(f"{skipped} skipped - no structured data and no pattern (see shared.pricing)")
        print(f"{len(readable)} to fetch\n")

        stats = Counter()
        found = {}
        semaphore = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient() as client:
            prices = await asyncio.gather(
                *(read_price(client, e, semaphore, stats) for e in readable)
            )

        per_source = defaultdict(Counter)
        for event, price in zip(readable, prices):
            if not price:
                continue
            found[event.id] = price
            per_source[event.source][price] += 1

        print(f"{'source':46} {'priced':>6}  values")
        for source in sorted(per_source, key=lambda s: -sum(per_source[s].values())):
            values = per_source[source].most_common(4)
            rendered = ", ".join(f"{v} x{n}" for v, n in values)
            print(f"{source[:46]:46} {sum(per_source[source].values()):6}  {rendered}")

        print(f"\nfetched {stats['fetched']}, priced {len(found)}")
        for reason, count in stats.most_common():
            if reason != "fetched":
                print(f"  {reason}: {count}")

        if not args.commit:
            print("\nDRY RUN - nothing written. Re-run with --commit.")
            return

        for event in readable:
            price = found.get(event.id)
            # Re-check emptiness: never overwrite a price, even if one arrived
            # between the read and the write.
            if price and not event.cost:
                event.cost = price
        await session.commit()
        print(f"\nWrote {len(found)} prices.")


def _may_have_jsonld(source: str) -> bool:
    """Whether a source is worth fetching for structured data alone.

    Ticketmaster is excluded outright: its pages answer 401 to anything that is
    not a browser, and its price already comes from the Discovery API, so there
    is nothing to gain. Everything else gets one attempt - a page either
    publishes schema.org offers or it does not, and one request settles it.
    """
    return source != "ticketmaster"


if __name__ == "__main__":
    asyncio.run(main())
