"""
Database tests: Models, queries, constraints, data integrity.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Base, EventModel, ChatThreadModel, ChatMessageModel, AuditLogModel


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


class TestEventModel:
    """Test Event model operations."""

    def test_create_event(self, test_db):
        """Create and store an event."""
        event = EventModel(
            name="Jazz Night",
            date=datetime.now() + timedelta(days=1),
            category="music",
            origination_url="http://example.com/event",
            source="test_source",
        )
        test_db.add(event)
        test_db.commit()

        retrieved = test_db.query(EventModel).filter_by(name="Jazz Night").first()
        assert retrieved is not None
        assert retrieved.name == "Jazz Night"
        assert retrieved.category == "music"

    def test_unique_url_constraint(self, test_db):
        """URL should be unique."""
        event1 = EventModel(
            name="Event 1",
            date=datetime.now(),
            origination_url="http://example.com/1",
            source="test",
        )
        event2 = EventModel(
            name="Event 2",
            date=datetime.now(),
            origination_url="http://example.com/1",  # Same URL
            source="test",
        )
        test_db.add(event1)
        test_db.commit()

        test_db.add(event2)
        with pytest.raises(Exception):  # Should raise IntegrityError
            test_db.commit()

    def test_query_by_category(self, test_db):
        """Query events by category."""
        test_db.add(EventModel(
            name="Jazz",
            date=datetime.now(),
            category="music",
            origination_url="http://example.com/1",
            source="test",
        ))
        test_db.add(EventModel(
            name="Comedy",
            date=datetime.now(),
            category="comedy",
            origination_url="http://example.com/2",
            source="test",
        ))
        test_db.commit()

        music_events = test_db.query(EventModel).filter_by(category="music").all()
        assert len(music_events) == 1
        assert music_events[0].name == "Jazz"

    def test_query_by_date_range(self, test_db):
        """Query events within date range."""
        now = datetime.now()
        test_db.add(EventModel(
            name="Today",
            date=now,
            origination_url="http://example.com/1",
            source="test",
        ))
        test_db.add(EventModel(
            name="Next week",
            date=now + timedelta(days=7),
            origination_url="http://example.com/2",
            source="test",
        ))
        test_db.add(EventModel(
            name="Next month",
            date=now + timedelta(days=30),
            origination_url="http://example.com/3",
            source="test",
        ))
        test_db.commit()

        week_events = test_db.query(EventModel).filter(
            EventModel.date >= now,
            EventModel.date <= now + timedelta(days=7)
        ).all()
        assert len(week_events) == 2

    def test_text_search(self, test_db):
        """Text search in event names."""
        test_db.add(EventModel(
            name="Jazz Night at Blue Note",
            date=datetime.now(),
            origination_url="http://example.com/1",
            source="test",
        ))
        test_db.add(EventModel(
            name="Rock Concert",
            date=datetime.now(),
            origination_url="http://example.com/2",
            source="test",
        ))
        test_db.commit()

        jazz_events = test_db.query(EventModel).filter(
            EventModel.name.ilike("%jazz%")
        ).all()
        assert len(jazz_events) == 1


class TestChatThreadModel:
    """Test chat thread management."""

    def test_create_thread(self, test_db):
        """Create a chat thread."""
        thread = ChatThreadModel()
        test_db.add(thread)
        test_db.commit()

        assert thread.id is not None
        assert thread.status == "active"
        assert thread.total_tokens == 0
        assert thread.turn_count == 0

    def test_track_tokens_and_turns(self, test_db):
        """Track tokens and turn count."""
        thread = ChatThreadModel(
            total_tokens=500,
            turn_count=2,
        )
        test_db.add(thread)
        test_db.commit()

        retrieved = test_db.query(ChatThreadModel).filter_by(id=thread.id).first()
        assert retrieved.total_tokens == 500
        assert retrieved.turn_count == 2

    def test_update_thread_status(self, test_db):
        """Update thread status."""
        thread = ChatThreadModel(status="active")
        test_db.add(thread)
        test_db.commit()

        thread.status = "completed"
        test_db.commit()

        retrieved = test_db.query(ChatThreadModel).filter_by(id=thread.id).first()
        assert retrieved.status == "completed"


class TestChatMessageModel:
    """Test chat message storage."""

    def test_create_message(self, test_db):
        """Store a chat message."""
        thread = ChatThreadModel()
        test_db.add(thread)
        test_db.commit()

        message = ChatMessageModel(
            thread_id=thread.id,
            role="user",
            content="What events?",
            token_count=3,
        )
        test_db.add(message)
        test_db.commit()

        retrieved = test_db.query(ChatMessageModel).filter_by(thread_id=thread.id).first()
        assert retrieved.role == "user"
        assert retrieved.content == "What events?"

    def test_thread_message_relationship(self, test_db):
        """Messages should relate to threads."""
        thread = ChatThreadModel()
        test_db.add(thread)
        test_db.commit()

        msg1 = ChatMessageModel(
            thread_id=thread.id,
            role="user",
            content="Query 1",
            token_count=10,
        )
        msg2 = ChatMessageModel(
            thread_id=thread.id,
            role="assistant",
            content="Response 1",
            token_count=50,
        )
        test_db.add_all([msg1, msg2])
        test_db.commit()

        messages = test_db.query(ChatMessageModel).filter_by(thread_id=thread.id).all()
        assert len(messages) == 2

    def test_cascade_delete(self, test_db):
        """Deleting thread should delete messages."""
        thread = ChatThreadModel()
        test_db.add(thread)
        test_db.commit()

        message = ChatMessageModel(
            thread_id=thread.id,
            role="user",
            content="Query",
        )
        test_db.add(message)
        test_db.commit()

        # Delete thread
        test_db.delete(thread)
        test_db.commit()

        # Messages should be deleted too
        messages = test_db.query(ChatMessageModel).filter_by(thread_id=thread.id).all()
        assert len(messages) == 0


class TestAuditLogModel:
    """Test audit logging."""

    def test_create_audit_log(self, test_db):
        """Store audit log entry."""
        log = AuditLogModel(
            thread_id="test-thread",
            operation="question_asked",
            status="success",
            duration_ms=150.5,
            tokens_used=50,
            metadata='{"query": "jazz"}',
        )
        test_db.add(log)
        test_db.commit()

        retrieved = test_db.query(AuditLogModel).filter_by(operation="question_asked").first()
        assert retrieved is not None
        assert retrieved.status == "success"
        assert retrieved.duration_ms == 150.5

    def test_audit_log_with_error(self, test_db):
        """Log errors to audit trail."""
        log = AuditLogModel(
            thread_id="test-thread",
            operation="execution_error",
            status="failure",
            error_message="Connection timeout",
        )
        test_db.add(log)
        test_db.commit()

        retrieved = test_db.query(AuditLogModel).filter_by(operation="execution_error").first()
        assert retrieved.status == "failure"
        assert "timeout" in retrieved.error_message.lower()

    def test_query_audit_logs(self, test_db):
        """Query audit logs by operation."""
        test_db.add(AuditLogModel(
            operation="chat_created",
            status="success",
            thread_id="1",
        ))
        test_db.add(AuditLogModel(
            operation="question_asked",
            status="success",
            thread_id="1",
        ))
        test_db.add(AuditLogModel(
            operation="security_blocked",
            status="blocked",
            thread_id="2",
        ))
        test_db.commit()

        security_logs = test_db.query(AuditLogModel).filter_by(
            operation="security_blocked"
        ).all()
        assert len(security_logs) == 1


class TestDatabaseIntegrity:
    """Test overall database integrity."""

    def test_full_conversation_flow(self, test_db):
        """Simulate a full conversation in database."""
        # Create thread
        thread = ChatThreadModel()
        test_db.add(thread)
        test_db.commit()

        # Add messages
        user_msg = ChatMessageModel(
            thread_id=thread.id,
            role="user",
            content="Show me concerts",
            token_count=3,
        )
        assistant_msg = ChatMessageModel(
            thread_id=thread.id,
            role="assistant",
            content="Found 3 concerts...",
            token_count=20,
        )
        test_db.add_all([user_msg, assistant_msg])

        # Add audit logs
        audit = AuditLogModel(
            thread_id=thread.id,
            operation="question_asked",
            status="success",
        )
        test_db.add(audit)
        test_db.commit()

        # Update thread totals
        thread.total_tokens += 23
        thread.turn_count += 1
        test_db.commit()

        # Verify all data
        retrieved_thread = test_db.query(ChatThreadModel).filter_by(id=thread.id).first()
        assert retrieved_thread.total_tokens == 23
        assert retrieved_thread.turn_count == 1

        messages = test_db.query(ChatMessageModel).filter_by(thread_id=thread.id).all()
        assert len(messages) == 2

        logs = test_db.query(AuditLogModel).filter_by(thread_id=thread.id).all()
        assert len(logs) == 1
