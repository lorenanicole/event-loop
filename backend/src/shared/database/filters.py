"""Shared query filters for event lookups.

Every surface that lists events - the REST API, the UI search, and the
chatbot's database tool - needs the same answer to "is this event still
worth showing?". Keeping that definition here stops the three from drifting.
"""

from datetime import datetime

from sqlalchemy import and_, case, func, or_

from .models import EventModel


def start_of_day(moment: datetime | None = None) -> datetime:
    """Midnight on the given day (defaults to today)."""
    moment = moment or datetime.now()  # noqa: DTZ005
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def upcoming_events_filter(now: datetime | None = None):
    """Match events that have not finished yet.

    An event counts as upcoming from midnight on its start date, so a show
    at 8pm tonight still appears when the query runs at 11am. A multi-day
    event stays upcoming until its end date passes, which keeps a festival
    that opened last week visible while it is still running.

    Events with neither a start nor an end date are excluded - there is no
    way to tell whether they have already happened.
    """
    today = start_of_day(now)
    return or_(
        # Multi-day event: still running until its end date passes.
        EventModel.date_end >= today,
        # Single-day event: starts today or later.
        and_(EventModel.date_end.is_(None), EventModel.date >= today),
    )


def feed_order(now: datetime | None = None):
    """The order a browse feed lists events in: soonest first, then name.

    Returned as a tuple to be splatted into `order_by`, so the REST list and
    the UI search sort identically by construction rather than by two copies
    of the same clause.

    Sorting on the raw start date was tried and reads wrong: 161 events are
    multi-day runs already under way, and an exhibition that opened in April
    is still open, so it sorted ahead of everything and pushed tonight's shows
    eight pages down. An event that is on today belongs in today's slot, so
    the key is the later of its start date and today.

    Name and id follow because date alone is not unique, and a non-unique
    sort key lets a row appear on two consecutive pages or on neither - which
    defeats the point of paging. The id guarantees a total order; name sits
    ahead of it so one day's events read alphabetically rather than in
    insertion order.
    """
    today = start_of_day(now)
    # `case` rather than SQLite's two-argument `max`, which other databases
    # spell `greatest`.
    effective_date = case((EventModel.date < today, today), else_=EventModel.date)
    return (
        effective_date.asc(),
        # Lowercased: SQLite's default collation sorts every capital ahead of
        # every lowercase letter, so "The Hideout" would precede "andrew bird".
        func.lower(EventModel.name).asc(),
        EventModel.id.asc(),
    )


# A conversation nobody has added to in this long is over, whatever its
# status says. Chosen to be comfortably longer than someone stepping away
# mid-chat and comfortably shorter than a day.
STALE_THREAD_HOURS = 6
