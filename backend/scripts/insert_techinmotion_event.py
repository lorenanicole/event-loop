#!/usr/bin/env python3
"""One-off: insert the Tech in Motion AI Data Governance event (Oct 22, 2026).

Run against local Postgres:
    uv run python scripts/insert_techinmotion_event.py

Run against Railway Postgres (supply DATABASE_URL):
    DATABASE_URL='postgresql+asyncpg://...' uv run python scripts/insert_techinmotion_event.py
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import EventModel

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://eventloop:eventloop@localhost:5433/eventloop",
)

EVENT = {
    "name": "Building Trust in AI: Data Governance, Risk, and Responsible Adoption",
    "date": datetime(2026, 10, 22, 18, 0),   # 6 PM
    "date_end": datetime(2026, 10, 22, 21, 0),  # 9 PM
    "category": "Tech",
    "categories": ["Tech", "Community"],
    "subcategories": ["Science & Tech", "Seminars"],
    "details": (
        "Join Tech in Motion Chicago as technology, data, and business leaders explore "
        "how organizations can responsibly scale AI by balancing innovation with governance, "
        "compliance, security, and data integrity.\n\n"
        "Topics: data quality & governance as AI enablers/blockers, navigating AI regulations, "
        "using AI responsibly with sensitive data, balancing innovation and accountability.\n\n"
        "Speakers: Anthony Rhem (CEO, A.J. Rhem & Associates), Jonathan Nagel (Head of AI "
        "Governance @ Vatascore), Josephine Wood (Director Data & AI @ SPR), Joshua Kohn "
        "(MD & EVP Strategy @ Quantum Rise).\n\n"
        "Agenda: 6:00 PM Networking, 6:50 PM Welcome, 7:00 PM Panel Discussion."
    ),
    "origination_url": "https://www.eventbrite.com/e/building-trust-in-ai-data-governance-risk-and-responsible-adoption-tickets-2002646716238",
    "source": "techinmotion",
    "cost": None,
    "age_range": None,
    "is_outdoor": "indoor",
    "address": "100 South Wacker Drive, Chicago, IL 60606",
    "venue_name": "100 S Wacker Dr",
    "locality": None,
    "latitude": 41.8824,
    "longitude": -87.6377,
    "neighborhood_id": None,  # Loop — will be None if not in our neighborhoods table
}


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Check if already exists
        existing = await session.scalar(
            select(EventModel).where(EventModel.origination_url == EVENT["origination_url"])
        )
        if existing:
            print(f"Event already exists (id={existing.id}), skipping.")
            await engine.dispose()
            return

        # Resolve neighborhood_id for the Loop
        from sqlalchemy import text
        loop_id = await session.scalar(
            text("SELECT id FROM neighborhoods WHERE name ILIKE '%loop%' LIMIT 1")
        )
        EVENT["neighborhood_id"] = loop_id

        event = EventModel(**EVENT)
        session.add(event)
        await session.commit()
        await session.refresh(event)
        print(f"✓ Inserted: '{event.name}' (id={event.id}, neighborhood_id={event.neighborhood_id})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
