"""Tests for telling a Chicago address from a suburban one.

do312 covers the whole metro, so 44 upcoming events are in Glencoe,
Naperville, Rosemont and seventeen other towns. Shown under a headline that
reads "anywhere in Chicago", they misrepresent themselves - so they are
labelled rather than deleted, because the Botanic Garden and the Evanston
rooms are worth knowing about.
"""

import pytest

from shared.locality import locality_of


class TestSuburbsAreLabelled:
    @pytest.mark.parametrize(
        "address,expected",
        [
            ("1476 Miner Street, Des Plaines, IL, 60016", "Des Plaines"),
            ("1000 Lake Cook Road, Glencoe, IL, 60022", "Glencoe"),
            ("9870 Berwyn Ave, Rosemont, IL, 60018", "Rosemont"),
            ("1245 Chicago Avenue, Evanston, IL, 60202", "Evanston"),
        ],
    )
    def test_a_suburb_is_named(self, address, expected):
        assert locality_of(address) == expected

    def test_a_suite_number_is_not_mistaken_for_a_city(self):
        """Messy addresses put a unit in the position a city usually occupies."""
        assert locality_of("Suite 8, Naperville, IL, 60540") == "Naperville"


class TestChicagoIsNotLabelled:
    @pytest.mark.parametrize(
        "address",
        [
            "2011 W North Ave, Chicago, IL",
            "Thalia Hall, 1807 S Allport St, Chicago, IL 60608",
            "1354 W Wabansia Ave, Chicago, Illinois 60642",
        ],
    )
    def test_a_chicago_address_gets_no_label(self, address):
        assert locality_of(address) is None

    def test_a_street_named_after_a_suburb_is_still_chicago(self):
        """The reason this reads the city position rather than matching names:
        "3020 N. Oak Park Ave" is a Chicago street, and a name match would
        move a real Chicago event to Oak Park."""
        assert locality_of("3020 N. Oak Park Ave. Chicago, IL 60634") is None


class TestNothingIsInvented:
    @pytest.mark.parametrize(
        "address", [None, "", "   ", "no address at all", "Somewhere, NY 10001"]
    )
    def test_an_unusable_address_gets_no_label(self, address):
        """None means "do not label". Inventing a locality is worse than
        omitting one, since the label is shown as fact on the card."""
        assert locality_of(address) is None


class TestItReachesTheModel:
    def test_event_create_derives_it_from_the_address(self):
        """Derived at the boundary, so no scraper has to know about it."""
        from datetime import datetime

        from shared.schemas import EventCreate

        event = EventCreate(
            name="Planting Design",
            date=datetime(2026, 11, 1),
            category="Arts",
            address="1000 Lake Cook Road, Glencoe, IL, 60022",
            origination_url="https://example.test/1",
        )
        assert event.locality == "Glencoe"

    def test_a_chicago_event_carries_no_locality(self):
        from datetime import datetime

        from shared.schemas import EventCreate

        event = EventCreate(
            name="Some Show",
            date=datetime(2026, 11, 1),
            category="Music",
            address="2011 W North Ave, Chicago, IL",
            origination_url="https://example.test/2",
        )
        assert event.locality is None
