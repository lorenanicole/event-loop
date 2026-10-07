#!/usr/bin/env python
"""Diagnostics: are the venues still producing events, and do the links work?

Replaces venue_health.py and link_health.py, which were two files doing the
same job - fetch something, compare it to what is stored, print what looks
wrong - and shared their argument parsing, their database path and their
"pretend to be a browser" header by copying it.

Neither subcommand writes anything. They are reports.

    python health.py venues           # scrape every configured venue, live
    python health.py venues --db      # what is in the database instead
    python health.py links            # one sampled link per source
    python health.py links --source chicago_venue_coless_bar

Read `links` output with some care: 401, 403 and 406 are usually bot
protection rather than a dead link - Ticketmaster, Songkick and several
venues reject a scripted request but serve the same URL fine in a browser. A
404 or a DNS failure is the real signal.
"""

import argparse
import asyncio
import logging
import sqlite3
import sys

# httpx logs every request at INFO as a full URL, which buries the report
# under its own traffic - and is how the SerpAPI key once reached a log file.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

sys.path.insert(0, "src")

import httpx  # noqa: E402

from scrapers.custom.venue.chicago_events_scraper import (  # noqa: E402
    CHICAGO_VENUES,
    venue_source_name,
)
from scrapers.custom.venue.venue_scraper import VenueScraper  # noqa: E402

DB = "data/events.db"
SCRAPE_TIMEOUT = 120
BROWSER_UA = {"User-Agent": "Mozilla/5.0"}

# Events that have not finished yet - the only ones worth checking.
UPCOMING = "(date_end >= date('now') OR (date_end IS NULL AND date >= date('now')))"


# --------------------------------------------------------------------------
# venues
# --------------------------------------------------------------------------

def venues_from_db() -> None:
    """What each configured venue has actually stored."""
    db = sqlite3.connect(DB)
    counts = dict(db.execute(
        "SELECT source, COUNT(*) FROM events WHERE date >= date('now') "
        "AND source LIKE 'chicago_venue_%' GROUP BY source"
    ).fetchall())
    live = dead = 0
    for hood, configs in sorted(CHICAGO_VENUES.items()):
        for config in configs:
            n = counts.get(venue_source_name(config), 0)
            live, dead = (live + 1, dead) if n else (live, dead + 1)
            print(f"  {'ok ' if n else 'ZERO'} {n:>4}  {config.name[:30]:<31} {hood}")
    print(f"\n{live} with events, {dead} with none, of {live + dead}")


async def venues_live() -> None:
    """Scrape every venue now, so "working" is a claim about all of them.

    Fixing venues one at a time and only re-testing the one just touched makes
    a venue that never worked indistinguishable from one that regressed.
    """
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
                            VenueScraper(config).scrape(client), timeout=SCRAPE_TIMEOUT
                        )
                        dated = sum(1 for e in events if e.date)
                        err = "" if dated else "empty"
                    except asyncio.TimeoutError:
                        events, dated, err = [], 0, "timeout"
                    except Exception as e:  # noqa: BLE001 - reporting every failure
                        events, dated, err = [], 0, type(e).__name__
                    if dated:
                        err = "" if attempt == 0 else "ok on retry"
                        break
                rows.append((hood, config.name, len(events), dated, err))
                h, n, total, dated, err = rows[-1]
                flag = "ok " if dated else "ZERO"
                print(f"  {flag} {dated:>4} dated / {total:>4} found  "
                      f"{n[:30]:<31} {h} {err}")

    working = sum(1 for r in rows if r[3])
    print(f"\n{working} of {len(rows)} venues produce dated events "
          f"({100 * working // len(rows)}%)")

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


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------

async def check_link(client, source, url, sem):
    async with sem:
        try:
            r = await client.head(url, timeout=20, follow_redirects=True)
            code = r.status_code
            if code in (403, 405):  # some servers reject HEAD
                r = await client.get(url, timeout=20, follow_redirects=True)
                code = r.status_code
        except Exception as exc:  # noqa: BLE001 - the failure is the result
            return source, url, f"ERR {type(exc).__name__}"
        return source, url, str(code)


async def links(source: str | None) -> None:
    """Check whether stored event links resolve.

    Every event card has a "Learn more" link, and nothing checked that any of
    them worked: the Den Theatre config carried a website_url whose domain did
    not exist, so all 29 of its links were dead and nobody would have known
    without clicking one.
    """
    db = sqlite3.connect(DB)
    if source:
        rows = db.execute(
            f"SELECT source, origination_url FROM events "
            f"WHERE {UPCOMING} AND source = ? AND origination_url LIKE 'http%'",
            (source,),
        ).fetchall()
    else:
        # One link per source, because the point is to find a source whose
        # links are all broken, not to crawl 3,000 URLs.
        rows = db.execute(
            f"SELECT source, MIN(origination_url) FROM events "
            f"WHERE {UPCOMING} AND origination_url LIKE 'http%' "
            f"GROUP BY source ORDER BY source"
        ).fetchall()

    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers=BROWSER_UA) as client:
        results = await asyncio.gather(
            *(check_link(client, s, u, sem) for s, u in rows)
        )
    bad = [r for r in results if not (r[2].startswith("2") or r[2].startswith("3"))]
    print(f"checked {len(results)} links, {len(bad)} look broken\n")
    for s, u, code in sorted(bad, key=lambda r: r[0]):
        print(f"  {code:18} {s[:36]:38} {u[:58]}")
    print(f"\n{len(results) - len(bad)} returned a usable link.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="what", required=True)

    venues = sub.add_parser("venues", help="are the venue scrapers producing events")
    venues.add_argument("--db", action="store_true",
                        help="report what is stored instead of scraping live")

    link = sub.add_parser("links", help="do the stored event links resolve")
    link.add_argument("--source", help="check every link from this source")

    args = parser.parse_args()
    if args.what == "venues":
        venues_from_db() if args.db else asyncio.run(venues_live())
    else:
        asyncio.run(links(args.source))


if __name__ == "__main__":
    main()
