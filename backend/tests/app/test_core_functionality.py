"""
Core functionality tests.

Covers the actual behaviour of the database layer, scraper config objects,
and the query-parsing helpers. Every assertion here checks something the
application does, not something Python does.

Classes that previously lived here and tested the Python interpreter
(TaskGroup, async context managers, `import json`, frozendict, sentinel,
lazy imports) have been removed — those are Python's responsibility, not
ours. test_chat_endpoint_exists (GET / accepting 404 as success) and
test_sse_chat_streaming (hitting /chat/stream which does not exist and
accepting 404/405) are also removed; real SSE tests live in test_chat_sse.py.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    from shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


class TestHealthEndpoint:
    """The /health endpoint must respond correctly."""

    @pytest.mark.asyncio
    async def test_returns_200(self, async_client):
        response = await async_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_status_field_is_healthy(self, async_client):
        response = await async_client.get("/health")
        assert response.json()["status"] == "healthy"


class TestDatabase:
    """The database layer must be reachable and hold the expected tables."""

    @pytest.mark.asyncio
    async def test_connection_executes_select(self, db_session):
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_event_table_has_expected_columns(self, db_session):
        from sqlalchemy import inspect

        from shared.database.models import EventModel

        cols = {col.name for col in inspect(EventModel).columns}
        for expected in ("id", "name", "date", "category", "origination_url"):
            assert expected in cols, f"EventModel missing column: {expected}"

    @pytest.mark.asyncio
    async def test_venue_table_has_name_column(self, db_session):
        from sqlalchemy import inspect

        from shared.database.models import VenueModel

        cols = {col.name for col in inspect(VenueModel).columns}
        assert "name" in cols

    @pytest.mark.asyncio
    async def test_neighborhood_table_has_expected_columns(self, db_session):
        from sqlalchemy import inspect

        from shared.database.models import NeighborhoodModel

        cols = {col.name for col in inspect(NeighborhoodModel).columns}
        for expected in ("id", "name"):
            assert expected in cols, f"NeighborhoodModel missing column: {expected}"

    @pytest.mark.asyncio
    async def test_events_table_is_populated(self, db_session):
        """The database must contain at least one event."""
        from sqlalchemy import func, select

        from shared.database.models import EventModel

        count = await db_session.scalar(select(func.count(EventModel.id)))
        assert count > 0, "Event table is empty — no data loaded"


class TestScraper:
    """VenueConfig must accept valid inputs."""

    def test_basic_config_accepted(self):
        from scrapers.venue.venue_scraper import VenueConfig

        config = VenueConfig(
            name="Test Venue",
            website_url="https://example.com",
            event_page_url="https://example.com/events",
            category="music",
            address="123 Main St",
            selectors={},
            use_playwright=False,
        )
        assert config.name == "Test Venue"
        assert config.category == "music"
        assert config.use_playwright is False

    def test_playwright_flag_preserved(self):
        from scrapers.venue.venue_scraper import VenueConfig

        config = VenueConfig(
            name="Theater Venue",
            website_url="https://theater.com",
            event_page_url="https://theater.com/events",
            category="theater",
            address="456 Broadway",
            selectors={},
            use_playwright=True,
        )
        assert config.use_playwright is True
        assert config.category == "theater"

    def test_active_venues_list_is_non_empty(self):
        """venues.py must export at least one runnable venue config."""
        from scrapers.venue.venues import CHICAGO_VENUES

        assert isinstance(CHICAGO_VENUES, dict)
        total = sum(len(v) for v in CHICAGO_VENUES.values())
        assert total > 0, "CHICAGO_VENUES is empty — no venues configured"


def test_chatbot_agent_importable():
    """The agent module must import without error."""
    from app.chat import chatbot

    assert hasattr(chatbot, "agent")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
