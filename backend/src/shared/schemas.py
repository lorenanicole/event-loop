from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.categories import (
    classify_all,
    infer_category,
    informative_subtags,
    normalize_category,
    to_parents,
)
from shared.locality import locality_of


class EventCreate(BaseModel):
    """An event as a scraper produces it, before it has a database id."""

    name: str = Field(..., description="Event title as the venue publishes it")
    date: datetime = Field(..., description="Start date. Stored at midnight local time")
    date_end: datetime | None = Field(
        default=None,
        description="End date, set only for multi-day events (theatre runs, "
        "festivals, exhibitions). An event stays 'upcoming' until this passes.",
    )
    time: str | None = Field(
        default=None,
        description="Start time as published, so it is shown the way the venue "
        "wrote it. Free text, not parsed: '7:30 PM', 'Doors 8 pm', 'Show: 8 pm'.",
    )
    time_end: str | None = None
    category: str = Field(
        ...,
        description="The primary parent category, shown on a tile and a result "
        "card. A source may supply its own wording here - Ticketmaster sends "
        "'Arts & Theatre' - and it is mapped to a parent on the way in.",
    )
    categories: list[str] | None = Field(
        default=None,
        description="Every applicable parent category, primary first. One event "
        "often belongs to several - a drag show at a music venue is both Music "
        "and LGBTQ - and a category filter matches any of them. Derived from "
        "the title when not supplied.",
    )
    subcategories: list[str] | None = Field(
        default=None,
        description="The source's own finer labels, where they say more than "
        "the parent does: 'Arts & Crafts' under Arts, 'Parties & DJs' under "
        "Music. Shown on a card, never filtered on.",
    )
    details: str | None = Field(default=None, description="Description, where the source gives one")
    origination_url: str = Field(
        ...,
        description="Where the event came from. UNIQUE in the database, so it "
        "doubles as the deduplication key across repeated scrapes.",
    )
    cost: str | None = Field(
        default=None,
        description="Price as text, because venues publish it in incompatible "
        "shapes: '$25', '$20-$25', 'From $64', 'Free', 'Donation'. null means "
        "the source published no price, not that the event is free.",
    )
    age_range: str | None = Field(default=None, description="e.g. '21+', 'All ages'")
    is_outdoor: str | None = None
    address: str | None = Field(default=None, description="Street address, venue name first")
    locality: str | None = Field(
        default=None,
        description="The suburb, when the event is not in Chicago. Derived "
        "from the address on the way in, so no scraper has to know about it. "
        "null means Chicago, which is almost everything.",
    )
    venue_name: str | None = None
    latitude: float | None = Field(
        default=None, description="Venue coordinates, when the source provides them"
    )
    longitude: float | None = None
    # Deliberately no `neighborhood` field: EventModel.neighborhood is the
    # relationship to NeighborhoodModel, so a same-named string field here makes
    # from_attributes read that object and fail validation on every response.
    date_retrieved: datetime = Field(
        default_factory=datetime.utcnow, description="When this row was last refreshed"
    )
    category_hint: str | None = Field(
        default=None,
        exclude=True,
        description="The source's own words for what the event is - "
        "Ticketmaster's genre ('Jazz'), Google's type ('Live jazz concert'), a "
        "listing's blurb. Used only to pick the categories, never stored: a "
        "title is frequently just a performer's name, and the hint is what "
        "makes it classifiable at all.",
    )

    @model_validator(mode="after")
    def _refine_category(self):
        """Override a blanket category where the title is unambiguous.

        Ticketmaster files a comedy jam under "Arts & Theatre"; a venue
        scraper labels a wine special at a music pub as "Music". The title
        settles those cases, and leaves everything else alone.
        """
        # Label anything outside the city. do312 covers the whole metro, so
        # without this a Naperville show appears under a headline reading
        # "anywhere in Chicago" with nothing to say otherwise.
        if self.locality is None and self.address:
            found = locality_of(self.address)
            if found:
                object.__setattr__(self, "locality", found)

        refined = infer_category(self.name, self.category)
        if refined != self.category:
            object.__setattr__(self, "category", refined)

        # The source's own labels first - a trans pride festival is both
        # Community and LGBTQ, and storing one made it invisible under the
        # other.
        subtags = self.categories or classify_all(self.name, self.category, hint=self.category_hint)

        # Then the parents those labels roll up to, which is what a filter
        # matches and what a tile is named after. Done here, at the boundary,
        # so no scraper has to know the taxonomy and no two of them can
        # disagree about it.
        parents = to_parents(subtags)
        if parents:
            object.__setattr__(self, "category", parents[0])
            object.__setattr__(self, "categories", parents)

        # Only the labels that say more than their parent already does.
        # Keeping "Music" as a subtag of Music would just print it twice.
        if self.subcategories is None:
            finer = informative_subtags(subtags, parents)
            object.__setattr__(self, "subcategories", finer or None)
        return self

    @field_validator("category")
    @classmethod
    def _normalize_category(cls, value: str) -> str:
        """Settle casing at the boundary, so one category is never two tiles.

        Sources disagree on case for the same category - "music" from the venue
        scrapers, "Music" from Ticketmaster - and the difference is meaningless.
        Wording is left alone: "Arts & Crafts" stays distinct from "Arts &
        Culture", and a search for "art" reaches both by prefix instead.
        """
        return normalize_category(value) or value


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
                {"query": "events", "limit": 20, "skip": 40},
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
    skip: int = Field(
        default=0,
        ge=0,
        description="How many results to skip, for paging. Results are ordered "
        "by date, so paging is stable as long as the query is unchanged. Paging "
        "past the end returns an empty array rather than an error.",
    )
    neighborhood: str | None = Field(
        default=None,
        description="Restrict results to one Chicago neighborhood, e.g. 'Wicker Park'. "
        "Matched exactly against the stored name, so use a value from "
        "GET /api/events/neighborhoods.",
    )
    category: str | None = Field(
        default=None,
        description="Restrict results to one category, e.g. 'Health & Wellness'. "
        "Matched case-insensitively against the stored category.",
    )
