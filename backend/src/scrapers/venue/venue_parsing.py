"""Reading dates, titles and prices out of a venue's page text.

Split out of chicago_events_scraper, which had grown to 4,118 lines holding
three unrelated things: how to read a page, which venues to read, and how to
store the result. These are the first - no venue is named here and nothing
touches the database, so a change to a date pattern cannot affect a venue's
configuration and vice versa.

Venues publish dates in every shape there is - "Oct 7", "Sep 10 - Dec 30",
"Wed, Oct 7th", "10/7" - and a surprising number publish a bare month and day
with no year, which is what `infer_event_year` is for.
"""

import logging
import re
from datetime import datetime

from .venue_scraper import VenueConfig

logger = logging.getLogger(__name__)

VENUE_SCRAPE_TIMEOUT = 120


_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def infer_event_year(month_str: str, today: datetime | None = None) -> int:
    """Pick the year for a yearless venue date like "Oct 6".

    Venue calendars list upcoming shows only, so a month earlier than the
    current one belongs to next year (a January show listed in October).
    """
    today = today or datetime.now()
    for fmt in ("%b", "%B"):
        try:
            month = datetime.strptime(month_str[:3] if fmt == "%b" else month_str, fmt).month
        except ValueError:
            continue
        return today.year + 1 if month < today.month else today.year
    return today.year


