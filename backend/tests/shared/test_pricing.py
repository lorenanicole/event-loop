"""Tests for reading a ticket price off an event page.

Half of these pin rejections. A wrong price is worse than no price - it is the
one field on a listing somebody might plan around - so every pattern that was
tried and measured as unreliable has a test here saying so, to stop it being
reintroduced as an obvious improvement.
"""

import pytest

from shared.pricing import (
    SOURCE_PRICE_RULES,
    cost_from_page,
    money,
    price_from_jsonld,
    price_from_offers,
    price_from_source_rules,
    render,
)
from bs4 import BeautifulSoup


def ld(payload: str) -> BeautifulSoup:
    return BeautifulSoup(
        f'<html><head><script type="application/ld+json">{payload}</script></head></html>',
        "html.parser",
    )


class TestMoney:
    def test_whole_dollars_lose_the_cents(self):
        assert money(25.0) == "$25"

    def test_a_part_dollar_keeps_two_places(self):
        """25.5 must not render as "$25.5", which reads like a truncation."""
        assert money(25.5) == "$25.50"


class TestRender:
    def test_one_amount(self):
        assert render([25.0]) == "$25"

    def test_a_span(self):
        assert render([25.0, 40.0]) == "$25-$40"

    def test_all_zero_is_free(self):
        assert render([0.0]) == "Free"

    def test_free_entry_with_paid_tiers_leads_with_free(self):
        """"$0-$40" reads like a bug."""
        assert render([0.0, 40.0]) == "Free-$40"

    def test_nothing_found_is_none(self):
        assert render([]) is None


class TestJsonLd:
    def test_a_single_offer(self):
        assert price_from_offers({"offers": {"price": "33.52"}}) == "$33.52"

    def test_tiers_become_a_span(self):
        node = {"offers": [{"price": 20}, {"price": 45}]}
        assert price_from_offers(node) == "$20-$45"

    def test_low_and_high_price(self):
        node = {"offers": {"lowPrice": 20, "highPrice": 60}}
        assert price_from_offers(node) == "$20-$60"

    def test_a_nested_price_specification(self):
        node = {"offers": {"priceSpecification": {"price": "41.00"}}}
        assert price_from_offers(node) == "$41"

    def test_a_zero_offer_is_free(self):
        assert price_from_offers({"offers": {"price": 0}}) == "Free"

    def test_no_offers_is_none(self):
        assert price_from_offers({"name": "A show"}) is None

    def test_a_non_numeric_price_is_ignored(self):
        assert price_from_offers({"offers": {"price": "call for pricing"}}) is None

    def test_an_event_wrapped_in_a_graph_is_still_found(self):
        """Sites nest the Event under @graph or mainEntity, so the walk has to
        go deeper than the top level."""
        soup = ld('{"@graph":[{"@type":"Event","offers":{"price":"26.22"}}]}')
        assert price_from_jsonld(soup) == "$26.22"

    def test_malformed_json_does_not_raise(self):
        assert price_from_jsonld(ld("{not json")) is None


