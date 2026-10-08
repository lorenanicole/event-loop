"""Which venues to scrape, and how to read each one.

Split out of chicago_events_scraper: this is data, and it was sitting in the
middle of 2,700 lines of parsing code. Keyed by neighborhood, which is how
coverage gets judged - a gap here is a part of Chicago the app cannot see.

Each entry names the page to read, the category to default its events to, and
either CSS selectors or an `extractor_fn` from `extractors` for the venues
whose markup no selector describes.

A venue's category is a default and not an assertion. A music venue hosts a
sewing night, so the category here is handed to `classify_all` as a fallback
that any title rule outranks.
"""

from .extractors import (
    extract_ace_calendar,
    extract_aeg_showtime,
    extract_auditorium_theatre,
    extract_cobra_lounge,
    extract_dated_links,
    extract_dated_list_items,
    extract_day_month_card,
    extract_den_theatre,
    extract_dice_widget,
    extract_eb_item,
    extract_events_from_json_ld,
    extract_eventscalendar_widget,
    extract_green_mill,
    extract_jamusa_events,
    extract_labelled_meeting,
    extract_lh_st,
    extract_martyrs,
    extract_old_town_school,
    extract_outset,
    extract_rhapsody_theater,
    extract_salt_shed_playwright,
    extract_songkick_venue,
    extract_squarespace_calendar,
    extract_squarespace_eventlist,
    extract_tessitura_calendar,
    extract_tickeri_venue,
    extract_tribe_events,
    extract_united_center,
    extract_zanies_calendar,
    scrolling,
)
from .venue_scraper import VenueConfig

