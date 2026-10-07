"""Tests for the guard on what the chatbot persists.

Search results are not all events. Roughly half of what had been stored this
way were artifacts of the search - page titles, listing pages, social posts -
so these pin down both what is rejected and what must not be.
"""

import pytest

from app.ai.chatbot import _looks_like_an_event


class TestLooksLikeAnEvent:
    @pytest.mark.parametrize("title", [
        "Public Events | Department of Astronomy and Astrophysics",
        "Events: Talks | Department of Astronomy and Astrophysics",
        "Events | Chicago Public Library",
        "Astrophysicist Events in Chicago",
        "Link in bio Learn about landscaping with native perennials.",
        "chicago",
        "",
    ])
    def test_rejects_search_artifacts(self, title):
        assert _looks_like_an_event(title) is False

    def test_rejects_a_missing_title(self):
        assert _looks_like_an_event(None) is False

    def test_rejects_a_single_word(self):
        """A real event title carries more than one word."""
        assert _looks_like_an_event("Lollapalooza") is False

    @pytest.mark.parametrize("title", [
        "Astronomy on Tap - CIERA-Northwestern",
        "From Quarks to the Cosmos",
        "Chicago Astronomer Public Observation Schedule",
        "Open house at Prosser/Hanson Park community garden",
        "Join us for Flora Festival 2026; a community event",
        "Learn about foraging wild plants and mushrooms in Chicago",
    ])
    def test_keeps_real_events(self, title):
        assert _looks_like_an_event(title) is True

    def test_keeps_a_title_containing_the_word_search(self):
        """"Search for Life" is part of this talk's name, not SERP furniture."""
        assert _looks_like_an_event(
            "In Conversation with Neil deGrasse Tyson - Search for Life"
        ) is True

    def test_rejects_explicit_search_furniture(self):
        assert _looks_like_an_event("jazz tonight - Google Search") is False
        assert _looks_like_an_event("Search results for concerts") is False
