import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from src.database import get_db
from src.database.models import EventModel, ChatThreadModel, AuditLogModel
from src.models import Event, EventSearch
from src.ai.executor import ChatExecutor, sse_event_formatter
from src import telemetry
from src.security import rate_limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", response_model=list[Event])
def list_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all events with pagination"""
    events = db.query(EventModel).offset(skip).limit(limit).all()
    return events


@router.get("/events/{event_id}", response_model=Event)
def get_event(event_id: int, db: Session = Depends(get_db)):
    """Get a specific event by ID"""
    event = db.query(EventModel).filter(EventModel.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/search", response_model=list[Event])
def search_events(
    search: EventSearch,
    db: Session = Depends(get_db),
):
    """
    Search events with natural language query.
    Examples:
    - "music events this weekend"
    - "comedy shows in chicago next week"
    - "18+ events this month"
    """
    query_str = search.query.lower()
    limit = search.limit

    # Extract keywords and filters from natural language query
    keywords = _extract_keywords(query_str)
    category_filters = _extract_categories(query_str)
    date_range = _extract_date_range(query_str)

    # Build database query
    db_query = db.query(EventModel)

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

    results = db_query.limit(limit).all()
    return results


@router.get("/search/categories")
def get_categories(db: Session = Depends(get_db)):
    """Get all available event categories"""
    categories = db.query(
        func.distinct(EventModel.category)
    ).filter(EventModel.category.isnot(None)).all()
    return {"categories": [cat[0] for cat in categories]}


@router.get("/search/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get statistics about indexed events"""
    total = db.query(func.count(EventModel.id)).scalar()
    categories = db.query(
        func.count(func.distinct(EventModel.category))
    ).scalar()
    date_range = db.query(
        func.min(EventModel.date),
        func.max(EventModel.date),
    ).first()

    return {
        "total_events": total,
        "unique_categories": categories,
        "earliest_event": date_range[0],
        "latest_event": date_range[1],
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
    message: str
    thread_id: Optional[str] = None


@router.post("/chat")
async def chat_endpoint(request: ChatStreamRequest):
    """
    Stream AI-powered event search via SSE.
    Returns a StreamingResponse that emits chat_started -> thinking -> tool_call* -> response -> complete events.
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


@router.get("/analytics/telemetry")
def get_telemetry():
    """Get current OpenTelemetry metrics snapshot."""
    return telemetry.get_metrics_snapshot()


@router.get("/analytics/audit")
def get_audit_logs(
    operation: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get audit logs with optional filtering by operation or status."""
    query = db.query(AuditLogModel)

    if operation:
        query = query.filter(AuditLogModel.operation == operation)
    if status:
        query = query.filter(AuditLogModel.status == status)

    logs = query.order_by(AuditLogModel.created_at.desc()).limit(limit).all()
    return {"logs": logs, "count": len(logs)}


@router.get("/analytics/summary")
def get_analytics_summary(db: Session = Depends(get_db)):
    """Get summary statistics for observability dashboard."""
    total_sessions = db.query(func.count(ChatThreadModel.id)).scalar()
    completed_sessions = db.query(func.count(ChatThreadModel.id)).filter(
        ChatThreadModel.status == "completed"
    ).scalar()
    total_turns = db.query(func.sum(ChatThreadModel.turn_count)).scalar() or 0
    total_tokens = db.query(func.sum(ChatThreadModel.total_tokens)).scalar() or 0

    avg_tokens_per_session = (
        total_tokens / completed_sessions if completed_sessions > 0 else 0
    )
    avg_turns_per_session = (
        total_turns / completed_sessions if completed_sessions > 0 else 0
    )

    # Get operation counts from audit logs
    operations = db.query(
        AuditLogModel.operation,
        func.count(AuditLogModel.id).label("count"),
    ).group_by(AuditLogModel.operation).all()

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


@router.get("/analytics/security")
def get_security_summary(db: Session = Depends(get_db)):
    """Get security metrics and suspicious activity summary."""
    # Get security events from audit logs
    blocked = db.query(func.count(AuditLogModel.id)).filter(
        AuditLogModel.operation == "security_blocked"
    ).scalar()

    sanitized = db.query(func.count(AuditLogModel.id)).filter(
        AuditLogModel.operation == "output_sanitized"
    ).scalar()

    out_of_scope = db.query(func.count(AuditLogModel.id)).filter(
        AuditLogModel.operation == "out_of_scope_question"
    ).scalar()

    # Get recent blocked requests
    recent_blocks = db.query(AuditLogModel).filter(
        AuditLogModel.operation == "security_blocked"
    ).order_by(AuditLogModel.created_at.desc()).limit(10).all()

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
