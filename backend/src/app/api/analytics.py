"""Operational telemetry, audit, analytics, and security endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import telemetry
from app.security import rate_limiter
from shared.database import get_db
from shared.database.models import AuditLogModel, ChatThreadModel

router = APIRouter()


@router.get("/analytics/telemetry", summary="OpenTelemetry metrics", tags=["Analytics"])
def get_telemetry():
    """Return the in-memory OpenTelemetry snapshot."""
    return telemetry.get_metrics_snapshot()


@router.get("/analytics/audit", summary="Query audit logs", tags=["Analytics"])
async def get_audit_logs(
    operation: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLogModel)
    if operation:
        query = query.where(AuditLogModel.operation == operation)
    if status:
        query = query.where(AuditLogModel.status == status)
    result = await db.execute(query.order_by(AuditLogModel.created_at.desc()).limit(limit))
    logs = result.scalars().all()
    return {"logs": logs, "count": len(logs)}


@router.get("/analytics/summary", summary="Analytics dashboard summary", tags=["Analytics"])
async def get_analytics_summary(db: AsyncSession = Depends(get_db)):
    total_sessions = await db.scalar(select(func.count(ChatThreadModel.id))) or 0
    completed_sessions = (
        await db.scalar(
            select(func.count(ChatThreadModel.id)).where(ChatThreadModel.status == "completed")
        )
        or 0
    )
    total_turns = await db.scalar(select(func.sum(ChatThreadModel.turn_count))) or 0
    total_tokens = await db.scalar(select(func.sum(ChatThreadModel.total_tokens))) or 0

    operations = (
        await db.execute(
            select(AuditLogModel.operation, func.count(AuditLogModel.id)).group_by(
                AuditLogModel.operation
            )
        )
    ).all()

    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "active_sessions": total_sessions - completed_sessions,
        "total_turns": total_turns,
        "total_tokens": total_tokens,
        "avg_tokens_per_session": round(total_tokens / completed_sessions, 2)
        if completed_sessions
        else 0,
        "avg_turns_per_session": round(total_turns / completed_sessions, 2)
        if completed_sessions
        else 0,
        "operations": [{"operation": op, "count": count} for op, count in operations],
    }


@router.get("/analytics/security", summary="Security metrics dashboard", tags=["Analytics"])
async def get_security_summary(db: AsyncSession = Depends(get_db)):
    blocked = (
        await db.scalar(
            select(func.count(AuditLogModel.id)).where(
                AuditLogModel.operation == "security_blocked"
            )
        )
        or 0
    )
    sanitized = (
        await db.scalar(
            select(func.count(AuditLogModel.id)).where(
                AuditLogModel.operation == "output_sanitized"
            )
        )
        or 0
    )
    out_of_scope = (
        await db.scalar(
            select(func.count(AuditLogModel.id)).where(
                AuditLogModel.operation == "out_of_scope_question"
            )
        )
        or 0
    )
    recent_blocks = (
        (
            await db.execute(
                select(AuditLogModel)
                .where(AuditLogModel.operation == "security_blocked")
                .order_by(AuditLogModel.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

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
                "timestamp": record.created_at.isoformat(),
                "thread_id": record.thread_id,
                "reason": record.metadata,
            }
            for record in recent_blocks
        ],
    }
