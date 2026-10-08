"""
Tests for shared.enrichment — cost, age, outdoor, address, and venue extraction.

These functions are pure regex with no DB or AI dependency. All imports come
directly from shared.enrichment, not via the deprecated app.chat.event_enrichment shim.
"""

from shared.enrichment import (
    extract_address,
    extract_age_range,
    extract_and_update_event,
    extract_cost,
    extract_from_event_text,
    extract_is_outdoor,
    extract_venue_name,
)


class TestExtractCost:
    def test_free_literal(self):
        assert extract_cost("Free Concert in the Park") == "Free"

    def test_no_admission_fee(self):
        assert extract_cost("No admission fee - all welcome!") == "Free"

    def test_dollar_amount(self):
        assert extract_cost("Comedy Show - $25") == "$25"

    def test_price_range(self):
        assert extract_cost("Tickets: $15-30") == "$15-30"

    def test_donation(self):
        assert extract_cost("Suggested donation: $10") == "Donation"

    def test_pwyc(self):
        assert extract_cost("PWYC") == "Donation"

    def test_none_when_no_price(self):
        assert extract_cost("A wonderful evening of jazz") is None

    def test_none_on_empty_string(self):
        assert extract_cost("") is None

    def test_case_insensitive(self):
        assert extract_cost("FREE Concert") == "Free"


class TestExtractAgeRange:
    def test_all_ages(self):
        assert extract_age_range("Family friendly event") == "All ages"

    def test_kids_friendly(self):
        assert extract_age_range("A fun event for kids") == "Kids friendly"

    def test_plus_format(self):
        result = extract_age_range("21+ event")
        assert result is not None and "21" in result

    def test_and_over_format(self):
        result = extract_age_range("18 and over")
        assert result is not None and "18" in result

    def test_years_old_format(self):
        result = extract_age_range("Must be 18 years old")
        assert result is not None and "18" in result

    def test_none_when_no_age(self):
        assert extract_age_range("A jazz concert downtown") is None

    def test_none_on_empty_string(self):
        assert extract_age_range("") is None

    def test_case_insensitive(self):
        result = extract_age_range("ALL AGES Welcome")
        assert result == "All ages"
        result2 = extract_age_range("18+ ONLY")
        assert result2 is not None and "18" in result2


class TestExtractIsOutdoor:
    def test_park_is_outdoor(self):
        assert extract_is_outdoor("Free Concert in the Park") == "outdoor"

    def test_lakefront_is_outdoor(self):
        assert extract_is_outdoor("Music festival at the lakefront") == "outdoor"

    def test_theater_is_indoor(self):
        assert extract_is_outdoor("Theater production at the Chicago Loop") == "indoor"

    def test_nightclub_is_indoor(self):
        assert extract_is_outdoor("Concert at Blue Note nightclub") == "indoor"

    def test_unclear_returns_none(self):
        assert extract_is_outdoor("Some random event") is None

    def test_empty_returns_none(self):
        assert extract_is_outdoor("") is None


class TestExtractAddress:
    def test_standard_address(self):
        addr = extract_address("Event at 123 N Michigan Ave")
        assert addr is not None
        assert "123" in addr
        assert "Michigan" in addr

    def test_address_with_city(self):
        addr = extract_address("Located at 456 State Street, Chicago")
        assert addr is not None
        assert "456" in addr

    def test_none_when_no_address(self):
        assert extract_address("Event at some venue") is None

    def test_none_on_empty(self):
        assert extract_address("") is None


class TestExtractVenueName:
    def test_at_venue(self):
        assert extract_venue_name("Concert at Blue Note") == "Blue Note"

    def test_at_the_venue(self):
        venue = extract_venue_name("Show at the Chicago Theatre")
        assert venue is not None and "Chicago" in venue

    def test_none_when_no_at(self):
        assert extract_venue_name("Random event title") is None

    def test_none_on_empty(self):
        assert extract_venue_name("") is None


class TestExtractFromEventText:
    def test_extracts_both_fields(self):
        cost, age = extract_from_event_text("Free concert - all ages", "")
        assert cost == "Free"
        assert age == "All ages"

    def test_empty_inputs(self):
        cost, age = extract_from_event_text("", "")
        assert cost is None
        assert age is None


class TestExtractAndUpdateEvent:
    def test_enriches_all_available_fields(self):
        event = {
            "name": "Free all ages music event",
            "details": "A free all ages music event",
            "category": "Music",
        }
        updated = extract_and_update_event(event)
        assert updated.get("cost") == "Free"
        assert updated.get("age_range") == "All ages"

    def test_enriches_partial_fields(self):
        event = {"name": "Concert - $25", "category": "Music"}
        updated = extract_and_update_event(event)
        assert updated.get("cost") == "$25"
        assert updated.get("age_range") is None

    def test_empty_dict_returned_unchanged(self):
        assert extract_and_update_event({}) == {}
