import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ConfigDict, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import String, and_, cast, func, or_, select

from shared.database import feed_order, get_db, start_of_day, upcoming_events_filter
from shared.database.models import (
    AuditLogModel,
    ChatThreadModel,
    EventModel,
    NeighborhoodModel,
)
from shared.categories import category_filter, extract_category_concepts
from shared.models import Event, EventSearch
from app.ai.executor import ChatExecutor, sse_event_formatter
from app import telemetry
from app.security import rate_limiter
from app.logging import get_logger

logger = get_logger(__name__)
# No router-level tags: each endpoint declares its own, and a tag here
# would be added on top, listing every operation twice in /docs.
router = APIRouter(prefix="/api")
analytics_router = APIRouter(prefix="")


# Reusable OpenAPI response blocks. FastAPI generates a schema-shaped example
# by default ("string", 0), which tells a reader nothing about what an event
# actually looks like, so every endpoint supplies a real one. Error codes are
# only declared where the handler can genuinely return them.
_EVENT_EXAMPLE = {
    "id": 1247,
    "name": "Comedy Open Mic",
    "date": "2026-10-07T00:00:00",
    "date_end": None,
    "time": "Show: 8 pm",
    "category": "music",
    "origination_url": "https://colesbarchicago.com/shows/comedy-open-mic-october-07-2026-717984",
    "cost": "Free",
    "address": "Cole's Bar, 2338 N Milwaukee Ave",
    "venue_name": "Cole's Bar",
    "date_retrieved": "2026-10-07T03:42:44.521539",
}
_RUN_EXAMPLE = {
    "id": 2990,
    "name": "The Winter's Tale",
    "date": "2026-10-13T00:00:00",
    "date_end": "2026-12-12T00:00:00",
    "time": None,
    "category": "theater",
    "origination_url": "https://www.chicagoshakes.com/plays-and-events/winters-tale",
    "cost": None,
    "address": "Chicago Shakespeare Theater, 800 E Grand Ave",
    "venue_name": "Chicago Shakespeare Theater",
    "date_retrieved": "2026-10-07T03:42:44.521539",
}


def _ok(example, description="Successful response"):
    """One 200 block carrying a concrete example."""
    return {200: {"description": description,
                  "content": {"application/json": {"example": example}}}}


_VALIDATION_ERROR = {
    422: {
        "description": "A query or body value failed validation - for instance "
                       "`limit` outside 1-100, or a missing `query`.",
        "content": {"application/json": {"example": {
            "detail": [{"loc": ["query", "limit"], "msg":
                        "Input should be less than or equal to 100",
                        "type": "less_than_equal"}]
        }}},
    }
}


def _category_matches(label: str):
    """Match an exact category against the primary or any secondary label.

    Picking "LGBTQ" has to return a drag show whose primary category is Music,
    or the multi-label data would change nothing for anyone clicking a tile.
    Stored categories carry stray whitespace ("Poetry & Literary "), so both
    sides are trimmed rather than trusting the data to be clean. The label is
    quoted inside the JSON match so "Arts" cannot match "Arts & Crafts".
    """
    wanted = label.strip()
    return or_(
        func.trim(EventModel.category).ilike(wanted),
        cast(EventModel.categories, String).ilike(f'%"{wanted}"%'),
    )


@router.get(
    "/events",
    response_model=list[Event],
    summary="List upcoming events",
    description=(
        "Chicago events happening today or later, soonest first. A multi-day "
        "event stays in the list until its end date passes, so a festival that "
        "opened last week still appears. Events with neither a start nor an end "
        "date are never returned, because there is no way to tell whether they "
        "have happened. Paging past the end returns an empty array, not a 404."
    ),
    tags=["Events"],
    responses={**_ok([_EVENT_EXAMPLE, _RUN_EXAMPLE],
                     "Events, soonest first. Empty array if `skip` is past the end."),
               **_VALIDATION_ERROR},
)
async def list_events(
    skip: int = Query(0, ge=0, description="Number of events to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum events to return (1-100)"),
    db: AsyncSession = Depends(get_db),
):
    """
    **List upcoming events with pagination**

    Returns a paginated list of Chicago events happening today or later,
    ordered soonest first. Multi-day events stay listed until their end
    date passes, so a festival already under way is still included.

    - **skip**: Pagination offset (default: 0)
    - **limit**: Number of results to return (default: 20, max: 100)

    **Example response:**
    ```json
    [
      {
        "id": 1,
        "name": "Lollapalooza 2026",
        "date": "2026-08-01",
        "location": "Grant Park, Chicago",
        "category": "music",
        "url": "https://lollapalooza.com",
        "source": "ticketmaster"
      }
    ]
    ```
    """
    result = await db.execute(
        select(EventModel)
        .filter(upcoming_events_filter())
        # Shared with /search, so the two paginate identically.
        .order_by(*feed_order())
        .offset(skip)
        .limit(limit)
    )
    events = result.scalars().all()
    return events


