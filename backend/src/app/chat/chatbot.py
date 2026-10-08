import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import RunContext
from sqlalchemy import and_, or_, select

from app.chat.search_query import (
    extract_date_range as _extract_date_range,
)
from app.chat.search_query import (
    extract_keywords as _extract_keywords,
)
from app.chat.search_query import (
    normalize_place as _normalize_place,
    extract_neighborhoods as _extract_neighborhoods,
    strip_neighborhoods as _strip_neighborhoods,
)
from app.chat.search_ranking import (
    _filter_top_results,
)
from app.chat.semantic_index import event_index
from app.logging import get_logger
from shared.categories import (
    category_filter,
    extract_category_concepts,
)
from shared.database import AsyncSessionLocal, start_of_day, upcoming_events_filter
from shared.database.models import EventModel, NeighborhoodModel

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
AGENT_REQUEST_LIMIT = 4
AGENT_TOOL_CALL_LIMIT = 3
AGENT_OUTPUT_TOKEN_LIMIT = 4000


@dataclass
class SearchPolicy:
    """Per-run state used to enforce the paid-search fallback policy."""

    user_message: str = ""
    local_search_completed: bool = False
    local_result_count: int = 0
    local_best_confidence: float = 0.0
    external_search_used: bool = False

    @property
    def may_search_web(self) -> bool:
        return (
            self.local_search_completed
            and not self.external_search_used
            and (
                self.local_result_count < DB_RESULT_THRESHOLD
                or self.local_best_confidence < LOCAL_CONFIDENCE_FLOOR
            )
        )


# EventResult and the SerpAPI pipeline have moved to web_search.py.
# Re-exported here so any code that still imports from chatbot keeps working.
from app.chat.web_search import (  # noqa: F401
    EventResult,
    _background_tasks,
    _looks_like_an_event,
    _spawn_background,
)


async def search_local_db(context: RunContext[SearchPolicy], query: str) -> str:
    """Search local database for events (FREE - no API cost)"""
    logger.info(f"search_local_db called with query: {query}")
    context.deps.local_search_completed = True
    context.deps.local_result_count = 0
    context.deps.local_best_confidence = 0.0
    try:
        async with AsyncSessionLocal() as db:
            query_str = query.lower()

            neighborhoods = await _extract_neighborhoods(db, query_str)
            keywords = _strip_neighborhoods(
                _extract_keywords(query_str), neighborhoods, query=query_str
            )
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
                condition = category_filter(EventModel.category, categories, EventModel.categories)
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

            # Candidate ceiling: raise to 100 when neighborhoods are present
            # because the join already narrows the set substantially, so 100
            # rows costs about the same as 50 unconstrained ones and prevents
            # the best match from falling off the bottom of a dense calendar.
            # feed_order() is the same sort the public API uses (date asc,
            # then name) so the two surfaces cannot drift.
            from shared.database import feed_order

            candidate_limit = 100 if neighborhoods else 50
            result = await db.execute(db_query.order_by(*feed_order()).limit(candidate_limit))
            results = result.scalars().all()

            logger.info(f"Database query returned {len(results)} raw results")

            # Keyword candidates are the soonest matches up to the ceiling, so
            # a highly relevant event further out may still be missed by SQL.
            # Semantic retrieval contributes its own candidates by meaning,
            # covering queries with no keyword overlap ("plant workshops" vs
            # "foraging wild plants") — often sparing a paid SerpAPI call.
            semantic_matches = await _semantic_candidates(
                db, query, date_range, neighborhoods=neighborhoods
            )
            by_id = {e.id: e for e in results}
            for event in semantic_matches:
                by_id.setdefault(event.id, event)
            results = list(by_id.values())

            logger.info(
                f"Candidates: {len(by_id)} total ({len(semantic_matches)} from semantic search)"
            )

            if not results:
                logger.info("No results found - returning NO_RESULTS")
                return "NO_RESULTS"

            neighborhood_ids = {
                event.neighborhood_id for event in results if event.neighborhood_id is not None
            }
            if neighborhood_ids:
                neighborhood_rows = await db.execute(
                    select(NeighborhoodModel.id, NeighborhoodModel.name).where(
                        NeighborhoodModel.id.in_(neighborhood_ids)
                    )
                )
                neighborhood_names = dict(neighborhood_rows.all())
                for event in results:
                    event.neighborhood_name = neighborhood_names.get(event.neighborhood_id)

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
            context.deps.local_result_count = len(top_events)
            context.deps.local_best_confidence = best_confidence
            logger.info(
                f"Local search found {len(top_events)} events, "
                f"best confidence: {best_confidence:.2f} (avg {avg_confidence:.2f})"
            )
            for evt in top_events:
                logger.info(f"  - {evt.title}: {evt.confidence:.2f}")

            if best_confidence < LOCAL_CONFIDENCE_FLOOR:
                logger.info(
                    f"Confidence {best_confidence:.2f} below threshold, falling back to SerpAPI"
                )
                return "LOW_CONFIDENCE_LOCAL_RESULTS"

            # Build response with event details
            from app.chat.persona import transit_for_neighborhood

            results_text = f"📍 **Found {len(top_events)} great match{'es' if len(top_events) != 1 else ''}:**\n\n"
            for i, event in enumerate(top_events, 1):
                # Category label
                category_tag = f" `{event.category}`" if event.category else ""
                results_text += f"{i}. **{event.title}**{category_tag}\n"

                # Date
                results_text += f"   📅 {event.date}\n"

                if event.neighborhood:
                    results_text += f"   🗺️ {event.neighborhood}"
                    transit = transit_for_neighborhood(event.neighborhood)
                    if transit:
                        results_text += f" | 🚉 {transit}"
                    results_text += "\n"

                # Address if available
                if event.address:
                    # locality is populated for venues outside Chicago proper
                    # (e.g. Naperville, Lombard). do312 covers the whole metro,
                    # so without this flag the model has no way to know the
                    # event is not in the city.
                    outside = f"  ⚠️ NOT in Chicago - {event.locality}" if event.locality else ""
                    results_text += f"   📍 {event.address}{outside}\n"

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
# _NOT_AN_EVENT, _looks_like_an_event, _background_tasks, _spawn_background,
# _persist_events_to_db, search_google_events -> moved to web_search.py.
from app.chat.web_search import search_google_events  # noqa: F401


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
    db,
    query: str,
    date_range,
    limit: int = 20,
    neighborhoods: list[str] | None = None,
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


def __getattr__(name: str):
    """Keep legacy prompt/agent imports working without an import cycle."""
    if name in {"SYSTEM_PROMPT", "agent", "todays_date"}:
        from app.chat import agent as agent_module

        return getattr(agent_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
