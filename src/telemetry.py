"""
OpenTelemetry setup for observability.
Tracks: session counts, question counts, operation latencies, token usage.
Persists metrics to database for historical analysis.
"""

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Database session will be injected at runtime
_db_session: Optional[object] = None

# Initialize metrics with in-memory reader for local development
reader = InMemoryMetricReader()
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("chicago-events-chatbot", version="0.1.0")

# Counters
chat_sessions_created = meter.create_counter(
    name="chat.sessions.created",
    description="Number of chat sessions created",
    unit="1",
)

chat_sessions_completed = meter.create_counter(
    name="chat.sessions.completed",
    description="Number of chat sessions completed successfully",
    unit="1",
)

questions_asked = meter.create_counter(
    name="chat.questions.asked",
    description="Total number of questions asked across all sessions",
    unit="1",
)

tool_calls_made = meter.create_counter(
    name="chat.tool_calls",
    description="Number of tool calls executed",
    unit="1",
)

tokens_used = meter.create_counter(
    name="chat.tokens.used",
    description="Total tokens consumed",
    unit="1",
)

# Histograms
session_duration = meter.create_histogram(
    name="chat.session.duration",
    description="Duration of chat sessions in milliseconds",
    unit="ms",
)

operation_latency = meter.create_histogram(
    name="chat.operation.latency",
    description="Latency of individual operations (tool calls, agent reasoning, etc)",
    unit="ms",
)

tokens_per_session = meter.create_histogram(
    name="chat.tokens.per_session",
    description="Tokens consumed per session",
    unit="1",
)

questions_per_session = meter.create_histogram(
    name="chat.questions.per_session",
    description="Number of questions per session",
    unit="1",
)


def record_session_created():
    """Record a new chat session."""
    chat_sessions_created.add(1, {})


def record_session_completed(tokens: int, question_count: int, duration_ms: float):
    """Record a completed chat session."""
    chat_sessions_completed.add(1, {})
    tokens_used.add(tokens, {})
    questions_per_session.record(question_count, {})
    session_duration.record(duration_ms, {})


def record_question_asked():
    """Record a question asked."""
    questions_asked.add(1, {})


def record_tool_call(operation: str, duration_ms: float, tokens: int = 0):
    """Record a tool call execution."""
    tool_calls_made.add(1, {"tool": operation})
    operation_latency.record(duration_ms, {"operation": operation})
    if tokens > 0:
        tokens_used.add(tokens, {})


def set_db_session(db_session: object) -> None:
    """Set the database session for metric persistence."""
    global _db_session
    _db_session = db_session


def persist_metrics_to_db() -> None:
    """Persist current metrics to database for historical tracking."""
    if not _db_session:
        logger.warning("Database session not available for metrics persistence")
        return

    try:
        from src.database.models import MetricsModel

        metrics_data = reader.get_metrics_data()
        if not metrics_data or not metrics_data.resource_metrics:
            return

        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    for data_point in metric.data.data_points:
                        # Extract attributes/labels
                        attributes_json = json.dumps(
                            {k: str(v) for k, v in (data_point.attributes or {}).items()}
                        )

                        # Create metric record
                        metric_record = MetricsModel(
                            metric_name=metric.name,
                            metric_type=type(metric.data).__name__.lower(),
                            value=getattr(data_point, "value", 0),
                            attributes=attributes_json,
                            unit=metric.unit,
                            timestamp=datetime.utcnow(),
                        )
                        _db_session.add(metric_record)

        _db_session.commit()
        logger.info("Metrics persisted to database")
    except Exception as e:
        logger.error(f"Error persisting metrics to database: {e}")
        _db_session.rollback()


def get_metrics_snapshot() -> dict:
    """
    Get current metrics snapshot for debugging/dashboards.
    Also persists metrics to database.
    """
    try:
        # Persist to database
        persist_metrics_to_db()

        # Return current snapshot
        metrics_data = reader.get_metrics_data()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics_data": str(metrics_data),
            "resource_metrics": len(metrics_data.resource_metrics) if metrics_data else 0,
            "persisted": True,
        }
    except Exception as e:
        logger.error(f"Error getting metrics snapshot: {e}")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }
