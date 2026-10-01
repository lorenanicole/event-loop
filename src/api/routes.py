import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, func, select

from src.database import get_db
from src.database.models import EventModel, ChatThreadModel, AuditLogModel
from src.models import Event, EventSearch
from src.ai.executor import ChatExecutor, sse_event_formatter
from src import telemetry
from src.security import rate_limiter
from src.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["events"])
analytics_router = APIRouter(prefix="", tags=["analytics"])


@router.get(
    "/events",
    response_model=list[Event],
    summary="List all events",
    description="Retrieve paginated list of all indexed Chicago events from the database",
    tags=["Events"],
)
async def list_events(
    skip: int = Query(0, ge=0, description="Number of events to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum events to return (1-100)"),
    db: AsyncSession = Depends(get_db),
):
    """
    **List all events with pagination**

    Returns a paginated list of Chicago events from the database.

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
    result = await db.execute(select(EventModel).offset(skip).limit(limit))
    events = result.scalars().all()
    return events


@router.get(
    "/events/{event_id}",
    response_model=Event,
    summary="Get event by ID",
    description="Retrieve detailed information about a specific event",
    tags=["Events"],
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
    category_filters = _extract_categories(query_str)
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
        category_conditions = [
            EventModel.category.ilike(cat) for cat in category_filters
        ]
        filters.append(or_(*category_conditions))

    # Apply filters with OR logic (if we have any filters)
    if filters:
        db_query = db_query.filter(or_(*filters))

    # Filter by date range (always apply if present)
    if date_range:
        start_date, end_date = date_range
        db_query = db_query.filter(
            and_(
                EventModel.date >= start_date,
                EventModel.date <= end_date,
            )
        )

    db_query = db_query.limit(limit)
    result = await db.execute(db_query)
    results = result.scalars().all()
    return results


@router.get(
    "/search/categories",
    summary="Get available categories",
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
    description="Retrieve aggregate statistics about indexed events",
    tags=["Search"],
)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """
    **Get statistics about indexed events**

    Returns counts and date ranges for all events in the database.

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
    total_result = await db.execute(select(func.count(EventModel.id)))
    total = total_result.scalar()

    categories_result = await db.execute(
        select(func.count(func.distinct(EventModel.category)))
    )
    categories = categories_result.scalar()

    date_range_result = await db.execute(
        select(func.min(EventModel.date), func.max(EventModel.date))
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
    # Remove common words
    stop_words = {
        "the", "a", "an", "and", "or", "is", "are", "in", "on", "at",
        "this", "that", "these", "those", "what", "when", "where", "why",
        "find", "get", "search", "show", "tell", "give", "all", "want",
        "looking", "events", "event", "i", "want", "to", "for"
    }

    words = query.split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    return keywords[:5]  # Limit to 5 keywords


def _extract_categories(query: str) -> list[str]:
    """Extract event categories from query"""
    category_keywords = {
        "music": ["music", "concert", "band", "dj", "acoustic"],
        "comedy": ["comedy", "stand-up", "standup", "laugh"],
        "theater": ["theater", "theatre", "play", "drama", "broadway"],
        "sports": ["sports", "game", "match", "tournament", "athletic"],
        "art": ["art", "gallery", "exhibition", "installation", "sculpture"],
        "food": ["food", "dining", "restaurant", "chef", "cooking"],
        "film": ["film", "movie", "cinema", "screening"],
    }

    found_categories = []
    for category, keywords in category_keywords.items():
        if any(kw in query for kw in keywords):
            found_categories.append(category)

    return found_categories


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
    message: str = Field(..., description="User message or question", max_length=2000)
    thread_id: Optional[str] = Field(None, description="Session thread ID for conversation context")


@router.post(
    "/chat",
    summary="AI-powered event search with streaming",
    description="Stream REACT agent reasoning for natural language event discovery via Server-Sent Events",
    tags=["Chat"],
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


class ChatRequest(BaseModel):
    """Chat message request with optional thread ID for conversation continuity."""
    message: str = Field(..., description="User's natural language query")
    thread_id: Optional[str] = Field(None, description="Thread ID for multi-turn conversations")


@router.post(
    "/chat",
    summary="AI-powered event chat with SSE streaming",
    description="Send natural language queries and receive event recommendations via Server-Sent Events (SSE)",
    tags=["Chat"],
)
async def chat(request: ChatRequest):
    """
    **Stream AI-powered chat responses for event discovery**

    Uses PydanticAI REACT agent with Claude to understand questions and find events.

    **Request:**
    - `message`: Natural language query (e.g., "free jazz concerts this weekend")
    - `thread_id` (optional): Reuse conversation thread for multi-turn chat

    **Response:** Server-Sent Events (SSE) stream with events:
    - `chat_started`: Thread initialized
    - `thinking`: Agent reasoning status
    - `tool_call`: Searching database/web
    - `tool_result`: Results found
    - `response`: Final message with event summary
    - `complete`: Chat finished
    - `error`: Error occurred

    **Example:**
    ```bash
    curl -X POST http://localhost:8000/api/chat \\
      -H "Content-Type: application/json" \\
      -d '{"message": "free events tonight"}'
    ```
    """
    logger.info(f"Chat request: message='{request.message[:50]}...' thread_id={request.thread_id}")
    executor = ChatExecutor()

    async def event_stream():
        """Stream events from executor"""
        try:
            async for event in executor.execute(request.message, request.thread_id):
                logger.debug(f"Chat event: {event.event}")
                yield sse_event_formatter(event)
        except Exception as e:
            logger.error(f"Chat execution error: {type(e).__name__}: {e}", exc_info=True)
            from src.ai.executor import StreamEvent
            yield sse_event_formatter(StreamEvent(
                event="error",
                data={"error": str(e)}
            ))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
