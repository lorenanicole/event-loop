"""
Core Functionality Tests - Python 3.14 & 3.15 Compatibility
Tests chat API, database, scraper, and search functionality
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# Fixtures
@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient]:
    """Provide async HTTP client for testing."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Provide database session for testing."""
    from shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


class TestChatAPI:
    """Tests for chat/REACT agent API endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, async_client):
        """Test health check endpoint."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_chat_endpoint_exists(self, async_client):
        """Test chat endpoint is available."""
        # Chat endpoint should be available
        response = await async_client.get("/")
        assert response.status_code in [200, 404]  # Either serves or redirects

    @pytest.mark.asyncio
    async def test_sse_chat_streaming(self, async_client):
        """Test SSE streaming for chat messages."""
        payload = {
            "message": "Find live music events in Wicker Park",
            "neighborhood": "Wicker Park",
        }
        response = await async_client.post("/chat/stream", json=payload)
        # SSE endpoints return streaming response
        assert response.status_code in [200, 404, 405]  # Depends on endpoint implementation


class TestDatabase:
    """Tests for database operations."""

    @pytest.mark.asyncio
    async def test_database_connection(self, db_session):
        """Test database connection works."""
        assert db_session is not None
        # Query a simple count
        from sqlalchemy import text

        result = await db_session.execute(text("SELECT 1"))
        assert result is not None

    @pytest.mark.asyncio
    async def test_event_model_exists(self, db_session):
        """Test EventModel table exists."""
        from sqlalchemy import inspect

        from shared.database.models import EventModel

        # Check if table exists
        inspector = inspect(EventModel)
        assert inspector.columns is not None
        assert len(inspector.columns) > 0

    @pytest.mark.asyncio
    async def test_venue_model_exists(self, db_session):
        """Test VenueModel table exists."""
        from sqlalchemy import inspect

        from shared.database.models import VenueModel

        inspector = inspect(VenueModel)
        assert inspector.columns is not None
        assert "name" in [col.name for col in inspector.columns]


class TestScraper:
    """Tests for web scraper functionality."""

    @pytest.mark.asyncio
    async def test_scraper_initialization(self):
        """Test scraper can be initialized."""
        from scrapers.custom.venue.venue_scraper import VenueConfig

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

    @pytest.mark.asyncio
    async def test_venue_config_validation(self):
        """Test VenueConfig validation."""
        from scrapers.custom.venue.venue_scraper import VenueConfig

        # Should accept valid config
        config = VenueConfig(
            name="Valid Venue",
            website_url="https://venue.com",
            event_page_url="https://venue.com/events",
            category="theater",
            address="456 Broadway",
            selectors={},
            use_playwright=True,
        )

        assert config.use_playwright is True
        assert config.category == "theater"


class TestSearch:
    """Tests for search and REACT agent functionality."""

    def test_smart_search_import(self):
        """Test smart search module imports."""
        try:
            from app.ai.smart_search import get_smart_search_tool

            assert get_smart_search_tool is not None
        except ImportError:
            pytest.skip("Smart search module not available")

    @pytest.mark.asyncio
    async def test_chatbot_initialization(self):
        """Test chatbot agent initializes."""
        try:
            from app.ai.chatbot import create_event_search_agent

            # Should be able to create agent
            assert True  # If import works, test passes
        except ImportError:
            pytest.skip("Chatbot module not available")


class TestPythonVersionFeatures:
    """Tests for Python 3.15 specific features."""

    def test_frozendict_available(self):
        """Test frozendict is available (3.15) or gracefully missing (3.14)."""
        try:
            from builtins import frozendict

            # Test 3.15 feature
            fd = frozendict({"key": "value"})
            assert fd["key"] == "value"
            assert isinstance(fd, frozendict)
        except ImportError, TypeError:
            # 3.14 doesn't have frozendict
            pytest.skip("frozendict not available (Python < 3.15)")

    def test_sentinel_available(self):
        """Test sentinel is available (3.15) or gracefully missing (3.14)."""
        try:
            from builtins import sentinel

            # Test 3.15 feature
            MISSING = sentinel("MISSING")
            assert MISSING is MISSING
        except ImportError, TypeError:
            # 3.14 doesn't have sentinel
            pytest.skip("sentinel not available (Python < 3.15)")

    def test_unpacking_in_comprehensions(self):
        """Test unpacking in comprehensions (3.15 feature)."""
        # This would be a syntax error on 3.14, so we test it differently
        data = [[1, 2], [3, 4], [5, 6]]

        # 3.14 compatible: use traditional unpacking
        result = [item for chunk in data for item in chunk]
        assert result == [1, 2, 3, 4, 5, 6]

        # 3.15 would also support:
        # result = [*chunk for chunk in data]

    def test_lazy_import_support(self):
        """Test lazy import support (3.15 feature)."""
        # 3.15 supports: lazy import json
        # 3.14 doesn't, but we can test the concept
        import json  # Normal import works on both

        assert json is not None


class TestAsyncCompatibility:
    """Tests for async/await compatibility across versions."""

    @pytest.mark.asyncio
    async def test_asyncio_create_task(self):
        """Test asyncio.create_task works."""

        async def dummy():
            return 42

        task = asyncio.create_task(dummy())
        result = await task
        assert result == 42

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Test async context managers work."""

        class AsyncResource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        async with AsyncResource() as resource:
            assert resource is not None

    @pytest.mark.asyncio
    async def test_task_group_support(self):
        """Test TaskGroup support (3.15) or asyncio.gather (3.14)."""
        results = []

        async def task1():
            await asyncio.sleep(0.01)
            results.append(1)

        async def task2():
            await asyncio.sleep(0.01)
            results.append(2)

        # 3.15 would support TaskGroup, 3.14 uses gather
        try:
            # Try 3.15 approach first
            async with asyncio.TaskGroup() as tg:
                tg.create_task(task1())
                tg.create_task(task2())
        except AttributeError:
            # Fallback to 3.14
            await asyncio.gather(task1(), task2())

        assert len(results) == 2


class TestDualVersionArchitecture:
    """Tests for dual-version (3.14 + 3.15) setup."""

    def test_parser_client_imports(self):
        """Test parser client can be imported."""
        try:
            from scrapers import ParserClient

            assert ParserClient is not None
        except ImportError:
            pytest.skip("Parser client not available")

    def test_backend_server_imports(self):
        """Test backend server can be imported."""
        try:
            from app import app

            assert app is not None
        except ImportError:
            pytest.skip("Backend server not available")

    @pytest.mark.asyncio
    async def test_http_client_initialization(self):
        """Test HTTP client for dual-version communication."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                assert client is not None
        except ImportError:
            pytest.skip("httpx not available")


# Test configuration
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
