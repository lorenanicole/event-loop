"""
SerpAPI web search tool and event persistence pipeline.

Extracted from chatbot.py. Everything here is about calling the live web
and persisting what comes back — distinct from the local DB search logic.

Three responsibilities, all tightly coupled:
1. EventResult — typed shape of a Google event card
2. search_google_events — the agent tool that calls SerpAPI
3. _persist_events_to_db / _spawn_background — background persistence
"""

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext

from app.chat.chatbot import SearchPolicy
from app.chat.search_query import extract_keywords as _extract_keywords
from app.logging import get_logger
from shared.categories import classify_all

_env_path = next(
    (p / ".env" for p in Path(__file__).resolve().parents if (p / ".env").is_file()), None
)
if _env_path:
    load_dotenv(_env_path)

logger = get_logger(__name__)
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
SERPAPI_TIMEOUT = 12  # see chatbot.py for measurement rationale


class EventResult(BaseModel):
    """One event card as returned by the Google Events API via SerpAPI."""

    title: str
    date: str | None = None
    location: str | None = None
    venue: str | None = None
    url: str | None = None
    type_hint: str | None = None
    source: str
    model_config = ConfigDict(extra="ignore")

    @property
    def classifier_text(self) -> str:
        return " ".join(part for part in (self.title, self.type_hint) if part)


_NOT_AN_EVENT = (
    re.compile(
        r"\s[|\u2013\u2014]\s.*(department|library|university|college"
        r"|museum|center|centre|institute)",
        re.IGNORECASE,
    ),
    re.compile(r"\bsearch results\b|\bgoogle search\b", re.IGNORECASE),
    re.compile(r"^(public\s+)?events?\b.*\|", re.IGNORECASE),
    re.compile(r"\bevents? in chicago\b", re.IGNORECASE),
    re.compile(r"\blink in bio\b|\bswipe\b|\bdm (us|me)\b|\bfollow us\b", re.IGNORECASE),
)


def _looks_like_an_event(title: str | None) -> bool:
    if not title:
        return False
    cleaned = " ".join(title.split())
    if len(cleaned) < 10 or " " not in cleaned:
        return False
    return not any(p.search(cleaned) for p in _NOT_AN_EVENT)


_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _done(finished: asyncio.Task) -> None:
        _background_tasks.discard(finished)
        if finished.cancelled():
            logger.warning("Background task was cancelled before finishing")
            return
        error = finished.exception()
        if error:
            logger.error("Background task failed: %s: %s", type(error).__name__, error)

    task.add_done_callback(_done)
    return task


async def _persist_events_to_db(events: list[EventResult]) -> None:
    """Background: persist external events to DB with retry on SQLite lock."""
    if not events:
        return
    from sqlalchemy import select

    from shared.database import AsyncSessionLocal
    from shared.database.models import EventModel

    max_retries, retry_delay = 3, 0.5
    for attempt in range(max_retries):
        try:
            await asyncio.sleep(retry_delay)
            async with AsyncSessionLocal() as db:
                persisted = skipped_noverifiable = skipped_undated = 0
                for ev in events:
                    if not _looks_like_an_event(ev.title):
                        continue
                    if not ev.url:
                        skipped_noverifiable += 1
                        continue
                    try:
                        event_date = datetime.fromisoformat(ev.date)
                    except ValueError, AttributeError, TypeError:
                        skipped_undated += 1
                        continue
                    existing = (
                        (await db.execute(select(EventModel).filter_by(origination_url=ev.url)))
                        .scalars()
                        .first()
                    )
                    if existing:
                        continue
                    labels = classify_all(ev.title, hint=ev.type_hint)
                    db.add(
                        EventModel(
                            name=ev.title,
                            date=event_date,
                            address=ev.location,
                            venue_name=ev.venue,
                            category=labels[0] if labels else "Events",
                            categories=labels or None,
                            origination_url=ev.url,
                            source="SerpAPI",
                        )
                    )
                    persisted += 1
                if persisted:
                    await db.commit()
                    logger.info("Persisted %d external events", persisted)
                return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                retry_delay *= 2
            else:
                logger.error("Failed to persist events: %s", e, exc_info=True)
                return


async def search_google_events(context: RunContext[SearchPolicy], query: str) -> str:
    """Search the live web for Chicago events not in our own database.

    Use when the local search finds little or nothing relevant.
    """
    logger.info("search_google_events called with query: %r", query)
    try:
        if context is not None and not context.deps.may_search_web:
            return (
                "Do not search the web: local search has not found sparse or "
                "low-confidence results. Answer from the local results."
            )
        if context is not None:
            context.deps.external_search_used = True
        if not SERPAPI_KEY:
            return "SerpAPI not configured"

        search_phrase = " ".join(_extract_keywords(query)) or query
        logger.info("Falling back to SerpAPI for: %r as %r", query, search_phrase)

        async with httpx.AsyncClient(timeout=SERPAPI_TIMEOUT) as client:
            response = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google",
                    "q": f"{search_phrase} events",
                    "location": "Chicago, Illinois, United States",
                    "google_domain": "google.com",
                    "api_key": SERPAPI_KEY,
                },
            )
            response.raise_for_status()
            data = response.json()

        if data.get("error"):
            logger.error("SerpAPI returned an error: %s", data["error"])
            return "Could not search online (API error)"

        events: list[EventResult] = []
        for ev in (data.get("events_results") or [])[:10]:
            try:
                raw = ev.get("address")
                if isinstance(raw, list):
                    parts = [p for p in (s.strip() for s in raw) if p]
                    address, venue = ", ".join(parts), (parts[0] if parts else None)
                else:
                    address, venue = raw, None
                events.append(
                    EventResult(
                        title=ev.get("title", "Untitled"),
                        date=ev.get("date") or ev.get("snippet"),
                        location=address or ev.get("displayed_link"),
                        venue=venue,
                        url=ev.get("link", ""),
                        type_hint=ev.get("type"),
                        source="SerpAPI",
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse SerpAPI event: %s", e)

        if not events:
            return "No additional events found online"

        try:
            _spawn_background(_persist_events_to_db(events))
        except RuntimeError:
            logger.warning("Could not create background task for event persistence")

        lines = [f"🌐 **Online Search** - Found {len(events)} events:\n"]
        for i, ev in enumerate(events, 1):
            labels = classify_all(ev.title, hint=ev.type_hint)
            lines += [
                f"{i}. **{ev.title}** [{', '.join(labels) if labels else 'Events'}]",
                f"   📅 {ev.date}",
            ]
            if ev.location:
                lines.append(f"   📍 {ev.location}")
            lines.append("   📌 Live web search (Google Events)")
            lines.append(
                f"   🔗 [View Event]({ev.url})"
                if ev.url
                else "   ⚠️ No event page to verify - not saved to our database, so tell the user to search for it themselves"
            )
            lines.append("")
        return "\n".join(lines)

    except httpx.TimeoutException as e:
        logger.error("SerpAPI %s after %ss for %r", type(e).__name__, SERPAPI_TIMEOUT, query)
        return (
            f"The online search timed out after {SERPAPI_TIMEOUT}s. "
            "Say so plainly and offer to try again — do not call this tool again in this turn."
        )
    except httpx.HTTPError as e:
        logger.error("SerpAPI %s: %s", type(e).__name__, str(e) or "(no message)")
        return "Could not search online (API error)"
    except Exception as e:
        logger.error("Search error: %s: %s", type(e).__name__, e, exc_info=True)
        return f"Error: {e!s}"
