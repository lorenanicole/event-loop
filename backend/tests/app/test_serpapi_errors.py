"""Tests for how a failing online search is reported.

A read timeout stringifies to the empty string, so the log read "SerpAPI
error: " with nothing after it and the user was told "API error" - neither
said what had happened or whether retrying was worth it.
"""

import httpx
import pytest

from app.ai import chatbot


class FakeClient:
    def __init__(self, raises):
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        raise self._raises


@pytest.fixture
def serpapi_key(monkeypatch):
    monkeypatch.setattr(chatbot, "SERPAPI_KEY", "test-key")


def capture_errors(monkeypatch) -> list[str]:
    """Collect logger.error calls, rendered.

    This module logs through structlog, which pytest's caplog does not see.
    """
    lines: list[str] = []

    def record(message, *args, **kwargs):
        try:
            lines.append(str(message) % args if args else str(message))
        except TypeError:
            lines.append(f"{message} {args}")

    monkeypatch.setattr(chatbot.logger, "error", record)
    return lines


def fail_with(monkeypatch, error):
    monkeypatch.setattr(chatbot.httpx, "AsyncClient", lambda **kw: FakeClient(error))


@pytest.mark.asyncio
class TestSerpapiFailures:
    async def test_a_timeout_says_it_timed_out(self, monkeypatch, serpapi_key):
        fail_with(monkeypatch, httpx.ReadTimeout(""))
        result = await chatbot.search_google_events(None, "ruby meetup")
        assert "timed out" in result.lower()
        assert str(chatbot.SERPAPI_TIMEOUT) in result

    async def test_a_timeout_logs_its_type(self, monkeypatch, serpapi_key):
        """The message is empty, so the type is the only identifying detail."""
        fail_with(monkeypatch, httpx.ReadTimeout(""))
        logged = capture_errors(monkeypatch)
        await chatbot.search_google_events(None, "ruby meetup")
        assert any("ReadTimeout" in line for line in logged), logged

    async def test_a_timeout_tells_the_model_not_to_retry_this_turn(self, monkeypatch, serpapi_key):
        """It already waited the full timeout; a second call just stalls the
        turn again and burns the budget."""
        fail_with(monkeypatch, httpx.ReadTimeout(""))
        result = await chatbot.search_google_events(None, "ruby meetup")
        assert "not call this tool again" in result.lower()

    async def test_a_transport_error_is_still_reported_as_an_api_error(
        self, monkeypatch, serpapi_key
    ):
        fail_with(monkeypatch, httpx.ConnectError("refused"))
        result = await chatbot.search_google_events(None, "ruby meetup")
        assert "API error" in result

    async def test_a_transport_error_logs_its_type(self, monkeypatch, serpapi_key):
        """An empty message must not produce a log line that trails off into
        nothing, which is what "SerpAPI error: " was."""
        fail_with(monkeypatch, httpx.ConnectError(""))
        logged = capture_errors(monkeypatch)
        await chatbot.search_google_events(None, "ruby meetup")
        assert any("ConnectError" in line for line in logged), logged
        assert any("(no message)" in line for line in logged), logged

    async def test_no_key_configured(self, monkeypatch):
        monkeypatch.setattr(chatbot, "SERPAPI_KEY", "")
        assert await chatbot.search_google_events(None, "x") == "SerpAPI not configured"
