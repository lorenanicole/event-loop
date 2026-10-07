import os
import logging
import re
import httpx
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from sqlalchemy import and_, or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import Optional, Union, Literal
from shared.database import AsyncSessionLocal, start_of_day, upcoming_events_filter
from shared.database.models import EventModel, NeighborhoodModel
from shared.categories import (
    category_filter,
    classify_from_title,
    extract_category_concepts,
)
from shared.database.neighborhoods import NEIGHBORHOOD_ALIASES
from app.ai.smart_search import get_smart_search_tool
from app.ai.semantic_index import event_index
from app.logging import get_logger

# Load .env before reading the keys below. This module is imported during app
# startup, before main.py gets to its own load_dotenv(), so it has to find the
# file itself. Walk up from this file rather than from the working directory,
# so the keys resolve however the server was launched.
_env_path = next(
    (parent / ".env" for parent in Path(__file__).resolve().parents if (parent / ".env").is_file()),
    None,
)
if _env_path:
    load_dotenv(_env_path)

logger = get_logger(__name__)

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
# Most of the wait this protects against is SerpAPI failing, not SerpAPI
# being slow. Measured over six real queries:
#
#   0.9s 200   1.1s 200   1.9s 200     <- normal
#   67.0s 200                          <- slow, but did return 10 events
#   90.2s 503  90.2s 503               <- "We couldn't get valid results"
#
# A successful call has a median of 1.5s, which matches the ~2.3s SerpAPI
# documents for the standard Google Search API. The minute-plus cases are a
# service-side failure mode: SerpAPI retries internally and then returns 503,
# so the old 45s ceiling spent 45 seconds of a chat turn waiting for an
# answer that was never coming. Two of six here, so it is not rare.
#
# There is nothing to make faster on our side - the call is a single GET, and
# the fast cases already land in about a second. The only real choice is how
# long to stall the user. 12s clears a normal call by a wide margin and gives
# up on the failures 78 seconds sooner. The known cost is the occasional slow
# success like the 67s one above, which is accepted deliberately: nobody
# waits a minute for a chat reply, and the local database has already been
# searched by this point, so a dropped web search degrades the answer rather
# than breaking it.
#
# The failure is transient rather than a property of the query, which is the
# tempting part: "watercolor workshop events" took 90s and 503'd, then
# returned 10 events in 1.4s a few minutes later. So an automatic retry was
# tried here, and is not kept. On the query still in the failing state
# ("zine fair events") both attempts hit the 12s cap, turning one stalled
# turn into 24 seconds of silence for nothing. Retrying is a coin flip that
# doubles the worst case, so the retry is left to the user instead: the tool
# says it timed out and offers to try again, and when they take it the call
# usually lands in the fast path.
SERPAPI_TIMEOUT = 12
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DB_RESULT_THRESHOLD = 5  # Minimum results before using SerpAPI
# How relevant the best local match must be before we stop and skip the paid
# web search. Applied to the top result, not the average of the list.
LOCAL_CONFIDENCE_FLOOR = 0.3

class EventResult(BaseModel):
    title: str
    date: Optional[str] = None
    location: Optional[str] = None
    # Google returns the address as ["Lincoln Park Zoo", "Chicago, IL"] - the
    # venue and then where it is. Keeping the venue apart from the joined
    # string means a stored event names its venue like every other source,
    # instead of having it buried in an address field.
    venue: Optional[str] = None
    url: Optional[str] = None
    source: str

    class Config:
        extra = "ignore"  # Ignore extra fields from API responses


class ToolCallAction(BaseModel):
    """Agent action: call a tool with arguments."""
    action_type: Literal["tool_call"] = Field(default="tool_call", description="Always 'tool_call'")
    tool: str = Field(description="Tool name: 'search_local_db' or 'search_google_events'")
    args: dict = Field(description="Tool arguments")


class ToolResultAction(BaseModel):
    """Agent observation: received tool results."""
    action_type: Literal["tool_result"] = Field(default="tool_result", description="Always 'tool_result'")
    tool: str = Field(description="Which tool was executed")
    found: int = Field(description="Number of results found")
    events: list[EventResult] = Field(description="The events/results")


class FinalResponse(BaseModel):
    """Agent response: final message to user."""
    action_type: Literal["response"] = Field(default="response", description="Always 'response'")
    message: str = Field(description="The response text to show user")
    context: str = Field(description="Context about what was searched/found")
    tokens: int = Field(description="Estimated tokens used")


