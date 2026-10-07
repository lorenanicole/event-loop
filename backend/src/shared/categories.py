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
        "canonical": "Music",
        "words": ["music", "concert", "band", "dj", "acoustic", "jazz", "gig", "live music"],
        "prefixes": ["music"],
    },
    "comedy": {
        "canonical": "Comedy",
        "words": ["comedy", "stand-up", "standup", "laugh", "improv"],
        "prefixes": ["comedy"],
    },
    "theater": {
        "canonical": "Theater",
        "words": ["theater", "theatre", "play", "drama", "broadway", "musical"],
        # Both spellings are stored, from different sources.
        "prefixes": ["theater", "theatre"],
        # "Arts & Theatre" is Ticketmaster's top-level segment rather than a
        # category, and it is where its theater lives - Operation Mincemeat,
        # Jekyll & Hyde, Drunk Shakespeare. A prefix cannot reach it from here
        # without also claiming every other Arts label, so name it outright.
        # It keeps its place under "art" too, because the segment genuinely
        # spans both and the source does not separate them.
        "labels": ["Arts & Theatre"],
    },
    "art": {
        "canonical": "Arts",
        "words": ["art", "arts", "gallery", "exhibition", "exhibit", "installation", "mural"],
        # Named outright rather than matched as "art%", which would sweep in
        # Ticketmaster's "Arts & Theatre" segment and answer "art galleries"
        # with 185 Broadway shows. These three are the genuine arts labels:
        # arts-venue programming, participatory making, and do312's culture
        # bucket. They are kept apart from each other on purpose - a craft
        # workshop and a gallery talk are not the same outing.
        "prefixes": [],
        "labels": ["Arts", "Arts & Crafts", "Arts & Culture"],
    },
    "film": {
        "canonical": "Film",
        "words": ["film", "movie", "cinema", "screening"],
        "prefixes": ["film", "tv"],
    },
    "food": {
        "canonical": "Food & Drink",
        "words": ["food", "dining", "restaurant", "chef", "cooking", "tasting", "brunch"],
        "prefixes": ["food"],
    },
    "sports": {
        "canonical": "Sports",
        "words": ["sports", "sport", "game", "match", "tournament", "athletic"],
        "prefixes": ["sport"],
    },
    "community": {
        "canonical": "Community",
        "words": ["community", "volunteer", "meetup", "workshop", "class"],
        "prefixes": ["community", "activism"],
    },
    "wellness": {
        "canonical": "Health & Wellness",
        "words": ["wellness", "yoga", "meditation", "fitness", "health"],
        "prefixes": ["health"],
    },
    "education": {
        "canonical": "Tech / Educational",
        "words": ["lecture", "seminar", "talk", "talks", "panel", "symposium",
                  "astronomy", "astronomer", "astrophysicist", "observation",
                  "in conversation", "science", "stem", "coding", "hackathon"],
        "prefixes": ["tech"],
    },
    "lgbtq": {
        "canonical": "LGBTQ",
        "words": ["lgbtq", "lgbt", "queer", "pride", "drag"],
        "prefixes": ["lgbtq"],
    },
}


# A venue scraper labels every event with the venue's own category, so a wine
# special at a music pub and a sewing class at a music hall both arrive as
# "Music" - and "music tonight in Avondale" answers with neither music.
#
# These rules override that from the title, and are deliberately narrow:
# precision matters far more than recall here, because a wrong category is
# worse than a vague one. Ordered, first match wins, so "Comedy Open Mic" is
# comedy rather than an open mic.
#
# Patterns that were tried and dropped for being wrong too often:
#   film|movie|screening  - matched concerts billed "live to film"
#                           ("Disney's Encanto In Concert Live to Film")
#   craft                 - matched craft beer
#   workshop              - far too broad
#   taco|pizza|cocktail   - matched band and party names
_TITLE_CATEGORY_RULES: list[tuple[str, str]] = [
    ("Comedy", r"\bcomedy\b|\bstand[- ]?up\b|\bimprov\b"),
    ("Karaoke/Trivia/Open Mics", r"\b(karaoke|trivia|bingo|open[- ]mic)\b"),
    ("Arts & Crafts", r"\b(sewing|knit|crochet|quilt|pottery|ceramics?|life drawing)\b"),
    ("Food & Drink",
     r"\b(wine wednesday|happy hour|bottomless|drag brunch|supper club)\b"
     r"|\bhalf[- ]price[d]?\s+(wine|beer|drink)"
     r"|\b(beer|whiskey|wine) tasting\b"),
]


def infer_category(title: Optional[str], fallback: str) -> str:
    """Override a venue's blanket category where the title is unambiguous.

    Returns `fallback` unchanged when nothing matches, which is the common
    case - about 3% of venue-scraped events are reclassified.
    """
    if not title:
        return fallback
    for category, pattern in _TITLE_CATEGORY_RULES:
        if re.search(pattern, title, re.IGNORECASE):
            return category
    return fallback


def classify_from_title(title: Optional[str], fallback: str = "Events") -> str:
    """Pick a category for an event that arrives without one.

    The external sources hand over a title, a date and a link - no category -
    and the chatbot was filing all of them under "Online Search", which
    describes where the event came from rather than what it is. Provenance is
    already recorded in `source`, so it does not belong here too.

    Tries the narrow title rules first, then the broader concept vocabulary,
    and falls back to the generic bucket rather than inventing something.
    """
    if not title:
        return fallback

    # The narrow rules are high precision, so they win.
    specific = infer_category(title, "")
    if specific:
        return specific

    for concept in extract_category_concepts(title):
        canonical = CATEGORY_CONCEPTS.get(concept, {}).get("canonical")
        if canonical:
            return canonical
    return fallback


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


def category_labels(concepts: list[str]) -> list[str]:
    """Stored values a concept claims outright, where a prefix cannot reach them.

    Needed where a source's label does not begin with the concept's own name -
    Ticketmaster files theater under "Arts & Theatre" - and where a prefix
    would overreach if widened to catch it.
    """
    return [v for c in concepts for v in CATEGORY_CONCEPTS.get(c, {}).get("labels", [])]


def category_filter(column, concepts: list[str]):
    """A SQLAlchemy condition matching any stored category for these concepts.

    Returns None when no concept was recognized, so a caller can tell "no
    category was named" apart from "a category was named and nothing has it".
    """
    clauses = [column.ilike(f"{prefix}%") for prefix in category_prefixes(concepts)]
    clauses += [column.ilike(label) for label in category_labels(concepts)]
    if not clauses:
        return None
    return or_(*clauses)
