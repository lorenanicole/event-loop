"""Scrape everything and fold the results in additively.

This is the entry point a scheduler runs. It covers both halves of the data -
the 76 venue scrapers and the external sources (Ticketmaster, do312, the Park
District, Broadway In Chicago) - which previously had no single caller at all,
so an automated run would have refreshed the venues and quietly let the
external sources go stale.

Unlike clean_rescrape.py this never deletes a row. It leans on
save_events_to_db's existing upsert: matched events are updated in place (and a
price is only ever filled in, never blanked), unmatched ones are inserted. A
venue that fails or gets bot-blocked on a given run therefore costs nothing -
its existing events simply stay as they are. That property is what makes it
safe to run unattended: a bad run is a no-op, not a loss.

Built for a scheduler as well as a terminal:

  - Only one run at a time. A scheduled run that collides with a manual one
    would have both writing to SQLite, which takes a single writer.
  - Every line is timestamped and flushed, so a log read after the fact says
    when each venue was reached and which ones were slow.
  - Exits non-zero when nothing at all was scraped, which is the only failure
    a scheduler can act on - individual venues failing is normal.

    python additive_scrape.py                  # everything
    python additive_scrape.py Metro Thalia     # only venues matching these names
    python additive_scrape.py --only external  # just the external sources
    python additive_scrape.py --log data/scrape.log
"""

import argparse
import asyncio
import errno
import logging
import os
import sys
import time
from datetime import datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, "src")

from scrapers.venue.chicago_events_scraper import (
    CHICAGO_VENUES,
    save_events_to_db,
)
from scrapers.venue.venue_scraper import VenueScraper
from shared.database import apply_sqlite_pragmas
from shared.database.models import EventModel
import contextlib

logging.basicConfig(level=logging.WARNING, format="%(message)s")

# httpx logs every request at INFO as a full URL, query string included, which
# is how an API key once reached a log file. A scheduled run writes to disk, so
# this matters more here than in a terminal.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Normalise DATABASE_URL to the asyncpg driver regardless of what Railway
# injects. Railway has been observed to inject postgresql+psycopg://, postgres://,
# and postgresql:// — none of which are installed. Only asyncpg is.
def _normalise_db_url(url: str) -> str:
    for prefix, replacement in [
        ("postgresql+psycopg2://", "postgresql+asyncpg://"),
        ("postgresql+psycopg://",  "postgresql+asyncpg://"),
        ("postgres://",            "postgresql+asyncpg://"),
        ("postgresql://",          "postgresql+asyncpg://"),
    ]:
        if url.startswith(prefix):
            return replacement + url[len(prefix):]
    return url

DB_URL = _normalise_db_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/events.db"))
LOCK_PATH = "data/.scrape.lock"
# Playwright venues are heavy; more than a handful at once thrashes the box and
# starts tripping timeouts that look like venue failures.
CONCURRENCY = 6
VENUE_TIMEOUT = 150


# The external sources, each a class exposing `scrape_and_save(session)`.
# Listed rather than discovered, so adding one is a deliberate edit and a
# half-finished scraper in the directory cannot start running on a schedule.
# bandsintown and eventbrite are deliberately absent - neither has ever put a
# row in the database.
EXTERNAL_SOURCES = [
    ("ticketmaster", "scrapers.sources.ticketmaster", "TicketmasterScraper"),
    ("do312", "scrapers.sources.do312", "DO312Scraper"),
    (
        "chicago_park_district",
        "scrapers.sources.chicago_park_district",
        "ChicagoParkDistrictScraper",
    ),
    ("broadway_in_chicago", "scrapers.sources.broadway_in_chicago", "BroadwayInChicagoScraper"),
    ("techinmotion", "scrapers.sources.techinmotion", "TechInMotionScraper"),
    ("mahjongsociety", "scrapers.sources.mahjongsociety", "MahjongSocietyScraper"),
    ("illinoisscience", "scrapers.sources.illinoisscience", "IllinoisScienceScraper"),
    ("cuddlebunny", "scrapers.sources.cuddlebunny", "CuddleBunnyScraper"),
]


def log(message=""):
    """Timestamped and flushed, because this output is usually read later."""
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"{stamp}  {message}" if message else "", flush=True)


class SingleRun:
    """Refuse to start if another scrape is already running.

    SQLite takes one writer, so a scheduled run colliding with a manual one
    means lock contention and partial saves. O_EXCL is the check and the claim
    in one step, which a separate exists()-then-create cannot be.

    A stale lock from a killed process is detected by signalling the recorded
    pid rather than by age - a long Playwright run is legitimately slow, so a
    timeout would either kill real runs or let dead locks linger.
    """

    def __init__(self, path=LOCK_PATH):
        self.path = path
        self.held = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if self._stale():
                os.unlink(self.path)
                return self.__enter__()
            raise SystemExit(f"another scrape is already running (lock: {self.path})") from exc
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self.held = True
        return self

    def _stale(self) -> bool:
        try:
            pid = int(open(self.path).read().strip())
        except (ValueError, OSError):
            return True  # unreadable lock is no lock
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)  # signal 0 only checks the process exists
        except ProcessLookupError:
            return True
        except PermissionError:
            return False  # alive and owned by someone else
        return False

    def __exit__(self, *exc):
        if self.held:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)


