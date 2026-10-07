from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    name: str
    date: datetime
    date_end: Optional[datetime] = None  # Set for multi-day events (theatre runs, festivals)
    time: Optional[str] = None  # Start time as published, e.g. "7:30 PM"
    time_end: Optional[str] = None
    category: str
    details: Optional[str] = None
    origination_url: str
    cost: Optional[str] = None
    age_range: Optional[str] = None
    is_outdoor: Optional[str] = None
    address: Optional[str] = None
    venue_name: Optional[str] = None
    latitude: Optional[float] = None  # Venue coordinates when the source provides them
    longitude: Optional[float] = None
    # Deliberately no `neighborhood` field: EventModel.neighborhood is the
    # relationship to NeighborhoodModel, so a same-named string field here makes
    # from_attributes read that object and fail validation on every response.
    date_retrieved: datetime = Field(default_factory=datetime.utcnow)


class Event(EventCreate):
    id: int

    class Config:
        from_attributes = True


class EventSearch(BaseModel):
    query: str = Field(..., description="Natural language search query")
    limit: int = Field(default=20, ge=1, le=100)
    neighborhood: Optional[str] = Field(
        default=None,
        description="Restrict results to one Chicago neighborhood, e.g. 'Wicker Park'",
    )
    category: Optional[str] = Field(
        default=None,
        description="Restrict results to one category, e.g. 'Health & Wellness'. "
        "Matched case-insensitively against the stored category.",
    )
