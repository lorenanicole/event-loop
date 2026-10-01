from datetime import datetime
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, Index, ForeignKey, Float
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class EventModel(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True)
    date = Column(DateTime, index=True)
    category = Column(String(100), index=True)
    details = Column(Text, nullable=True)
    origination_url = Column(String(500), unique=True)
    date_retrieved = Column(DateTime, default=datetime.utcnow)
    source = Column(String(50), default="unknown", index=True)  # do312, yourchicagoguide, ticketmaster, etc.
    cost = Column(String(100), nullable=True)  # "Free", "$25", "$15-30", "Donation", etc.
    age_range = Column(String(100), nullable=True)  # "All ages", "18+", "21+", "13+", etc.

    __table_args__ = (
        Index("idx_date_category", "date", "category"),
        Index("idx_name_search", "name"),
        Index("idx_source", "source"),
        Index("idx_cost", "cost"),
        Index("idx_age_range", "age_range"),
    )


class ChatThreadModel(Base):
    """Represents a conversation thread (session)."""
    __tablename__ = "chat_threads"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    total_tokens = Column(Integer, default=0)
    turn_count = Column(Integer, default=0)  # Number of user-assistant exchanges
    status = Column(String(20), default="active", index=True)  # "active", "closed", "completed"

    messages = relationship("ChatMessageModel", back_populates="thread", cascade="all, delete-orphan")


class ChatMessageModel(Base):
    """Represents a single message in a conversation thread."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String(36), ForeignKey("chat_threads.id"), index=True)
    role = Column(String(20), index=True)  # "user" or "assistant"
    content = Column(Text)
    token_count = Column(Integer, default=0)
    tool_calls_made = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    thread = relationship("ChatThreadModel", back_populates="messages")

    __table_args__ = (
        Index("idx_thread_created", "thread_id", "created_at"),
    )


class AuditLogModel(Base):
    """Audit trail for observability: tracks operations, metrics, and performance."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String(36), ForeignKey("chat_threads.id"), index=True, nullable=True)
    operation = Column(String(50), index=True)  # "chat_created", "question_asked", "tool_call", "completion"
    status = Column(String(20), index=True)  # "success", "failure", "timeout"
    duration_ms = Column(Float)  # Operation duration in milliseconds
    tokens_used = Column(Integer, default=0)
    metadata = Column(Text)  # JSON string with extra context
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_operation_created", "operation", "created_at"),
        Index("idx_status_created", "status", "created_at"),
        Index("idx_thread_operation", "thread_id", "operation"),
    )


class MetricsModel(Base):
    """Time-series metrics storage for observability dashboard."""
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String(100), index=True)  # e.g., "http.server.request.duration", "chat.sessions.created"
    metric_type = Column(String(20), index=True)  # "counter", "gauge", "histogram"
    value = Column(Float)  # Current value
    attributes = Column(Text)  # JSON string with labels/tags
    unit = Column(String(50), nullable=True)  # e.g., "ms", "tokens", "requests"
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_metric_timestamp", "metric_name", "timestamp"),
        Index("idx_metric_type", "metric_type", "timestamp"),
    )