async def scrape_external(session_maker) -> int:
    """Run each external source, letting any one of them fail alone.

    Imported lazily and per source: Ticketmaster raises at construction when
    its API key is missing, and that must skip one source rather than abort
    the whole run.
    """
    import importlib

    saved_total = 0
    ran_ok = 0
    for name, module_path, class_name in EXTERNAL_SOURCES:
        started = time.monotonic()
        try:
            module = importlib.import_module(module_path)
            scraper = getattr(module, class_name)()
            async with session_maker() as session:
                saved = await scraper.scrape_and_save(session)
            saved_total += saved or 0
            ran_ok += 1
            log(
                f"{name[:34]:34} {saved or 0:4} new"
                f"                        {time.monotonic() - started:.0f}s"
            )
        except Exception as exc:
            log(f"{name[:34]:34}    - {type(exc).__name__}: {str(exc)[:48]}")
    # Return (saved, ran_ok) so main() can distinguish "up to date" from "all failed"
    return saved_total, ran_ok


async def scrape_one(config, hood, sem, client):
    async with sem:
        started = time.monotonic()
        # Retried once on a zero. Under concurrency, sites intermittently serve
        # an empty page, and because this scrape is additive a transient zero
        # is silent: the venue's events simply never get added. House of Blues
        # returned 35 alone and 0 in a parallel run, which is what prompted this.
        note = ""
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(5)
            try:
                events = await asyncio.wait_for(
                    VenueScraper(config).scrape(client), timeout=VENUE_TIMEOUT
                )
                note = f"{time.monotonic() - started:.0f}s" + (" (retry)" if attempt else "")
            except TimeoutError:
                events, note = [], f"timeout after {VENUE_TIMEOUT}s"
            except Exception as exc:
                events, note = [], f"{type(exc).__name__}: {exc}"
            if events:
                break
        return hood, config, events, note


async def snapshot(session_maker):
    async with session_maker() as session:
        total = await session.scalar(
            select(func.count()).select_from(EventModel).where(EventModel.date >= func.date("now"))
        )
        priced = await session.scalar(
            select(func.count())
            .select_from(EventModel)
            .where((EventModel.date >= func.date("now")) & EventModel.cost.isnot(None))
        )
    return total, priced


async def main(args) -> int:
    """Returns a process exit code: 0 if anything was scraped, 1 if nothing was."""
    wanted = [a.lower() for a in args.venues]
    do_venues = args.only in (None, "venues")
    do_external = args.only in (None, "external") and not wanted

    targets = (
        [
            (config, hood)
            for hood, configs in CHICAGO_VENUES.items()
            for config in configs
            if not wanted or any(w in config.name.lower() for w in wanted)
        ]
        if do_venues
        else []
    )

    if do_venues and wanted and not targets:
        log(f"no venue matches {args.venues}")
        return 1

    engine = create_async_engine(DB_URL, echo=False)
    # The same WAL and busy-timeout pragmas the API uses. Without them this
    # process is the one that takes the chat down: SQLite allows a single
    # writer, and a scrape saving 76 venues holds the lock in bursts.
    apply_sqlite_pragmas(engine)
    session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        before = await snapshot(session_maker)
        log(f"before: {before[0]} upcoming, {before[1]} priced")

        scraped_any = False

        if targets:
            log(f"scraping {len(targets)} venues, {CONCURRENCY} at a time")
            log()
            sem = asyncio.Semaphore(CONCURRENCY)
            async with httpx.AsyncClient(follow_redirects=True) as client:
                tasks = [scrape_one(c, h, sem, client) for c, h in targets]
                results = []
                for coro in asyncio.as_completed(tasks):
                    hood, config, events, note = await coro
                    dated = sum(1 for e in events if e.date)
                    priced = sum(1 for e in events if e.cost)
                    log(
                        f"{config.name[:34]:34} {len(events):4} events  "
                        f"{dated:4} dated  {priced:4} priced   {note}"
                    )
                    results.append((hood, config, events))

            # Saved serially: SQLite takes one writer, and save_events_to_db
            # queries for existing rows as it goes.
            for hood, config, events in results:
                if events:
                    await save_events_to_db(session_maker, config, events, neighborhood=hood)
            scraped_any = scraped_any or any(e for _, _, e in results)

        if do_external:
            log()
            log(f"external sources ({len(EXTERNAL_SOURCES)})")
            log()
            saved, ran_ok = await scrape_external(session_maker)
            # A run is successful if at least one source ran without an exception,
            # even if it returned 0 new events (the DB is simply up to date).
            scraped_any = scraped_any or ran_ok > 0

        after = await snapshot(session_maker)
        log()
        log(
            f"after: {after[0]} upcoming ({after[0] - before[0]:+d}), "
            f"{after[1]} priced ({after[1] - before[1]:+d})"
        )
        log("Additive scrape complete")
    finally:
        await engine.dispose()

    # A run where every single source failed is the one thing a scheduler
    # should notice. Individual venues failing is routine and additive, so it
    # is not an error.
    if not scraped_any:
        log("every source failed — no scraper completed without an exception")
        return 1
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("venues", nargs="*", help="only venues whose name contains one of these")
    parser.add_argument(
        "--only", choices=["venues", "external"], help="scrape just one half (default: both)"
    )
    parser.add_argument(
        "--log", metavar="PATH", help="append output to this file as well as stdout"
    )
    args = parser.parse_args()

    if args.log:
        os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
        # Line-buffered, so a log tailed during a run is current rather than
        # arriving in 8KB bursts.
        stream = open(args.log, "a", buffering=1)
        sys.stdout = _Tee(sys.__stdout__, stream)
        log(f"=== run started {datetime.now():%Y-%m-%d %H:%M:%S} ===")

    with SingleRun():
        return asyncio.run(main(args))


class _Tee:
    """Write to the terminal and the log file at once."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


if __name__ == "__main__":
    sys.exit(cli())
