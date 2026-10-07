"""Category vocabulary: one copy, shared by the API and the chatbot.

Categories arrive from a dozen sources that each label their own events, so the
stored vocabulary is genuinely varied: "Music" from one, "Arts & Theatre" from
another, "Theatre & Performing Arts" from a third. Casing is normalized on the
way in (see `normalize_category`), but the wording is left alone - collapsing
"Arts & Crafts" into "Arts & Culture" would throw away a real distinction.

What that costs is matching: a search for "art" has to reach every Arts* label
rather than a single exact value. `category_filter` does that by prefix, so one
concept spans the variants without a hand-maintained list of every spelling.
"""

import re
from typing import Optional

from sqlalchemy import or_

# Tokens that are acronyms rather than words, and must not be title-cased into
# "Lgbtq" or "Tv".
_ACRONYMS = {"LGBTQ", "TV", "DJ", "DJS", "BYOB", "NYE", "EDM", "RSVP", "ASL"}

# A concept -> the words a person might use for it, and the prefixes it should
# match against stored category values. Prefixes rather than substrings because
# "%art%" also matches "Parties", while "art%" does not.
CATEGORY_CONCEPTS: dict[str, dict[str, list[str]]] = {
    "music": {
        "words": ["music", "concert", "band", "dj", "acoustic", "jazz", "gig", "live music"],
        "prefixes": ["music"],
    },
    "comedy": {
        "words": ["comedy", "stand-up", "standup", "laugh", "improv"],
        "prefixes": ["comedy"],
    },
    "theater": {
        "words": ["theater", "theatre", "play", "drama", "broadway", "musical"],
        # Both spellings are stored, from different sources.
        "prefixes": ["theater", "theatre"],
    },
    "art": {
        "words": ["art", "arts", "gallery", "exhibition", "exhibit", "installation", "mural"],
        "prefixes": ["art"],
    },
    "film": {
        "words": ["film", "movie", "cinema", "screening"],
        "prefixes": ["film", "tv"],
    },
    "food": {
        "words": ["food", "dining", "restaurant", "chef", "cooking", "tasting", "brunch"],
        "prefixes": ["food"],
    },
    "sports": {
        "words": ["sports", "sport", "game", "match", "tournament", "athletic"],
        "prefixes": ["sport"],
    },
    "community": {
        "words": ["community", "volunteer", "meetup", "workshop", "class"],
        "prefixes": ["community", "activism"],
    },
    "wellness": {
        "words": ["wellness", "yoga", "meditation", "fitness", "health"],
        "prefixes": ["health"],
    },
    "lgbtq": {
        "words": ["lgbtq", "lgbt", "queer", "pride", "drag"],
        "prefixes": ["lgbtq"],
    },
}


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Normalize a category's casing and whitespace, leaving its wording alone.

    "music" and "Music" are the same category from two sources and should not
    be two tiles; "Arts & Crafts" and "Arts & Culture" are not, and stay apart.
    Acronyms survive, so LGBTQ does not become Lgbtq.
    """
    if value is None:
        return None
    collapsed = " ".join(value.split())
    if not collapsed:
        return None

    def fix(word: str) -> str:
        # An existing internal capital is deliberate - "DJs", "McCormick" -
        # so leave it. Checked before the acronym list, or "DJs" would be
        # flattened to "DJS".
        if any(ch.isupper() for ch in word[1:]):
            return word
        if word.upper() in _ACRONYMS:
            return word.upper()
        return word[:1].upper() + word[1:].lower()

    # Split on spaces but keep separators like "/" intact inside a token.
    return " ".join(
        "/".join(fix(part) for part in word.split("/")) for word in collapsed.split(" ")
    )


def extract_category_concepts(query: str) -> list[str]:
    """Concepts named in a free-text query, as concept keys."""
    text = f" {re.sub(r'[^a-z0-9 -]', ' ', query.lower())} "
    text = re.sub(r"\s+", " ", text)
    found = []
    for concept, spec in CATEGORY_CONCEPTS.items():
        # Also match the regular plural, so "workshops" finds "workshop".
        if any(f" {word} " in text or f" {word}s " in text for word in spec["words"]):
            found.append(concept)
    return found


def category_prefixes(concepts: list[str]) -> list[str]:
    """The stored-value prefixes those concepts should match."""
    return [p for c in concepts for p in CATEGORY_CONCEPTS.get(c, {}).get("prefixes", [])]


def category_filter(column, concepts: list[str]):
    """A SQLAlchemy condition matching any stored category for these concepts.

    Returns None when nothing matched, so a caller can tell "no category was
    named" apart from "a category was named and nothing has it".
    """
    prefixes = category_prefixes(concepts)
    if not prefixes:
        return None
    return or_(*[column.ilike(f"{prefix}%") for prefix in prefixes])