@router.get(
    "/events/categories",
    response_model=list[str],
    summary="Get event categories",
    description=(
        "Distinct categories that currently have at least one upcoming event, so "
        "a category tile in the UI never leads to an empty page. Categories whose "
        "events have all passed are left out, which means this list changes over "
        "time. Values are the raw stored slugs and are mixed in style - 'music' "
        "alongside 'Health & Wellness' - because they come from different sources."
    ),
    tags=["Events"],
    responses=_ok(["Arts & Culture", "Comedy", "Food & Drink", "Health & Wellness",
                   "Music", "Theatre & Performing Arts", "comedy", "music", "theater"],
                  "Categories with upcoming events. Casing and wording are "
                  "inconsistent because each source labels its own events; "
                  "'Music' and 'music' are different sources, not duplicates."),
)
async def get_event_categories(db: AsyncSession = Depends(get_db)):
    """
    **Get categories that have upcoming events**

    Only categories with at least one event still to come, so a tile in the UI
    never leads to an empty page. Categories whose events have all passed are
    left out.

    **Example response:**
    ```json
    ["music", "comedy", "theater", "sports", "art", "food", "film", "tech"]
    ```
    """
    result = await db.execute(
        select(EventModel.category)
        .distinct()
        .filter(EventModel.category.isnot(None))
        .filter(upcoming_events_filter())
    )

    def is_valid_category(cat: str) -> bool:
        if not cat or len(cat.strip()) < 3:
            return False
        cat_lower = cat.lower()

        # Exclude placeholder/junk categories
        if cat_lower in ['undefined', 'miscellaneous', 'events', 'other', 'online search']:
            return False

        date_patterns = [
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)',
            r'^\d+\s*,',
            r'until\s+',
            r'\d{4}',
        ]
        has_date = any(re.search(pattern, cat_lower, re.IGNORECASE) for pattern in date_patterns)
        has_digit = bool(re.search(r'\d', cat_lower))
        return not (has_date or has_digit)

    # The same category is stored with different casing ("Music" and "music"),
    # which would otherwise render as two tiles that each return half the
    # events. Collapse case-insensitively and keep the tidiest spelling.
    by_key: dict[str, str] = {}
    for cat in result.scalars().all():
        if not is_valid_category(cat):
            continue
        key = cat.strip().lower()
        existing = by_key.get(key)
        # Prefer the capitalised form, which reads better as a label.
        if existing is None or (cat[:1].isupper() and not existing[:1].isupper()):
            by_key[key] = cat.strip()
    return sorted(by_key.values(), key=str.lower)