class TestSourceRules:
    def test_park_district_free_programming(self):
        text = "2411 W. 55th St. Chicago, IL 60632 Event Fee $0.00 Age Range Early Childhood"
        assert price_from_source_rules("chicago_park_district", text) == "Free"

    def test_park_district_paid_programming(self):
        text = "4707 W. Marquette Rd. Chicago, IL 60629 Event Fee $5.00 Age Range Youth"
        assert price_from_source_rules("chicago_park_district", text) == "$5"

    def test_jazz_showcase_general_admission(self):
        text = "TICKETS General Admission $25 VIP $40 Student Tickets $20 CASH ONLY"
        assert price_from_source_rules("chicago_venue_jazz_showcase", text) == "$25"

    def test_jazz_showcase_writes_it_the_other_way_round_too(self):
        text = "the innovation coalition of Forbes. TICKETS Thursday - $30 general admission"
        assert price_from_source_rules("chicago_venue_jazz_showcase", text) == "$30"

    def test_old_town_reports_the_advertised_total_not_the_base(self):
        """"$23 General Public ($20 + $3 fee)" - $23 is what somebody pays.
        A nearest-number scan reported $20 and undercut every show."""
        text = "Maurer Concert Hall 773.728.6000 $23 General Public ($20 + $3 fee)"
        got = price_from_source_rules("chicago_venue_old_town_school_of_folk_music", text)
        assert got == "$23"

    def test_sleeping_village_collects_every_tier(self):
        text = "Doors open - 9:00 PM Tickets TIER 1 $20.00 Get tickets TIER 2 $25.00"
        assert price_from_source_rules("chicago_venue_sleeping_village", text) == "$20-$25"

    def test_sleeping_village_early_bird(self):
        text = "Tickets EARLY BIRD $20.00 Get tickets General Admission $25.00"
        assert price_from_source_rules("chicago_venue_sleeping_village", text) == "$20-$25"

    def test_goodman_reports_the_whole_span(self):
        text = "Select Evening - 15 Performances - $73.00 to $82.00 Sold Out!"
        assert price_from_source_rules("chicago_venue_goodman_theatre", text) == "$73-$82"

    def test_den_theatre(self):
        text = "Show Length: 60 Minutes Tickets: $20 Rated: R"
        assert price_from_source_rules("chicago_venue_den_theatre", text) == "$20"

    def test_martyrs_advance_and_door(self):
        text = "Wed, Oct 7th - Doors 7PM - Show 8PM - $10adv/$15doors Beat The Meatles"
        assert price_from_source_rules("chicago_venue_martyrss", text) == "$10-$15"

    def test_navy_pier(self):
        text = "for the date you plan to attend. General admission is $27 when purchased online"
        assert price_from_source_rules("chicago_venue_navy_pier", text) == "$27"

    def test_a_source_with_no_rules_reads_nothing(self):
        assert price_from_source_rules("do312", "Tickets: $20") is None

    def test_an_unknown_source_reads_nothing(self):
        assert price_from_source_rules(None, "Tickets: $20") is None


class TestRejections:
    """Patterns that look like prices and are not. Each was observed on a real
    page and produced a confident wrong answer before being excluded."""

    @pytest.mark.parametrize("source,text", [
        # McCormick Place: exhibitor billing, not admission.
        ("chicago_venue_mccormick_place",
         "for centrally billed companies, a usage deposit of $300 per line is required"),
        # Broadway In Chicago: a limited day-of-show offer, not the ticket.
        ("broadway_in_chicago",
         "rush offer details A Limited number of $49* day-of-show rush tickets will be"),
        # Zanies: the per-show URL renders the whole month, so any price found
        # belongs to some other show on the page.
        ("chicago_venue_zanies_comedy_club",
         "Wed, Oct 07 2026 Vidura Bandara Rajapaksa Ages 21 and up $37 FULL PERFORMANCE LISTING"),
        # Reggies serves bytes that decode to garbage with stray dollar signs.
        ("chicago_venue_reggies_chicago", "\x03\x05\x07 $7AH ... \x15$7 garbage"),
    ])
    def test_these_sources_have_no_rule_so_nothing_is_read(self, source, text):
        assert source not in SOURCE_PRICE_RULES
        assert price_from_source_rules(source, text) is None

    def test_a_time_is_not_a_price(self):
        assert price_from_source_rules("chicago_venue_den_theatre", "Doors 7:30 PM") is None


class TestCostFromPage:
    def test_structured_data_wins_over_text(self):
        """Where both are present the numeric one is trusted."""
        html = (
            '<html><head><script type="application/ld+json">'
            '{"@type":"Event","offers":{"price":"41.00"}}</script></head>'
            "<body>Tickets: $20</body></html>"
        )
        assert cost_from_page(html, "chicago_venue_den_theatre") == "$41"

    def test_falls_back_to_the_source_rule(self):
        html = "<html><body>Show Length: 60 Minutes Tickets: $20 Rated: R</body></html>"
        assert cost_from_page(html, "chicago_venue_den_theatre") == "$20"

    def test_a_script_tag_price_is_not_read_as_prose(self):
        """Scripts are stripped before the text scan, or a price in a tracking
        payload would be reported as the ticket price."""
        html = (
            "<html><body><script>var ticketPrice = 'Tickets: $999'</script>"
            "<p>Doors 7pm</p></body></html>"
        )
        assert cost_from_page(html, "chicago_venue_den_theatre") is None

    def test_empty_input(self):
        assert cost_from_page("", "chicago_park_district") is None

    def test_a_non_html_body_is_not_parsed(self):
        """Reggies responds with bytes that are not a document."""
        assert cost_from_page("\x00\x03\x05 $7 \x11", "chicago_venue_reggies_chicago") is None