class ScoredEvent(BaseModel):
    """Event with relevance confidence score."""
    title: str
    date: str
    location: Optional[str] = None
    url: Optional[str] = None
    source: str
    category: Optional[str] = None
    details: Optional[str] = None
    cost: Optional[str] = None
    age_range: Optional[str] = None
    is_outdoor: Optional[str] = None
    address: Optional[str] = None
    confidence: float = Field(description="Relevance score 0.0-1.0")


class AgentAction(BaseModel):
    """Union type for all agent actions in the REACT loop."""
    action: Union[ToolCallAction, ToolResultAction, FinalResponse] = Field(
        discriminator="action_type",
        description="One of: tool_call, tool_result, response"
    )


async def search_local_db(context: RunContext[str], query: str) -> str:
    """Search local database for events (FREE - no API cost)"""
    logger.info(f"search_local_db called with query: {query}")
    try:
        async with AsyncSessionLocal() as db:
            query_str = query.lower()

            neighborhoods = await _extract_neighborhoods(db, query_str)
            keywords = _strip_neighborhoods(_extract_keywords(query_str), neighborhoods)
            categories = extract_category_concepts(query_str)
            date_range = _extract_date_range(query_str)

            logger.info(f"Extracted keywords ({len(keywords)}): {keywords[:6]}")
            logger.info(f"Extracted categories: {categories}")
            logger.info(f"Extracted neighborhoods: {neighborhoods}")

            db_query = select(EventModel)
            filters = []

            # Named neighborhoods are a hard constraint, exactly as in the UI:
            # joined and matched on name, not OR-ed in with the keywords. Several
            # can be named at once, in which case any of them will do.
            if neighborhoods:
                db_query = db_query.join(
                    NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id
                ).filter(NeighborhoodModel.name.in_(neighborhoods))

            if keywords:
                keyword_conditions = [EventModel.name.ilike(f"%{kw}%") for kw in keywords]
                filters.append(or_(*keyword_conditions))

            if categories:
                # Prefix-matched via the shared vocabulary, so "art" reaches
                # every Arts* label rather than needing an exact value.
                condition = category_filter(
                    EventModel.category, categories, EventModel.categories
                )
                if condition is not None:
                    filters.append(condition)

            if filters:
                db_query = db_query.filter(or_(*filters))

            # Never recommend events that have already finished.
            db_query = db_query.filter(upcoming_events_filter())

            if date_range:
                start_date, end_date = date_range
                # Match events overlapping the window, not just starting in it,
                # so a run already under way still counts. Dates are stored at
                # midnight, so the lower bound is the start of the day -
                # otherwise "what's on tonight?" at 11am returns nothing.
                window_start = start_of_day(start_date)
                db_query = db_query.filter(
                    and_(
                        EventModel.date <= end_date,
                        or_(
                            EventModel.date_end >= window_start,
                            and_(EventModel.date_end.is_(None), EventModel.date >= window_start),
                        ),
                    )
                )

            result = await db.execute(db_query.order_by(EventModel.date.asc()).limit(50))
            results = result.scalars().all()

            logger.info(f"Database query returned {len(results)} raw results")

            # Keyword candidates are the 50 *soonest* matches, so a highly
            # relevant event further out never gets considered. Semantic
            # retrieval contributes its own candidates by meaning, which also
            # covers queries that share no keyword with the event at all
            # ("plant workshops" vs "foraging wild plants") - often sparing a
            # paid SerpAPI call.
            semantic_matches = await _semantic_candidates(
                db, query, date_range, neighborhoods=neighborhoods
            )
            by_id = {e.id: e for e in results}
            for event in semantic_matches:
                by_id.setdefault(event.id, event)
            results = list(by_id.values())

            logger.info(
                f"Candidates: {len(by_id)} total "
                f"({len(semantic_matches)} from semantic search)"
            )

            if not results:
                logger.info("No results found - returning NO_RESULTS")
                return "NO_RESULTS"

            semantic_scores = await _semantic_scores(db, query, [e.id for e in results])

            # Score and filter to top 5 most relevant events
            top_events = _filter_top_results(
                results, query, keywords, categories, limit=5, semantic_scores=semantic_scores
            )

            if not top_events:
                logger.info(f"No results after scoring for query: {query}")
                return "NO_RESULTS"

            # Judge on the best match, not the average: the list is ranked, so
            # averaging lets weak tail entries veto a strong leading result and
            # send an answerable query out to the paid API.
            best_confidence = max(e.confidence for e in top_events)
            avg_confidence = sum(e.confidence for e in top_events) / len(top_events)
            logger.info(
                f"Local search found {len(top_events)} events, "
                f"best confidence: {best_confidence:.2f} (avg {avg_confidence:.2f})"
            )
            for evt in top_events:
                logger.info(f"  - {evt.title}: {evt.confidence:.2f}")

            if best_confidence < LOCAL_CONFIDENCE_FLOOR:
                logger.info(f"Confidence {best_confidence:.2f} below threshold, falling back to SerpAPI")
                return "LOW_CONFIDENCE_LOCAL_RESULTS"

            # Build response with event details
            results_text = f"📍 **Found {len(top_events)} great match{'es' if len(top_events) != 1 else ''}:**\n\n"
            for i, event in enumerate(top_events, 1):
                # Category label
                category_tag = f" `{event.category}`" if event.category else ""
                results_text += f"{i}. **{event.title}**{category_tag}\n"

                # Date
                results_text += f"   📅 {event.date}\n"

                # Address if available
                if event.address:
                    results_text += f"   📍 {event.address}\n"

                # Outdoor/Indoor designation
                if event.is_outdoor:
                    outdoor_emoji = "🌳" if event.is_outdoor == "outdoor" else "🏢"
                    results_text += f"   {outdoor_emoji} {event.is_outdoor.capitalize()}\n"

                # Cost and age range
                if event.cost or event.age_range:
                    details_parts = []
                    if event.cost:
                        details_parts.append(f"💰 {event.cost}")
                    if event.age_range:
                        details_parts.append(f"👥 {event.age_range}")
                    results_text += f"   {' | '.join(details_parts)}\n"

                # Source/Location
                if event.source:
                    results_text += f"   📌 {event.source}\n"

                # Summary
                if event.details:
                    results_text += f"   📝 {event.details}\n"

                # Clickable link
                if event.url:
                    results_text += f"   🔗 [View Event]({event.url})\n"

                results_text += "\n"

            return results_text

    except Exception as e:
        logger.error(f"DB search error: {e}")
        return "NO_RESULTS"


