from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    """An event as a scraper produces it, before it has a database id."""

    name: str = Field(..., description="Event title as the venue publishes it")
    date: datetime = Field(..., description="Start date. Stored at midnight local time")
    date_end: Optional[datetime] = Field(
        default=None,
        description="End date, set only for multi-day events (theatre runs, "
        "festivals, exhibitions). An event stays 'upcoming' until this passes.",
    )
    time: Optional[str] = Field(
        default=None,
        description="Start time as published, so it is shown the way the venue "
        "wrote it. Free text, not parsed: '7:30 PM', 'Doors 8 pm', 'Show: 8 pm'.",
    )
    time_end: Optional[str] = None
    category: str = Field(..., description="Category slug, e.g. 'music', 'theater', 'comedy'")
    details: Optional[str] = Field(default=None, description="Description, where the source gives one")
    origination_url: str = Field(
        ...,
        description="Where the event came from. UNIQUE in the database, so it "
        "doubles as the deduplication key across repeated scrapes.",
    )
    cost: Optional[str] = Field(
        default=None,
        description="Price as text, because venues publish it in incompatible "
        "shapes: '$25', '$20-$25', 'From $64', 'Free', 'Donation'. null means "
        "the source published no price, not that the event is free.",
    )
    age_range: Optional[str] = Field(default=None, description="e.g. '21+', 'All ages'")
    is_outdoor: Optional[str] = None
    address: Optional[str] = Field(default=None, description="Street address, venue name first")
    venue_name: Optional[str] = None
    latitude: Optional[float] = Field(
        default=None, description="Venue coordinates, when the source provides them"
    )
    longitude: Optional[float] = None
    # Deliberately no `neighborhood` field: EventModel.neighborhood is the
    # relationship to NeighborhoodModel, so a same-named string field here makes
    # from_attributes read that object and fail validation on every response.
    date_retrieved: datetime = Field(
        default_factory=datetime.utcnow, description="When this row was last refreshed"
    )


class Event(EventCreate):
    """A stored event, as every read endpoint returns it."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1247,
                    "name": "Comedy Open Mic",
                    "date": "2026-10-07T00:00:00",
                    "date_end": None,
                    "time": "Show: 8 pm",
                    "time_end": None,
                    "category": "music",
                    "details": None,
                    "origination_url": "https://colesbarchicago.com/shows/comedy-open-mic-october-07-2026-717984",
                    "cost": "Free",
                    "age_range": None,
                    "is_outdoor": None,
                    "address": "Cole's Bar, 2338 N Milwaukee Ave",
                    "venue_name": "Cole's Bar",
                    "latitude": None,
                    "longitude": None,
                    "date_retrieved": "2026-10-07T03:42:44.521539",
                },
                {
                    "id": 2990,
                    "name": "The Winter's Tale",
                    "date": "2026-10-13T00:00:00",
                    "date_end": "2026-12-12T00:00:00",
                    "time": None,
                    "time_end": None,
                    "category": "theater",
                    "details": None,
                    "origination_url": "https://www.chicagoshakes.com/plays-and-events/winters-tale",
                    "cost": None,
                    "age_range": None,
                    "is_outdoor": None,
                    "address": "Chicago Shakespeare Theater, 800 E Grand Ave",
                    "venue_name": "Chicago Shakespeare Theater",
                    "latitude": None,
                    "longitude": None,
                    "date_retrieved": "2026-10-07T03:42:44.521539",
                },
            ]
        },
    )

    id: int


class EventSearch(BaseModel):
    """Body for POST /api/search."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"query": "jazz tonight", "limit": 20},
                {
                    "query": "plant workshops this weekend",
                    "limit": 10,
                    "neighborhood": "Logan Square",
                },
                {"query": "comedy", "limit": 5, "category": "Comedy"},
            ]
        }
    )

    query: str = Field(
        ...,
        description="Natural language search. Keywords are matched against event "
        "names and a date range is read from phrases like 'tonight', 'this "
        "weekend' or 'next week'. An empty-ish query with a neighborhood or "
        "category set still works as a plain filter.",
    )
    limit: int = Field(default=20, ge=1, le=100, description="Maximum results to return")
    neighborhood: Optional[str] = Field(
        default=None,
        description="Restrict results to one Chicago neighborhood, e.g. 'Wicker Park'. "
        "Matched exactly against the stored name, so use a value from "
        "GET /api/events/neighborhoods.",
    )
    category: Optional[str] = Field(
        default=None,
        description="Restrict results to one category, e.g. 'Health & Wellness'. "
        "Matched case-insensitively against the stored category.",
    )
