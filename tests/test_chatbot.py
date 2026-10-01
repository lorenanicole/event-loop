"""
Tests for chatbot utilities: keyword extraction, category detection, date parsing.
"""

import pytest
from datetime import datetime, timedelta
from src.ai.chatbot import (
    _extract_keywords,
    _extract_categories,
    _extract_date_range,
    _score_event_relevance,
    _filter_top_results,
)


class TestKeywordExtraction:
    """Test keyword extraction from queries."""

    def test_extracts_single_keyword(self):
        """Extract keywords from simple query."""
        keywords = _extract_keywords("jazz concerts")
        assert "jazz" in keywords
        assert "concerts" in keywords

    def test_filters_stop_words(self):
        """Filter common stop words."""
        keywords = _extract_keywords("the and or a in on at")
        # Should be mostly empty or only have words > 2 chars
        for kw in keywords:
            assert len(kw) > 2

    def test_filters_event_words(self):
        """Filter common event-related stop words."""
        keywords = _extract_keywords("show me all events this weekend")
        assert "events" not in keywords
        assert "weekend" in keywords or "show" not in keywords

    def test_limits_keyword_count(self):
        """Limit to 5 keywords."""
        query = "jazz rock pop metal classical funk soul blues dance"
        keywords = _extract_keywords(query)
        assert len(keywords) <= 5


class TestCategoryDetection:
    """Test event category detection."""

    def test_detects_music(self):
        """Detect music category."""
        categories = _extract_categories("jazz concert this weekend")
        assert "music" in categories

    def test_detects_comedy(self):
        """Detect comedy category."""
        categories = _extract_categories("stand up comedy show")
        assert "comedy" in categories

    def test_detects_theater(self):
        """Detect theater category."""
        categories = _extract_categories("broadway play drama")
        assert "theater" in categories

    def test_detects_sports(self):
        """Detect sports category."""
        categories = _extract_categories("chicago bears game")
        assert "sports" in categories

    def test_detects_art(self):
        """Detect art category."""
        categories = _extract_categories("art gallery exhibition")
        assert "art" in categories

    def test_no_category_match(self):
        """Return empty list for no match."""
        categories = _extract_categories("random words")
        assert len(categories) == 0


class TestDateRangeExtraction:
    """Test date range extraction from queries."""

    def test_extracts_this_weekend(self):
        """Extract 'this weekend' date range."""
        date_range = _extract_date_range("concerts this weekend")
        assert date_range is not None
        start, end = date_range
        assert start < end
        # Should be within 7 days
        assert (end - start).days <= 2

    def test_extracts_this_week(self):
        """Extract 'this week' date range."""
        date_range = _extract_date_range("events this week")
        assert date_range is not None
        start, end = date_range
        assert (end - start).days >= 7

    def test_extracts_this_month(self):
        """Extract 'this month' date range."""
        date_range = _extract_date_range("events this month")
        assert date_range is not None
        start, end = date_range
        assert (end - start).days >= 20

    def test_extracts_next_week(self):
        """Extract 'next week' date range."""
        date_range = _extract_date_range("events next week")
        assert date_range is not None

    def test_extracts_tonight(self):
        """Extract 'tonight' date range."""
        date_range = _extract_date_range("events tonight")
        assert date_range is not None
        start, end = date_range
        # Should be same day
        assert start.date() == end.date()

    def test_no_date_specified(self):
        """Return None when no date in query."""
        date_range = _extract_date_range("jazz concerts")
        assert date_range is None


class TestEventScoring:
    """Test event relevance scoring."""

    def test_scores_keyword_match(self):
        """Score higher for keyword matches."""
        from src.database.models import EventModel

        # Mock event
        event = type('Event', (), {
            'name': 'Jazz Night at Blue Note',
            'category': 'music',
            'date': datetime.now() + timedelta(days=2)
        })()

        score = _score_event_relevance(event, "jazz concert", ["music"])
        assert score > 0.3  # Should have decent score

    def test_scores_category_match(self):
        """Score higher for category match."""
        from src.database.models import EventModel

        event = type('Event', (), {
            'name': 'Comedy Show',
            'category': 'comedy',
            'date': datetime.now() + timedelta(days=2)
        })()

        score = _score_event_relevance(event, "stand up comedy", ["comedy"])
        assert score > 0.4  # Should have good score with category match

    def test_scores_recent_events_higher(self):
        """Score recent events higher than far future."""
        event_soon = type('Event', (), {
            'name': 'Concert',
            'category': 'music',
            'date': datetime.now() + timedelta(days=1)
        })()

        event_far = type('Event', (), {
            'name': 'Concert',
            'category': 'music',
            'date': datetime.now() + timedelta(days=60)
        })()

        score_soon = _score_event_relevance(event_soon, "concert", ["music"])
        score_far = _score_event_relevance(event_far, "concert", ["music"])

        assert score_soon > score_far

    def test_scores_range_0_to_1(self):
        """Scores should be between 0.0 and 1.0."""
        event = type('Event', (), {
            'name': 'Random Event',
            'category': 'other',
            'date': datetime.now() + timedelta(days=100)
        })()

        score = _score_event_relevance(event, "query", [])
        assert 0.0 <= score <= 1.0


class TestResultFiltering:
    """Test result filtering and ranking."""

    def test_filters_to_top_n(self):
        """Filter results to top N items."""
        from src.database.models import EventModel

        events = [
            type('Event', (), {
                'name': f'Event {i}',
                'category': 'music',
                'date': datetime.now() + timedelta(days=i),
                'origination_url': f'http://example.com/{i}',
                'source': 'test'
            })()
            for i in range(10)
        ]

        top_events = _filter_top_results(events, "music", limit=5)
        assert len(top_events) <= 5

    def test_ranks_by_confidence(self):
        """Rank results by confidence score."""
        from src.database.models import EventModel

        events = [
            type('Event', (), {
                'name': 'Jazz Night',
                'category': 'music',
                'date': datetime.now() + timedelta(days=1),
                'origination_url': 'http://example.com/1',
                'source': 'test'
            })(),
            type('Event', (), {
                'name': 'Random Event',
                'category': 'other',
                'date': datetime.now() + timedelta(days=50),
                'origination_url': 'http://example.com/2',
                'source': 'test'
            })(),
        ]

        results = _filter_top_results(events, "jazz", limit=10)
        # First result should have higher confidence
        assert results[0].confidence >= results[-1].confidence
