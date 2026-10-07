"""Tests that a result says where it came from.

search_local_db tagged every row with its source; search_google_events tagged
only the batch header. So when the model merged the two into one answer, the
database rows kept their provenance and the live web results quietly lost
theirs - a Google card read as though it were a confirmed venue listing.
"""

import pytest

from app.ai import chatbot
from app.ai.chatbot import EventResult


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return FakeResponse(self._payload)


@pytest.fixture
def serpapi(monkeypatch):
    monkeypatch.setattr(chatbot, "SERPAPI_KEY", "test-key")
    # Persistence is a background task and irrelevant to the text under test.
    monkeypatch.setattr(chatbot, "_spawn_background", lambda coro: coro.close())

    def _install(events):
        payload = {"events_results": events}
        monkeypatch.setattr(chatbot.httpx, "AsyncClient", lambda **kw: FakeClient(payload))
    return _install


LINKLESS = [{
    "title": "Chicago Marathon Family Community Event",
    "date": "Oct 11",
    "address": ["Cooking with Cass LLC", "Lake View East"],
}]


@pytest.mark.asyncio
class TestWebResultProvenance:
    async def test_every_event_is_tagged_not_just_the_header(self, serpapi):
        serpapi(LINKLESS * 2)
        text = await chatbot.search_google_events(None, "family events")
        # One tag per event, so the label survives being merged with DB rows.
        assert text.count("📌") == 2, text

    async def test_the_tag_names_the_live_web_search(self, serpapi):
        serpapi(LINKLESS)
        text = await chatbot.search_google_events(None, "family events")
        assert "Live web search" in text

    async def test_an_event_with_no_link_is_flagged_as_unverifiable(self, serpapi):
        """Google's event cards carry no URL, so there is nothing to check."""
        serpapi(LINKLESS)
        text = await chatbot.search_google_events(None, "family events")
        assert "No event page to verify" in text
        assert "not saved to our database" in text
        assert "View Event" not in text

    async def test_an_event_with_a_link_gets_the_link_not_the_warning(self, serpapi):
        serpapi([{**LINKLESS[0], "link": "https://example.com/e"}])
        text = await chatbot.search_google_events(None, "family events")
        assert "https://example.com/e" in text
        assert "No event page to verify" not in text

    async def test_the_venue_is_split_out_of_the_address(self, monkeypatch, serpapi):
        """["Lincoln Park Zoo", "Chicago, IL"] is the venue, then where it is,
        so the first entry becomes venue_name like every other source."""
        serpapi([{
            "title": "Fall Fest", "date": "Oct 9",
            "address": ["Lincoln Park Zoo", "Chicago, IL"],
        }])

        # Capture what would have been handed to persistence, by holding the
        # coroutine the tool spawns and awaiting it here instead.
        persisted: list[EventResult] = []
        spawned = []

        async def fake_persist(events):
            persisted.extend(events)

        monkeypatch.setattr(chatbot, "_persist_events_to_db", fake_persist)
        monkeypatch.setattr(chatbot, "_spawn_background", spawned.append)

        text = await chatbot.search_google_events(None, "fall fest")
        for coro in spawned:
            await coro
        assert "Lincoln Park Zoo, Chicago, IL" in text
        assert [e.venue for e in persisted] == ["Lincoln Park Zoo"], persisted


class TestPromptDemandsAttribution:
    def test_the_prompt_tells_the_model_to_keep_sources_apart(self):
        prompt = chatbot.agent._system_prompts[0] if hasattr(chatbot.agent, "_system_prompts") else ""
        if not prompt:
            pytest.skip("system prompt not introspectable in this pydantic-ai version")
        assert "never merge the two kinds" in prompt.lower()
        assert "unverified" in prompt.lower()


class TestEventResultCarriesVenue:
    def test_venue_is_a_field(self):
        event = EventResult(title="x", venue="Lincoln Park Zoo", source="SerpAPI")
        assert event.venue == "Lincoln Park Zoo"

    def test_venue_defaults_to_none(self):
        assert EventResult(title="x", source="SerpAPI").venue is None
