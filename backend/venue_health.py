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
                try:
                    events = await asyncio.wait_for(
                        VenueScraper(config).scrape(client), timeout=TIMEOUT
                    )
                    dated = sum(1 for e in events if e.date)
                    rows.append((hood, config.name, len(events), dated, ""))
                except asyncio.TimeoutError:
                    rows.append((hood, config.name, 0, 0, "timeout"))
                except Exception as e:
                    rows.append((hood, config.name, 0, 0, type(e).__name__))
                h, n, total, dated, err = rows[-1]
                flag = "ok " if dated else "ZERO"
                print(f"  {flag} {dated:>4} dated / {total:>4} found  {n[:30]:<31} {h} {err}")

    working = sum(1 for r in rows if r[3])
    print(f"\n{working} of {len(rows)} venues produce dated events ({100 * working // len(rows)}%)")
    broken = [r for r in rows if not r[3]]
    if broken:
        print("\nproducing nothing:")
        for h, n, _, _, err in broken:
            print(f"   {n[:32]:<33} {h:<18} {err}")


if __name__ == "__main__":
    if "--db" in sys.argv:
        from_db()
    else:
        asyncio.run(live_check())
