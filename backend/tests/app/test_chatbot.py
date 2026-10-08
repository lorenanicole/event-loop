"""
Tests for chatbot.py internals: SearchPolicy gate logic, relevance scoring,
and result filtering/ranking.

Keyword extraction and date parsing have their own file (test_search_query.py)
because they live in search_query.py, not here. Event enrichment tests live in
test_event_enrichment.py. Category detection tests live in test_categories.py
in tests/shared/.
"""

from datetime import datetime, timedelta

from app.chat.chatbot import (
    DB_RESULT_THRESHOLD,
    LOCAL_CONFIDENCE_FLOOR,
    SearchPolicy,
    _filter_top_results,
)
from app.chat.search_ranking import _score_event_relevance


class TestSearchPolicy:
    def test_web_search_requires_local_search_first(self):
        assert SearchPolicy().may_search_web is False

    def test_sufficient_relevant_local_results_block_web_search(self):
        policy = SearchPolicy(
            local_search_completed=True,
            local_result_count=DB_RESULT_THRESHOLD,
            local_best_confidence=LOCAL_CONFIDENCE_FLOOR,
        )
        assert policy.may_search_web is False

    def test_sparse_local_results_allow_web_search(self):
        policy = SearchPolicy(local_search_completed=True, local_result_count=1)
        assert policy.may_search_web is True

    def test_low_confidence_local_results_allow_web_search(self):
        policy = SearchPolicy(
            local_search_completed=True,
            local_result_count=DB_RESULT_THRESHOLD,
            local_best_confidence=LOCAL_CONFIDENCE_FLOOR - 0.01,
        )
        assert policy.may_search_web is True

    def test_web_search_can_only_be_used_once_per_turn(self):
        policy = SearchPolicy(local_search_completed=True, local_result_count=0)
        policy.external_search_used = True
        assert policy.may_search_web is False


class TestEventScoring:
    """Test event relevance scoring."""

    def test_scores_keyword_match(self):
        """Score higher for keyword matches."""

        # Mock event
        event = type(
            "Event",
            (),
            {
                "name": "Jazz Night at Blue Note",
                "category": "music",
                "date": datetime.now() + timedelta(days=2),
            },
        )()

        score = _score_event_relevance(event, ["jazz", "concert"], ["music"])
        assert score > 0.3  # Should have decent score

    def test_scores_category_match(self):
        """Score higher for category match."""

        event = type(
            "Event",
            (),
            {
                "name": "Comedy Show",
                "category": "comedy",
                "date": datetime.now() + timedelta(days=2),
            },
        )()

        score = _score_event_relevance(event, ["stand", "up", "comedy"], ["comedy"])
        assert score > 0.4  # Should have good score with category match

    def test_scores_recent_events_higher(self):
        """Score recent events higher than far future."""
        event_soon = type(
            "Event",
            (),
            {"name": "Concert", "category": "music", "date": datetime.now() + timedelta(days=1)},
        )()

        event_far = type(
            "Event",
            (),
            {"name": "Concert", "category": "music", "date": datetime.now() + timedelta(days=60)},
        )()

        score_soon = _score_event_relevance(event_soon, ["concert"], ["music"])
        score_far = _score_event_relevance(event_far, ["concert"], ["music"])

        assert score_soon > score_far

    def test_scores_range_0_to_1(self):
        """Scores should be between 0.0 and 1.0."""
        event = type(
            "Event",
            (),
            {
                "name": "Random Event",
                "category": "other",
                "date": datetime.now() + timedelta(days=100),
            },
        )()

        score = _score_event_relevance(event, ["query"], [])
        assert 0.0 <= score <= 1.0


class TestResultFiltering:
    """Test result filtering and ranking."""

    def test_filters_to_top_n(self):
        """Filter results to top N items."""

        events = [
            type(
                "Event",
                (),
                {
                    "name": f"Event {i}",
                    "category": "music",
                    "date": datetime.now() + timedelta(days=i),
                    "origination_url": f"http://example.com/{i}",
                    "source": "test",
                    "details": "A great event with music and fun times",
                },
            )()
            for i in range(10)
        ]

        top_events = _filter_top_results(events, "music", ["music"], ["music"], limit=5)
        assert len(top_events) <= 5

    def test_ranks_by_confidence(self):
        """Rank results by confidence score."""

        events = [
            type(
                "Event",
                (),
                {
                    "name": "Jazz Night",
                    "category": "music",
                    "date": datetime.now() + timedelta(days=1),
                    "origination_url": "http://example.com/1",
                    "source": "test",
                    "details": "Live jazz performance with local musicians",
                },
            )(),
            type(
                "Event",
                (),
                {
                    "name": "Random Event",
                    "category": "other",
                    "date": datetime.now() + timedelta(days=50),
                    "origination_url": "http://example.com/2",
                    "source": "test",
                    "details": "Some random event happening later",
                },
            )(),
        ]

        results = _filter_top_results(events, "jazz", ["jazz"], ["music"], limit=10)
        # First result should have higher confidence
        assert results[0].confidence >= results[-1].confidence

    def test_keeps_database_neighborhood_for_grounded_context(self):
        event = type(
            "Event",
            (),
            {
                "name": "Show at Subterranean",
                "category": "music",
                "date": datetime.now() + timedelta(days=2),
                "origination_url": "https://example.com/event",
                "source": "test",
                "details": None,
                "neighborhood_name": "Wicker Park",
            },
        )()

        results = _filter_top_results([event], "music", ["music"], ["music"])

        assert results[0].neighborhood == "Wicker Park"
