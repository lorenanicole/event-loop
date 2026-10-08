"""
shared.database — engine, session factory, table init, and query helpers.

Everything that was in database.py is now here directly; there is no inner
database/database.py module. All external imports use `shared.database` (this
package), so the extra file was only providing an indirection layer with no
callers outside the package itself.
"""

import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .filters import feed_order, start_of_day, upcoming_events_filter
from .models import Base, EventModel

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/events.db")

IS_SQLITE = "sqlite" in DATABASE_URL

# How long a writer waits for the lock before giving up.
#
# The default is to fail instantly, which surfaced as "database is locked" in
# the API and a failed reply in the chat window whenever a scrape was running.
# WAL (below) fixes readers; this covers writer-against-writer, which SQLite
# serializes no matter what.
#
# 30s rather than 10s, measured: at 10s, eight `INSERT INTO chat_threads` -
# the first write of a chat turn - still failed under six concurrent chats
# during an external scrape. Each external source commits once after adding
# several hundred events, so that single transaction can hold the write lock
# for a long stretch while its existence checks run.
BUSY_TIMEOUT_MS = 30_000

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    echo=False,
)


def apply_sqlite_pragmas(target_engine) -> None:
    """Attach the connection pragmas to any engine.

    Exported because the scripts build their own engines — the scraper is the
    other writer, so it is the one that most needs the busy timeout.
    """

    @event.listens_for(target_engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """Make SQLite survive a reader and a writer at the same time.

        WAL fixes the common case: readers no longer block and are not blocked,
        and only writer-against-writer contends. `busy_timeout` covers what is
        left by making that writer wait rather than fail on the spot.

        Both are per-connection pragmas, so they are set on every connect
        rather than once at startup.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


if IS_SQLITE:
    apply_sqlite_pragmas(engine)


AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
)


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Dependency: get async database session for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


__all__ = [
    "AsyncSessionLocal",
    "Base",
    "EventModel",
    "apply_sqlite_pragmas",
    "feed_order",
    "get_db",
    "init_db",
    "start_of_day",
    "upcoming_events_filter",
]
