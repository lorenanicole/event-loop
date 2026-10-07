import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

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
#
# The right fix is for the bulk writers to commit incrementally; until then
# this makes an interactive write wait rather than fail, which is the correct
# trade for a human sitting in front of a chat window.
BUSY_TIMEOUT_MS = 30_000

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    echo=False,
)


def apply_sqlite_pragmas(target_engine) -> None:
    """Attach the connection pragmas to any engine.

    Exported because the scripts build their own engines - the scraper is the
    other writer, so it is the one that most needs the busy timeout.
    """

    @event.listens_for(target_engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """Make SQLite survive a reader and a writer at the same time.

        The app has two writers by design - the API persisting events found by
        the chatbot, and the scraper folding in a run - plus every page load
        reading. In SQLite's default rollback-journal mode a writer blocks
        readers outright, so a scrape running in the background took the chat
        down with "database is locked".

        WAL fixes the common case: readers no longer block and are not blocked,
        and only writer-against-writer contends. `busy_timeout` covers what is
        left by making that writer wait rather than fail on the spot.

        Both are per-connection pragmas, so they are set on every connect
        rather than once at startup. WAL itself is persistent in the file, but
        setting it is idempotent and costs nothing.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            # Durable enough for this, and markedly faster under WAL: a commit
            # does not wait for a disk flush, so a crash can lose the last
            # transaction but cannot corrupt the database.
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


if IS_SQLITE:
    apply_sqlite_pragmas(engine)


# Async session factory
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