# Search results are not all events. Roughly half of what had been persisted
# this way were artifacts of the search rather than things to attend: page
# titles ("Events | Chicago Public Library"), listing pages ("Astrophysicist
# Events in Chicago"), a bare "chicago", and social posts ("Link in bio Learn
# about landscaping..."). These are cheap, specific signals for that, kept
# deliberately conservative - a missed event costs less than a junk row in a
# discovery feed.
_NOT_AN_EVENT = (
    # A site-title separator: "<section> | <site>".
    re.compile(r"\s[|\u2013\u2014]\s.*(department|library|university|college"
               r"|museum|center|centre|institute)", re.I),
    # Search-engine furniture. Deliberately not a bare "- search": "In
    # Conversation with Neil deGrasse Tyson - Search for Life" is a real talk.
    re.compile(r"\bsearch results\b|\bgoogle search\b", re.I),
    # A listing page rather than one event.
    re.compile(r"^(public\s+)?events?\b.*\|", re.I),
    re.compile(r"\bevents? in chicago\b", re.I),
    # Social copy.
    re.compile(r"\blink in bio\b|\bswipe\b|\bdm (us|me)\b|\bfollow us\b", re.I),
)


def _looks_like_an_event(title: Optional[str]) -> bool:
    """Whether a search result is plausibly a single event worth storing."""
    if not title:
        return False
    cleaned = " ".join(title.split())
    # A real event title carries more than one word.
    if len(cleaned) < 10 or " " not in cleaned:
        return False
    return not any(pattern.search(cleaned) for pattern in _NOT_AN_EVENT)


