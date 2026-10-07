"""Tests for price parsing and the reusable venue extractors.

All fixtures are trimmed from the real markup each venue serves, so these
tests fail if a shared extractor regresses without needing a live request.
"""

from bs4 import BeautifulSoup

from scrapers.custom.venue.chicago_events_scraper import (
    extract_dated_list_items,
    extract_tribe_events,
)
from scrapers.custom.venue.venue_scraper import VenueConfig, parse_cost
from scrapers.external.broadway_in_chicago import BroadwayInChicagoScraper


def config(name="Test Venue", address="1 N Test St"):
    return VenueConfig(
        name=name,
        website_url="https://example.com",
        event_page_url="https://example.com/events",
        category="music",
        address=address,
        selectors={},
    )


class TestParseCost:
    """parse_cost normalizes how venues print prices."""

    def test_plain_amount(self):
        assert parse_cost("$25") == "$25"

    def test_decimal_amount_keeps_cents(self):
        assert parse_cost("$12.50") == "$12.50"

    def test_whole_dollar_decimal_drops_cents(self):
        assert parse_cost("$30.00") == "$30"

    def test_range(self):
        assert parse_cost("$20-$25") == "$20-$25"

    def test_spaced_range(self):
        assert parse_cost("Tickets $45 - $120") == "$45-$120"

    def test_starting_at_is_a_floor_not_a_price(self):
        assert parse_cost("Starting at $64") == "From $64"

    def test_tickets_from(self):
        assert parse_cost("Tickets from $15") == "From $15"

    def test_no_cover_is_free(self):
        assert parse_cost("No cover") == "Free"

    def test_free_with_condition(self):
        assert parse_cost("Free w/ RSVP") == "Free"

    def test_donation(self):
        assert parse_cost("Donation at the door") == "Donation"

    def test_pay_what_you_can(self):
        assert parse_cost("Pay what you can") == "Donation"

    def test_age_limit_is_not_a_price(self):
        assert parse_cost("21+ doors 7:00 PM") is None

    def test_time_is_not_a_price(self):
        assert parse_cost("Doors 6:30PM - Show 7:30PM") is None

    def test_free_parking_is_not_a_free_event(self):
        assert parse_cost("Free parking available") is None

    def test_no_price_at_all(self):
        assert parse_cost("Live music tonight") is None

    def test_empty_and_none(self):
        assert parse_cost("") is None
        assert parse_cost(None) is None


class TestExtractTribeEvents:
    """The Events Calendar emits a machine-readable date, so trust it."""

    LIST_HTML = """
    <div>
      <article class="tribe-events-calendar-list__event">
        <h3 class="tribe-events-calendar-list__event-title">
          <a href="/event/sons-of-chicago/">Sons of Chicago: Rocking Blues</a>
        </h3>
        <div class="tribe-events-calendar-list__event-datetime">
          <time datetime="2026-10-17">October 17 @ 7:30 pm</time>
        </div>
        <div>Non-members - $35</div>
      </article>
      <article class="tribe-events-calendar-list__event">
        <h3 class="tribe-events-calendar-list__event-title">
          <a href="https://example.com/event/moth/">The Moth StorySLAM</a>
        </h3>
        <div class="tribe-events-calendar-list__event-datetime">
          <time datetime="2026-11-02">November 2 @ 7:00 pm</time>
        </div>
      </article>
    </div>
    """

    def extracted(self):
        return extract_tribe_events(BeautifulSoup(self.LIST_HTML, "html.parser"), config())

    def test_finds_every_event(self):
        assert len(self.extracted()) == 2

    def test_uses_the_iso_datetime_attribute(self):
        assert self.extracted()[0].date == "Oct 17, 2026"

    def test_reads_the_time(self):
        assert self.extracted()[0].time == "7:30 PM"

    def test_collects_the_price(self):
        assert self.extracted()[0].cost == "$35"

    def test_absent_price_stays_none(self):
        assert self.extracted()[1].cost is None

    def test_relative_url_is_made_absolute(self):
        assert self.extracted()[0].url == "https://example.com/event/sons-of-chicago/"

    def test_absolute_url_is_left_alone(self):
        assert self.extracted()[1].url == "https://example.com/event/moth/"

    def test_ignores_a_bare_clock_time_in_the_time_element(self):
        """Month view emits <time datetime="14:00">, which is not a date."""
        html = """
        <article class="tribe-events-calendar-month__calendar-event">
          <time datetime="14:00">2:00 PM</time>
          <div class="tribe-events-calendar-month__calendar-event-title">
            <a href="/event/film/">65+ Film: Mildred Pierce</a>
          </div>
          <time datetime="2026-10-02"></time>
        </article>
        """
        events = extract_tribe_events(BeautifulSoup(html, "html.parser"), config())
        assert [e.date for e in events] == ["Oct 2, 2026"]

    def test_multiday_event_is_not_repeated_per_day(self):
        html = """
        <div>
          <article class="tribe-events-calendar-month__multiday-event">
            <time datetime="2026-10-02"></time>
            <div class="tribe-events-calendar-month__multiday-event-bar-title">Bridge Showcase</div>
          </article>
          <article class="tribe-events-calendar-month__multiday-event">
            <time datetime="2026-10-02"></time>
            <div class="tribe-events-calendar-month__multiday-event-bar-title">Bridge Showcase</div>
          </article>
        </div>
        """
        assert len(extract_tribe_events(BeautifulSoup(html, "html.parser"), config())) == 1