@router.get(
    "/events/neighborhoods",
    summary="Get neighborhoods with upcoming events",
    description=(
        "Chicago neighborhoods that currently have events, with counts, busiest "
        "first. Only neighborhoods with events are returned, so a filter offered "
        "by the UI can never come back empty. Names are whichever a Chicagoan "
        "would say - Wicker Park rather than West Town, Pilsen rather than Lower "
        "West Side - and are the exact values POST /api/search expects in its "
        "`neighborhood` field. `min_events` trims the long tail: geocoding "
        "reaches the whole city, so dozens of neighborhoods hold one or two "
        "events. Pass min_events=1 for all of them."
    ),
    tags=["Events"],
    responses={**_ok([{"name": "Loop", "event_count": 379},
                      {"name": "Lincoln Park", "event_count": 295},
                      {"name": "Wicker Park", "event_count": 294},
                      {"name": "Pilsen", "event_count": 172}],
                     "Neighborhoods with at least `min_events` upcoming events"),
               **_VALIDATION_ERROR},
)
async def get_event_neighborhoods(
    min_events: int = Query(
        3, ge=1, le=100, description="Hide neighborhoods with fewer events than this"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    **Get neighborhoods that actually have upcoming events**

    Only returns neighborhoods with upcoming events, so the UI never offers a
    filter that comes back empty. Geocoding reaches right across the city, which
    leaves a long tail of neighborhoods holding a single event; `min_events`
    keeps the tile row to places worth browsing. Pass `min_events=1` for all.

    **Example response:**
    ```json
    [
      {"name": "Wicker Park", "event_count": 230},
      {"name": "Lincoln Park", "event_count": 228}
    ]
    ```
    """
    result = await db.execute(
        select(NeighborhoodModel.name, func.count(EventModel.id).label("event_count"))
        .join(EventModel, EventModel.neighborhood_id == NeighborhoodModel.id)
        .where(upcoming_events_filter())
        .group_by(NeighborhoodModel.name)
        .having(func.count(EventModel.id) >= min_events)
        .order_by(func.count(EventModel.id).desc())
    )
    return [{"name": name, "event_count": count} for name, count in result.all()]


@router.get(
    "/events/filter-counts",
    summary="Counts for the filter tiles, honoring the current selection",
    description=(
        "Event counts per category and per neighborhood, for drawing the filter "
        "tiles with numbers that match what clicking one actually returns.\n\n"
        "Faceted: each list applies the *other* filters but not its own. Asking "
        "with `neighborhood=Avondale` returns neighborhood counts computed "
        "without that constraint - otherwise every other neighborhood would "
        "read zero and the grid would become unusable - while the category "
        "counts are narrowed to Avondale. The same holds the other way round.\n\n"
        "A category or neighborhood with no matching events is omitted rather "
        "than returned as zero, so a tile never leads to an empty result. With "
        "no parameters this is every upcoming event, which is the page's "
        "opening state.\n\n"
        "`timeframe` takes the same words the sentence offers - 'tonight', "
        "'this weekend', 'next week' - and is parsed exactly as the search "
        "query is. An unrecognized value applies no date window rather than "
        "failing."
    ),
    tags=["Events"],
    responses=_ok({"categories": [{"name": "Music", "event_count": 1912},
                                  {"name": "Theater", "event_count": 209}],
                   "neighborhoods": [{"name": "Loop", "event_count": 379},
                                     {"name": "Lincoln Park", "event_count": 295}]},
                  "Counts for each facet, busiest first"),
)
async def get_filter_counts(
    category: Optional[str] = Query(
        None, description="Restrict the neighborhood counts to this category"
    ),
    neighborhood: Optional[str] = Query(
        None, description="Restrict the category counts to this neighborhood"
    ),
    timeframe: Optional[str] = Query(
        None, description="Restrict both, e.g. 'tonight' or 'this weekend'"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Counts for the filter tiles, so the numbers match the results."""
    date_range = _extract_date_range(f"events {timeframe}") if timeframe else None

    def constrain(stmt, *, with_category: bool, with_neighborhood: bool):
        stmt = stmt.where(upcoming_events_filter())
        if date_range:
            start, end = date_range
            window_start = start_of_day(start)
            stmt = stmt.where(
                and_(
                    EventModel.date <= end,
                    or_(
                        EventModel.date_end >= window_start,
                        and_(EventModel.date_end.is_(None),
                             EventModel.date >= window_start),
                    ),
                )
            )
        if with_category and category:
            stmt = stmt.where(_category_matches(category))
        if with_neighborhood and neighborhood:
            stmt = stmt.where(NeighborhoodModel.name == neighborhood)
        return stmt

    # Categories: narrowed by neighborhood and timeframe, not by category.
    #
    # Counted across every label rather than just the primary, because the
    # filter matches every label too - an LGBTQ tile reading only the events
    # whose *primary* category is LGBTQ would undercount the drag shows filed
    # under Music, and the number would stop matching what clicking it
    # returns. json_each expands the array; events predating the column fall
    # back to their single category.
    label = func.json_each(
        func.coalesce(EventModel.categories, func.json_array(EventModel.category))
    ).table_valued("value", joins_implicitly=True)
    category_stmt = constrain(
        select(label.c.value, func.count(EventModel.id).label("n"))
        .outerjoin(NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id)
        .where(EventModel.category.isnot(None)),
        with_category=False,
        with_neighborhood=True,
    ).group_by(label.c.value).order_by(func.count(EventModel.id).desc())

    # Neighborhoods: narrowed by category and timeframe, not by neighborhood.
    neighborhood_stmt = constrain(
        select(NeighborhoodModel.name, func.count(EventModel.id).label("n"))
        .join(EventModel, EventModel.neighborhood_id == NeighborhoodModel.id),
        with_category=True,
        with_neighborhood=False,
    ).group_by(NeighborhoodModel.name).order_by(func.count(EventModel.id).desc())

    categories = (await db.execute(category_stmt)).all()
    neighborhoods = (await db.execute(neighborhood_stmt)).all()
    return {
        "categories": [{"name": name, "event_count": n} for name, n in categories],
        "neighborhoods": [{"name": name, "event_count": n} for name, n in neighborhoods],
    }



@router.get(
    "/events/{event_id}",
    response_model=Event,
    summary="Get event by ID",
    description=(
        "One event by its database id. Returns the event whether or not it has "
        "already happened, unlike the list endpoints, so a link to a past event "
        "still resolves rather than 404ing."
    ),
    tags=["Events"],
    responses={**_ok(_EVENT_EXAMPLE, "The requested event"),
               404: {"description": "No event with that id.",
                     "content": {"application/json": {
                         "example": {"detail": "Event not found"}}}},
               **_VALIDATION_ERROR},
)
async def get_event(
    event_id: int = Path(..., description="Unique event identifier", ge=1),
    db: AsyncSession = Depends(get_db),
):
    """
    **Get a specific event by ID**

    Returns full details of an event including name, date, location, and source information.

    **Example response:**
    ```json
    {
      "id": 1,
      "name": "Lollapalooza 2026",
      "date": "2026-08-01",
      "location": "Grant Park, Chicago",
      "category": "music",
      "url": "https://lollapalooza.com",
      "source": "ticketmaster"
    }
    ```
    """
    result = await db.execute(select(EventModel).filter(EventModel.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post(
    "/search",
    response_model=list[Event],
    summary="Natural language event search",
    responses={**_ok([_EVENT_EXAMPLE],
                     "Matching events, soonest first. An empty array means "
                     "nothing matched - it is not an error."),
               **_VALIDATION_ERROR},
    description="Search events using natural language queries with category and date filtering",
    tags=["Search"],
)
async def search_events(
    search: EventSearch,
    db: AsyncSession = Depends(get_db),
):
    """
    **Search events with natural language query**

    Supports semantic search with automatic extraction of:
    - Event categories (music, comedy, theater, sports, art, food, film)
    - Date ranges (this weekend, this week, this month, tonight, etc.)
    - Keywords and venue names

    **Example queries:**
    - "music events this weekend"
    - "comedy shows in chicago next week"
    - "18+ food events this month"
    - "jazz concerts tonight"

    **Example request:**
    ```json
    {
      "query": "comedy shows this weekend",
      "limit": 20
    }
    ```

    **Example response:**
    ```json
    [
      {
        "id": 5,
        "name": "Comedy Cellar Presents",
        "date": "2026-10-04",
        "location": "Lincoln Park, Chicago",
        "category": "comedy",
        "url": "https://comedycellar.com/chicago",
        "source": "timeout_chicago"
      }
    ]
    ```
    """
    query_str = search.query.lower()
    limit = search.limit

    # Extract keywords and filters from natural language query
    keywords = _extract_keywords(query_str)
    category_filters = extract_category_concepts(query_str)
    date_range = _extract_date_range(query_str)

    # Build database query
    db_query = select(EventModel)

    # Combine keyword and category filters with OR
    filters = []

    # Filter by keywords
    if keywords:
        keyword_conditions = [
            EventModel.name.ilike(f"%{kw}%") for kw in keywords
        ]
        filters.append(or_(*keyword_conditions))

    # Filter by category
    if category_filters:
        condition = category_filter(
            EventModel.category, category_filters, EventModel.categories
        )
        if condition is not None:
            filters.append(condition)

    # Apply filters with OR logic (if we have any filters)
    if filters:
        db_query = db_query.filter(or_(*filters))

    # Never surface events that have already finished.
    db_query = db_query.filter(upcoming_events_filter())

    # Category, like neighborhood, is a structured filter rather than words in
    # the query string. Matched through the query text it had to appear in an
    # event's *title*, so picking "Health & Wellness" or "Cannabis" returned
    # nothing at all - no event is literally named that.
    if search.category:
        db_query = db_query.filter(_category_matches(search.category))

    # Neighborhood is a structured filter rather than a word in the query
    # string, so picking a tile narrows results exactly instead of relying on
    # the name happening to appear in an event title.
    if search.neighborhood:
        db_query = db_query.join(
            NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id
        ).filter(NeighborhoodModel.name == search.neighborhood)

    # Filter by date range (always apply if present)
    if date_range:
        start_date, end_date = date_range
        # Match events that *overlap* the window rather than start inside it.
        # A festival running Sep 25 - Nov 2 is on "this month" even though it
        # began before the range started. Dates are stored at midnight, so the
        # lower bound is the start of the day, otherwise a query run at 11am
        # hides everything happening today.
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

    # Soonest first, then name - shared with GET /events so the two surfaces
    # cannot drift. See `feed_order` for why name is not the primary key.
    db_query = (
        db_query.order_by(*feed_order())
        .offset(search.skip)
        .limit(limit)
    )
    result = await db.execute(db_query)
    results = result.scalars().all()
    return results


@router.get(
    "/search/categories",
    summary="Get available categories",
    responses=_ok({"categories": ["Arts & Culture", "Comedy", "Food & Drink",
                                  "Music", "Theatre & Performing Arts"]},
                  "Same list as GET /api/events/categories, wrapped in an "
                  "object for older clients."),
    description="List all event categories indexed in the database",
    tags=["Search"],
)
async def get_categories(db: AsyncSession = Depends(get_db)):
    """
    **Get all available event categories**

    Returns a list of all unique event categories in the database.

    **Example response:**
    ```json
    {
      "categories": [
        "music",
        "comedy",
        "theater",
        "sports",
        "art",
        "food",
        "film"
      ]
    }
    ```
    """
    result = await db.execute(
        select(func.distinct(EventModel.category)).filter(EventModel.category.isnot(None))
    )
    categories = result.scalars().all()
    return {"categories": categories}


@router.get(
    "/search/stats",
    summary="Get event statistics",
    description=(
        "Aggregate counts over upcoming events only, so the totals shrink as "
        "events pass and grow as scrapes run. `earliest_event` and "
        "`latest_event` are null when nothing is indexed."
    ),
    tags=["Search"],
    responses=_ok({"total_events": 3150, "unique_categories": 24,
                   "earliest_event": "2026-10-07", "latest_event": "2027-06-13"},
                  "Aggregates over upcoming events"),
)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """
    **Get statistics about future indexed events**

    Returns counts and date ranges for events from today onwards.

    **Example response:**
    ```json
    {
      "total_events": 1022,
      "unique_categories": 7,
      "earliest_event": "2026-10-01",
      "latest_event": "2026-12-31"
    }
    ```
    """
    future_filter = upcoming_events_filter()

    total_result = await db.execute(select(func.count(EventModel.id)).where(future_filter))
    total = total_result.scalar()

    categories_result = await db.execute(
        select(func.count(func.distinct(EventModel.category))).where(future_filter)
    )
    categories = categories_result.scalar()

    date_range_result = await db.execute(
        select(func.min(EventModel.date), func.max(EventModel.date)).where(future_filter)
    )
    date_range = date_range_result.first()

    return {
        "total_events": total,
        "unique_categories": categories,
        "earliest_event": date_range[0] if date_range else None,
        "latest_event": date_range[1] if date_range else None,
    }


def _extract_keywords(query: str) -> list[str]:
    """Extract search keywords from query"""
    # Shares the chatbot's stop list so UI search and the chat agent agree on
    # what counts as a search term - filler like "would"/"see" and temporal
    # words like "weekend" (already handled by _extract_date_range) are dropped.
    from app.ai.chatbot import STOP_WORDS

    words = [w.strip(".,!?;:'\"()") for w in query.lower().split()]
    keywords = [w for w in words if w and w not in STOP_WORDS and len(w) > 2]
    return list(dict.fromkeys(keywords))[:5]  # Limit to 5 keywords


def _extract_date_range(query: str) -> Optional[tuple[datetime, datetime]]:
    """Extract date range from natural language query"""
    now = datetime.now()
    query_lower = query.lower()

    # Check for "this weekend"
    if "this weekend" in query_lower or "this saturday" in query_lower or "this sunday" in query_lower:
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        saturday = now + timedelta(days=days_until_saturday)
        sunday = saturday + timedelta(days=1)
        return (saturday, sunday.replace(hour=23, minute=59, second=59))

    # Check for "this week"
    if "this week" in query_lower:
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        end_of_week = now + timedelta(days=7)
        return (now, end_of_week)

    # Check for "this month"
    if "this month" in query_lower:
        end_of_month = now.replace(day=1) + timedelta(days=32)
        end_of_month = end_of_month.replace(day=1) - timedelta(days=1)
        return (now, end_of_month.replace(hour=23, minute=59, second=59))

    # Check for "next week"
    if "next week" in query_lower:
        start = now + timedelta(days=7)
        end = start + timedelta(days=7)
        return (start, end)

    # Check for "tonight" or "today"
    if "tonight" in query_lower or "today" in query_lower:
        end = now.replace(hour=23, minute=59, second=59)
        return (now, end)

    return None


class ChatMessage(BaseModel):
    message: str
    thread_id: Optional[str] = None


class ChatStreamRequest(BaseModel):
    """Body for POST /api/chat."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"message": "comedy in Pilsen this weekend"},
                {"message": "plant workshops in Logan Square, Humboldt Park"},
                {"message": "free jazz tonight"},
                {
                    "message": "anything else that night?",
                    "thread_id": "3f9a1c84-7b2e-4d51-9a6f-1e2d3c4b5a60",
                },
            ]
        }
    )

    message: str = Field(
        ...,
        max_length=2000,
        description="A natural language question about Chicago events. A "
        "neighborhood, category or date phrase in here becomes a real filter.",
    )
    thread_id: Optional[str] = Field(
        None,
        description="Thread id from a previous `complete` frame, to continue "
        "that conversation. Omit to start a new one.",
    )


@router.post(
    "/chat/{thread_id}/close",
    summary="End a conversation",
    description=(
        "Marks a conversation finished, so it stops counting as active.\n\n"
        "Called when somebody starts a new chat. Without it a thread only ever "
        "ended by exhausting its budget, which almost nobody does - 270 "
        "conversations sat open, some of them days old.\n\n"
        "Idempotent: closing an already-closed thread is a no-op, and an "
        "unknown thread id is not an error. Nothing here is worth failing a "
        "page load over."
    ),
    responses={200: {"content": {"application/json": {
        "example": {"thread_id": "6782dca6-...", "closed": True}
    }}}},
)
async def close_chat_thread(thread_id: str, db: AsyncSession = Depends(get_db)):
    from app.ai.threads import close_thread

    try:
        changed = await close_thread(db, thread_id)
    except Exception:
        changed = False
    return {"thread_id": thread_id, "closed": changed}


@router.get(
    "/chat/greeting",
    summary="The assistant's opening message",
    description=(
        "The first message a new chat shows: who the assistant is, a Chicago "
        "fact, some example questions and what it is built on.\n\n"
        "Served from the API rather than hardcoded in the UI so the persona and "
        "the facts live in one place - `app.ai.persona` - and can change "
        "without a frontend rebuild. The fact rotates per request, so opening "
        "two chats does not show the same one."
    ),
    responses={
        200: {
            "description": "Markdown, ready to render.",
            "content": {
                "application/json": {
                    "example": {
                        "name": "Loopara",
                        "greeting": "🏙️ **Loopara** here - your Chicago events guide...",
                    }
                }
            },
        }
    },
)
async def chat_greeting(db: AsyncSession = Depends(get_db)):
    from app.ai.persona import ASSISTANT_NAME, greeting, whats_on_tonight

    # Real events, so the opener names things that are actually on rather than
    # describing a generic city. A failure here loses the examples, not the
    # greeting - the chat still has to open.
    try:
        tonight = await whats_on_tonight(db)
    except Exception:
        tonight = None

    return {"name": ASSISTANT_NAME, "greeting": greeting(tonight=tonight)}


@router.post(
    "/chat",
    summary="Ask Loopara (streaming)",
    description=(
        "Natural language event discovery, streamed as Server-Sent Events.\n\n"
        "**This is a stream, so 'Try it out' in this page will show raw SSE "
        "frames rather than JSON.** Each frame is `data: {...}` with an `event` "
        "field: `thinking` while the agent works, `events` when results are "
        "found, `response` for the written answer, `complete` with the token "
        "count, or `error`.\n\n"
        "Out-of-scope questions are rejected before any expensive call: an "
        "intent classifier runs first, and anything not about Chicago events "
        "comes back as a `response` frame with `out_of_scope: true`.\n\n"
        "A neighborhood named in the message is applied as a real filter, the "
        "same join `POST /api/search` uses, so 'comedy in Pilsen' constrains by "
        "location rather than searching for the word 'Pilsen' in event titles. "
        "Several can be named at once; naming none searches the whole city.\n\n"
        "Pass `thread_id` from a previous `complete` frame to continue a "
        "conversation. Threads are capped on both turns and tokens; once either "
        "runs out the reply says so instead of failing."
    ),
    tags=["Chat"],
    responses={200: {"description":
        "An SSE stream (`text/event-stream`). Frames arrive in order: one or "
        "more `thinking`, then optionally `events`, then `response`, then "
        "`complete`.",
        "content": {"text/event-stream": {"example":
            'data: {"event":"thinking","data":{"status":"Analyzing your question..."}}\n\n'
            'data: {"event":"events","data":{"events":[{"id":1247,'
            '"name":"Comedy Open Mic","date":"2026-10-07T00:00:00",'
            '"venue_name":"Cole\'s Bar","cost":"Free"}]}}\n\n'
            'data: {"event":"response","data":{"message":"There is a free comedy '
            'open mic at Cole\'s Bar tonight.","tokens":312}}\n\n'
            'data: {"event":"complete","data":{"thread_id":"a3f...","tokens_used":312}}\n\n'
        }}},
        **_VALIDATION_ERROR},
)
async def chat_endpoint(request: ChatStreamRequest):
    """
    **Stream AI-powered event search via SSE (Server-Sent Events)**

    Establishes a real-time streaming connection that emits events as the REACT agent reasons through:
    1. **chat_started** - Session initialized
    2. **thinking** - Agent analyzing query
    3. **tool_call** - Executing search (smart_search, db_search, or external API)
    4. **tool_result** - Received results
    5. **response** - Final answer with matched events
    6. **complete** - Session ended

    Supports multi-turn conversation with **thread_id** for context persistence.

    **Request body:**
    ```json
    {
      "message": "Music events this weekend under $50",
      "thread_id": null
    }
    ```

    **Stream output (SSE format):**
    ```
    event: chat_started
    data: {"thread_id": "chatb_abc123"}

    event: thinking
    data: {"status": "Analyzing query for music events..."}

    event: tool_call
    data: {"tool": "smart_search_expand", "args": {"query": "music events weekend"}}

    event: tool_result
    data: {"tool": "search_local_db", "result_count": 12, "snippet": "Found 12 music events"}

    event: response
    data: {"message": "🎵 Found 5 great music events this weekend..."}

    event: complete
    data: {"tokens_used": 1247, "remaining_turns": 4}
    ```

    **Token budget:** 4,000 tokens per session, 5 turns maximum
    **Rate limit:** 3 attempts before rate limiting
    """
    async def event_generator():
        executor = ChatExecutor()
        async for event in executor.execute(request.message, thread_id=request.thread_id):
            yield sse_event_formatter(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@analytics_router.get(
    "/analytics/telemetry",
    summary="OpenTelemetry metrics",
    responses=_ok({"timestamp": "2026-10-07T11:45:18.810877",
                   "metrics_data": "MetricsData(resource_metrics=[...])"},
                  "Counters and histograms as OpenTelemetry's own repr, not "
                  "parsed JSON - intended for eyeballing, not for machines."),
    description="Get current metrics snapshot for observability",
    tags=["Analytics"],
)
def get_telemetry():
    """
    **Get current OpenTelemetry metrics snapshot**

    Returns aggregated metrics about application performance and usage.

    **Example response:**
    ```json
    {
      "timestamp": "2026-10-01T13:53:43.067825Z",
      "message": "Metrics endpoint available (OpenTelemetry SDK configured)"
    }
    ```
    """
    return telemetry.get_metrics_snapshot()


@analytics_router.get(
    "/analytics/audit",
    summary="Query audit logs",
    responses={**_ok({"logs": [{"id": 1, "action": "chat_question",
                                "detail": "comedy in Pilsen",
                                "created_at": "2026-10-07T11:45:18"}],
                      "count": 1},
                     "Matching audit entries, newest first. `logs` is empty "
                     "when nothing matches."),
               **_VALIDATION_ERROR},
    description="Retrieve audit trail of operations with filtering",
    tags=["Analytics"],
)
async def get_audit_logs(
    operation: Optional[str] = Query(None, description="Filter by operation type (e.g., 'chat', 'search', 'security_blocked')"),
    status: Optional[str] = Query(None, description="Filter by status (e.g., 'success', 'error')"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum logs to return (1-1000)"),
    db: AsyncSession = Depends(get_db),
):
    """
    **Get audit logs with optional filtering**

    Retrieves audit trail for security, performance, and usage analysis.

    **Filters:**
    - **operation**: Type of operation (chat, search_db, search_google, security_blocked, etc.)
    - **status**: Operation status (success, error)
    - **limit**: Number of logs to return (default: 100, max: 1000)

    **Example response:**
    ```json
    {
      "logs": [
        {
          "id": 1,
          "thread_id": "chatb_xyz",
          "operation": "chat",
          "status": "success",
          "duration_ms": 1247,
          "tokens_used": 342,
          "created_at": "2026-10-01T13:52:00Z"
        }
      ],
      "count": 1
    }
    ```
    """
    query = select(AuditLogModel)

    if operation:
        query = query.filter(AuditLogModel.operation == operation)
    if status:
        query = query.filter(AuditLogModel.status == status)

    query = query.order_by(AuditLogModel.created_at.desc()).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()
    return {"logs": logs, "count": len(logs)}


@analytics_router.get(
    "/analytics/summary",
    summary="Analytics dashboard summary",
    responses=_ok({"total_sessions": 118, "completed_sessions": 0,
                   "active_sessions": 118, "total_turns": 118,
                   "total_tokens": 18163, "avg_tokens_per_session": 0,
                   "avg_turns_per_session": 0, "operations": []},
                  "Counters since the process started. A session counts as "
                  "active until it is explicitly completed, so a restart "
                  "leaves them active."),
    description="Get aggregate statistics for observability dashboard",
    tags=["Analytics"],
)
async def get_analytics_summary(db: AsyncSession = Depends(get_db)):
    """
    **Get summary statistics for observability dashboard**

    Provides high-level metrics about sessions, tokens, and operations.

    **Example response:**
    ```json
    {
      "total_sessions": 42,
      "completed_sessions": 38,
      "active_sessions": 4,
      "total_turns": 156,
      "total_tokens": 45821,
      "avg_tokens_per_session": 1206.34,
      "avg_turns_per_session": 4.1,
      "operations": [
        {"operation": "chat", "count": 156},
        {"operation": "search_db", "count": 320},
        {"operation": "search_google", "count": 12}
      ]
    }
    ```
    """
    total_sessions_result = await db.execute(select(func.count(ChatThreadModel.id)))
    total_sessions = total_sessions_result.scalar()

    completed_sessions_result = await db.execute(
        select(func.count(ChatThreadModel.id)).filter(ChatThreadModel.status == "completed")
    )
    completed_sessions = completed_sessions_result.scalar()

    total_turns_result = await db.execute(select(func.sum(ChatThreadModel.turn_count)))
    total_turns = total_turns_result.scalar() or 0

    total_tokens_result = await db.execute(select(func.sum(ChatThreadModel.total_tokens)))
    total_tokens = total_tokens_result.scalar() or 0

    avg_tokens_per_session = (
        total_tokens / completed_sessions if completed_sessions > 0 else 0
    )
    avg_turns_per_session = (
        total_turns / completed_sessions if completed_sessions > 0 else 0
    )

    # Get operation counts from audit logs
    operations_result = await db.execute(
        select(AuditLogModel.operation, func.count(AuditLogModel.id)).group_by(AuditLogModel.operation)
    )
    operations = operations_result.all()

    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "active_sessions": total_sessions - completed_sessions,
        "total_turns": total_turns,
        "total_tokens": total_tokens,
        "avg_tokens_per_session": round(avg_tokens_per_session, 2),
        "avg_turns_per_session": round(avg_turns_per_session, 2),
        "operations": [{"operation": op, "count": cnt} for op, cnt in operations],
    }


@analytics_router.get(
    "/analytics/security",
    summary="Security metrics dashboard",
    responses=_ok({"security_events": {"blocked_requests": 0,
                                       "outputs_sanitized": 0,
                                       "out_of_scope_questions": 0},
                   "active_injection_attempts": {}, "blocked_sessions": [],
                   "recent_blocks": []},
                  "Prompt-injection and sanitization counters. All zero means "
                  "nothing has been blocked since startup."),
    description="Real-time security monitoring and threat detection metrics",
    tags=["Analytics"],
)
async def get_security_summary(db: AsyncSession = Depends(get_db)):
    """
    **Get security metrics and suspicious activity summary**

    Monitors prompt injection attempts, output sanitization, and threat metrics.

    **Metrics include:**
    - **blocked_requests**: Requests blocked by security filters
    - **outputs_sanitized**: Responses sanitized to remove sensitive data
    - **out_of_scope_questions**: Questions rejected as out of scope
    - **active_injection_attempts**: Real-time threat tracking
    - **blocked_sessions**: Sessions blocked due to rate limiting
    - **recent_blocks**: Last 10 blocked requests

    **Example response:**
    ```json
    {
      "security_events": {
        "blocked_requests": 3,
        "outputs_sanitized": 5,
        "out_of_scope_questions": 12
      },
      "active_injection_attempts": {
        "session_xyz": 2
      },
      "blocked_sessions": [],
      "recent_blocks": [
        {
          "timestamp": "2026-10-01T13:50:00Z",
          "thread_id": "chatb_123",
          "reason": "SQL injection pattern detected"
        }
      ]
    }
    ```
    """
    # Get security events from audit logs
    blocked_result = await db.execute(
        select(func.count(AuditLogModel.id)).filter(AuditLogModel.operation == "security_blocked")
    )
    blocked = blocked_result.scalar()

    sanitized_result = await db.execute(
        select(func.count(AuditLogModel.id)).filter(AuditLogModel.operation == "output_sanitized")
    )
    sanitized = sanitized_result.scalar()

    out_of_scope_result = await db.execute(
        select(func.count(AuditLogModel.id)).filter(AuditLogModel.operation == "out_of_scope_question")
    )
    out_of_scope = out_of_scope_result.scalar()

    # Get recent blocked requests
    recent_blocks_result = await db.execute(
        select(AuditLogModel).filter(AuditLogModel.operation == "security_blocked")
        .order_by(AuditLogModel.created_at.desc()).limit(10)
    )
    recent_blocks = recent_blocks_result.scalars().all()

    return {
        "security_events": {
            "blocked_requests": blocked,
            "outputs_sanitized": sanitized,
            "out_of_scope_questions": out_of_scope,
        },
        "active_injection_attempts": dict(rate_limiter.injection_attempts),
        "blocked_sessions": [
            session_id
            for session_id, count in rate_limiter.injection_attempts.items()
            if count >= rate_limiter.BLOCK_THRESHOLD
        ],
        "recent_blocks": [
            {
                "timestamp": log.created_at.isoformat(),
                "thread_id": log.thread_id,
                "reason": log.metadata,
            }
            for log in recent_blocks
        ],
    }


@router.post(
    "/venue-events/refresh",
    summary="Fetch and persist venue events",
    responses={**_ok({"status": "success", "new_events": 43},
                     "Scrape finished. `new_events` counts rows inserted; events "
                     "already stored are updated in place and not counted."),
               500: {"description": "The scrape or the database write failed; the "
                                    "message carries the underlying error.",
                     "content": {"application/json": {
                         "example": {"detail": "database is locked"}}}}},
    description="Scrape entertainment venues and persist their events to the database",
    tags=["Admin"],
)
async def refresh_venue_events(db: AsyncSession = Depends(get_db)):
    """
    **Fetch events from entertainment venues and persist to database**

    This endpoint triggers a scrape of all registered venue websites (Second City,
    Steppenwolf, iO Theater, etc.) and persists new events to the database.

    - Only adds new events that don't already exist
    - Respects API rate limits
    - Returns count of new events added

    **Example:**
    ```bash
    curl -X POST http://localhost:8000/api/venue-events/refresh
    ```
    """
    from scrapers.venue_events_persist import fetch_and_persist_venue_events

    logger.info("Starting venue events refresh")
    try:
        count = await fetch_and_persist_venue_events(db)
        logger.info(f"Venue refresh complete: {count} new events")

        # Re-embed so the new events are semantically searchable. A full
        # rebuild takes well under a second, so there is nothing to optimize.
        if count:
            try:
                from app.ai.semantic_index import event_index

                await event_index.rebuild(db)
            except Exception as e:
                logger.warning(f"Semantic index refresh failed: {e}")

        return {"status": "success", "new_events": count}
    except Exception as e:
        logger.error(f"Venue events refresh failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