# Strong references to in-flight background tasks.
#
# The event loop keeps only a weak reference to a task, so a task nobody else
# holds may be collected before it finishes - the hazard the asyncio docs warn
# about, still current in 3.15. Holding it in a set and discarding it from a
# done callback is the pattern those docs recommend.
#
# This is defensive rather than a fix for an observed loss: when the online
# search persisted nothing, the cause turned out to be that SerpAPI returns no
# `link` on an event, so every row was dropped by the URL check below. A task
# suspended on `asyncio.sleep` is in fact kept alive by that sleep's future,
# which is why the loss was deterministic rather than a race.
#
# It earns its place on the second count: a bare task keeps its exception to
# itself, so "persisting failed" and "there was nothing to persist" looked
# identical in the logs. Now they do not.
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    """Run a coroutine detached from the request, and actually keep it alive.

    The task is held until it completes, and its outcome is logged: a bare
    background task swallows its own exception, so a failure to persist looked
    identical to there being nothing to persist.
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _done(finished: asyncio.Task) -> None:
        _background_tasks.discard(finished)
        if finished.cancelled():
            logger.warning("Background task was cancelled before finishing")
            return
        error = finished.exception()
        if error:
            logger.error(
                "Background task failed: %s: %s", type(error).__name__, error
            )

    task.add_done_callback(_done)
    return task


async def _persist_events_to_db(events: list[EventResult]) -> None:
    """Background task: persist external events to DB (non-blocking) with retry."""
    if not events:
        return

    max_retries = 3
    retry_delay = 0.5

    for attempt in range(max_retries):
        try:
            await asyncio.sleep(retry_delay)
            async with AsyncSessionLocal() as db:
                persisted_count = 0
                for event in events:
                    if not _looks_like_an_event(event.title):
                        logger.info(f"Skipping non-event search result: {event.title!r}")
                        continue

                    try:
                        event_date = datetime.fromisoformat(event.date.replace('Z', '+00:00'))
                    except (ValueError, AttributeError, TypeError):
                        event_date = datetime.now() + timedelta(days=30)

                    # Google's event cards carry no link at all - title,
                    # address, date, time and a thumbnail, and nothing else.
                    # Requiring a URL here therefore dropped every single
                    # online-search result before it reached the database,
                    # silently, which is why no row from this source had been
                    # written in a day while the searches kept succeeding.
                    #
                    # So identity falls back to the name and the day. Both
                    # paths still dedupe; only the key differs.
                    if event.url:
                        existing = await db.execute(
                            select(EventModel).filter_by(origination_url=event.url)
                        )
                    else:
                        existing = await db.execute(
                            select(EventModel).filter(
                                func.lower(EventModel.name) == (event.title or "").lower(),
                                func.date(EventModel.date) == event_date.date(),
                            )
                        )
                    if existing.scalars().first():
                        continue

                    new_event = EventModel(
                        name=event.title,
                        date=event_date,
                        address=event.location,
                        venue_name=event.venue,
                        # Derived from the title. It used to be hardcoded to
                        # "Online Search", which says where the event came
                        # from rather than what it is - and provenance is
                        # already recorded in `source` on the next line.
                        category=classify_from_title(event.title),
                        # Left null rather than faked. A synthetic value here
                        # would render as a dead "Learn more" link on the card.
                        origination_url=event.url or None,
                        source="SerpAPI",
                    )
                    db.add(new_event)
                    persisted_count += 1

                if persisted_count > 0:
                    await db.commit()
                    logger.info(f"✅ Persisted {persisted_count} external events to DB")
                else:
                    logger.info(f"No new events to persist (all {len(events)} already existed)")
                return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                retry_delay *= 2
                logger.warning(f"DB locked (attempt {attempt + 1}/{max_retries}), retrying...")
            else:
                logger.error(f"❌ Failed to persist events: {e}", exc_info=True)
                return


async def search_google_events(context: RunContext[str], query: str) -> str:
    """Search Google Events using SerpAPI (PAID - only if DB has few results)"""
    logger.info(f"search_google_events called with query: {query}")
    try:
        if not SERPAPI_KEY:
            return "SerpAPI not configured"

        # Google returns no structured events for a conversational sentence, so
        # reduce it to the subject ("plant workshops"). The city is dropped too -
        # the `location` param already scopes the search to Chicago.
        search_phrase = " ".join(_extract_keywords(query)) or query
        logger.info(f"Falling back to SerpAPI for: {query!r} as {search_phrase!r}")

        # See SERPAPI_TIMEOUT for why the ceiling is where it is.
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
                logger.error(f"SerpAPI returned an error: {data['error']}")
                return "Could not search online (API error)"

            events = []
            # events_results only. organic_results are undated web pages - they
            # were being rendered as events, which is how five-year-old Facebook
            # posts ended up presented as answers to "this weekend".
            results = data.get("events_results") or []
            for event in results[:10]:
                try:
                    # Handle address as list or string. As a list it reads
                    # ["Lincoln Park Zoo", "Chicago, IL"] - venue first, then
                    # where it is - so the first entry is the venue name.
                    raw_address = event.get("address")
                    if isinstance(raw_address, list):
                        parts = [p for p in (s.strip() for s in raw_address) if p]
                        address = ", ".join(parts)
                        venue = parts[0] if parts else None
                    else:
                        address = raw_address
                        venue = None

                    events.append(
                        EventResult(
                            title=event.get("title", "Untitled"),
                            date=event.get("date") or event.get("snippet"),
                            location=address or event.get("displayed_link"),
                            venue=venue,
                            url=event.get("link", ""),
                            source="SerpAPI",
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse SerpAPI event: {e}, data: {event}")
                    continue

            if not events:
                return "No additional events found online"

            # Fire async DB persistence task (non-blocking)
            try:
                _spawn_background(_persist_events_to_db(events))
            except RuntimeError:
                logger.warning("Could not create background task for event persistence")

            results_text = f"🌐 **Online Search** - Found {len(events)} events:\n\n"
            for i, event in enumerate(events, 1):
                results_text += f"{i}. **{event.title}**\n"
                results_text += f"   📅 {event.date}\n"
                if event.location:
                    results_text += f"   📍 {event.location}\n"
                # Tagged per event, not just in the header above.
                # `search_local_db` labels every row with its source, this one
                # labelled only the batch - so when the model merged the two
                # lists into one answer, the database rows kept their
                # provenance and these quietly lost theirs. The result read as
                # if a live Google card and a scraped venue listing were
                # equally confirmed.
                results_text += "   📌 Live web search (Google Events)\n"
                if event.url:
                    results_text += f"   🔗 [View Event]({event.url})\n"
                else:
                    # Google's event cards have no link, so there is nothing
                    # for the reader to check. Say so rather than leave a gap.
                    results_text += "   ⚠️ No event page available to verify\n"
                results_text += "\n"

            return results_text

    except httpx.TimeoutException as e:
        # Reported separately from other transport errors because it is not an
        # error on SerpAPI's side and it is not worth retrying inside the same
        # turn - the call already waited SERPAPI_TIMEOUT seconds.
        #
        # The exception type is logged, not just the message: a ReadTimeout's
        # message is the empty string, so `f"{e}"` alone logged "SerpAPI
        # error: " and left no way to tell a timeout from anything else.
        logger.error(
            "SerpAPI %s after %ss for %r", type(e).__name__, SERPAPI_TIMEOUT, query
        )
        return (
            f"The online search timed out after {SERPAPI_TIMEOUT}s. "
            "Say so plainly and offer to try again - do not call this tool "
            "again in this turn."
        )
    except httpx.HTTPError as e:
        # `str(e) or ...`, not `e or ...`: an exception object is truthy even
        # when its message is empty, which is exactly the case being handled.
        logger.error("SerpAPI %s: %s", type(e).__name__, str(e) or "(no message)")
        return "Could not search online (API error)"
    except Exception as e:
        logger.error("Search error: %s: %s", type(e).__name__, e, exc_info=True)
        return f"Error: {str(e)}"


def _count_word_matches(keywords: list[str], text: str) -> int:
    """How many keywords appear in `text` as whole words.

    Plurals are treated as the same word so "workshops" matches "Workshop",
    but unrelated words that merely share a prefix are not ("class"/"Classic").
    """
    words = {w.strip(".,!?;:'\"()-") for w in text.lower().split()}
    stems = {w.rstrip("s") for w in words if w}
    return sum(1 for kw in keywords if kw in words or kw.rstrip("s") in stems)


def _score_event_relevance(
    event: EventModel,
    keywords: list[str],
    query_categories: list[str],
    semantic_score: Optional[float] = None,
) -> float:
    """
    Score event relevance to query (0.0-1.0).
    Combines keyword matching, semantic similarity, category match, and date proximity.
    Uses pre-extracted keywords to ensure consistent scoring.
    """
    score = 0.0

    # Keyword matching (0-0.4) - every term here is one the user actually typed.
    # Whole words only: the SQL filter matches substrings for recall, which
    # scores "Classic Stadium Tour" against a query for a "class" unless
    # scoring is stricter than retrieval.
    event_text = f"{event.name} {event.category or ''}".lower()
    matching_keywords = _count_word_matches(keywords, event_text)
    if matching_keywords > 0:
        score += min(0.4, 0.15 + (matching_keywords / max(len(keywords), 1)) * 0.25)

    # Semantic similarity (0-0.4), weighted on par with keywords so a genuinely
    # related event can outrank a coincidental substring hit. Scaled for the
    # range these embeddings actually produce - a clearly related short title
    # lands around 0.35-0.45 cosine, which has to clear the confidence floor on
    # its own for keyword-free matches ("gardening class" vs "community garden").
    if semantic_score is not None and semantic_score > 0:
        score += min(0.4, max(0.0, semantic_score) * 0.9)

    # Category match (0-0.15)
    if event.category and query_categories:
        if event.category.lower() in [c.lower() for c in query_categories]:
            score += 0.15

    # Date proximity (0-0.05): a tiebreaker between comparably relevant events,
    # not a ranking signal of its own. Weighted heavily before, it buried the
    # relevant results under whatever happened to be on soonest.
    now = datetime.now()
    if event.date and event.date >= now:
        days_away = (event.date - now).days
        if days_away <= 7:
            score += 0.05
        elif days_away <= 30:
            score += 0.03
        else:
            score += 0.01

    return min(1.0, score)


def _truncate_summary(text: str, words: int = 10) -> str:
    """Truncate text to N words."""
    if not text:
        return ""
    return " ".join(text.split()[:words]) + ("..." if len(text.split()) > words else "")


async def _ensure_semantic_index(db) -> bool:
    """Build the embedding index on first use. False if it is unavailable."""
    try:
        if not event_index.is_ready:
            await event_index.rebuild(db)
        return event_index.is_ready
    except Exception as e:
        # Semantic search is an enhancement - a missing model or failed
        # download must never take down keyword search with it.
        logger.warning(f"Semantic index unavailable: {e}")
        return False


async def _semantic_scores(db, query: str, event_ids: list[int]) -> dict[int, float]:
    """Similarity of the query to each candidate event, for ranking."""
    if not await _ensure_semantic_index(db):
        return {}
    try:
        return event_index.scores_for(query, event_ids)
    except Exception as e:
        logger.warning(f"Semantic scoring failed: {e}")
        return {}


async def _semantic_candidates(
    db, query: str, date_range, limit: int = 20,
    neighborhoods: Optional[list[str]] = None,
) -> list[EventModel]:
    """Find events by meaning, to stand alongside the keyword candidates."""
    if not await _ensure_semantic_index(db):
        return []
    try:
        matches = event_index.search(query, limit=limit)
    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")
        return []
    if not matches:
        return []

    # The index is built over upcoming events, but the caller's date window
    # still has to be honored - "this weekend" means this weekend.
    stmt = select(EventModel).where(EventModel.id.in_([eid for eid, _ in matches]))
    stmt = stmt.where(upcoming_events_filter())
    # The index searches the whole city, so named neighborhoods have to
    # constrain these candidates too - otherwise semantic matches from
    # elsewhere leak past the filter the keyword query just applied.
    if neighborhoods:
        stmt = stmt.join(
            NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id
        ).where(NeighborhoodModel.name.in_(neighborhoods))
    if date_range:
        start_date, end_date = date_range
        stmt = stmt.where(
            and_(EventModel.date >= start_of_day(start_date), EventModel.date <= end_date)
        )

    found = (await db.execute(stmt)).scalars().all()
    logger.info(f"Semantic fallback matched {len(found)} events for {query!r}")
    return list(found)


def _format_event_date(event: EventModel) -> str:
    """Render an event's date for the chat reply.

    The date column is stored at midnight, so reading a clock time off it
    reported every event as "@ 12:00 AM". The published time lives in `time`,
    and a multi-day event shows its run instead.
    """
    if not event.date:
        return "Date not listed"

    label = event.date.strftime("%a, %b %d, %Y")

    date_end = getattr(event, "date_end", None)
    if date_end and date_end.date() != event.date.date():
        return f"{label} through {date_end.strftime('%a, %b %d, %Y')}"

    time_str = (getattr(event, "time", None) or "").strip()
    return f"{label} @ {time_str}" if time_str else label


def _filter_top_results(
    events: list[EventModel],
    query: str,
    keywords: list[str],
    categories: list[str],
    limit: int = 5,
    semantic_scores: Optional[dict[int, float]] = None,
) -> list[ScoredEvent]:
    """
    Score and filter events to top N results by relevance.
    Returns only high-confidence matches to avoid overwhelming user.
    Uses pre-extracted keywords and categories to avoid re-extraction.
    `semantic_scores` maps event id to cosine similarity, when the index is available.
    """
    semantic_scores = semantic_scores or {}
    scored = [
        ScoredEvent(
            title=event.name,
            date=_format_event_date(event),
            location=None,
            url=event.origination_url,
            source=event.source or "Local DB",
            category=event.category,
            details=_truncate_summary(event.details) if event.details else None,
            cost=event.cost if hasattr(event, 'cost') else None,
            age_range=event.age_range if hasattr(event, 'age_range') else None,
            is_outdoor=event.is_outdoor if hasattr(event, 'is_outdoor') else None,
            address=event.address if hasattr(event, 'address') else None,
            # getattr, not event.id: this is called with plain objects in tests
            # and with rows that have not been flushed, and an absent id just
            # means there is no semantic score to apply.
            confidence=_score_event_relevance(
                event, keywords, categories, semantic_scores.get(getattr(event, "id", None))
            ),
        )
        for event in events
    ]

    # Sort by confidence and return top N
    return sorted(scored, key=lambda e: e.confidence, reverse=True)[:limit]


STOP_WORDS = {
    "the", "a", "an", "and", "or", "is", "are", "in", "on", "at",
    "this", "that", "these", "those", "what", "when", "where", "why",
    "find", "get", "search", "show", "tell", "give", "all", "want",
    "looking", "events", "event", "i", "want", "to", "for", "any",
    # Location/context - filter out to avoid matching irrelevant events
    "chicago", "city", "illinois", "windy", "area", "town", "region",
    # Conversational filler. Left in, these became search terms in their own
    # right: "like" and "see" match a huge slice of the events table.
    "like", "would", "see", "me", "my", "please", "can", "could", "need",
    "there", "some", "something", "anything", "know", "about", "happening",
    "going", "see", "got", "have", "has", "near", "around", "list",
    # Temporal words - _extract_date_range already turns these into a date
    # filter, so matching them against event *names* only adds noise.
    "today", "tonight", "tomorrow", "weekend", "week", "month", "year",
    "next", "upcoming", "soon", "now", "weekends", "nights", "night",
}

# OR-ing more terms than this against event names drags in junk faster than it
# finds anything. Matches the cap the API's own keyword extraction uses.
MAX_KEYWORDS = 5


def _normalize_place(text: str) -> str:
    """Lowercase and collapse a place name or query for literal matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]", " ", text.lower())).strip()