class TestExtractDatedListItems:
    """Keys off date text, so it survives builders with unstable classes."""

    def test_wix_style_card_with_obfuscated_classes(self):
        """The innermost dated element is a bare date div; the title is a sibling."""
        html = """
        <ul>
          <li class="qElViY">
            <div class="aBc"><div class="dEf">Juebebes De Comedia</div></div>
            <div class="gHi">Thu, Oct 08</div>
            <a class="jKl" href="/event-info/comedia">TICKETS</a>
          </li>
        </ul>
        """
        events = extract_dated_list_items(BeautifulSoup(html, "html.parser"), config())
        assert len(events) == 1
        assert events[0].name == "Juebebes De Comedia"
        assert events[0].date.startswith("Oct 8,")

    def test_date_then_title_with_weekday(self):
        html = """
        <ul><li class="first">
          <span class="date">OCT 7 &bull; WEDNESDAY</span>
          <h3><a href="/show/uk-revisited/">Eddie Jobson's U.K. Revisited</a></h3>
          <span>8:00 pm</span>
        </li></ul>
        """
        events = extract_dated_list_items(BeautifulSoup(html, "html.parser"), config())
        assert len(events) == 1
        assert events[0].name == "Eddie Jobson's U.K. Revisited"
        assert events[0].time == "8:00 PM"

    def test_run_stores_a_start_and_an_end(self):
        html = """
        <div class="event"><div class="wrap">
          <h2>The Winter's Tale</h2>
          <p class="dates">OCT 13&mdash;DEC 12, 2026</p>
          <a href="/plays/winters-tale/">BUY TICKETS</a>
        </div></div>
        """
        events = extract_dated_list_items(BeautifulSoup(html, "html.parser"), config())
        assert len(events) == 1
        assert events[0].date == "Oct 13, 2026"
        assert events[0].date_end == "Dec 12, 2026"

    def test_run_crossing_new_year_starts_the_previous_year(self):
        """"OCT 27-MAR 20, 2027" runs from 2026 into 2027."""
        html = """
        <div class="event"><div class="wrap">
          <h2>80 Minutes Around the World</h2>
          <p>OCT 27&mdash;MAR 20, 2027</p>
        </div></div>
        """
        events = extract_dated_list_items(BeautifulSoup(html, "html.parser"), config())
        assert events[0].date == "Oct 27, 2026"
        assert events[0].date_end == "Mar 20, 2027"

    def test_list_container_is_not_reported_as_one_event(self):
        html = """
        <ul class="shows">
          <li class="a"><span>Oct 8</span><h3>First Band</h3></li>
          <li class="b"><span>Oct 9</span><h3>Second Band</h3></li>
        </ul>
        """
        events = extract_dated_list_items(BeautifulSoup(html, "html.parser"), config())
        assert sorted(e.name for e in events) == ["First Band", "Second Band"]

    def test_card_without_a_date_is_skipped(self):
        html = '<ul><li class="a"><h3>Private Event Rental</h3><a href="/x">INFO</a></li></ul>'
        assert extract_dated_list_items(BeautifulSoup(html, "html.parser"), config()) == []

    def test_card_with_only_a_date_is_skipped(self):
        html = '<ul><li class="a"><span>Oct 8</span><a href="/x">TICKETS</a></li></ul>'
        assert extract_dated_list_items(BeautifulSoup(html, "html.parser"), config()) == []


class TestBroadwayInChicago:
    """One site programs five theaters, so the venue drives the neighborhood."""

    CARD_HTML = """
    <div class="elementor">
      <div class="card">
        <span>Sep 29</span><span>&ndash;</span><span>Oct 11, 2026</span>
        <h3>Operation Mincemeat: A New Musical</h3>
        <p>CIBC Theatre</p>
        <a href="/shows/operation-mincemeat-a-new-musical/">SHOW AND TICKET INFO</a>
      </div>
      <div class="card">
        <span>Oct 27</span><span>&ndash;</span><span>Mar 20, 2027</span>
        <h3>80 Minutes Around the World</h3>
        <p>Cadillac Palace Theatre</p>
        <a href="/shows/80-minutes/">SHOW AND TICKET INFO</a>
      </div>
    </div>
    """

    def parsed(self):
        return BroadwayInChicagoScraper()._parse(self.CARD_HTML)

    def test_parses_each_show_once(self):
        assert len(self.parsed()) == 2

    def test_title_excludes_the_theatre_and_the_cta(self):
        assert self.parsed()[0].name == "Operation Mincemeat: A New Musical"

    def test_run_dates(self):
        show = self.parsed()[0]
        assert (show.date.month, show.date.day, show.date.year) == (9, 29, 2026)
        assert (show.date_end.month, show.date_end.day, show.date_end.year) == (10, 11, 2026)

    def test_run_crossing_new_year_starts_the_previous_year(self):
        show = self.parsed()[1]
        assert show.date.year == 2026 and show.date.month == 10
        assert show.date_end.year == 2027 and show.date_end.month == 3

    def test_theatre_becomes_the_venue_and_address(self):
        show = self.parsed()[0]
        assert show.venue_name == "CIBC Theatre"
        assert "18 W Monroe St" in show.address

    def test_every_mapped_theatre_has_an_address_and_neighborhood(self):
        for venue, address, hood in BroadwayInChicagoScraper.THEATRES.values():
            assert venue and address and hood
