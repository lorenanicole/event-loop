import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import router as analytics_router  # noqa: F401 — re-exported via __init__
from app.api.chat import router as chat_router
from app.chat.search_query import extract_date_range as _extract_date_range
from app.chat.search_query import extract_keywords as _extract_keywords
from app.logging import get_logger
from app.security import require_admin_key
from shared.categories import category_filter, extract_category_concepts
from shared.database import feed_order, get_db, start_of_day, upcoming_events_filter
from shared.database.models import EventModel, NeighborhoodModel
from shared.schemas import Event, EventSearch

logger = get_logger(__name__)
# No router-level tags: each endpoint declares its own, and a tag here
# would be added on top, listing every operation twice in /docs.
router = APIRouter(prefix="/api")
router.include_router(chat_router)


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
    return {
        200: {"description": description, "content": {"application/json": {"example": example}}}
    }


_VALIDATION_ERROR = {
    422: {
        "description": "A query or body value failed validation - for instance "
        "`limit` outside 1-100, or a missing `query`.",
        "content": {
            "application/json": {
                "example": {
                    "detail": [
                        {
                            "loc": ["query", "limit"],
                            "msg": "Input should be less than or equal to 100",
                            "type": "less_than_equal",
                        }
                    ]
                }
            }
        },
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


@router.post(
    "/venue-events/refresh",
    summary="Fetch and persist venue events",
    include_in_schema=False,
    dependencies=[Depends(require_admin_key)],
    responses={
        **_ok(
            {"status": "success", "new_events": 43},
            "Scrape finished. `new_events` counts added event rows.",
        ),
        500: {
            "description": "The scrape failed.",
            "content": {"application/json": {"example": {"detail": "venue refresh failed"}}},
        },
    },
    description="Scrape configured Chicago venues and add their events to the database.",
    tags=["Admin"],
)
async def refresh_venue_events(db: AsyncSession = Depends(get_db)):
    """Run the configured venue scrapers and report how many rows were added."""
    from scrapers.venue.chicago_events_scraper import scrape_chicago_events

    before = await db.scalar(select(func.count(EventModel.id))) or 0
    await db.commit()
    try:
        await scrape_chicago_events()
        after = await db.scalar(select(func.count(EventModel.id))) or 0
        inserted = max(0, after - before)

        if inserted:
            try:
                from app.chat.semantic_index import event_index

                await event_index.rebuild(db)
            except Exception as exc:
                logger.warning("Semantic index refresh failed: %s", exc)

        return {"status": "success", "new_events": inserted}
    except Exception as exc:
        logger.exception("Venue events refresh failed: %s", exc)
        raise HTTPException(status_code=500, detail="Venue event refresh failed") from exc


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
    responses={
        **_ok(
            [_EVENT_EXAMPLE, _RUN_EXAMPLE],
            "Events, soonest first. Empty array if `skip` is past the end.",
        ),
        **_VALIDATION_ERROR,
    },
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
    responses=_ok(
        [
            "Arts & Culture",
            "Comedy",
            "Food & Drink",
            "Health & Wellness",
            "Music",
            "Theatre & Performing Arts",
            "comedy",
            "music",
            "theater",
        ],
        "Categories with upcoming events. Casing and wording are "
        "inconsistent because each source labels its own events; "
        "'Music' and 'music' are different sources, not duplicates.",
    ),
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
        if cat_lower in ["undefined", "miscellaneous", "events", "other", "online search"]:
            return False

        date_patterns = [
            r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
            r"^\d+\s*,",
            r"until\s+",
            r"\d{4}",
        ]
        has_date = any(re.search(pattern, cat_lower, re.IGNORECASE) for pattern in date_patterns)
        has_digit = bool(re.search(r"\d", cat_lower))
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
    responses={
        **_ok(
            [
                {"name": "Loop", "event_count": 379},
                {"name": "Lincoln Park", "event_count": 295},
                {"name": "Wicker Park", "event_count": 294},
                {"name": "Pilsen", "event_count": 172},
            ],
            "Neighborhoods with at least `min_events` upcoming events",
        ),
        **_VALIDATION_ERROR,
    },
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
    responses=_ok(
        {
            "categories": [
                {"name": "Music", "event_count": 1912},
                {"name": "Theater", "event_count": 209},
            ],
            "neighborhoods": [
                {"name": "Loop", "event_count": 379},
                {"name": "Lincoln Park", "event_count": 295},
            ],
        },
        "Counts for each facet, busiest first",
    ),
)
async def get_filter_counts(
    category: str | None = Query(
        None, description="Restrict the neighborhood counts to this category"
    ),
    neighborhood: str | None = Query(
        None, description="Restrict the category counts to this neighborhood"
    ),
    timeframe: str | None = Query(
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
                        and_(EventModel.date_end.is_(None), EventModel.date >= window_start),
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
    # returns. json_array_elements_text unnests the JSON array to individual
    # text rows (Postgres equivalent of SQLite's json_each). Events predating
    # the categories column fall back to their single category string wrapped
    # in a one-element JSON array via json_build_array. Returning text means
    # GROUP BY works without needing an equality operator on json.
    label = func.json_array_elements_text(
        func.coalesce(EventModel.categories, func.json_build_array(EventModel.category))
    ).column_valued("value", joins_implicitly=True)
    category_stmt = (
        constrain(
            select(label, func.count(EventModel.id).label("n"))
            .outerjoin(NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id)
            .where(EventModel.category.isnot(None)),
            with_category=False,
            with_neighborhood=True,
        )
        .group_by(label)
        .order_by(func.count(EventModel.id).desc())
    )

    # Neighborhoods: narrowed by category and timeframe, not by neighborhood.
    neighborhood_stmt = (
        constrain(
            select(NeighborhoodModel.name, func.count(EventModel.id).label("n")).join(
                EventModel, EventModel.neighborhood_id == NeighborhoodModel.id
            ),
            with_category=True,
            with_neighborhood=False,
        )
        .group_by(NeighborhoodModel.name)
        .order_by(func.count(EventModel.id).desc())
    )

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
    responses={
        **_ok(_EVENT_EXAMPLE, "The requested event"),
        404: {
            "description": "No event with that id.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
        **_VALIDATION_ERROR,
    },
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
    responses={
        **_ok(
            [_EVENT_EXAMPLE],
            "Matching events, soonest first. An empty array means "
            "nothing matched - it is not an error.",
        ),
        **_VALIDATION_ERROR,
    },
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
        keyword_conditions = [EventModel.name.ilike(f"%{kw}%") for kw in keywords]
        filters.append(or_(*keyword_conditions))

    # Filter by category
    if category_filters:
        condition = category_filter(EventModel.category, category_filters, EventModel.categories)
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
    db_query = db_query.order_by(*feed_order()).offset(search.skip).limit(limit)
    result = await db.execute(db_query)
    results = result.scalars().all()
    return results


@router.get(
    "/search/categories",
    summary="Get available categories",
    responses=_ok(
        {
            "categories": [
                "Arts & Culture",
                "Comedy",
                "Food & Drink",
                "Music",
                "Theatre & Performing Arts",
            ]
        },
        "Same list as GET /api/events/categories, wrapped in an object for older clients.",
    ),
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
    responses=_ok(
        {
            "total_events": 3150,
            "unique_categories": 24,
            "earliest_event": "2026-10-07",
            "latest_event": "2027-06-13",
        },
        "Aggregates over upcoming events",
    ),
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


# _extract_keywords and _extract_date_range are imported from app.chat.search_query
# at the top of this file. The local copies that used to live here have been
# removed: they duplicated logic that already existed there and diverged silently
# (missing contraction stripping, a stale STOP_WORDS import, slightly different
# date handling). Using the shared versions keeps the UI/API search and the chat
# agent consistent.