async def _extract_neighborhoods(db, query: str) -> list[str]:
    """Find every neighborhood named in the query, matching the UI's filter.

    The UI filters on NeighborhoodModel.name, so the chatbot has to as well:
    treating "Pilsen" as a keyword matches it against the event *title*, which
    almost never hits, because the neighborhood is a relationship rather than
    words in the name.

    A query can name several ("in Logan Square, Humboldt Park"), so all of
    them are returned and OR-ed together. Names are matched longest-first and
    the matched span is consumed, so "West Loop" is not also read as "Loop",
    and "West Pullman" not as "Pullman".

    Naming no neighborhood - "plant workshops this weekend", or "in Chicago",
    which is not a neighborhood - returns nothing and searches the whole city.
    """
    names = (await db.execute(select(NeighborhoodModel.name))).scalars().all()

    # Match on what people type as well as what we store: "lakeview" and
    # "wrigleyville" both mean Lake View. The alias table is the same one the
    # boundary loader uses, so the two cannot drift apart.
    candidates = {_normalize_place(n): n for n in names}
    for spoken, canonical in NEIGHBORHOOD_ALIASES.items():
        if canonical in names:
            candidates.setdefault(_normalize_place(spoken), canonical)

    haystack = f" {_normalize_place(query)} "
    found = []
    for needle in sorted(candidates, key=len, reverse=True):
        if needle and f" {needle} " in haystack:
            name = candidates[needle]
            if name not in found:
                found.append(name)
            # Consume the span so a shorter nested name cannot match it too.
            haystack = haystack.replace(f" {needle} ", "  ")
    return found


