"""Scrape every venue in parallel and fold the results in additively.

Unlike clean_rescrape.py this never deletes a row. It leans on
save_events_to_db's existing upsert: matched events are updated in place (and a
price is only ever filled in, never blanked), unmatched ones are inserted. A
venue that fails or gets bot-blocked on a given run therefore costs nothing -
its existing events simply stay as they are.

    python additive_scrape.py            # all venues
    python additive_scrape.py Metro Thalia   # only venues matching these names
"""

import asyncio
import logging
import sys
import time

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, "src")

from scrapers.custom.venue.chicago_events_scraper import (  # noqa: E402
    CHICAGO_VENUES,
    save_events_to_db,
)
from scrapers.custom.venue.venue_scraper import VenueScraper  # noqa: E402
from shared.database.models import EventModel  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")

DB_URL = "sqlite+aiosqlite:///data/events.db"
# Playwright venues are heavy; more than a handful at once thrashes the box and
# starts tripping timeouts that look like venue failures.
CONCURRENCY = 6
VENUE_TIMEOUT = 150


async def scrape_one(config, hood, sem, client):
    async with sem:
        started = time.monotonic()
        try:
            events = await asyncio.wait_for(
                VenueScraper(config).scrape(client), timeout=VENUE_TIMEOUT
            )
        except asyncio.TimeoutError:
            return hood, config, [], f"timeout after {VENUE_TIMEOUT}s"
        except Exception as exc:
            return hood, config, [], f"{type(exc).__name__}: {exc}"
        return hood, config, events, f"{time.monotonic() - started:.0f}s"


async def snapshot(session_maker):
    async with session_maker() as session:
        total = await session.scalar(
            select(func.count()).select_from(EventModel).where(EventModel.date >= func.date("now"))
        )
        priced = await session.scalar(
            select(func.count()).select_from(EventModel).where(
                (EventModel.date >= func.date("now")) & EventModel.cost.isnot(None)
            )
        )
    return total, priced


async def main():
    wanted = [a.lower() for a in sys.argv[1:]]
    targets = [
        (config, hood)
        for hood, configs in CHICAGO_VENUES.items()
        for config in configs
        if not wanted or any(w in config.name.lower() for w in wanted)
    ]

    engine = create_async_engine(DB_URL, echo=False)
    session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    before = await snapshot(session_maker)
    print(f"before: {before[0]} upcoming, {before[1]} priced")
    print(f"scraping {len(targets)} venues, {CONCURRENCY} at a time\n", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [scrape_one(c, h, sem, client) for c, h in targets]
        results = []
        for coro in asyncio.as_completed(tasks):
            hood, config, events, note = await coro
            dated = sum(1 for e in events if e.date)
            priced = sum(1 for e in events if e.cost)
            print(
                f"{config.name[:34]:34} {len(events):4} events  {dated:4} dated  "
                f"{priced:4} priced   {note}",
                flush=True,
            )
            results.append((hood, config, events))

    # Saved serially: SQLite takes one writer, and save_events_to_db queries for
    # existing rows as it goes.
    for hood, config, events in results:
        if events:
            await save_events_to_db(session_maker, config, events, neighborhood=hood)

    after = await snapshot(session_maker)
    print(f"\nafter: {after[0]} upcoming ({after[0] - before[0]:+d}), "
          f"{after[1]} priced ({after[1] - before[1]:+d})")
    print("Additive scrape complete")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
