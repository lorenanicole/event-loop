#!/usr/bin/env python
"""Scrape every configured venue and report what each one yields, right now.

Fixing venues one at a time and only re-testing the one just touched makes a
venue that never worked indistinguishable from one that regressed. This runs
the whole set, so "working" is a claim about the current state of all of them.

    python venue_health.py            # live check, every venue
    python venue_health.py --db       # what is in the database instead
"""

import asyncio
import sqlite3
import sys

sys.path.insert(0, "src")

import httpx

from scrapers.custom.venue.chicago_events_scraper import CHICAGO_VENUES
from scrapers.custom.venue.venue_scraper import VenueScraper

TIMEOUT = 120


def source_name(venue: str) -> str:
    return "chicago_venue_" + venue.lower().replace(" ", "_").replace("'", "s")


def from_db() -> None:
    db = sqlite3.connect("data/events.db")
    counts = dict(db.execute(
        "SELECT source, COUNT(*) FROM events WHERE date >= date('now') "
        "AND source LIKE 'chicago_venue_%' GROUP BY source"
    ).fetchall())
    live = dead = 0
    for hood, configs in sorted(CHICAGO_VENUES.items()):
        for config in configs:
            n = counts.get(source_name(config.name), 0)
            live, dead = (live + 1, dead) if n else (live, dead + 1)
            print(f"  {'ok ' if n else 'ZERO'} {n:>4}  {config.name[:30]:<31} {hood}")
    print(f"\n{live} with events, {dead} with none, of {live + dead}")


async def live_check() -> None:
    rows = []
    async with httpx.AsyncClient(timeout=25) as client:
        for hood, configs in sorted(CHICAGO_VENUES.items()):
            for config in configs:
                # A zero is retried once. Over a run of 70 venues, sites start
                # rate limiting and a working venue intermittently returns
                # nothing - which previously showed up here as a regression and
                # sent us chasing extractors that were fine. Only a venue that
                # returns nothing twice is reported as dark.
                events, dated, err = [], 0, ""
                for attempt in range(2):
                    if attempt:
                        await asyncio.sleep(5)
                    try:
                        events = await asyncio.wait_for(
                            VenueScraper(config).scrape(client), timeout=TIMEOUT
                        )
                        dated = sum(1 for e in events if e.date)
                        err = "" if dated else "empty"
                    except asyncio.TimeoutError:
                        events, dated, err = [], 0, "timeout"
                    except Exception as e:
                        events, dated, err = [], 0, type(e).__name__
                    if dated:
                        err = "" if attempt == 0 else "ok on retry"
                        break
                rows.append((hood, config.name, len(events), dated, err))
                h, n, total, dated, err = rows[-1]
                flag = "ok " if dated else "ZERO"
                print(f"  {flag} {dated:>4} dated / {total:>4} found  {n[:30]:<31} {h} {err}")

    working = sum(1 for r in rows if r[3])
    print(f"\n{working} of {len(rows)} venues produce dated events ({100 * working // len(rows)}%)")

    # Two very different failures, previously reported as one list. A venue
    # whose page loads but lists nothing may simply have nothing booked - an
    # open-air pavilion in winter, a gallery between shows - and needs no fix.
    # Only an unreachable or erroring venue is a problem to chase.
    empty = [r for r in rows if not r[3] and r[4] == "empty"]
    failing = [r for r in rows if not r[3] and r[4] != "empty"]

    if empty:
        print("\nreachable but listing no events (may be out of season):")
        for h, n, _, _, _ in empty:
            print(f"   {n[:32]:<33} {h}")
    if failing:
        print("\nfailing - unreachable, erroring, or blocked:")
        for h, n, _, _, err in failing:
            print(f"   {n[:32]:<33} {h:<18} {err}")


if __name__ == "__main__":
    if "--db" in sys.argv:
        from_db()
    else:
        asyncio.run(live_check())
