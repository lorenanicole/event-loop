"""Tests for turning a chat query into the same structured filter the UI uses.

A neighborhood is a relationship on EventModel, not words in its name, so
reading "Pilsen" as a keyword matches it against event titles and finds almost
nothing. These cover the translation step.
"""

import pytest

from app.ai.chatbot import (
    _extract_keywords,
    _extract_neighborhoods,
    _normalize_place,
    _strip_neighborhoods,
)


class FakeResult:
    def __init__(self, names):
        self._names = names

    def scalars(self):
        return self

    def all(self):
        return self._names


class FakeDB:
    """Stands in for a session, returning a fixed neighborhood list."""

    NAMES = [
        "Loop", "West Loop", "Pullman", "West Pullman", "Lake View", "Pilsen",
        "Logan Square", "Humboldt Park", "Wicker Park", "Bucktown", "Uptown",
        "Hyde Park", "Bronzeville", "Little Village", "East Village",
        "Ukrainian Village", "Greater Grand Crossing", "Near South Side",
        "Chicago Lawn", "South Chicago",
    ]

    async def execute(self, _stmt):
        return FakeResult(self.NAMES)


@pytest.fixture
def db():
    return FakeDB()


class TestNormalizePlace:
    def test_lowercases_and_collapses(self):
        assert _normalize_place("  West   Loop ") == "west loop"

    def test_drops_punctuation(self):
        assert _normalize_place("Rush & Division,") == "rush & division"


@pytest.mark.asyncio
class TestExtractNeighborhoods:
    async def test_single_neighborhood(self, db):
        assert await _extract_neighborhoods(db, "comedy in pilsen") == ["Pilsen"]

    async def test_several_neighborhoods(self, db):
        found = await _extract_neighborhoods(
            db, "plant workshops in logan square, humboldt park"
        )
        assert sorted(found) == ["Humboldt Park", "Logan Square"]

    async def test_three_joined_by_and(self, db):
        found = await _extract_neighborhoods(db, "comedy in pilsen and wicker park and uptown")
        assert sorted(found) == ["Pilsen", "Uptown", "Wicker Park"]

    async def test_chicago_is_not_a_neighborhood(self, db):
        """"in Chicago" means the whole city, not a filter."""
        assert await _extract_neighborhoods(db, "plant workshops in chicago") == []

    async def test_no_place_named(self, db):
        assert await _extract_neighborhoods(db, "plant workshops this weekend") == []

    async def test_longer_name_wins_over_nested_one(self, db):
        """"West Loop" must not also register as "Loop"."""
        assert await _extract_neighborhoods(db, "shows in west loop tonight") == ["West Loop"]

    async def test_other_nested_pair(self, db):
        assert await _extract_neighborhoods(db, "music in west pullman") == ["West Pullman"]

    async def test_bare_nested_name_still_matches(self, db):
        assert await _extract_neighborhoods(db, "events in the loop") == ["Loop"]

    async def test_spoken_alias_resolves(self, db):
        """People type "lakeview"; the city spells it "Lake View"."""
        assert await _extract_neighborhoods(db, "anything in lakeview") == ["Lake View"]

    async def test_vernacular_alias_resolves(self, db):
        assert await _extract_neighborhoods(db, "shows in wrigleyville") == ["Lake View"]

    async def test_a_word_inside_another_word_does_not_match(self, db):
        """"uptown" inside "uptowner" is not a neighborhood reference."""
        assert await _extract_neighborhoods(db, "the uptowner bar") == []

    async def test_no_duplicate_when_name_appears_twice(self, db):
        assert await _extract_neighborhoods(db, "pilsen events in pilsen") == ["Pilsen"]


class TestStripNeighborhoods:
    def test_removes_the_neighborhood_words(self):
        """Otherwise "comedy in Pilsen" demands "pilsen" in the event title."""
        assert _strip_neighborhoods(["comedy", "pilsen"], ["Pilsen"]) == ["comedy"]

    def test_removes_both_words_of_a_two_word_name(self):
        kept = _strip_neighborhoods(["plant", "workshops", "logan", "square"], ["Logan Square"])
        assert kept == ["plant", "workshops"]

    def test_removes_the_spelling_the_user_typed(self):
        assert _strip_neighborhoods(["shows", "wrigleyville"], ["Lake View"]) == ["shows"]

    def test_leaves_keywords_alone_when_no_neighborhood(self):
        assert _strip_neighborhoods(["plant", "workshops"], []) == ["plant", "workshops"]

    def test_does_not_strip_a_word_that_is_also_a_subject(self):
        """"park" belongs to the name here, but "music" never does."""
        assert "music" in _strip_neighborhoods(["music", "park"], ["Humboldt Park"])


class TestKeywordsUnaffected:
    def test_keywords_still_extracted(self):
        assert "plant" in _extract_keywords("plant workshops this weekend")
