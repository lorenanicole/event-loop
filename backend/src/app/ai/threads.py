"""The lifecycle of a chat thread: open, closed, or quietly abandoned.

Threads were only ever created. 270 of them sat at status "active", including
ones last touched six days earlier, because the one transition that existed -
to "completed" - fires only when a conversation exhausts its budget, and
almost nobody does that. Everything else just stopped mid-sentence and stayed
open forever.

Three end states, which are worth telling apart when reading the table later:

    completed  ran out of turns or tokens; the assistant said goodbye
    closed     the person started a new chat, so this one is done
    abandoned  nothing happened for STALE_THREAD_HOURS; nobody came back

A thread with no turns at all is abandoned regardless of age: it was opened
and never used, usually by an off-topic question that never got as far as a
real exchange.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update

from shared.database.filters import STALE_THREAD_HOURS
from shared.database.models import ChatThreadModel

logger = logging.getLogger(__name__)

ACTIVE = "active"
COMPLETED = "completed"
CLOSED = "closed"
ABANDONED = "abandoned"


async def close_thread(session, thread_id: str, status: str = CLOSED) -> bool:
    """Mark one conversation finished. Returns whether anything changed."""
    result = await session.execute(
        update(ChatThreadModel)
        .where(ChatThreadModel.id == thread_id, ChatThreadModel.status == ACTIVE)
        .values(status=status, updated_at=datetime.utcnow())
    )
    await session.commit()
    return bool(result.rowcount)


async def sweep_stale_threads(session, hours: int = STALE_THREAD_HOURS) -> int:
    """Close conversations nobody came back to. Returns how many.

    Run at startup rather than on a timer: the process restarting is a
    natural moment to tidy, and a sweep that only runs while the app is up
    would never reach the threads left by the previous run.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await session.execute(
        update(ChatThreadModel)
        .where(
            ChatThreadModel.status == ACTIVE,
            or_(
                ChatThreadModel.updated_at < cutoff,
                # Opened and never used - no amount of waiting will help.
                ChatThreadModel.turn_count == 0,
            ),
        )
        .values(status=ABANDONED)
    )
    await session.commit()
    if result.rowcount:
        logger.info("Closed %d stale chat threads", result.rowcount)
    return result.rowcount or 0


async def count_by_status(session) -> dict[str, int]:
    """How many threads are in each state, for a health check."""
    from sqlalchemy import func

    rows = (
        await session.execute(
            select(ChatThreadModel.status, func.count()).group_by(ChatThreadModel.status)
        )
    ).all()
    return {status: count for status, count in rows}