def _strip_neighborhoods(keywords: list[str], neighborhoods: list[str]) -> list[str]:
    """Drop the neighborhoods' own words from the keyword list.

    Otherwise the name constrains the title as well as the location, and
    "comedy in Pilsen" demands "pilsen" appear in the event's name.
    """
    parts = {w for name in neighborhoods for w in _normalize_place(name).split()}
    # Also drop the spelling the user actually typed: "shows in wrigleyville"
    # resolves to Lake View, but "wrigleyville" would otherwise stay behind as
    # a keyword and be matched against event titles.
    for spoken, canonical in NEIGHBORHOOD_ALIASES.items():
        if canonical in neighborhoods:
            parts.update(_normalize_place(spoken).split())
    return [kw for kw in keywords if kw not in parts]


def _extract_keywords(query: str) -> list[str]:
    """Extract search keywords, most meaningful first, with bounded synonyms.

    Order matters: the words the user actually typed come first and are never
    displaced. Synonyms only fill whatever budget is left over - previously the
    whole set was built unordered and truncated, which could drop the subject of
    the query ("plant") while keeping a WordNet artifact ("pass", "ilk").
    """
    words = [w.strip(".,!?;:'\"()") for w in query.lower().split()]
    keywords = [w for w in words if w and w not in STOP_WORDS and len(w) > 2]

    if not keywords:
        return []

    # dict.fromkeys dedupes while preserving the order they were typed in.
    #
    # No WordNet expansion: these terms are OR-ed as `name ILIKE %kw%`, so a
    # single bad synonym silently captures the whole result set. WordNet ranks
    # by general English, not by this domain - "jazz" resolves to the nonsense
    # sense ("malarkey", "bunk") and "happening" to "pass", which is what
    # surfaced a United Center parking pass for a plant-workshop query.
    # Category synonyms live in shared.categories, matched by prefix.
    return list(dict.fromkeys(keywords))[:MAX_KEYWORDS]


