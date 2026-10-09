#!/usr/bin/env python3
"""
One-time migration: SQLite → PostgreSQL.

Usage:
    uv run python scripts/migrate_sqlite_to_postgres.py \
        --sqlite data/events.db \
        --postgres postgresql+asyncpg://eventloop:eventloop@localhost:5433/eventloop

The script:
  1. Creates all tables in Postgres via SQLAlchemy (safe to re-run — uses
     create_all which is a no-op for existing tables).
  2. Reads every row from SQLite using the ORM.
  3. Bulk-inserts into Postgres in table-dependency order so FK constraints
     are never violated.
  4. Prints a row count summary at the end.

Tables migrated (in order):
    neighborhoods → venues → geocode_cache → events
    chat_threads  → chat_messages → audit_logs → metrics
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from the backend/ root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from shared.database.models import (
    AuditLogModel,
    Base,
    ChatMessageModel,
    ChatThreadModel,
    EventModel,
    GeocodeCacheModel,
    MetricsModel,
    NeighborhoodModel,
    VenueModel,
)

# Migration order must respect FK dependencies
MIGRATION_ORDER = [
    NeighborhoodModel,
    VenueModel,
    GeocodeCacheModel,
    EventModel,
    ChatThreadModel,
    ChatMessageModel,
    AuditLogModel,
    MetricsModel,
]

CHUNK_SIZE = 500  # rows per INSERT batch


def make_engine(url: str, **kwargs):
    is_sqlite = "sqlite" in url
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    return create_async_engine(url, connect_args=connect_args, echo=False, **kwargs)


def coerce_row(Model, columns, values: tuple) -> dict:
    """Convert a raw SQLite row to a dict with proper Python types.

    SQLite quirks handled:
    - Datetimes stored as strings → datetime objects (asyncpg requires them)
    - Columns declared as JSON type → parsed from string to Python object
    """
    import json
    from datetime import datetime
    from sqlalchemy import JSON

    # Build a set of column names that are JSON-typed in the model
    json_cols = {
        c.name
        for c in Model.__table__.columns
        if isinstance(c.type, JSON)
    }

    def coerce(col, val):
        if not isinstance(val, str):
            return val
        # Parse JSON columns (e.g. categories, subcategories)
        if col in json_cols:
            try:
                return json.loads(val)
            except (json.JSONDecodeError, ValueError):
                return val
        # Try ISO datetime formats SQLite uses
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        return val  # leave other strings as-is

    return {col: coerce(col, val) for col, val in zip(columns, values, strict=False)}


async def migrate(sqlite_url: str, pg_url: str) -> None:
    sqlite_engine = make_engine(sqlite_url)
    pg_engine = make_engine(pg_url)

    SqliteSession = sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    PgSession = sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

    # Step 1: create schema in Postgres
    print("Creating schema in Postgres...")
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  ✓ Schema ready")

    # Step 2: migrate each table — disable FK checks for the whole migration
    # so gaps in auto-increment IDs (deleted rows) don't cause violations.
    async with pg_engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = 'replica'"))
    print("  FK checks disabled for migration session")

    totals = {}
    for Model in MIGRATION_ORDER:
        table = Model.__tablename__
        print(f"\nMigrating {table}...")

        async with SqliteSession() as src:
            result = await src.execute(text(f"SELECT COUNT(*) FROM {table}"))
            total = result.scalar()
            print(f"  {total} rows to migrate")

            if total == 0:
                totals[table] = 0
                continue

            # Fetch all rows as dicts
            result = await src.execute(text(f"SELECT * FROM {table}"))
            columns = result.keys()
            rows = result.fetchall()
            dicts = [coerce_row(Model, columns, row) for row in rows]

        # Bulk insert in chunks into Postgres
        inserted = 0
        async with PgSession() as dst, dst.begin():
            for i in range(0, len(dicts), CHUNK_SIZE):
                chunk = dicts[i : i + CHUNK_SIZE]
                await dst.execute(Model.__table__.insert(), chunk)
                inserted += len(chunk)
                print(f"  inserted {inserted}/{total}...", end="\r")

        # For tables with integer serial PKs, sync the sequence so future
        # inserts don't collide with migrated rows. Skip UUID/string PKs.
        pk_cols = [c for c in Model.__table__.primary_key.columns]
        if pk_cols and pk_cols[0].autoincrement is True:
            pk_col = pk_cols[0]
            type_name = type(pk_col.type).__name__
            if type_name in ("Integer", "BigInteger"):
                pk_name = pk_col.name
                seq = f"{table}_{pk_name}_seq"
                async with pg_engine.begin() as conn:
                    await conn.execute(
                        text(
                            f"SELECT setval('{seq}',"
                            f" (SELECT MAX({pk_name})::bigint FROM {table}))"
                        )
                    )

        totals[table] = inserted
        print(f"  ✓ {inserted} rows migrated")

    # Step 3: summary
    print("\n" + "=" * 50)
    print("Migration complete!")
    print("=" * 50)
    for table, count in totals.items():
        print(f"  {table:30s} {count:>6} rows")

    # Re-enable FK checks
    async with pg_engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = 'origin'"))
    print("  FK checks re-enabled")

    await sqlite_engine.dispose()
    await pg_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default="data/events.db",
        help="Path to SQLite DB file (default: data/events.db)",
    )
    parser.add_argument(
        "--postgres",
        default="postgresql+asyncpg://eventloop:eventloop@localhost:5433/eventloop",
        help="PostgreSQL async URL",
    )
    args = parser.parse_args()

    sqlite_url = f"sqlite+aiosqlite:///{args.sqlite}"
    pg_url = args.postgres

    print(f"Source:      {sqlite_url}")
    print(f"Destination: {pg_url}")
    print()

    asyncio.run(migrate(sqlite_url, pg_url))


if __name__ == "__main__":
    main()
