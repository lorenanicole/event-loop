"""
Tests for app.chat.search_query — keyword extraction and date parsing.

These functions are the shared pre-retrieval layer used by both the chat agent
(search_local_db) and the UI search endpoint (POST /api/search). All imports
come directly from search_query, not via chatbot re-exports.
"""

from app.chat.search_query import extract_date_range, extract_keywords


class TestKeywordExtraction:
    def test_extracts_content_words(self):
        kw = extract_keywords("jazz concerts")
        assert "jazz" in kw
        assert "concerts" in kw

    def test_strips_stop_words(self):
        kw = extract_keywords("the and or a in on at")
        assert all(len(w) > 2 for w in kw)

    def test_strips_event_stop_words(self):
        kw = extract_keywords("show me all events this weekend")
        assert "events" not in kw

    def test_strips_contractions(self):
        kw = extract_keywords("what's happening tonight")
        assert "what's" not in kw

    def test_max_five_keywords(self):
        kw = extract_keywords("jazz rock pop metal classical funk soul blues dance")
        assert len(kw) <= 5

    def test_deduplicates(self):
        kw = extract_keywords("jazz jazz jazz")
        assert kw.count("jazz") == 1

    def test_empty_query_returns_empty(self):
        assert extract_keywords("") == []

    def test_all_stop_words_returns_empty(self):
        assert extract_keywords("what are the events in chicago") == []


class TestDateRangeExtraction:
    def test_this_weekend_starts_saturday(self):
        result = extract_date_range("concerts this weekend")
        assert result is not None
        start, _end = result
        assert start.weekday() == 5  # Saturday

    def test_this_saturday(self):
        result = extract_date_range("anything this saturday")
        assert result is not None
        assert result[0].weekday() == 5

    def test_this_sunday(self):
        result = extract_date_range("brunch this sunday")
        assert result is not None
        assert result[0].weekday() == 6

    def test_this_week_spans_seven_days(self):
        result = extract_date_range("events this week")
        assert result is not None
        start, end = result
        assert (end - start).days >= 7

    def test_this_month_spans_most_of_month(self):
        result = extract_date_range("events this month")
        assert result is not None
        start, end = result
        assert (end - start).days >= 20

    def test_next_week_returns_range(self):
        assert extract_date_range("events next week") is not None

    def test_tonight_ends_at_midnight(self):
        result = extract_date_range("free stuff tonight")
        assert result is not None
        _, end = result
        assert end.hour == 23 and end.minute == 59

    def test_today_returns_range(self):
        assert extract_date_range("what's on today") is not None

    def test_no_date_phrase_returns_none(self):
        assert extract_date_range("jazz at the Green Mill") is None

    def test_unrecognised_phrase_returns_none(self):
        assert extract_date_range("jazz concerts") is None
