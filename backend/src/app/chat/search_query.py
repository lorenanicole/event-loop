"""Turn event-search language into keywords and structured date/place filters."""

import re
from datetime import datetime, timedelta

from sqlalchemy import select

from shared.database.models import NeighborhoodModel
from shared.geo.neighborhoods import CHICAGO_REGION_ALIASES, NEIGHBORHOOD_ALIASES

STOP_WORDS = {
    "whats",
    "wheres",
    "whos",
    "hows",
    "thats",
    "dont",
    "doesnt",
    "didnt",
    "cant",
    "wont",
    "isnt",
    "arent",
    "im",
    "ive",
    "ill",
    "id",
    "youre",
    "its",
    "lets",
    "theres",
    "heres",
    "who",
    "how",
    "the",
    "a",
    "an",
    "and",
    "or",
    "is",
    "are",
    "in",
    "on",
    "at",
    "this",
    "that",
    "these",
    "those",
    "what",
    "when",
    "where",
    "why",
    "find",
    "get",
    "search",
    "show",
    "tell",
    "give",
    "all",
    "want",
    "looking",
    "events",
    "event",
    "i",
    "to",
    "for",
    "any",
    "chicago",
    "city",
    "illinois",
    "windy",
    "area",
    "town",
    "region",
    "like",
    "would",
    "see",
    "me",
    "my",
    "please",
    "can",
    "could",
    "need",
    "there",
    "some",
    "something",
    "anything",
    "know",
    "about",
    "happening",
    "going",
    "got",
    "have",
    "has",
    "near",
    "around",
    "list",
    "today",
    "tonight",
    "tomorrow",
    "weekend",
    "week",
    "month",
    "year",
    "next",
    "upcoming",
    "soon",
    "now",
    "weekends",
    "nights",
    "night",
}

MAX_KEYWORDS = 5
_CONTRACTIONS = ("'s", "'ll", "'re", "'ve", "'d", "'m", "n't", "'t")


def normalize_place(text: str) -> str:
    """Lowercase and collapse a place name or query for literal matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]", " ", text.lower())).strip()


async def extract_neighborhoods(db, query: str) -> list[str]:
    """Resolve named neighborhoods and broad Chicago regions to DB rows."""
    names = (await db.execute(select(NeighborhoodModel.name))).scalars().all()
    candidates = {normalize_place(name): name for name in names}
    for spoken, canonical in NEIGHBORHOOD_ALIASES.items():
        if canonical in names:
            candidates.setdefault(normalize_place(spoken), canonical)

    haystack = f" {normalize_place(query)} "
    found: list[str] = []
    for region in sorted(CHICAGO_REGION_ALIASES, key=len, reverse=True):
        needle = normalize_place(region)
        if f" {needle} " not in haystack:
            continue
        for name in CHICAGO_REGION_ALIASES[region]:
            if name in names and name not in found:
                found.append(name)
        haystack = haystack.replace(f" {needle} ", "  ")

    for needle in sorted(candidates, key=len, reverse=True):
        if needle and f" {needle} " in haystack:
            name = candidates[needle]
            if name not in found:
                found.append(name)
            haystack = haystack.replace(f" {needle} ", "  ")
    return found


def strip_neighborhoods(
    keywords: list[str], neighborhoods: list[str], query: str | None = None
) -> list[str]:
    """Remove place-name terms so SQL title matching only sees the subject."""
    parts = {word for name in neighborhoods for word in normalize_place(name).split()}
    for spoken, canonical in NEIGHBORHOOD_ALIASES.items():
        if canonical in neighborhoods:
            parts.update(normalize_place(spoken).split())
    if query:
        normalized_query = f" {normalize_place(query)} "
        for region in CHICAGO_REGION_ALIASES:
            if f" {normalize_place(region)} " in normalized_query:
                parts.update(normalize_place(region).split())
    return [keyword for keyword in keywords if keyword not in parts]


def _stem_contraction(word: str) -> str:
    for ending in _CONTRACTIONS:
        if word.endswith(ending) and len(word) > len(ending):
            return word[: -len(ending)]
    return word


def extract_keywords(query: str) -> list[str]:
    """Return bounded, ordered content words from a user query."""
    words = [_stem_contraction(word.strip(".,!?;:'\"()")) for word in query.lower().split()]
    keywords = [word for word in words if word and word not in STOP_WORDS and len(word) > 2]
    return list(dict.fromkeys(keywords))[:MAX_KEYWORDS]


def extract_date_range(query: str) -> tuple[datetime, datetime] | None:
    """Parse the supported relative date phrases into a date window."""
    now = datetime.now()  # noqa: DTZ005 — intentionally naive for local date arithmetic
    query_lower = query.lower()

    if (
        "this weekend" in query_lower
        or "this saturday" in query_lower
        or "this sunday" in query_lower
    ):
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        saturday = now + timedelta(days=days_until_saturday)
        sunday = saturday + timedelta(days=1)
        # "this sunday" → window starts on Sunday, not Saturday
        if (
            "this sunday" in query_lower
            and "this saturday" not in query_lower
            and "this weekend" not in query_lower
        ):
            return sunday, sunday.replace(hour=23, minute=59, second=59)
        return saturday, sunday.replace(hour=23, minute=59, second=59)
    if "this week" in query_lower:
        return now, now + timedelta(days=7)
    if "this month" in query_lower:
        end_of_month = now.replace(day=1) + timedelta(days=32)
        end_of_month = end_of_month.replace(day=1) - timedelta(days=1)
        return now, end_of_month.replace(hour=23, minute=59, second=59)
    if "next week" in query_lower:
        start = now + timedelta(days=7)
        return start, start + timedelta(days=7)
    if "tonight" in query_lower or "today" in query_lower:
        return now, now.replace(hour=23, minute=59, second=59)
    return None