CHICAGO_VENUES = {
    "Rush & Division": [
        VenueConfig(
            # Exhibitions and scholarly programming, mostly multi-week runs.
            name="Newberry Library",
            website_url="https://www.newberry.org",
            event_page_url="https://www.newberry.org/calendar",
            category="Arts & Culture",
            address="60 W Walton St",
            selectors={
                "event_container": "div.col-12.col-md-6",
                "title": "h4",
            },
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    "Loop": [
        VenueConfig(
            # A monthly user group rather than a venue: the meeting moves to
            # whichever company is hosting, so the address is read off the page
            # and this neighborhood is only where it usually lands.
            name="ChiPy (Chicago Python User Group)",
            website_url="https://www.chipy.org",
            event_page_url="https://www.chipy.org/",
            category="Tech / Educational",
            address="Varies by month",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_labelled_meeting,
        ),
        VenueConfig(
            # Policy talks and civic programming - a whole category of event
            # the venue scrapers had none of.
            name="Chicago Council on Global Affairs",
            website_url="https://globalaffairs.org",
            event_page_url="https://globalaffairs.org/upcoming-events",
            # A foreign-policy institute, and its calendar is lectures,
            # panels and in-conversation events - "Africa and the New Global
            # Order". "Community" put those next to ward meetings and
            # neighborhood potlucks. This is the same bucket as ChiPy and Chi
            # Hack Night, which is where somebody looking for a talk will go.
            category="Tech / Educational",
            address="130 E Randolph St",
            selectors={
                "event_container": "div.listing_teaser.future",
                "title": "h2.listing_teaser_title",
                "date": ".listing_teaser_content_date",
            },
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        # CIBC Theatre and the James M. Nederlander are programmed by Broadway
        # In Chicago and publish no calendar of their own, so they are covered
        # by scrapers.sources.broadway_in_chicago instead of here.
        VenueConfig(
            name="Chicago Theatre",
            website_url="https://www.thechicagotheatre.com",
            event_page_url="https://www.thechicagotheatre.com",
            category="theater",
            address="175 N State St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Jazz Showcase",
            website_url="https://www.jazzshowcase.com",
            event_page_url="https://www.jazzshowcase.com/calendar",
            category="music",
            address="806 S Plymouth Ct",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_squarespace_calendar,
        ),
        VenueConfig(
            name="Auditorium Theatre",
            website_url="https://www.auditoriumtheatre.org",
            event_page_url="https://www.auditoriumtheatre.org/events",
            category="theater",
            address="50 E Congress Pkwy",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_auditorium_theatre,
        ),
        VenueConfig(
            name="Goodman Theatre",
            website_url="https://www.goodmantheatre.org",
            event_page_url="https://my.goodmantheatre.org/Events",
            category="theater",
            address="170 N Dearborn St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tessitura_calendar,
        ),
        VenueConfig(
            # The venue's own subdomain lists 72 shows; houseofblues.com/chicago
            # carried none, which is why this was dark.
            name="House of Blues Chicago",
            website_url="https://chicago.houseofblues.com",
            event_page_url="https://chicago.houseofblues.com/shows",
            category="music",
            address="329 N Dearborn St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Civic Opera House",
            website_url="https://www.lyricopera.org",
            event_page_url="https://www.lyricopera.org/calendar/",
            category="theater",
            address="20 N Wacker Dr",
            selectors={},
            use_playwright=True,
            page_extractor_fn=extract_ace_calendar,
        ),
        VenueConfig(
            # An open-air pavilion, so its calendar is empty out of season.
            # The page currently says "No upcoming events found" in as many
            # words: zero here is the venue's answer, not a broken extractor.
            # Left wired so the summer season appears on its own.
            name="Jay Pritzker Pavilion",
            website_url="https://www.millenniumparkpavilion.org",
            event_page_url="https://www.millenniumparkpavilion.org/jay-pritzker-pavilion-schedule/",
            category="music",
            address="201 E Randolph St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Buddy Guy's Legends",
            website_url="https://buddyguy.com",
            event_page_url="https://buddyguy.com/",
            category="music",
            address="700 S Wabash Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],
    "Wicker Park": [
        VenueConfig(
            name="Subterranean",
            website_url="https://www.subt.net",
            event_page_url="https://subt.net/",
            category="music",
            address="2011 W North Ave",
            selectors={
                "event_container": "li.seetickets-list-event-container",
                "title": "p.event-title a",
                "date": "p.event-date",
            },
        ),
        VenueConfig(
            name="Chop Shop",
            website_url="https://chopshopchi.com",
            event_page_url="https://chopshopchi.com/calendar/index.html",
            category="music",
            address="2033 W North Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dice_widget,
        ),
        VenueConfig(
            name="Empty Bottle",
            website_url="https://www.emptybottle.com",
            event_page_url="https://www.emptybottle.com/",
            category="music",
            address="1035 N Western Ave",
            selectors={
                "event_container": ".show-details",
                "title": "div.title",
                "date": "div.date",
            },
            use_playwright=True,
        ),
        VenueConfig(
            name="Den Theatre",
            # Not www.dentheatre.com, which does not resolve - every event URL
            # built from it was a dead link.
            website_url="https://thedentheatre.com",
            event_page_url="https://thedentheatre.com/calendar?view=calendar&month=10-2026",
            category="comedy",
            address="1331 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_den_theatre,
        ),
        VenueConfig(
            name="Rosa's Lounge",
            website_url="https://www.rosaslounge.com",
            event_page_url="https://www.rosaslounge.com/calendar",
            category="music",
            address="3420 W Armitage Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
    ],
    "Bucktown": [
        VenueConfig(
            name="The Hideout",
            website_url="https://www.hideoutchicago.com",
            event_page_url="https://www.hideoutchicago.com/shows",
            category="music",
            address="1354 W Wabansia Ave",
            selectors={
                "event_container": ".show-collection-item",
                "title": ".show-name",
                "date": ".show-start-date",
            },
        ),
        VenueConfig(
            name="Concord Music Hall",
            website_url="https://concordmusichall.com",
            event_page_url="https://concordmusichall.com/calendar/",
            category="music",
            address="2047 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_day_month_card,
        ),
        VenueConfig(
            name="Salt Shed",
            website_url="https://www.saltshedchicago.com",
            event_page_url="https://www.saltshedchicago.com/home#shows",
            category="music",
            address="1357 N Elston Ave",
            selectors={},
            use_playwright=True,
            page_extractor_fn=extract_salt_shed_playwright,
        ),
        VenueConfig(
            name="Outset",
            website_url="https://outsetlive.com",
            event_page_url="https://outsetlive.com/events/",
            category="music",
            address="1675 N Elston Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_outset,
        ),
    ],
    "Rogers Park": [
        VenueConfig(
            name="Loyola University Performing Arts Center",
            website_url="https://www.luc.edu/performingarts",
            event_page_url="https://www.luc.edu/performingarts/calendar",
            category="theater",
            address="6525 N Sheridan Rd",
            selectors={},
            use_playwright=True,
        ),
        VenueConfig(
            name="Rogers Park Music Venue",
            website_url="https://www.rogersparkcenter.org",
            event_page_url="https://www.rogersparkcenter.org/events",
            category="music",
            address="7211 N Clark St",
            selectors={},
            use_playwright=True,
        ),
    ],
    "Uptown": [
        VenueConfig(
            name="Green Mill Jazz Club",
            website_url="https://www.greenmilljazz.com",
            event_page_url="https://www.greenmilljazz.com/calendar/",
            category="music",
            address="4802 N Broadway Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_green_mill,
        ),
        VenueConfig(
            name="Byline Bank Aragon Ballroom",
            website_url="https://www.aragonballroomchicago.com",
            event_page_url="https://www.aragonballroomchicago.com/",
            category="music",
            address="1106 W Lawrence Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_day_month_card,
        ),
        VenueConfig(
            name="Riviera Theatre",
            website_url="https://www.jamusa.com/riviera-theatre",
            event_page_url="https://www.jamusa.com/riviera-theatre",
            category="music",
            address="4746 N Racine Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_jamusa_events,
        ),
    ],
    "Lincoln Park": [
        VenueConfig(
            name="Steppenwolf Theatre Company",
            website_url="https://www.steppenwolf.org",
            event_page_url="https://www.steppenwolf.org/whats-on/current-season",
            category="theater",
            address="1650 N Halsted St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Lincoln Hall",
            website_url="https://www.lh-st.com",
            event_page_url="https://lh-st.com/",
            category="music",
            address="2424 N Lincoln Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_lh_st,
        ),
        VenueConfig(
            name="Kingston Mines",
            website_url="https://www.kingstonmines.com",
            event_page_url="https://kingstonmines.com/",
            category="music",
            address="2548 N Halsted St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Second City",
            website_url="https://www.secondcity.com",
            event_page_url="https://www.secondcity.com/shows",
            category="comedy",
            address="1616 N Wells St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_events_from_json_ld,
        ),
        VenueConfig(
            name="Park West",
            website_url="https://www.jamusa.com/venues/park-west",
            event_page_url="https://www.jamusa.com/venues/park-west",
            category="music",
            address="322 W Armitage Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_jamusa_events,
        ),
    ],
    "Edgewater": [
        VenueConfig(
            name="Uncommon Ground",
            website_url="https://www.uncommonground.com",
            event_page_url="https://www.uncommonground.com/events-page",
            category="music",
            address="3800 N Clark St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_squarespace_eventlist,
        ),
    ],
    "Lake View": [
        VenueConfig(
            name="Metro Chicago",
            website_url="https://www.metrochicago.com",
            event_page_url="https://www.metrochicago.com/events",
            category="music",
            address="3730 N Clark St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="The Vic Theatre",
            website_url="https://www.jamusa.com/venues/the-vic",
            event_page_url="https://www.jamusa.com/venues/the-vic",
            category="music",
            address="3145 N Sheffield Ave",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=extract_jamusa_events,
        ),
        VenueConfig(
            name="Schubas Tavern",
            website_url="https://lh-st.com",
            event_page_url="https://lh-st.com",
            category="music",
            address="3159 N Southport Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_lh_st,
        ),
    ],
    "Lincoln Square": [
        VenueConfig(
            name="Old Town School of Folk Music",
            website_url="https://www.oldtownschool.org",
            event_page_url="https://www.oldtownschool.org/concerts",
            category="music",
            address="4544 N Lincoln Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_old_town_school,
        ),
    ],
    "River North": [
        VenueConfig(
            # A weekly civic-tech meetup. Sessions are currently online, which
            # the event titles say ("Online: ..."); this neighborhood is its
            # venue of record at the Merchandise Mart rather than where each
            # meeting physically happens.
            name="Chi Hack Night",
            website_url="https://chihacknight.org",
            event_page_url="https://chihacknight.org/events/",
            category="Tech / Educational",
            address="222 W Merchandise Mart Plaza",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_links,
        ),
        VenueConfig(
            # Listed under the festival's own address because that is what the
            # listing gives us; the events themselves run at partner venues
            # across the city (the Athenaeum, the MCA), so the neighborhood
            # here is the organizer's rather than each event's.
            name="Chicago Humanities",
            website_url="https://www.chicagohumanities.org",
            event_page_url="https://www.chicagohumanities.org/events/",
            category="Arts & Culture",
            address="445 N Franklin St",
            selectors={
                "event_container": "article.tile.tile-event",
                "title": "h3.title",
                "date": "span.event-date",
            },
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Sound Bar",
            website_url="https://sound-bar.com",
            event_page_url="https://sound-bar.com/events",
            category="music",
            address="226 W Ontario St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],
    "Pilsen": [
        VenueConfig(
            name="Thalia Hall",
            website_url="https://www.thaliahallchicago.com",
            event_page_url="https://www.thaliahallchicago.com/shows",
            category="music",
            address="1807 S Allport St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_eb_item,
        ),
        VenueConfig(
            # An AEG/carbonhouse site: /events/all lists the full calendar as
            # div.entry cards. Ticketing runs through AXS, whose own venue page
            # is not parseable - the venue's own site is.
            name="Radius Chicago",
            website_url="https://www.radius-chicago.com",
            event_page_url="https://www.radius-chicago.com/events/all",
            category="music",
            address="640 W Cermak Rd",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_aeg_showtime,
        ),
    ],
    "Logan Square": [
        VenueConfig(
            name="The Whistler",
            website_url="https://whistlerchicago.com",
            event_page_url="https://whistlerchicago.com/events",
            category="music",
            address="2421 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_squarespace_eventlist,
        ),
        VenueConfig(
            name="Cole's Bar",
            website_url="https://colesbarchicago.com",
            event_page_url="https://colesbarchicago.com",
            category="music",
            address="2338 N Milwaukee Ave",
            selectors={
                "event_container": "article.evcard",
                "title": "h3.evcard-title",
                "date": "div.evcard-header",
                "time": "p.evcard-time",
                "url": "a.evcard-btn",
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="The Lincoln Lodge",
            website_url="https://www.thelincolnlodge.com",
            event_page_url="https://www.thelincolnlodge.com/calendar",
            category="comedy",
            address="2040 N Milwaukee Ave",
            selectors={},
            use_playwright=True,
            page_extractor_fn=extract_eventscalendar_widget,
        ),
    ],
    "Humboldt Park": [
        VenueConfig(
            name="Martyrs'",
            website_url="https://martyrslive.com",
            event_page_url="https://martyrslive.com/calendar",
            category="music",
            address="3855 N Lincoln Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_martyrs,
        ),
    ],
    "West Loop": [
        VenueConfig(
            name="Green Dolphin Street",
            website_url="https://www.greendolphinchicago.com",
            event_page_url="https://www.greendolphinchicago.com/events",
            category="music",
            address="2200 N Ashland Ave",
            selectors={},
            use_playwright=True,
        ),
    ],
    "Near West Side": [
        VenueConfig(
            name="United Center",
            website_url="https://www.unitedcenter.com",
            event_page_url="https://www.unitedcenter.com/events/",
            category="music",
            address="1901 W Madison St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_united_center,
        ),
    ],
    "Old Town": [
        VenueConfig(
            name="Zanies Comedy Club",
            website_url="https://chicago.zanies.com",
            event_page_url="https://chicago.zanies.com/chicago",
            category="comedy",
            address="1548 N Wells St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_zanies_calendar,
        ),
        VenueConfig(
            name="A Red Orchid Theatre",
            website_url="https://aredorchidtheatre.org",
            event_page_url="https://aredorchidtheatre.org",
            category="theater",
            address="1641 N Halsted St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
    ],
    "West Loop": [
        VenueConfig(
            name="City Winery",
            website_url="https://citywinery.com",
            event_page_url="https://citywinery.com/pages/events/chicago",
            category="music",
            address="1200 W Randolph St",
            selectors={
                "event_container": 'div[class*="event"], li[class*="event"], article, .event-item',
                "title": '[class*="title"], [class*="name"], .event-title, h3, h4',
                "date": '.date, .start-time, .end-time, [class*="date"], [class*="time"], .event-date, .show-date, [class*="datetime"], .event-time, time',
            },
            use_playwright=True,
            extractor_fn=None,
        ),
        VenueConfig(
            name="Cobra Lounge",
            website_url="https://cobralounge.com",
            event_page_url="https://cobralounge.com/events",
            category="music",
            address="235 N Ashland Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_cobra_lounge,
        ),
        VenueConfig(
            # The homepage does carry the calendar (/art-events does not, which
            # is why this was dark), and cards render as one run-together
            # string: "wed07oct(oct 7)7:00 pmSalsa on a School Night".
            #
            # Deliberately left unwired: extract_dated_list_items reads that
            # page as 168 "events", mixing in room names ("Epiphany Hall",
            # "Cafe Bar") and attaching the wrong dates, because the markup
            # nests each show's rooms as sibling blocks. Needs a venue-specific
            # extractor; junk is worse than a gap.
            name="Epiphany Center for the Arts",
            website_url="https://epiphanychi.com",
            event_page_url="https://epiphanychi.com/",
            category="arts",
            address="311 W Carroll Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=None,
        ),
    ],
    "Rogers Park": [
        VenueConfig(
            name="Rhapsody Theater",
            website_url="https://www.rhapsodytheater.com",
            event_page_url="https://www.rhapsodytheater.com/upcoming-events/",
            category="theater",
            address="1328 W Morse Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_rhapsody_theater,
        ),
        VenueConfig(
            # Publishes a season page, not a calendar: each show is a run of
            # several weeks, stored with a date_end so it stays visible
            # throughout. The homepage carried no JSON-LD, hence the blank.
            name="Lifeline Theatre",
            website_url="https://lifelinetheatre.com",
            event_page_url="https://lifelinetheatre.com/2026-27-season/",
            category="theater",
            address="6912 N Glenwood Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    # South Side coverage. Every venue above is North or Central, which left
    # the whole South Side unrepresented in the neighborhood filter even though
    # these venues publish full calendars.
    "Beverly": [
        VenueConfig(
            name="Beverly Arts Center",
            website_url="https://thebeverlyartscenter.com",
            event_page_url="https://thebeverlyartscenter.com/events",
            category="arts",
            address="2407 W 111th St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
    ],
    "Hyde Park": [
        VenueConfig(
            name="Hyde Park Art Center",
            website_url="https://www.hydeparkart.org",
            event_page_url="https://www.hydeparkart.org/events/",
            category="arts",
            address="5020 S Cornell Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
        VenueConfig(
            name="The Promontory",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/2716303-promontory",
            category="music",
            address="5311 S Lake Park Ave W",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],
    "Albany Park": [
        VenueConfig(
            # In Mayfair, inside the Albany Park community area. The 658-seat
            # Mayfair Theatre here is the city's main Irish music stage.
            name="Irish American Heritage Center",
            website_url="https://www.irish-american.org",
            event_page_url="https://www.irish-american.org/events/",
            category="music",
            address="4626 N Knox Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    "Jefferson Park": [
        VenueConfig(
            name="Copernicus Center",
            website_url="https://copernicuscenter.org",
            event_page_url="https://copernicuscenter.org/events/",
            category="music",
            address="5216 W Lawrence Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    "Bronzeville": [
        VenueConfig(
            # The oldest Black American art center in the US, 1940.
            name="South Side Community Art Center",
            website_url="https://sscartcenter.org",
            event_page_url="https://sscartcenter.org/events/",
            category="arts",
            address="3831 S Michigan Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
        VenueConfig(
            name="Room 43",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/620356-room-43",
            category="music",
            address="1043 E 43rd St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="Bronzeville Winery",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/4506126-bronzeville-winery",
            category="music",
            address="4420 S Cottage Grove Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],
    # Tickeri only for Los Globos and V-Live, not Songkick as well: the two
    # sources name the same concert differently ("Rata Blanca" vs "Rata Blanca
    # en concierto en Chicago"), so running both duplicated every show rather
    # than merging it. Tickeri wins because it carries ticket prices.
    #
    # Little Village's music venues are real but web-invisible: Los Globos and
    # V-Live both book touring regional Mexican acts, and neither has a working
    # site - Los Globos has none at all and vlivechicago.com refuses
    # connections. Songkick carries both calendars.
    "Little Village": [
        VenueConfig(
            name="Los Globos",
            # No website at all; Instagram is the venue's home. Same reasoning
            # as V-Live below: linked, not scraped.
            website_url="https://www.instagram.com/losgloboschicago/",
            event_page_url="https://www.tickeri.com/venues/60d2525292d3766d2a792de2",
            category="music",
            address="3059 S Central Park Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tickeri_venue,
        ),
        VenueConfig(
            # Tickeri holds a second, duplicate record for the same room under
            # a mistyped address; it carries shows the first one does not.
            name="Los Globos",
            website_url="https://www.instagram.com/losgloboschicago/",
            event_page_url="https://www.tickeri.com/venues/96bf9258-7c35-4db1-8c31-260ab2e28b35",
            category="music",
            address="3059 S Central Park Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tickeri_venue,
        ),
        VenueConfig(
            name="V-Live",
            # vlivechicago.com refuses connections; the venue's actual home is
            # Instagram. Not scraped - Instagram gates posts behind a login,
            # blocks automation and forbids it in its terms - but recorded as
            # the venue's real link, since Songkick is where the calendar
            # comes from and not where the venue lives.
            website_url="https://www.instagram.com/vlivechicagoofficial/",
            event_page_url="https://www.tickeri.com/venues/54cbefe9e7fbb67858965f0c",
            category="music",
            address="2501 S Kedzie Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tickeri_venue,
        ),
        VenueConfig(
            name="Apollo's 2000",
            # Real site, but its /events page lists nothing, so the calendar
            # comes from Songkick.
            website_url="https://www.apollos2000.com",
            event_page_url="https://www.songkick.com/venues/49204-apollos-2000",
            category="music",
            address="2875 W Cermak Rd",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        # Songkick's "Cermak Hall" was removed: 3 of its 4 events are the same
        # shows as Radius Chicago on the same nights (Jan Blomqvist, Maddix,
        # Somewhen), so it is Radius under a wrong name and a wrong address -
        # which also put those events in Little Village instead of Pilsen.
    ],
    "Bridgeport": [
        VenueConfig(
            name="Ramova Theatre",
            website_url="https://ramovachicago.com",
            event_page_url="https://ramovachicago.com/events/",
            category="music",
            address="3520 S Halsted St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    "Near South Side": [
        VenueConfig(
            # Mostly conventions and trade shows, but the public ones (the auto
            # show, the marathon expo) are among the largest events in the city.
            name="McCormick Place",
            website_url="https://www.mccormickplace.com",
            event_page_url="https://www.mccormickplace.com/events/",
            category="community",
            address="2301 S King Dr",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Reggies Chicago",
            website_url="https://www.reggieslive.com",
            event_page_url="https://www.reggieslive.com/2026/10/?post_type=show",
            category="music",
            address="2105 S State St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    "Streeterville": [
        VenueConfig(
            name="Navy Pier",
            website_url="https://navypier.org",
            event_page_url="https://navypier.org/events/",
            category="community",
            address="600 E Grand Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Chicago Shakespeare Theater",
            website_url="https://www.chicagoshakes.com",
            event_page_url="https://www.chicagoshakes.com/plays-and-events",
            category="theater",
            address="800 E Grand Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Lookingglass Theatre",
            website_url="https://lookingglasstheatre.org",
            event_page_url="https://lookingglasstheatre.org/whats-on/",
            category="theater",
            address="821 N Michigan Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
    ],
    "Avondale": [
        VenueConfig(
            # Each listing repeats the stage name ("Sleeping Village") above
            # the title, which _title_from is told to skip via config.name.
            name="Sleeping Village",
            website_url="https://sleeping-village.com",
            event_page_url="https://sleeping-village.com/events/",
            category="music",
            address="3734 W Belmont Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Chief O'Neill's Pub",
            website_url="https://chiefoneillspub.com",
            event_page_url="https://chiefoneillspub.com/events/",
            category="music",
            address="3471 N Elston Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_dated_list_items,
        ),
        VenueConfig(
            name="Avondale Music Hall",
            website_url="https://avondalemusichall.com",
            event_page_url="https://avondalemusichall.com/",
            category="music",
            address="3528 W Belmont Ave",
            selectors={},
            use_playwright=True,
            page_extractor_fn=scrolling(extract_dated_list_items),
        ),
    ],
    "Washington Park": [
        VenueConfig(
            name="DuSable Black History Museum",
            website_url="https://www.dusablemuseum.org",
            event_page_url="https://www.dusablemuseum.org/events/",
            category="arts",
            address="740 E 56th Pl",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_tribe_events,
        ),
    ],
    "South Shore": [
        VenueConfig(
            name="South Shore Cultural Center",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/36861-south-shore-cultural-center",
            category="music",
            address="7059 S South Shore Dr",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
        VenueConfig(
            name="Lee's Unleaded Blues",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/532626-lees-unleaded-blues",
            category="music",
            address="7401 S South Chicago Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],
    "Greater Grand Crossing": [
        VenueConfig(
            name="The New Apartment Lounge",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/777551-new-apartment-lounge",
            category="music",
            address="504 E 75th St",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],
    "North Center": [
        VenueConfig(
            name="Constellation",
            website_url="https://www.songkick.com",
            event_page_url="https://www.songkick.com/venues/3028939-constellation-chicago",
            category="music",
            address="3111 N Western Ave",
            selectors={},
            use_playwright=True,
            extractor_fn=extract_songkick_venue,
        ),
    ],
}
