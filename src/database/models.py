from datetime import datetime
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, Index, ForeignKey, Float, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class NeighborhoodModel(Base):
    """Chicago neighborhood with metadata for event discovery."""
    __tablename__ = "neighborhoods"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)  # "Wicker Park", "Loop", etc.
    official_name = Column(String(100), nullable=True)  # Official City of Chicago name
    description = Column(Text, nullable=True)  # Neighborhood description
    entertainment_level = Column(String(20), nullable=True)  # "high", "medium", "low"
    is_researched = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    venues = relationship("VenueModel", back_populates="neighborhood", cascade="all, delete-orphan")
    events = relationship("EventModel", back_populates="neighborhood")

    __table_args__ = (
        Index("idx_name_researched", "name", "is_researched"),
    )


class VenueModel(Base):
    """Entertainment venue within a neighborhood."""
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)
    neighborhood_id = Column(Integer, ForeignKey("neighborhoods.id"), index=True)
    name = Column(String(255), index=True)  # "Rosa's Lounge", "Steppenwolf", etc.
    category = Column(String(50), index=True)  # "music", "theater", "comedy", "cinema", "other"
    address = Column(String(255), nullable=True)
    website_url = Column(String(500), nullable=True)
    event_page_url = Column(String(500), nullable=True)  # Direct URL to events/calendar page
    phone = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    capacity = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    scraper_status = Column(String(50), default="not_started", index=True)  # "not_started", "in_progress", "working", "failed"
    last_scraped_at = Column(DateTime, nullable=True)
    events_count = Column(Integer, default=0)  # Number of events extracted from this venue
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    neighborhood = relationship("NeighborhoodModel", back_populates="venues")
    events = relationship("EventModel", back_populates="venue")

    __table_args__ = (
        Index("idx_neighborhood_category", "neighborhood_id", "category"),
        Index("idx_venue_status", "scraper_status", "is_active"),
    )


class EventModel(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True)
    date = Column(DateTime, index=True)
    category = Column(String(100), index=True)
    details = Column(Text, nullable=True)
    origination_url = Column(String(500), unique=True)
    date_retrieved = Column(DateTime, default=datetime.utcnow)
    source = Column(String(50), default="unknown", index=True)  # do312, yourchicagoguide, ticketmaster, scraper, etc.
    cost = Column(String(100), nullable=True)  # "Free", "$25", "$15-30", "Donation", etc.
    age_range = Column(String(100), nullable=True)  # "All ages", "18+", "21+", "13+", etc.
    is_outdoor = Column(String(20), nullable=True)  # "outdoor", "indoor", "hybrid"
    address = Column(String(255), nullable=True)  # Street address or location
    venue_name = Column(String(255), nullable=True)  # Venue/location name
    neighborhood_id = Column(Integer, ForeignKey("neighborhoods.id"), nullable=True, index=True)  # Link to neighborhood
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True, index=True)  # Link to venue

    neighborhood = relationship("NeighborhoodModel", back_populates="events")
    venue = relationship("VenueModel", back_populates="events")

    __table_args__ = (
        Index("idx_date_category", "date", "category"),
        Index("idx_name_search", "name"),
        Index("idx_source", "source"),
        Index("idx_cost", "cost"),
        Index("idx_age_range", "age_range"),
        Index("idx_is_outdoor", "is_outdoor"),
        Index("idx_address", "address"),
        Index("idx_venue_neighborhood", "venue_id", "neighborhood_id"),
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
