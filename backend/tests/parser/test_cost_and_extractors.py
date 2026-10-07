"""Tests for price parsing and the reusable venue extractors.

All fixtures are trimmed from the real markup each venue serves, so these
tests fail if a shared extractor regresses without needing a live request.
"""

from datetime import datetime

from bs4 import BeautifulSoup

from scrapers.custom.venue.chicago_events_scraper import (
    extract_dated_links,
    extract_dated_list_items,
    extract_labelled_meeting,
    extract_songkick_venue,
    extract_tickeri_venue,
    extract_tribe_events,
)
from scrapers.custom.venue.venue_scraper import VenueConfig, parse_cost
from scrapers.external.broadway_in_chicago import BroadwayInChicagoScraper
from scrapers.external.chicago_park_district import ChicagoParkDistrictScraper
from scrapers.external.ticketmaster import TicketmasterScraper


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
        """ "OCT 27-MAR 20, 2027" runs from 2026 into 2027."""
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


class TestExtractSongkickVenue:
    """For venues with no website of their own."""

    HTML = """
    <div class="component events-summary">
      <ul class="event-listings">
        <li class="with-date"><strong><time datetime="2026-10-10T21:00:00-0500">Saturday 10 October 2026</time></strong></li>
        <li>
          <time datetime="2026-10-10T21:00:00-0500"></time>
          <a href="/concerts/43435793-mazizo-musical-at-los-globos">
            <p class="artists">Mazizo Musical</p>
            <p class="location">Los Globos, Chicago, IL, US</p>
          </a>
          <span>BUY TICKETS</span><span>INTERESTED</span><span>GOING</span>
        </li>
        <li>
          <time datetime="2026-11-05T20:00:00-0600"></time>
          <a href="/concerts/99999-rata-blanca">
            <p class="artists">Rata Blanca</p>
            <p class="location">Los Globos, Chicago, IL, US</p>
          </a>
        </li>
      </ul>
    </div>
    """

    def extracted(self):
        config_ = config(name="Los Globos", address="3059 S Central Park Ave")
        return extract_songkick_venue(BeautifulSoup(self.HTML, "html.parser"), config_)

    def test_one_event_per_concert(self):
        """The date-header <li> must not become a third event."""
        assert len(self.extracted()) == 2

    def test_artist_is_the_title(self):
        assert [e.name for e in self.extracted()] == ["Mazizo Musical", "Rata Blanca"]

    def test_date_and_time_from_the_iso_stamp(self):
        event = self.extracted()[0]
        assert event.date == "Oct 10, 2026"
        assert event.time == "9:00 PM"

    def test_handles_a_different_utc_offset(self):
        assert self.extracted()[1].date == "Nov 5, 2026"

    def test_url_is_made_absolute(self):
        assert self.extracted()[0].url.startswith("https://www.songkick.com/concerts/")

    def test_venue_name_and_address_are_ours_not_songkick_s(self):
        event = self.extracted()[0]
        assert event.venue_name == "Los Globos"
        assert "3059 S Central Park Ave" in event.location


class TestParkDistrictDates:
    """Park District cards print dates three different ways."""

    TODAY = datetime(2026, 10, 6)

    def short(self, text):
        start, end = ChicagoParkDistrictScraper._dates_from_short(text, self.TODAY)
        fmt = lambda d: d.strftime("%Y-%m-%d") if d else None
        return fmt(start), fmt(end)

    def full(self, text):
        start, end = ChicagoParkDistrictScraper._dates_from_text(text)
        fmt = lambda d: d.strftime("%Y-%m-%d") if d else None
        return fmt(start), fmt(end)

    def test_full_run_with_years(self):
        assert self.full("April 25, 2026 - October 31, 2026") == ("2026-04-25", "2026-10-31")

    def test_full_single_date(self):
        assert self.full("October 8, 2026") == ("2026-10-08", None)

    def test_full_ignores_clock_times(self):
        assert self.full("10:00 AM - 12:00 PM") == (None, None)

    def test_yearless_single_date(self):
        assert self.short("Oct 7") == ("2026-10-07", None)

    def test_yearless_earlier_month_is_next_year(self):
        """The listing only shows current and upcoming events."""
        assert self.short("Feb 3") == ("2027-02-03", None)

    def test_yearless_run_is_anchored_on_its_end(self):
        """ "Apr 25 - Oct 31" read in October is under way, not starting next April."""
        assert self.short("Apr 25 - Oct 31") == ("2026-04-25", "2026-10-31")

    def test_yearless_run_crossing_new_year(self):
        assert self.short("Dec 20 - Jan 5") == ("2026-12-20", "2027-01-05")

    def test_repeated_same_date_is_not_a_run(self):
        assert self.short("Oct 7 Oct 7") == ("2026-10-07", None)

    def test_no_date_at_all(self):
        assert self.short("") == (None, None)

    def test_venue_is_read_from_the_title(self):
        """Park names are written into the title as "... at Austin TH"."""
        venue = ChicagoParkDistrictScraper._venue_from_title
        assert venue("Boxing Show at Fuller") == "Fuller"
        assert venue("Community Climb at Steelworkers") == "Steelworkers"
        assert venue("Drop-In Toddler Garden Hour") is None