async def smart_search_expand(context: RunContext[str], query: str) -> str:
    """Expand user query with synonyms and extract intent using NLP (FREE)"""
    logger.info(f"smart_search_expand called with query: {query}")
    try:
        tool = get_smart_search_tool()
        result = await tool.query_expansion_and_search(query)

        output = f"🧠 **Smart Query Analysis**\n\n"
        output += f"**Original:** {result['user_query']}\n"
        output += f"**Expanded:** {result['query_expansion']['expanded']}\n\n"

        if result['intent']['categories']:
            output += f"📂 **Categories:** {', '.join(result['intent']['categories'])}\n"
        if result['intent']['time_frame']:
            output += f"📅 **Timeframe:** {result['intent']['time_frame']}\n"
        if result['intent']['vibe']:
            output += f"✨ **Vibe:** {result['intent']['vibe']}\n"

        output += f"\n💡 **Recommendation:** Search for: '{result['recommendation']['search_with']}'\n"
        return output

    except Exception as e:
        logger.error(f"Smart search error: {e}")
        return f"Error analyzing query: {str(e)}"


def _extract_date_range(query: str) -> Optional[tuple[datetime, datetime]]:
    """Extract date range from query"""
    now = datetime.now()
    query_lower = query.lower()

    if "this weekend" in query_lower:
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        saturday = now + timedelta(days=days_until_saturday)
        sunday = saturday + timedelta(days=1)
        return (saturday, sunday.replace(hour=23, minute=59, second=59))

    if "this week" in query_lower:
        end_of_week = now + timedelta(days=7)
        return (now, end_of_week)

    if "this month" in query_lower:
        end_of_month = now.replace(day=1) + timedelta(days=32)
        end_of_month = end_of_month.replace(day=1) - timedelta(days=1)
        return (now, end_of_month.replace(hour=23, minute=59, second=59))

    if "next week" in query_lower:
        start = now + timedelta(days=7)
        end = start + timedelta(days=7)
        return (start, end)

    if "tonight" in query_lower or "today" in query_lower:
        end = now.replace(hour=23, minute=59, second=59)
        return (now, end)

    return None


