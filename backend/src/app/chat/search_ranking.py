"""Event relevance scoring and formatting for chatbot search results."""

from datetime import datetime

from pydantic import BaseModel, Field

from shared.database.models import EventModel


class ScoredEvent(BaseModel):
    """Event summary ranked against a chat query."""

    title: str
    date: str
    location: str | None = None
    neighborhood: str | None = None
    url: str | None = None
    source: str
    category: str | None = None
    details: str | None = None
    cost: str | None = None
    age_range: str | None = None
    is_outdoor: str | None = None
    address: str | None = None
    locality: str | None = None  # suburb/city when venue is outside Chicago proper
    confidence: float = Field(description="Relevance score 0.0-1.0")


def _count_word_matches(keywords: list[str], text: str) -> int:
    """Count whole-word matches, allowing simple plural forms."""
    words = {word.strip(".,!?;:'\"()-") for word in text.lower().split()}
    stems = {word.rstrip("s") for word in words if word}
    return sum(1 for keyword in keywords if keyword in words or keyword.rstrip("s") in stems)


def score_event_relevance(
    event: EventModel,
    keywords: list[str],
    query_categories: list[str],
    semantic_score: float | None = None,
) -> float:
    """Combine lexical, semantic, category, and date-proximity relevance."""
    score = 0.0
    event_text = f"{event.name} {event.category or ''}".lower()
    matching_keywords = _count_word_matches(keywords, event_text)
    if matching_keywords > 0:
        score += min(0.4, 0.15 + (matching_keywords / max(len(keywords), 1)) * 0.25)

    if semantic_score is not None and semantic_score > 0:
        score += min(0.4, max(0.0, semantic_score) * 0.9)

    if (
        event.category
        and query_categories
        and event.category.lower() in [c.lower() for c in query_categories]
    ):
        score += 0.15

    now = datetime.now()  # noqa: DTZ005 — intentionally naive for local date arithmetic
    if event.date and event.date >= now:
        days_away = (event.date - now).days
        score += 0.05 if days_away <= 7 else 0.03 if days_away <= 30 else 0.01

    return min(1.0, score)


def truncate_summary(text: str, words: int = 10) -> str:
    """Keep event descriptions compact in the agent context."""
    if not text:
        return ""
    parts = text.split()
    return " ".join(parts[:words]) + ("..." if len(parts) > words else "")


def format_event_date(event: EventModel) -> str:
    """Format an event date, preserving time and multi-day runs."""
    if not event.date:
        return "Date not listed"

    label = event.date.strftime("%a, %b %d, %Y")
    date_end = getattr(event, "date_end", None)
    if date_end and date_end.date() != event.date.date():
        return f"{label} through {date_end.strftime('%a, %b %d, %Y')}"

    time_str = (getattr(event, "time", None) or "").strip()
    return f"{label} @ {time_str}" if time_str else label


def filter_top_results(
    events: list[EventModel],
    query: str,
    keywords: list[str],
    categories: list[str],
    limit: int = 5,
    semantic_scores: dict[int, float] | None = None,
) -> list[ScoredEvent]:
    """Score events and return the highest-ranked compact result records."""
    semantic_scores = semantic_scores or {}
    scored = [
        ScoredEvent(
            title=event.name,
            date=format_event_date(event),
            neighborhood=getattr(event, "neighborhood_name", None),
            url=event.origination_url,
            source=event.source or "Local DB",
            category=event.category,
            details=truncate_summary(event.details) if event.details else None,
            cost=event.cost if hasattr(event, "cost") else None,
            age_range=event.age_range if hasattr(event, "age_range") else None,
            is_outdoor=event.is_outdoor if hasattr(event, "is_outdoor") else None,
            address=event.address if hasattr(event, "address") else None,
            locality=getattr(event, "locality", None),
            confidence=score_event_relevance(
                event, keywords, categories, semantic_scores.get(getattr(event, "id", None))
            ),
        )
        for event in events
    ]
    return sorted(scored, key=lambda event: event.confidence, reverse=True)[:limit]


# Backwards-compatible private names used by existing tests and callers.
_score_event_relevance = score_event_relevance
_truncate_summary = truncate_summary
_format_event_date = format_event_date
_filter_top_results = filter_top_results
