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


# After this many turns, a Haiku call generates a one-sentence summary that
# is stored on the thread and prepended to the history window on every
# subsequent turn. The window holds HISTORY_MESSAGES messages (6 by default,
# meaning 3 exchanges). Anything before turn 8 would otherwise be invisible
# from turn 9 onward.
SUMMARY_TRIGGER_TURN = 8


async def maybe_summarise_thread(session, thread_id: str, turn_count: int) -> str | None:
    """Generate and store a context summary when the thread exceeds the trigger.

    Returns the summary string if generated, or the existing one if already
    present, or None if the thread is too short to need one.

    Uses claude-haiku-4-5 (same as the intent classifier) — a one-sentence
    extraction is not a reasoning task and does not need Sonnet.
    """
    if turn_count < SUMMARY_TRIGGER_TURN:
        return None

    # Re-load the thread to get any existing summary
    from sqlalchemy import select as _select

    row = (
        await session.execute(_select(ChatThreadModel).where(ChatThreadModel.id == thread_id))
    ).scalar_one_or_none()

    if row is None:
        return None

    # Already summarised this session — return the cached value
    if row.context_summary:
        return row.context_summary

    # Load the messages we'll summarise (all of them, oldest first)
    from shared.database.models import ChatMessageModel

    msgs = (
        (
            await session.execute(
                _select(ChatMessageModel)
                .where(ChatMessageModel.thread_id == thread_id)
                .order_by(ChatMessageModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    if not msgs:
        return None

    transcript = "\n".join(f"{m.role.upper()}: {(m.content or '')[:300]}" for m in msgs)

    try:
        import os
        from pathlib import Path as _Path

        from dotenv import load_dotenv

        _env = next(
            (p / ".env" for p in _Path(__file__).resolve().parents if (p / ".env").is_file()), None
        )
        if _env:
            load_dotenv(_env)

        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=80,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarise this Chicago events chatbot conversation in ONE sentence "
                        "covering what the user wants (event type, neighborhood, date, budget). "
                        "Be specific. Output only the sentence.\n\n" + transcript
                    ),
                }
            ],
        )
        summary = response.content[0].text.strip()
        logger.info("Generated context summary for thread %s: %s", thread_id, summary)

        # Persist it
        await session.execute(
            update(ChatThreadModel)
            .where(ChatThreadModel.id == thread_id)
            .values(context_summary=summary)
        )
        await session.commit()
        return summary

    except Exception as exc:
        # A failed summary is not a failed conversation
        logger.warning("Context summary generation failed for %s: %s", thread_id, exc)
        return None


async def load_thread_history(
    db,
    thread_id: str,
    exclude_content: str,
    history_limit: int,
    system_prompt: str,
    persona_fn,
    date_fn,
) -> list:
    """Prior turns of this thread formatted as pydantic-ai messages.

    Extracted from ChatExecutor._load_history so that history assembly lives
    alongside the rest of the thread lifecycle code rather than buried in the
    executor's state machine.

    Parameters
    ----------
    db:               async SQLAlchemy session
    thread_id:        UUID of the thread to load
    exclude_content:  the current user message (excluded to avoid sending it twice)
    history_limit:    how many recent messages to load (HISTORY_MESSAGES constant)
    system_prompt:    the static system prompt string
    persona_fn:       callable(category) -> str — the dynamic voice prompt
    date_fn:          callable() -> str — the dynamic date grounding prompt
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        SystemPromptPart,
        TextPart,
        UserPromptPart,
    )

    from app.chat.persona import CHICAGO_FACTS
    from shared.categories import extract_category_concepts
    from shared.database.models import ChatMessageModel

    rows = (
        (
            await db.execute(
                select(ChatMessageModel)
                .where(ChatMessageModel.thread_id == thread_id)
                .order_by(ChatMessageModel.created_at.desc())
                .limit(history_limit + 1)
            )
        )
        .scalars()
        .all()
    )

    history = []
    for row in reversed(rows):
        content = (row.content or "").strip()
        if not content:
            continue
        if row.role == "user" and content == exclude_content.strip():
            continue
        if row.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=content)]))

    # A history must not start with a reply to nothing.
    while history and isinstance(history[0], ModelResponse):
        history.pop(0)

    if not history:
        return history

    # The system prompts have to be replayed into the history, because
    # pydantic-ai does not re-apply the agent's own once `message_history`
    # is given — it assumes the history already carries them.
    #
    # Measured: with a history the run's messages contained UserPromptPart
    # and TextPart and no SystemPromptPart, so every turn after the first was
    # losing the persona, the date and the brevity rules together.
    #
    # The dynamic prompts are evaluated now rather than stored, so a
    # conversation spanning midnight does not keep yesterday's date.
    categories = extract_category_concepts(exclude_content)
    category = next(
        (known for known in CHICAGO_FACTS if known.lower() in {v.lower() for v in categories}),
        None,
    )
    system_parts = [
        SystemPromptPart(content=system_prompt),
        SystemPromptPart(content=persona_fn(category)),
        SystemPromptPart(content=date_fn()),
    ]

    # Prepend context summary if the thread has one (generated after turn 8+).
    try:
        thread_row = (
            await db.execute(select(ChatThreadModel).where(ChatThreadModel.id == thread_id))
        ).scalar_one_or_none()
        if thread_row:
            summary = await maybe_summarise_thread(db, thread_id, thread_row.turn_count)
            if summary:
                system_parts.append(
                    SystemPromptPart(
                        content=f"Context from earlier in this conversation: {summary}"
                    )
                )
    except Exception as exc:  # noqa: BLE001 - history must not fail a turn
        logger.warning("Context summary lookup failed: %s", exc)

    history.insert(0, ModelRequest(parts=system_parts))
    return history


async def count_by_status(session) -> dict[str, int]:
    """How many threads are in each state, for a health check."""
    from sqlalchemy import func

    rows = (
        await session.execute(
            select(ChatThreadModel.status, func.count()).group_by(ChatThreadModel.status)
        )
    ).all()
    return {status: count for status, count in rows}
