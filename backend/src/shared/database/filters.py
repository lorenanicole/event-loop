"""Shared query filters for event lookups.

Every surface that lists events - the REST API, the UI search, and the
chatbot's database tool - needs the same answer to "is this event still
worth showing?". Keeping that definition here stops the three from drifting.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_

from .models import EventModel


def start_of_day(moment: Optional[datetime] = None) -> datetime:
    """Midnight on the given day (defaults to today)."""
    moment = moment or datetime.now()
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def upcoming_events_filter(now: Optional[datetime] = None):
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
