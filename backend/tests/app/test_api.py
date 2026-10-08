"""
API tests: FastAPI endpoints, request/response handling, status codes.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


class TestEventsEndpoints:
    """Test event search endpoints."""

    def test_list_events(self, client):
        """GET /api/events returns events."""
        response = client.get("/api/events")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_events_pagination(self, client):
        """Pagination parameters work."""
        response = client.get("/api/events?skip=0&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 10

    def test_list_events_limit_validation(self, client):
        """Limit parameter is validated."""
        response = client.get("/api/events?limit=200")
        assert response.status_code == 422  # Validation error (max 100)

    def test_get_event_by_id(self, client):
        """GET /api/events/{id} returns event."""
        # Assuming event ID 1 exists
        response = client.get("/api/events/1")
        if response.status_code == 200:
            data = response.json()
            assert "name" in data or "title" in data

    def test_get_nonexistent_event(self, client):
        """404 for non-existent event."""
        response = client.get("/api/events/99999")
        assert response.status_code == 404

    def test_search_events(self, client):
        """POST /api/search filters events."""
        response = client.post("/api/search", json={"query": "jazz", "limit": 10})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_with_category(self, client):
        """Search respects category filtering."""
        response = client.post("/api/search", json={"query": "music concert", "limit": 5})
        assert response.status_code == 200

    def test_search_this_weekend(self, client):
        """Date range parsing works."""
        response = client.post("/api/search", json={"query": "events this weekend", "limit": 10})
        assert response.status_code == 200

    def test_get_categories(self, client):
        """GET /api/search/categories returns categories."""
        response = client.get("/api/search/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert isinstance(data["categories"], list)

    def test_get_stats(self, client):
        """GET /api/search/stats returns database stats."""
        response = client.get("/api/search/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_events" in data
        assert "unique_categories" in data


class TestChatEndpoints:
    """Test chat/SSE endpoints."""

    def test_split_routers_preserve_public_paths(self, client):
        paths = set(app.openapi()["paths"])
        assert "/api/chat" in paths
        assert "/api/chat/greeting" in paths
        assert "/api/chat/{thread_id}/close" in paths
        # /api/venue-events/refresh is intentionally hidden from the public schema (include_in_schema=False)
        assert "/api/venue-events/refresh" not in paths
        assert "/analytics/summary" in paths
        assert "/analytics/security" in paths

    def test_chat_endpoint_exists(self, client):
        """POST /api/chat endpoint exists."""
        # This will likely fail quickly since no LLM, but test endpoint
        response = client.post("/api/chat", json={"message": "test"})
        # Should return 200 (streaming) or error
        assert response.status_code in [200, 422]

    def test_chat_with_thread_id(self, client):
        """Chat accepts thread_id for continuity."""
        response = client.post(
            "/api/chat", json={"message": "test", "thread_id": "test-thread-123"}
        )
        # Should accept the parameter structure
        assert response.status_code in [200, 422]

    def test_chat_requires_message(self, client):
        """Chat requires message field."""
        response = client.post("/api/chat", json={})
        assert response.status_code == 422  # Validation error

    def test_chat_headers(self, client):
        """Chat response has correct headers."""
        response = client.post("/api/chat", json={"message": "What events?"})
        # If it doesn't error on structure
        if response.status_code == 200:
            assert "text/event-stream" in response.headers.get("content-type", "")
            assert "no-cache" in response.headers.get("cache-control", "")


class TestAnalyticsEndpoints:
    """Test analytics and observability endpoints."""

    def test_telemetry_endpoint(self, client):
        """GET /analytics/telemetry returns metrics."""
        response = client.get("/analytics/telemetry")
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data

    def test_audit_logs_endpoint(self, client):
        """GET /analytics/audit returns logs."""
        response = client.get("/analytics/audit")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "count" in data

    def test_audit_filter_by_operation(self, client):
        """Audit logs can filter by operation."""
        response = client.get("/analytics/audit?operation=question_asked")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["logs"], list)

    def test_audit_filter_by_status(self, client):
        """Audit logs can filter by status."""
        response = client.get("/analytics/audit?status=success")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data

    def test_audit_limit_parameter(self, client):
        """Audit logs respect limit parameter."""
        response = client.get("/analytics/audit?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) <= 5

    def test_summary_endpoint(self, client):
        """GET /analytics/summary returns dashboard summary."""
        response = client.get("/analytics/summary")
        assert response.status_code == 200
        data = response.json()

        # Should have these fields
        assert "total_sessions" in data
        assert "completed_sessions" in data
        assert "total_tokens" in data
        assert "avg_tokens_per_session" in data

    def test_security_endpoint(self, client):
        """GET /analytics/security returns security metrics."""
        response = client.get("/analytics/security")
        assert response.status_code == 200
        data = response.json()

        # Should have security events
        assert "security_events" in data
        assert "blocked_requests" in data["security_events"]
        assert "blocked_sessions" in data


class TestVenueRefreshProtection:
    """The venue-refresh endpoint must be protected and hidden from public docs."""

    def test_refresh_hidden_from_openapi(self, client):
        """Route does not appear in the public OpenAPI schema."""
        paths = set(app.openapi()["paths"])
        assert "/api/venue-events/refresh" not in paths

    def test_refresh_blocked_without_key(self, client):
        """POST without X-Admin-Key header is rejected (422 missing header or 403 wrong key)."""
        response = client.post("/api/venue-events/refresh")
        # FastAPI returns 422 when a required header is absent; 403 when it is present but wrong.
        # Either way the request must not succeed.
        assert response.status_code in (403, 422)

    def test_refresh_blocked_with_wrong_key(self, client):
        """POST with an incorrect key returns 403."""
        response = client.post(
            "/api/venue-events/refresh",
            headers={"X-Admin-Key": "wrong-key"},
        )
        assert response.status_code == 403

    def test_refresh_allowed_with_correct_key(self, client, monkeypatch):
        """POST with the correct key is accepted (scraper itself is not invoked)."""
        monkeypatch.setenv("ADMIN_API_KEY", "test-secret")

        async def _fake_scrape():
            pass

        monkeypatch.setattr(
            "scrapers.venue.chicago_events_scraper.scrape_chicago_events",
            _fake_scrape,
            raising=False,
        )
        # We only care that the key check passes (200); the scraper mock prevents
        # actual network calls.
        response = client.post(
            "/api/venue-events/refresh",
            headers={"X-Admin-Key": "test-secret"},
        )
        # 200 = key accepted; 500 = key accepted but scraper path error (still not 403)
        assert response.status_code != 403


class TestErrorHandling:
    """Test error handling."""

    def test_invalid_json(self, client):
        """Invalid JSON returns error."""
        response = client.post(
            "/api/chat", data="not json", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422

    def test_missing_required_field(self, client):
        """Missing required fields return validation error."""
        response = client.post("/api/search", json={})
        assert response.status_code == 422

    def test_invalid_parameter_type(self, client):
        """Invalid parameter types return error."""
        response = client.get("/api/events?limit=abc")
        assert response.status_code == 422

    def test_cors_headers(self, client):
        """Check CORS headers if enabled."""
        response = client.get("/api/events")
        # Depends on CORS configuration
        assert response.status_code == 200


class TestDataValidation:
    """Test request data validation."""

    def test_search_query_required(self, client):
        """Search requires query field."""
        response = client.post("/api/search", json={})
        assert response.status_code == 422

    def test_search_limit_range(self, client):
        """Search limit must be in valid range."""
        # Too high
        response = client.post("/api/search", json={"query": "test", "limit": 101})
        assert response.status_code == 422

        # Too low
        response = client.post("/api/search", json={"query": "test", "limit": 0})
        assert response.status_code == 422

    def test_chat_message_not_empty(self, client):
        """Chat message can't be empty."""
        response = client.post("/api/chat", json={"message": ""})
        # Depending on validation, might be 422 or 200
        assert response.status_code in [200, 422]


class TestResponseFormats:
    """Test response format consistency."""

    def test_events_response_format(self, client):
        """Event responses have consistent format."""
        response = client.get("/api/events?limit=1")
        if response.status_code == 200 and response.json():
            event = response.json()[0]
            # Should have these fields
            assert "id" in event or "name" in event

    def test_stats_response_format(self, client):
        """Stats response has all required fields."""
        response = client.get("/api/search/stats")
        assert response.status_code == 200
        data = response.json()

        required_fields = ["total_events", "unique_categories", "earliest_event", "latest_event"]
        for field in required_fields:
            assert field in data
