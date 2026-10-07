"""Tests for background work surviving the request that started it.

The event loop keeps only a weak reference to a task, so a bare
`asyncio.create_task(...)` can be garbage collected mid-await - silently.
Every event found by an online search was lost this way: searches kept
succeeding while the newest persisted row stayed a day old.
"""

import asyncio
import gc

import pytest

from app.ai.chatbot import _background_tasks, _spawn_background


@pytest.mark.asyncio
class TestSpawnBackground:
    async def test_the_task_survives_a_garbage_collection(self):
        """The regression: nothing held a reference, so the task was collected
        before it finished and its work never happened."""
        done = asyncio.Event()

        async def work():
            await asyncio.sleep(0.05)
            done.set()

        _spawn_background(work())
        # Drop any local reference the caller might have had, then force a
        # collection - this is what used to kill the task.
        gc.collect()
        await asyncio.wait_for(done.wait(), timeout=2)
        assert done.is_set()

    async def test_the_task_is_tracked_while_in_flight(self):
        async def work():
            await asyncio.sleep(0.05)

        task = _spawn_background(work())
        assert task in _background_tasks
        await task

    async def test_the_task_is_released_once_finished(self):
        """Tracking must not become a leak that grows for the process's life."""

        async def work():
            return None

        task = _spawn_background(work())
        await task
        await asyncio.sleep(0)  # let the done callback run
        assert task not in _background_tasks

    async def test_a_failure_is_logged_rather_than_swallowed(self, monkeypatch):
        """A bare task holds its exception and never reports it, so a failure
        to persist looked exactly like having nothing to persist."""
        from app.ai import chatbot

        logged = []
        monkeypatch.setattr(
            chatbot.logger,
            "error",
            lambda msg, *a, **k: logged.append(str(msg) % a if a else str(msg)),
        )

        async def boom():
            raise ValueError("persistence exploded")

        task = _spawn_background(boom())
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)
        assert any("ValueError" in line for line in logged), logged
        assert any("persistence exploded" in line for line in logged), logged

    async def test_a_failure_does_not_leak_the_task(self, monkeypatch):
        from app.ai import chatbot

        monkeypatch.setattr(chatbot.logger, "error", lambda *a, **k: None)

        async def boom():
            raise ValueError("x")

        task = _spawn_background(boom())
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)
        assert task not in _background_tasks