class TestTicketmasterPriceRanges:
    """Discovery's structured priceRanges beats scanning the title text."""

    price = staticmethod(TicketmasterScraper._price_from_ranges)

    def test_range(self):
        assert self.price([{"type": "standard", "min": 35.0, "max": 95.0}]) == "$35-$95"

    def test_single_price(self):
        assert self.price([{"type": "standard", "min": 49.0, "max": 49.0}]) == "$49"

    def test_zero_is_free(self):
        assert self.price([{"type": "standard", "min": 0, "max": 0}]) == "Free"

    def test_resale_range_is_ignored(self):
        """Resale runs far above what the event actually costs."""
        ranges = [
            {"type": "standard", "min": 20, "max": 40},
            {"type": "resale", "min": 300, "max": 900},
        ]
        assert self.price(ranges) == "$20-$40"

    def test_untyped_range_is_used(self):
        assert self.price([{"min": 25.50, "max": 25.50}]) == "$25.50"

    def test_whole_dollars_omit_cents(self):
        assert self.price([{"min": 30.00, "max": 30.00}]) == "$30"

    def test_missing_or_malformed_input(self):
        assert self.price(None) is None
        assert self.price([]) is None
        assert self.price("nope") is None
        assert self.price([{"currency": "USD"}]) is None


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


class TestExtractTickeriVenue:
    """Tickeri ships its page data as JSON, including ticket prices."""

    HTML = """
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props": {"pageProps": {"data": {"venue": {"events": [
      {"__typename": "Event", "name": "Chencho Corleone", "status": "LIVE",
       "url": "https://www.tickeri.com/events/vrip6vps83ym/chencho-corleone",
       "ticketPriceRange": {"min": {"major": 70}},
       "eventDate": {"date": {"isoDateTime": "2026-10-16T20:00:00-05:00"}}},
      {"__typename": "Event", "name": "Rata Blanca", "status": "LIVE",
       "url": "https://www.tickeri.com/events/x/rata-blanca",
       "ticketPriceRange": {"min": {"major": 60}, "max": {"major": 120}},
       "eventDate": {"date": {"isoDateTime": "2026-11-05T20:00:00-06:00"}}},
      {"__typename": "Event", "name": "Scrapped Show", "status": "CANCELED",
       "url": "https://www.tickeri.com/events/y/scrapped",
       "ticketPriceRange": {"min": {"major": 25}},
       "eventDate": {"date": {"isoDateTime": "2026-11-20T20:00:00-06:00"}}}
    ]}}}}}
    </script></body></html>
    """

    def extracted(self):
        config_ = config(name="V-Live", address="2501 S Kedzie Ave")
        return extract_tickeri_venue(BeautifulSoup(self.HTML, "html.parser"), config_)

    def test_canceled_shows_are_skipped(self):
        assert [e.name for e in self.extracted()] == ["Chencho Corleone", "Rata Blanca"]

    def test_date_and_time_from_the_iso_stamp(self):
        event = self.extracted()[0]
        assert event.date == "Oct 16, 2026"
        assert event.time == "8:00 PM"

    def test_a_floor_price_is_labelled_as_one(self):
        """ "min" alone is a starting price, not the whole price."""
        assert self.extracted()[0].cost == "From $70"

    def test_a_real_range_is_shown_as_a_range(self):
        assert self.extracted()[1].cost == "$60-$120"

    def test_missing_next_data_returns_nothing(self):
        assert extract_tickeri_venue(BeautifulSoup("<html></html>", "html.parser"), config()) == []

    def test_malformed_json_returns_nothing(self):
        html = '<script id="__NEXT_DATA__">{not json</script>'
        assert extract_tickeri_venue(BeautifulSoup(html, "html.parser"), config()) == []