_model = AnthropicModel("claude-sonnet-5-5") if CLAUDE_API_KEY else None  # AnthropicModel wraps the model name

agent = Agent(
    model=_model or "test",
    system_prompt="""You are EventLoop, a Chicago events discovery chatbot. Help users find great events efficiently.

TOOLS AVAILABLE:
1. smart_search_expand(query) - Analyzes user intent and expands query
2. search_local_db(query) - Searches local event database (FREE)
3. search_google_events(query) - Searches Google/SerpAPI for events (PAID fallback)

SEARCH STRATEGY:
1. First, call smart_search_expand to understand what user wants
2. Then, call search_local_db with the original query
3. If local results don't look good enough, call search_google_events
4. Present the best results to user in a warm, friendly way

IMPORTANT:
- Always try local database first (no cost)
- Fall back to Google search only if local results are insufficient
- Show top 3-5 best-matched events
- Format results with emojis and clear information (date, location, links, price info)
- Keep responses concise and helpful

SAY WHERE EACH EVENT CAME FROM:
Every event a tool returns carries a "📌" line naming its source. Keep that
distinction in your answer - never merge the two kinds into one plain list.
- Events from search_local_db come from our own scrapers of venue and city
  calendars. Treat these as confirmed.
- Events marked "Live web search (Google Events)" were just pulled off the
  web, have not been checked by us, and usually have no page to link to.
  Group them separately under a heading that says so, such as "From a live
  web search (unverified)".
If an event carries "⚠️ No event page available to verify", do not invent a
link or a price for it, and tell the user there is nothing to confirm it
against. Never present a web result as though it were in our database.""",
)

# Register tools with the agent
agent.tool(search_local_db)
agent.tool(search_google_events)
agent.tool(smart_search_expand)


async def chat(user_message: str) -> str:
    """
    Process user message using REACT flow with structured outputs.
    Returns formatted response text (ChatExecutor handles event streaming).
    """
    try:
        # Run agent with structured output constraint
        result = await agent.run(
            user_message,
            # Note: PydanticAI will return structured action objects
        )

        # Parse the agent's structured output
        if isinstance(result.data, str):
            # Fallback: agent returned plain text
            return result.data

        # Agent returned structured AgentAction - extract response
        if hasattr(result.data, 'action'):
            action = result.data.action
            if isinstance(action, FinalResponse):
                return f"{action.message}\n\n_Context: {action.context} ({action.tokens} tokens)_"

        return str(result.data)

    except Exception as e:
        logger.error(f"Chatbot error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"
