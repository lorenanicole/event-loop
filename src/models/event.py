from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    name: str
    date: datetime
    category: str
    details: Optional[str] = None
    origination_url: str
    date_retrieved: datetime = Field(default_factory=datetime.utcnow)


class Event(EventCreate):
    id: int

    class Config:
        from_attributes = True


class EventSearch(BaseModel):
    query: str = Field(..., description="Natural language search query")
    limit: int = Field(default=20, le=100)