class TestNamedSelectors:
    """Where markup is semantic, name the elements instead of guessing.

    The heuristic reads the first plausible line as the title, which on these
    sites is a kicker label or a photo credit sitting above the real one.
    """

    NEWBERRY_HTML = """
    <div class="col-12 col-md-6">
      <p class="tag-label">EVENT&mdash;EXHIBITION</p>
      <h4>Collecting Stories: New Acquisitions at the Newberry</h4>
      <p>Sep 10&ndash;Dec 30, 2026</p>
      <p>At the Newberry &ndash; Hanson Gallery</p>
      <a href="/calendar/collecting-stories">More</a>
    </div>
    """

    def newberry(self):
        config_ = config(name="Newberry Library", address="60 W Walton St")
        config_.selectors = {"event_container": "div.col-12.col-md-6", "title": "h4"}
        return extract_dated_list_items(BeautifulSoup(self.NEWBERRY_HTML, "html.parser"), config_)

    def test_named_title_beats_the_kicker_label(self):
        """Without the selector this came out as "Event—Exhibition"."""
        assert self.newberry()[0].name == "Collecting Stories: New Acquisitions at the Newberry"

    def test_run_dates_still_parsed(self):
        event = self.newberry()[0]
        assert event.date == "Sep 10, 2026"
        assert event.date_end == "Dec 30, 2026"

    def test_a_named_date_element_is_used_when_given(self):
        html = """
        <div class="listing_teaser future">
          <h2 class="listing_teaser_title">Africa and the New Global Order</h2>
          <div class="listing_teaser_media">THEMBA HADEBE / AP</div>
          <div class="listing_teaser_content_date"><span>Oct</span><span>7</span></div>
        </div>
        """
        config_ = config(name="Chicago Council on Global Affairs", address="130 E Randolph St")
        config_.selectors = {
            "event_container": "div.listing_teaser.future",
            "title": "h2.listing_teaser_title",
            "date": ".listing_teaser_content_date",
        }
        events = extract_dated_list_items(BeautifulSoup(html, "html.parser"), config_)
        # Without the named title this came out as the photo credit.
        assert events[0].name == "Africa and the New Global Order"
        assert events[0].date.startswith("Oct 7,")

    def test_a_card_without_a_date_is_skipped(self):
        html = '<div class="col-12 col-md-6"><h4>Undated thing</h4></div>'
        config_ = config()
        config_.selectors = {"event_container": "div.col-12.col-md-6", "title": "h4"}
        assert extract_dated_list_items(BeautifulSoup(html, "html.parser"), config_) == []


class TestLabelledMeeting:
    """A user group's homepage is prose, not a calendar."""

    HTML = """
    <div>
      <h3>NEXT EVENT CHIPY __MAIN__ MEETING</h3>
      <p><strong>When:</strong></p>
      <p>Oct. 8, 2026, 6 p.m.</p>
      <p><strong>Where:</strong></p>
      <p>AlphaSense</p>
      <p>200 N. LaSalle Street.</p>
      <p>Suite 1100.</p>
      <p>Chicago, IL 60601</p>
      <p><strong>Directions:</strong></p>
      <p>Building entry details that must not be read as an address.</p>
    </div>
    """

    def extracted(self):
        config_ = config(name="ChiPy (Chicago Python User Group)", address="Varies by month")
        return extract_labelled_meeting(BeautifulSoup(self.HTML, "html.parser"), config_)

    def test_one_event(self):
        assert len(self.extracted()) == 1

    def test_date_and_time(self):
        event = self.extracted()[0]
        assert event.date == "Oct 8, 2026"
        assert event.time == "6 PM"

    def test_kicker_stripped_from_the_title(self):
        assert self.extracted()[0].name == "CHIPY __MAIN__ MEETING"

    def test_host_venue_read_from_the_page(self):
        """The group meets at a different company each month."""
        event = self.extracted()[0]
        assert event.venue_name == "AlphaSense"
        assert "200 N. LaSalle Street" in event.location

    def test_the_next_label_stops_the_address(self):
        """ "Directions:" must not be swallowed into the address."""
        assert "Building entry" not in self.extracted()[0].location

    def test_no_when_block_yields_nothing(self):
        html = "<div><h3>Some Meeting</h3><p>No details yet.</p></div>"
        assert extract_labelled_meeting(BeautifulSoup(html, "html.parser"), config()) == []


class TestDatedLinks:
    """Jekyll-style sites put the date in the URL: /events/YYYY/MM/DD/slug."""

    HTML = """
    <div>
      <a href="/events/2099/10/13/cook-county-digital-equity-team">Online: Cook County Digital Equity Team</a>
      <a href="/events/2099/10/13/cook-county-digital-equity-team">Details</a>
      <a href="/events/2099/10/20/open-hack">Online: Open Hack #703</a>
      <a href="/events/2001/09/29/ancient-meeting">Online: Open Hack #1</a>
      <a href="/blog/2099/02/09/board-member-elections">Board Member Elections</a>
      <a href="/about">About us</a>
    </div>
    """

    def extracted(self):
        config_ = config(name="Chi Hack Night", address="222 W Merchandise Mart Plaza")
        config_.website_url = "https://chihacknight.org"
        return extract_dated_links(BeautifulSoup(self.HTML, "html.parser"), config_)

    def test_reads_the_date_from_the_url(self):
        """No year to infer and no date in the prose to trip over."""
        dates = {e.date for e in self.extracted()}
        assert "Oct 13, 2099" in dates

    def test_past_events_are_dropped(self):
        """These sites keep every past meeting linked forever - 718 of them."""
        assert all("2001" not in e.date for e in self.extracted())

    def test_the_same_event_is_not_counted_twice(self):
        """Each card links the event from its title and from "Details"."""
        titles = [e.name for e in self.extracted()]
        assert titles.count("Online: Cook County Digital Equity Team") == 1

    def test_a_details_link_is_not_a_title(self):
        assert "Details" not in [e.name for e in self.extracted()]

    def test_undated_links_are_ignored(self):
        assert "About us" not in [e.name for e in self.extracted()]

    def test_relative_urls_are_made_absolute(self):
        assert all(e.url.startswith("https://chihacknight.org/") for e in self.extracted())
