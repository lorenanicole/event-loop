"""
Tests for chatbot utilities: keyword extraction, category detection, date parsing.
"""

import pytest
from datetime import datetime, timedelta
from app.ai.chatbot import (
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
        from shared.database.models import EventModel

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
        from shared.database.models import EventModel

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
        from shared.database.models import EventModel

        events = [
            type('Event', (), {
                'name': f'Event {i}',
                'category': 'music',
                'date': datetime.now() + timedelta(days=i),
                'origination_url': f'http://example.com/{i}',
                'source': 'test',
                'details': f'A great event with music and fun times'
            })()
            for i in range(10)
        ]

        top_events = _filter_top_results(events, "music", limit=5)
        assert len(top_events) <= 5

    def test_ranks_by_confidence(self):
        """Rank results by confidence score."""
        from shared.database.models import EventModel

        events = [
            type('Event', (), {
                'name': 'Jazz Night',
                'category': 'music',
                'date': datetime.now() + timedelta(days=1),
                'origination_url': 'http://example.com/1',
                'source': 'test',
                'details': 'Live jazz performance with local musicians'
            })(),
            type('Event', (), {
                'name': 'Random Event',
                'category': 'other',
                'date': datetime.now() + timedelta(days=50),
                'origination_url': 'http://example.com/2',
                'source': 'test',
                'details': 'Some random event happening later'
            })(),
        ]

        results = _filter_top_results(events, "jazz", limit=10)
        # First result should have higher confidence
        assert results[0].confidence >= results[-1].confidence


class TestEventEnrichment:
    """Test cost and age_range extraction from event data."""

    def test_extract_cost_free(self):
        """Extract 'free' from event text."""
        from app.ai.event_enrichment import extract_cost

        cost = extract_cost("Free Concert in the Park")
        assert cost == "Free"

        cost = extract_cost("No admission fee - all welcome!")
        assert cost == "Free"

    def test_extract_cost_price_range(self):
        """Extract price ranges like $10-20."""
        from app.ai.event_enrichment import extract_cost

        cost = extract_cost("Comedy Show - $25")
        assert cost == "$25"

        cost = extract_cost("Tickets: $15-30")
        assert cost == "$15-30"

    def test_extract_cost_donation(self):
        """Extract donation-based pricing."""
        from app.ai.event_enrichment import extract_cost

        cost = extract_cost("Suggested donation: $10")
        assert cost == "Donation"

        cost = extract_cost("Pay What You Can - PWYC")
        assert cost == "Donation"

    def test_extract_cost_paid(self):
        """Extract generic paid designation."""
        from app.ai.event_enrichment import extract_cost

        cost = extract_cost("Paid ticketed event")
        assert cost == "Paid"

    def test_extract_cost_none(self):
        """Return None when no cost found."""
        from app.ai.event_enrichment import extract_cost

        cost = extract_cost("Random event with no cost info")
        assert cost is None

    def test_extract_age_range_all_ages(self):
        """Extract 'all ages' designation."""
        from app.ai.event_enrichment import extract_age_range

        age = extract_age_range("All ages welcome - Family Friendly Event")
        assert age == "All ages"

    def test_extract_age_range_kids_friendly(self):
        """Extract kids/family friendly designation."""
        from app.ai.event_enrichment import extract_age_range

        age = extract_age_range("Kids Friendly Workshop")
        assert age == "Kids friendly"

        age = extract_age_range("Family Event - Children Welcome")
        assert age == "Kids friendly"

    def test_extract_age_range_plus_format(self):
        """Extract age+ format (18+, 21+, etc)."""
        from app.ai.event_enrichment import extract_age_range

        age = extract_age_range("18+ Bar Crawl")
        assert age == "18+"

        age = extract_age_range("21+ Only - Must have valid ID")
        assert age == "21+"

        age = extract_age_range("13+ concert")
        assert age == "13+"

    def test_extract_age_range_and_over_format(self):
        """Extract 'age and over' format."""
        from app.ai.event_enrichment import extract_age_range

        age = extract_age_range("Event for 18 and over attendees")
        assert age == "18+"

        age = extract_age_range("21 and up only")
        assert age == "21+"

    def test_extract_age_range_years_old_format(self):
        """Extract 'age years old' format."""
        from app.ai.event_enrichment import extract_age_range

        age = extract_age_range("Children 5 years old and up")
        assert age == "5+"

    def test_extract_age_range_none(self):
        """Return None when no age_range found."""
        from app.ai.event_enrichment import extract_age_range

        age = extract_age_range("Random event with no age restrictions")
        assert age is None

    def test_extract_from_event_text_both_fields(self):
        """Extract both cost and age_range from combined text."""
        from app.ai.event_enrichment import extract_from_event_text

        cost, age = extract_from_event_text(
            event_name="Free Comedy Show",
            details="$10 donation - 18+ only - Adult humor"
        )
        # Should prioritize details for better extraction
        assert cost in ["Free", "$10", "Donation"]
        assert age == "18+"

    def test_extract_from_event_text_empty(self):
        """Handle empty text gracefully."""
        from app.ai.event_enrichment import extract_from_event_text

        cost, age = extract_from_event_text("", None)
        assert cost is None
        assert age is None

    def test_extract_and_update_event(self):
        """Extract and update event dict with cost/age_range."""
        from app.ai.event_enrichment import extract_and_update_event

        event = {
            "name": "Free All-Ages Concert",
            "details": "Family friendly music event",
            "category": "Music"
        }

        updated = extract_and_update_event(event)
        assert updated.get("cost") == "Free"
        assert updated.get("age_range") == "All ages"

    def test_extract_and_update_event_partial(self):
        """Extract and update only available fields."""
        from app.ai.event_enrichment import extract_and_update_event

        event = {
            "name": "Concert - $25",
            "category": "Music"
        }

        updated = extract_and_update_event(event)
        assert updated.get("cost") == "$25"
        # age_range not in details, should be None
        assert updated.get("age_range") is None

    def test_case_insensitive_extraction(self):
        """Extraction should work regardless of case."""
        from app.ai.event_enrichment import extract_cost, extract_age_range

        cost = extract_cost("FREE Concert")
        assert cost == "Free"

        age = extract_age_range("18+ ONLY")
        assert age == "18+"

        age = extract_age_range("ALL AGES Welcome")
        assert age == "All ages"

    def test_extract_is_outdoor_park(self):
        """Extract outdoor designation for park events."""
        from app.ai.event_enrichment import extract_is_outdoor

        outdoor = extract_is_outdoor("Free Concert in the Park")
        assert outdoor == "outdoor"

        outdoor = extract_is_outdoor("Music festival at the lakefront")
        assert outdoor == "outdoor"

    def test_extract_is_outdoor_indoor(self):
        """Extract indoor designation for theater/venue events."""
        from app.ai.event_enrichment import extract_is_outdoor

        indoor = extract_is_outdoor("Theater production at the Chicago Loop")
        assert indoor == "indoor"

        indoor = extract_is_outdoor("Concert at Blue Note nightclub")
        assert indoor == "indoor"

    def test_extract_is_outdoor_none(self):
        """Return None when designation unclear."""
        from app.ai.event_enrichment import extract_is_outdoor

        result = extract_is_outdoor("Some random event")
        assert result is None

    def test_extract_address_standard(self):
        """Extract standard street addresses."""
        from app.ai.event_enrichment import extract_address

        address = extract_address("Event at 123 N Michigan Ave")
        assert address is not None
        assert "123" in address
        assert "Michigan" in address

        address = extract_address("Located at 456 State Street, Chicago")
        assert address is not None
        assert "456" in address

    def test_extract_address_none(self):
        """Return None when no address found."""
        from app.ai.event_enrichment import extract_address

        address = extract_address("Event at some venue")
        assert address is None

    def test_extract_venue_name(self):
        """Extract venue name from event title."""
        from app.ai.event_enrichment import extract_venue_name

        venue = extract_venue_name("Concert at Blue Note")
        assert venue == "Blue Note"

        venue = extract_venue_name("Show at the Chicago Theatre")
        assert venue is not None
        assert "Chicago" in venue

    def test_extract_venue_name_none(self):
        """Return None when no venue found."""
        from app.ai.event_enrichment import extract_venue_name

        venue = extract_venue_name("Random event title")
        assert venue is None