def parse_date_range(date_str: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse date string to start and end dates. Returns (start_date, end_date)."""
    if not date_str or not date_str.strip():
        return None, None

    date_str = date_str.strip()

    try:
        # Try ISO format first: "2026-10-06T04:59:00+00:00" or "2026-10-06T04:59:00Z"
        try:
            # Handle Z timezone
            iso_str = date_str.replace("Z", "+00:00")
            start = datetime.fromisoformat(iso_str)
            return start, None
        except ValueError, AttributeError:
            pass

        # Try date range: "Oct 23 - 27, 2026"
        range_match = re.search(r"(\w+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s+(\d{4})", date_str)
        if range_match:
            month_str = range_match.group(1)
            start_day = range_match.group(2)
            end_day = range_match.group(3)
            year = range_match.group(4)
            try:
                start = datetime.strptime(f"{month_str} {start_day} {year}", "%b %d %Y")
                end = datetime.strptime(f"{month_str} {end_day} {year}", "%b %d %Y")
                return start, end
            except ValueError:
                pass

        # Try two-month range: "Oct 1 - Nov 4, 2026"
        multi_month = re.search(
            r"(\w+)\s+(\d{1,2})\s*[-–]\s*(\w+)\s+(\d{1,2}),?\s+(\d{4})", date_str
        )
        if multi_month:
            start_month = multi_month.group(1)
            start_day = multi_month.group(2)
            end_month = multi_month.group(3)
            end_day = multi_month.group(4)
            year = multi_month.group(5)
            try:
                start = datetime.strptime(f"{start_month} {start_day} {year}", "%b %d %Y")
                end = datetime.strptime(f"{end_month} {end_day} {year}", "%b %d %Y")
                return start, end
            except ValueError:
                pass

        # Try single date: "Oct 2, 2026" or "October 3, 2026"
        for fmt in ["%B %d, %Y", "%b %d, %Y", "%a, %b %d, %Y", "%b %d %Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                date_only = date_str.split("-")[0].split("–")[0].strip()
                start = datetime.strptime(date_only, fmt)
                return start, None
            except ValueError:
                continue

        # Try date without year: "Oct 4" or "Mon October 5" (assume current/next year)
        # Handle weekday: "Mon October 5"
        weekday_date = re.search(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+)\s+(\d{1,2})", date_str)
        if weekday_date:
            month_str = weekday_date.group(1)
            day_str = weekday_date.group(2)
            for year in [2026, 2027]:
                for fmt in ["%B %d %Y", "%b %d %Y"]:
                    try:
                        start = datetime.strptime(f"{month_str} {day_str} {year}", fmt)
                        return start, None
                    except ValueError:
                        continue

        # Try date without year: "Oct 4" (assume current/next year)
        short_date = re.search(r"(\w+)\s+(\d{1,2})", date_str)
        if short_date:
            month_str = short_date.group(1)
            day_str = short_date.group(2)
            # Assume current year (2026) - Jazz Showcase uses abbreviated dates for upcoming shows
            for year in [2026, 2027]:
                try:
                    start = datetime.strptime(f"{month_str} {day_str} {year}", "%b %d %Y")
                    return start, None
                except ValueError:
                    continue

        logger.debug(f"Could not parse date: {date_str}")
        return None, None

    except Exception as e:
        logger.debug(f"Date parsing error for '{date_str}': {e}")
        return None, None


def venue_source_name(config: VenueConfig) -> str:
    """The `source` an event from this venue is stamped with.

    One unique value per venue - "chicago_venue_rosass_lounge" - so events can
    be attributed, counted and re-examined per venue even where the venue
    publishes no unique URL per event.

    Shared rather than derived at the call site, because anything that goes
    back over stored rows has to arrive at byte-identical values. The
    apostrophe becoming "s" is not elegant, but it is what thousands of rows
    already carry, so it stays.
    """
    slug = config.name.lower().replace(" ", "_").replace("'", "s")
    return f"chicago_venue_{slug}"


def jsonld_offer_cost(event_data: dict) -> str | None:
    """Read a price out of a schema.org Event's `offers`.

    This is the one structured price in the whole pipeline, so prefer its
    numeric fields over sniffing text. `offers` may be a single object or a
    list of them (one per ticket tier), in which case report the range.
    """
    offers = event_data.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None

    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        spec = offer.get("priceSpecification")
        source = spec if isinstance(spec, dict) else offer
        for key in ("price", "lowPrice", "highPrice", "minPrice", "maxPrice"):
            value = source.get(key)
            if value in (None, ""):
                continue
            try:
                prices.append(float(str(value).replace("$", "").replace(",", "")))
            except ValueError:
                continue

    if not prices:
        return None
    low, high = min(prices), max(prices)
    if low == 0 and high == 0:
        return "Free"

    def money(value: float) -> str:
        return f"${value:.0f}" if value == int(value) else f"${value:.2f}"

    return money(low) if low == high else f"{money(low)}-{money(high)}"


_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
# "SEP 11-OCT 18, 2026" / "OCT 27-MAR 20, 2027" - a run, not a single night.
_RUN_RE = re.compile(
    rf"(?P<m1>{_MONTH})\s*(?P<d1>\d{{1,2}})\s*[–—-]\s*"
    # Convention calendars write the weekday on both ends of a run:
    # "Monday, October 05 - Wednesday, October 07".
    rf"(?:[A-Za-z]{{3,9}},\s*)?"
    rf"(?:(?P<m2>{_MONTH})\s*)?(?P<d2>\d{{1,2}})(?:,?\s*(?P<y>\d{{4}}))?",
    re.IGNORECASE,
)
# "Oct 7 - Wednesday", "Thu, Oct 08", "October 17, 2026"
_ONE_RE = re.compile(rf"(?P<m>{_MONTH})\s*(?P<d>\d{{1,2}})(?:,?\s*(?P<y>\d{{4}}))?", re.IGNORECASE)
_BOILERPLATE = (
    "tickets",
    "buy tickets",
    "more info",
    "learn more",
    "details",
    "sold out",
    "rsvp",
    "doors",
    "on sale",
    "free",
    "info",
    "read more",
    "get tickets",
)


_MONTH_WORDS = {m.lower() for m in _MONTHS} | {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
# Page furniture that sits inside an event card's ancestor and would otherwise
# be mistaken for a title.
_SECTION_HEADINGS = {
    "events",
    "all events",
    "upcoming events",
    "events & public programs",
    "public programs",
    "whats on",
    "calendar",
    "event calendar",
    "more events",
    # Datepicker controls, which sit in the same container as the cards.
    "today",
    "tomorrow",
    "month",
    "week",
    "day",
    "list",
    "agenda",
    "view",
    "next",
    "prev",
    "previous",
    "filter",
    "filters",
    "search",
    "clear",
    "reset",
    "apply",
    "submit",
    "select date",
    "all",
    "close",
    "confirm",
    "cancel",
    "ok",
    "done",
    "more info",
    "sold out",
    "tickets",
    "time",
    "event details",
    "details",
    "venue",
    "location",
    "price",
    # Calendar legends.
    "multiday event",
    "multi day event",
    "single day event",
    "recurring event",
}

_WEEKDAY_RE = re.compile(
    r"\b(?:Mon|Tue|Tues|Wed|Weds|Thu|Thur|Thurs|Fri|Sat|Sun)(?:day|sday|nesday|rsday|urday)?\b",
    re.IGNORECASE,
)


_WEEKDAY_PREFIXES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _card_lines(el) -> list[str]:
    """Split a card into text lines, even when it has no line breaks.

    Some sites render a whole card into a single text node with no separator
    between the title and the date: "EPIK HIGH NORTH AMERICAN TOURWed Oct 7,
    2026Buy Tickets". Splitting that around the date recovers the title.
    """
    lines = [ln.strip() for ln in el.get_text("\n", strip=True).split("\n") if ln.strip()]
    if len(lines) == 1:
        match = _ONE_RE.search(lines[0])
        if match:
            lines = [
                part.strip()
                for part in (lines[0][: match.start()], match.group(0), lines[0][match.end() :])
                if part.strip()
            ]
    return lines


def _title_from(lines: list[str], skip: str | None = None) -> str | None:
    """Pick the event title out of a card's text lines.

    `skip` is the venue's own name, which many sites print inside each card -
    Sleeping Village labels every listing with its stage - and which would
    otherwise be read as the title of every event there.

    The title is the first line that is neither the date nor a call to action.
    A line like "OCT 7 - WEDNESDAY" is all date, so the weekday is stripped
    alongside the date before checking whether real words are left - otherwise
    the weekday alone passes for a title.
    """
    skip_bare = re.sub(r"[^a-z0-9& ]", "", skip.lower()).strip() if skip else None
    for line in lines:
        bare = re.sub(r"[^a-z0-9& ]", "", line.lower()).strip()
        if skip_bare and bare == skip_bare:
            continue
        if line.lower().rstrip(":").startswith(_BOILERPLATE):
            continue
        # A month picker ("October") or a section heading is not an event.
        if bare in _MONTH_WORDS or bare in _SECTION_HEADINGS:
            continue
        # A datepicker's current selection, e.g. "Today - Sun, Oct 18, 2026".
        if bare.startswith(("today ", "tomorrow ", "this week", "this month")):
            continue
        remainder = _WEEKDAY_RE.sub("", _RUN_RE.sub("", _ONE_RE.sub("", line)))
        remainder = re.sub(r"\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?|\bat\b", "", remainder)
        if len(re.sub(r"[^A-Za-z]", "", remainder)) <= 3:
            continue
        # Some venues run the title straight into the blurb in one text node
        # ("Plim Plim in the Gateway Theater > DATE: October 15 TIME: 6:00pm").
        # Cut at the marker that starts the blurb.
        title = re.split(r"\s*[►▶‣]\s*|\s+DATE:\s*|\s+TIME:\s*", line)[0].strip()
        # A run-together card leaves the weekday stuck to the title ("...TOURWed").
        title = re.sub(
            r"(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?\.?$", "", title
        ).strip(" ,-–—")
        # ...and leaves punctuation and the start time on the front of it
        # (")7:00 pmSalsa on a School Night").
        title = re.sub(r"^[^A-Za-z0-9]+", "", title)
        title = re.sub(r"^\d{1,2}(?::\d{2})?\s*[apAP]\.?[mM]\.?\s*", "", title)
        if len(title) >= 3:
            return title
    return None


def _dates_from_text(text: str) -> tuple[str | None, str | None]:
    """Read a single date or a run out of a card's text.

    Returns ("Oct 7, 2026", None) or ("Sep 10, 2026", "Dec 30, 2026").
    """
    run = _RUN_RE.search(text or "")
    if run:
        start_month = run.group("m1")[:3].title()
        end_month = (run.group("m2") or run.group("m1"))[:3].title()
        crosses = _MONTHS.get(end_month, 0) < _MONTHS.get(start_month, 0)
        if run.group("y"):
            end_year = int(run.group("y"))
            start_year = end_year - 1 if crosses else end_year
        else:
            start_year = infer_event_year(start_month)
            end_year = start_year + 1 if crosses else start_year
        return (
            f"{start_month} {int(run.group('d1'))}, {start_year}",
            f"{end_month} {int(run.group('d2'))}, {end_year}",
        )

    one = _ONE_RE.search(text or "")
    if not one:
        return None, None
    year = one.group("y") or infer_event_year(one.group("m"))
    return f"{one.group('m')[:3].title()} {int(one.group('d'))}, {year}", None
