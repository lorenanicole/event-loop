"""Tests for a conversation ending.

Threads were only ever created. 270 sat at status "active", some days old,
because the one transition that existed - to "completed" - fires only when a
conversation exhausts its budget, and almost nobody does that.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.chat.threads import (
    ABANDONED,
    ACTIVE,
    CLOSED,
    SUMMARY_TRIGGER_TURN,
    close_thread,
    count_by_status,
    maybe_summarise_thread,
    sweep_stale_threads,
)
from shared.database import AsyncSessionLocal
from shared.database.models import ChatThreadModel


async def make_thread(session, *, turns=1, age_hours=0, status=ACTIVE):
    thread = ChatThreadModel(
        status=status,
        turn_count=turns,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=age_hours),
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


class TestContextSummary:
    """maybe_summarise_thread() must not fire before the trigger turn,
    must return None gracefully when the API is unavailable, and must
    return the cached summary on subsequent calls without re-calling the API."""

    @pytest.mark.asyncio
    async def test_short_thread_returns_none_without_api_call(self, monkeypatch):
        """Threads under SUMMARY_TRIGGER_TURN should return None immediately."""
        called = []

        async def fake_api(*a, **kw):
            called.append(True)

        monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: None)

        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, turns=SUMMARY_TRIGGER_TURN - 1)
            result = await maybe_summarise_thread(session, tid, SUMMARY_TRIGGER_TURN - 1)

        assert result is None
        assert called == [], "API must not be called for short threads"

    @pytest.mark.asyncio
    async def test_api_failure_returns_none_without_raising(self, monkeypatch):
        """A network error or missing key must not crash the conversation."""

        class BrokenClient:
            async def messages_create(self, *a, **kw):
                raise RuntimeError("network down")

        class BrokenAnthropic:
            def __init__(self, **kw):
                pass

            @property
            def messages(self):
                return BrokenClient()

        monkeypatch.setattr("anthropic.AsyncAnthropic", BrokenAnthropic)

        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, turns=SUMMARY_TRIGGER_TURN + 2)
            # Should not raise
            result = await maybe_summarise_thread(session, tid, SUMMARY_TRIGGER_TURN + 2)

        assert result is None

    @pytest.mark.asyncio
    async def test_cached_summary_returned_without_second_api_call(self, monkeypatch):
        """Once stored, context_summary is returned without another API call."""
        from sqlalchemy import update

        from shared.database.models import ChatThreadModel

        api_calls = []

        async with AsyncSessionLocal() as session:
            tid = await make_thread(session, turns=SUMMARY_TRIGGER_TURN + 2)
            # Pre-populate the summary
            await session.execute(
                update(ChatThreadModel)
                .where(ChatThreadModel.id == tid)
                .values(context_summary="User wants free jazz in Pilsen this weekend.")
            )
            await session.commit()

            result = await maybe_summarise_thread(session, tid, SUMMARY_TRIGGER_TURN + 2)

        assert result == "User wants free jazz in Pilsen this weekend."
        assert api_calls == [], "Cached summary must not trigger another API call"
