#!/usr/bin/env python3
"""
Fix Postgres sequence desync after a migration that copied rows with explicit id values.

When rows are inserted with explicit integer PKs (as a migration does), Postgres
sequences are never advanced. The next auto-generated id starts at 1 and immediately
collides with existing rows, causing UniqueViolationError on every INSERT.

Fix: for every table with a serial/bigserial PK, set the sequence to max(id) + 1.

Usage (from backend/):
    DATABASE_URL=postgresql+asyncpg://... uv run python scripts/fix_sequences.py

Or point at Railway Postgres:
    DATABASE_URL="$(railway variables get DATABASE_URL)" uv run python scripts/fix_sequences.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Tables that have an integer serial PK — adjust if your schema differs.
TABLES = [
    "chat_messages",
    "audit_logs",
    "metrics",
    "events",
    "neighborhoods",
    "venues",
    "geocode_cache",
]


async def fix_sequences(database_url: str):
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        for table in TABLES:
            # Check if the table has a sequence (serial PK)
            # pg_get_serial_sequence returns NULL for tables without one (e.g. UUID PKs)
            result = await conn.execute(
                text(f"SELECT pg_get_serial_sequence('{table}', 'id')")
            )
            seq_name = result.scalar()

            if not seq_name:
                print(f"  {table}: no serial sequence (UUID PK or no rows) — skipping")
                continue

            # Get the current max id
            result = await conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}"))
            max_id = result.scalar()

            # Get the current sequence value
            result = await conn.execute(text(f"SELECT last_value FROM {seq_name}"))
            current_seq = result.scalar()

            if max_id == 0:
                print(f"  {table}: empty table — skipping")
                continue

            if current_seq >= max_id:
                print(f"  {table}: sequence OK (last_value={current_seq}, max_id={max_id})")
                continue

            # Reset the sequence to max(id) so the next insert gets max(id)+1
            await conn.execute(
                text(f"SELECT setval('{seq_name}', {max_id})")
            )
            print(f"  {table}: ✅ FIXED — sequence reset from {current_seq} → {max_id} (next insert gets {max_id + 1})")

    await engine.dispose()


async def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL env var is required")
        sys.exit(1)

    # asyncpg driver required for Postgres
    if "postgresql" in db_url and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    if "postgres://" in db_url and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://")

    print(f"Connecting to: {db_url[:40]}...")
    print("Checking and fixing sequences:\n")
    await fix_sequences(db_url)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
