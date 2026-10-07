"""Tests for a conversation ending.

Threads were only ever created. 270 sat at status "active", some days old,
because the one transition that existed - to "completed" - fires only when a
conversation exhausts its budget, and almost nobody does that.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.ai.threads import (
    ABANDONED,
    ACTIVE,
    CLOSED,
    close_thread,
    count_by_status,
    sweep_stale_threads,
)
from shared.database import AsyncSessionLocal
from shared.database.models import ChatThreadModel


async def make_thread(session, *, turns=1, age_hours=0, status=ACTIVE):
    thread = ChatThreadModel(
        status=status,
        turn_count=turns,
        updated_at=datetime.utcnow() - timedelta(hours=age_hours),
    )
    session.add(thread)
    await session.commit()
    return thread.id


async def status_of(session, thread_id):
    return await session.scalar(
        select(ChatThreadModel.status).where(ChatThreadModel.id == thread_id)
    )


@pytest.mark.asyncio
class TestClosing:
    async def test_closing_marks_the_thread(self):
        async with AsyncSessionLocal() as session:
            tid = await make_thread(session)
            assert await close_thread(session, tid) is True
            assert await status_of(session, tid) == CLOSED

    async def test_closing_twice_changes_nothing(self):
        """The UI closes on New Chat; a double click must not error."""
        async with AsyncSessionLocal() as session:
            tid = await make_thread(session)
            await close_thread(session, tid)
            assert await close_thread(session, tid) is False
            assert await status_of(session, tid) == CLOSED

    async def test_an_unknown_thread_is_not_an_error(self):
        """Nothing here is worth failing a page load over."""
        async with AsyncSessionLocal() as session:
            assert await close_thread(session, "no-such-thread") is False


@pytest.mark.asyncio
class TestSweep:
    async def test_a_stale_thread_is_abandoned(self):
        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, age_hours=48)
            await sweep_stale_threads(session)
            assert await status_of(session, tid) == ABANDONED

    async def test_a_fresh_thread_is_left_alone(self):
        """Somebody mid-conversation must not have it closed under them."""
        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, age_hours=0)
            await sweep_stale_threads(session)
            assert await status_of(session, tid) == ACTIVE
            await close_thread(session, tid)  # tidy up

    async def test_a_thread_with_no_turns_is_abandoned_whatever_its_age(self):
        """Opened and never used - usually an off-topic question that never
        reached a real exchange. No amount of waiting helps."""
        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, turns=0, age_hours=0)
            await sweep_stale_threads(session)
            assert await status_of(session, tid) == ABANDONED

    async def test_it_does_not_reopen_finished_threads(self):
        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, age_hours=48)
            await close_thread(session, tid)
            await sweep_stale_threads(session)
            assert await status_of(session, tid) == CLOSED

    async def test_counts_are_reported_by_status(self):
        async with AsyncSessionLocal() as session:
            counts = await count_by_status(session)
            assert isinstance(counts, dict)
            assert all(isinstance(v, int) for v in counts.values())
