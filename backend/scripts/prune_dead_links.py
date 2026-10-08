"""Remove events whose own page is gone.

Venues cancel and rename shows, and because the scrape is additive - it adds
and updates but never deletes - our row survives with a link that now 404s.
Four of twelve sampled Cole's Bar links were dead this way.

The safe signal is the 404 itself. Deleting events that merely stopped
appearing in a scrape is not safe: venues intermittently return nothing at
all (bot-blocking, timeouts), so absence cannot be told apart from a bad run -
which is why the scrape is additive in the first place. A 404 is different. It
is the venue's own server saying the page is gone.

Deliberately narrow about what counts as gone:

  404, 410   the page is gone. Prune.
  401/403/406  bot protection. These serve fine in a browser - Ticketmaster,
               Songkick and several venues reject a scripted request - so they
               are never pruned.
  5xx, timeouts, DNS failures  the site is having a bad day, or we are being
               throttled. Never pruned.

Each URL is confirmed twice before anything is deleted, because a single 404
can be a transient edge or a rate limiter in disguise.

    python prune_dead_links.py --dry-run          # report only
    python prune_dead_links.py                    # delete confirmed-dead rows
    python prune_dead_links.py --source chicago_venue_coless_bar
"""

import asyncio
import sqlite3
import sys

import httpx

DB_PATH = "data/events.db"
UPCOMING = "(date_end >= date('now') OR (date_end IS NULL AND date >= date('now')))"

# Only these mean "this page is gone". Everything else is a reason to leave
# the row alone.
GONE = {404, 410}
CONCURRENCY = 6
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


async def status(client: httpx.AsyncClient, url: str) -> int | str:
    """The status of one URL, following redirects."""
    try:
        response = await client.head(url, timeout=20, follow_redirects=True)
        # Some servers refuse HEAD but answer GET.
        if response.status_code in (401, 403, 405, 406):
            response = await client.get(url, timeout=20, follow_redirects=True)
        return response.status_code
    except Exception as exc:
        return type(exc).__name__


async def confirm_gone(client, url: str, sem: asyncio.Semaphore) -> bool:
    """Whether a URL is gone, checked twice to rule out a transient 404."""
    async with sem:
        first = await status(client, url)
        if first not in GONE:
            return False
        await asyncio.sleep(2)
        return await status(client, url) in GONE


async def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = sqlite3.connect(DB_PATH)

    query = f"""SELECT id, source, origination_url, name FROM events
                WHERE {UPCOMING} AND origination_url LIKE 'http%'"""
    params: tuple = ()
    if "--source" in sys.argv:
        query += " AND source = ?"
        params = (sys.argv[sys.argv.index("--source") + 1],)
    rows = db.execute(query, params).fetchall()
    print(f"checking {len(rows)} upcoming events\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=HEADERS) as client:
        verdicts = await asyncio.gather(*(confirm_gone(client, url, sem) for _, _, url, _ in rows))

    dead = [row for row, gone in zip(rows, verdicts, strict=False) if gone]
    print(f"{len(dead)} events whose page is gone (confirmed twice):")
    for _, source, url, name in dead:
        print(f"   {source[:34]:36} {name[:34]:36} {url[-44:]}")

    if dead and not dry_run:
        db.executemany("DELETE FROM events WHERE id = ?", [(row[0],) for row in dead])
        db.commit()
        print(f"\ndeleted {len(dead)} rows")
    elif dead:
        print("\n(dry run - nothing deleted)")
    else:
        print("\nnothing to prune")

    (remaining,) = db.execute(f"SELECT COUNT(*) FROM events WHERE {UPCOMING}").fetchone()
    print(f"upcoming events remaining: {remaining}")


if __name__ == "__main__":
    asyncio.run(main())
