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
from .utils import to_naive_utc
from .models import Base, EventModel

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./data/events.db",
)

IS_SQLITE = "sqlite" in DATABASE_URL

# SQLite-only: how long a writer waits for the lock before giving up.
# Not needed for Postgres which handles concurrent writers natively.
BUSY_TIMEOUT_MS = 30_000

_connect_args = {"check_same_thread": False} if IS_SQLITE else {}

engine = create_async_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
)


def apply_sqlite_pragmas(target_engine) -> None:
    """Attach WAL + busy_timeout pragmas to a SQLite engine.

    No-op (and not called) when running against Postgres.
    Exported because scraper scripts build their own engines and need this too.
    """
    if "sqlite" not in str(target_engine.url):
        return

    @event.listens_for(target_engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
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
    "to_naive_utc",
    "upcoming_events_filter",
]
