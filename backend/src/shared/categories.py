"""Category vocabulary: one copy, shared by the API and the chatbot.

Categories arrive from a dozen sources that each label their own events in
their own words. Stored verbatim, that produced 24 distinct categories with
four ways to say theater ("Theater", "Arts & Theatre", "Theatre & Performing
Arts") and a do312 bucket called "Activism & Community Events" that filed a
library's Teen Anime Night under activism.

So there are two levels, and `CATEGORY_TAXONOMY` below is the map between
them:

  parent   - a short, fixed list, and the only thing a filter tile shows.
  subtag   - the source's own label, kept as it was written.

A subtag is never thrown away, because some of them carry a real distinction:
"Arts & Crafts" is making things and "Arts & Culture" is going to look at
them, and both sit under Arts. Filtering matches parents, so an event is
findable under the tile a person would actually click, while the finer label
survives for display and for anyone who wants it.

The mapping is written by hand, which is a deliberate choice. Mapping the
labels by embedding similarity was measured first, with the same model2vec
model the search uses, and it does not work - not because it is imprecise but
because it ranks the wrong answer above the right one:

    Arts & Theatre <-> Theatre & Performing Arts   0.91   right
    Arts & Theatre <-> Arts                        0.84   WRONG
    Theater        <-> Arts & Theatre              0.77   right, ranked below
    Community      <-> Activism & Community        0.56   right, ranked below
    Karaoke/Trivia <-> Music                       0.18   noise

No threshold separates those: at 0.80 you merge theater into arts and still
miss Community, and at 0.55 you catch Community but also swallow the generic
bucket. The label set is 24, finite and known, so a table is exact, testable
and reviewable where a similarity score is none of the three. Similarity is
still useful for noticing a label nobody has mapped yet - see
`unmapped_labels`.
"""

import re
from collections.abc import Iterable

from sqlalchemy import String, cast, or_

# Tokens that are acronyms rather than words, and must not be title-cased into
# "Lgbtq" or "Tv".
_ACRONYMS = {"LGBTQ", "TV", "DJ", "DJS", "BYOB", "NYE", "EDM", "RSVP", "ASL"}


# Parent -> the source labels that belong under it.
#
# A label may appear under two parents, and one does: Ticketmaster's
# "Arts & Theatre" is a single segment covering both, and it holds 172 events -
# a quarter of the theater data. Forcing it either way mislabels the other
# half, so it is listed under both and the event carries both parents. That is
# what the multi-label column is for.
#
# The generic parent is last on purpose: it is where labels that say nothing
# about what an event is ("Events", "Miscellaneous", "Other") go, so they stop
# competing with real categories for a filter tile.
CATEGORY_TAXONOMY: dict[str, list[str]] = {
    "Music": ["Music", "Parties & DJs"],
    "Theater": ["Theater", "Theatre", "Theatre & Performing Arts", "Arts & Theatre"],
    # "Arts & Crafts" stays a distinct subtag under Arts. Making something and
    # going to look at something are different outings, and collapsing them
    # outright was the objection to a flat list in the first place.
    "Arts": ["Arts", "Arts & Culture", "Arts & Crafts", "Poetry & Literary", "Arts & Theatre"],
    "Comedy": ["Comedy"],
    "Film": ["Film", "TV & Film"],
    # "Activism & Community Events" is do312's own bucket, and it is why a
    # library's Teen Anime Night was filed under activism.
    "Community": ["Community", "Activism & Community Events", "Charity"],
    "Tech / Educational": ["Tech / Educational"],
    # A parent in its own right, not a flavour of Community. 41 events - yoga,
    # meditation, sound baths - and the drift report is what surfaced it: it
    # was the one real category missing from the first draft of this table.
    "Health & Wellness": ["Health & Wellness"],
    "Food & Drink": ["Food & Drink", "Happy Hour / Specials"],
    # "Sports & Fitness" is do312's label and covers both a 5k and a yoga
    # class. Filed under Sports, which is where somebody looking for a game
    # would look; the yoga ones reach Health & Wellness through their titles.
    "Sports": ["Sports", "Sports & Fitness"],
    "LGBTQ": ["LGBTQ"],
    "Karaoke/Trivia/Open Mics": ["Karaoke/Trivia/Open Mics"],
    "Holiday & Seasonal": ["Holiday & Seasonal", "Halloween"],
    "Festival": ["Festival"],
    "Shopping": ["Shopping"],
    "Other": ["Other", "Events", "Miscellaneous", "Cannabis"],
}

# The parent every filter tile is drawn from, in the order they are offered.
PARENT_CATEGORIES: list[str] = list(CATEGORY_TAXONOMY)

# Labels that mean "no category", so they are never kept as a finer subtag.
_UNINFORMATIVE_LABELS = {"events", "miscellaneous", "other", "uncategorized"}

# subtag (lowercased) -> its parents, primary first. Built once from the table
# above so the table stays the single place anything is declared.
_SUBTAG_PARENTS: dict[str, list[str]] = {}
for _parent, _subtags in CATEGORY_TAXONOMY.items():
    for _subtag in _subtags:
        _SUBTAG_PARENTS.setdefault(_subtag.lower(), []).append(_parent)


def parents_of(label: str | None) -> list[str]:
    """The parent categories a source label belongs to, primary first.

    An unmapped label is returned as its own parent rather than dropped or
    forced into the generic bucket: a new label from a source is a gap in the
    table, and silently filing it under "Other" is how it would stay a gap.
    `unmapped_labels` is how they get noticed.
    """
    clean = normalize_category(label)
    if not clean:
        return []
    return list(_SUBTAG_PARENTS.get(clean.lower(), [clean]))


def to_parents(labels: Iterable[str | None]) -> list[str]:
    """Every parent for a list of source labels, in order, de-duplicated."""
    parents: list[str] = []
    for label in labels:
        for parent in parents_of(label):
            if parent not in parents:
                parents.append(parent)
    return parents


def informative_subtags(labels: Iterable[str | None], parents: list[str]) -> list[str]:
    """The source labels worth keeping next to their parents.

    A subtag earns its place by saying something the parent does not.
    "Arts & Crafts" under Arts does. "Events" under Other does not - it is the
    absence of a category, and printing it on a card as though it were a
    finer-grained one is worse than printing nothing.
    """
    keep = []
    for label in labels:
        clean = normalize_category(label)
        if not clean or clean in parents or clean in keep:
            continue
        if clean.lower() in _UNINFORMATIVE_LABELS:
            continue
        keep.append(clean)
    return keep


def unmapped_labels(labels: Iterable[str | None]) -> list[str]:
    """Labels with no entry in the taxonomy, so a gap can be reported.

    This is the job similarity scoring is actually good at: not deciding where
    a label belongs, but noticing that a source has started emitting one
    nobody has placed yet.
    """
    missing = []
    for label in labels:
        clean = normalize_category(label)
        if clean and clean.lower() not in _SUBTAG_PARENTS and clean not in missing:
            missing.append(clean)
    return missing


# A concept -> the words a person might use for it, and the prefixes it should
# match against stored category values. Prefixes rather than substrings because
# "%art%" also matches "Parties", while "art%" does not.
CATEGORY_CONCEPTS: dict[str, dict[str, list[str]]] = {
    "music": {
        "canonical": "Music",
        # Genres, because people ask by genre and not by the word "music".
        # "blues tonight on the South Side" matched no category at all, which
        # in a Chicago events app is close to absurd - the city is where
        # electric blues was invented and four of the venues scraped here book
        # it nightly.
        #
        # Only genre names that are not also ordinary words. "house" is left
        # out deliberately: it matches open house, haunted house and house
        # party. "soul" is out for "soul food" and song titles.
        "words": [
            "music",
            "concert",
            "band",
            "dj",
            "acoustic",
            "gig",
            "live music",
            "blues",
            "jazz",
            "funk",
            "r&b",
            "hip hop",
            "rap",
            "techno",
            "punk",
            "metal",
            "indie",
            "folk",
            "bluegrass",
            "reggae",
            "salsa",
            "cumbia",
            "mariachi",
            "orchestra",
            "symphony",
            "opera",
            "choir",
            "dj set",
        ],
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
        "words": [
            "food",
            "dining",
            "restaurant",
            "chef",
            "cooking",
            "tasting",
            "brunch",
            "oktoberfest",
            "mocktoberfest",
            "beer garden",
            "wine",
            "cocktail",
            "whiskey",
            "brewery",
        ],
        "prefixes": ["food"],
    },
    "sports": {
        "canonical": "Sports",
        # Deliberately no sport names here. They were added - volleyball,
        # basketball, marathon and the rest - to catch fixtures like "DePaul
        # Blue Demons Womens Volleyball vs. Villanova", which none of the
        # generic words match. Measured over the stored events, half the hits
        # were wrong: "Torn Light Presents - Naturalblkinvention & Donkey
        # Basketball" is a band, and "LCF 2024 Presents: The Marathon Show" is
        # comedy. A sport's name in a title is usually a joke or a band.
        #
        # Fixtures are matched by `_TITLE_CATEGORY_RULES` instead, which
        # requires the sport AND a "vs" - the thing that actually distinguishes
        # a game from a gig.
        # "marathon", "5k" and "fun run" are races. Bare "run" is not added:
        # it matches a show's run, a run of dates, and "run the world".
        "words": [
            "sports",
            "sport",
            "game",
            "match",
            "tournament",
            "athletic",
            "marathon",
            "triathlon",
            "5k",
            "10k",
            "fun run",
            "half marathon",
        ],
        "prefixes": ["sport"],
    },
    "community": {
        "canonical": "Community",
        "words": [
            "community",
            "volunteer",
            "meetup",
            "meeting",
            "user group",
            "workshop",
            "class",
            "potluck",
            "mixer",
            "social",
        ],
        "prefixes": ["community", "activism"],
    },
    "wellness": {
        "canonical": "Health & Wellness",
        "words": ["wellness", "yoga", "meditation", "fitness", "health"],
        "prefixes": ["health"],
    },
    "education": {
        "canonical": "Tech / Educational",
        "words": [
            "lecture",
            "seminar",
            "talk",
            "talks",
            "panel",
            "symposium",
            "hack night",
            "open hack",
            "hack day",
            "astronomy",
            "astronomer",
            "astrophysicist",
            "observation",
            "in conversation",
            "science",
            "stem",
            "coding",
            "hackathon",
        ],
        "prefixes": ["tech"],
    },
    "lgbtq": {
        "canonical": "LGBTQ",
        "words": ["lgbtq", "lgbt", "queer", "pride", "drag"],
        "prefixes": ["lgbtq"],
    },
    # Added because the generic bucket was full of them. TimeOut supplies no
    # category at all, and a third of what it sends in October is seasonal:
    # "Night of 1,000 Jack-o'-Lanterns", "Haunted Halsted Halloween Fest",
    # "Lincoln Park Spooktacular", "Nightmare on Clark Street". None of those
    # is Music, Theater or Community, and filing them under "Other" hid the
    # single most seasonal thing a Chicago events site should be good at.
    "holiday": {
        "canonical": "Holiday & Seasonal",
        "words": [
            "halloween",
            "haunted",
            "haunt",
            "spooktacular",
            "spooky",
            "jack-o-lantern",
            "trick or treat",
            "day of the dead",
            "dia de los muertos",
            "christmas",
            "holiday",
            "hanukkah",
            "kwanzaa",
            "new year",
            "nye",
            "thanksgiving",
            "easter",
            "valentine",
            "lunar new year",
            "juneteenth",
            # How Chicago actually titles its October events: "A Nightmare on
            # Fulton Street", "Ravenswood Costume Crawl", "Creepy Cruise",
            # "Drunk Dracula", "Terror in the Tropics", "Howl-O-Ween Canine
            # Cruise". None of them contains the word Halloween.
            "nightmare",
            "costume",
            "creepy",
            "terror",
            "dracula",
            "zombie",
            "howl-o-ween",
            "all hallows",
            # "pumpkin" and "ghost" were here and are removed. Both are band
            # and series names at least as often as they are seasonal:
            # "Smashing Pumpkins" at the United Center and "Relax Attack Jazz
            # Series: Common Ghosts" both picked up a Holiday label and turned
            # up under the Halloween filter. Scored on the labelled set,
            # dropping them takes precision from 90% to 94% and cuts spurious
            # secondary labels from 4 to 1, for 6 points of coverage - the
            # right way round, since a wrong category hides an event from the
            # filter somebody would actually use.
        ],
        "prefixes": ["holiday"],
    },
    # "Manhattan Vintage", "Handmade Market", "Illinois Product Expo" - all
    # shopping, all previously uncategorized. "Market" is included knowing it
    # also matches a night market at a music venue, which is a fair reading:
    # that event is both.
    "shopping": {
        "canonical": "Shopping",
        "words": [
            "market",
            "expo",
            "vintage",
            "flea",
            "bazaar",
            "pop-up",
            "trunk show",
            "makers",
            "handmade",
            "shopping",
        ],
        "prefixes": ["shopping"],
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
    # A fixture: a sport or a Chicago team AND a "vs". Both halves are
    # needed. The name alone is usually a joke or a band - "Donkey
    # Basketball" is a band, "The Marathon Show" is comedy, and "Daikaiju, 95
    # Bulls, PaSsy" is a bill of three bands - while "vs" alone catches DJ
    # battles and double bills. Together they are reliable.
    #
    # The team names earn their place because the venue cannot: the United
    # Center is configured as a music venue, which is right for most of its
    # calendar and filed every Bulls and Blackhawks game under Music. A title
    # rule outranks the venue default, which is the point of these.
    (
        "Sports",
        r"(?:\b(?:volleyball|basketball|soccer|hockey|baseball|football|lacrosse"
        r"|rugby|softball|tennis|wrestling"
        r"|bulls|blackhawks|bears|cubs|white sox|sky|fire|red stars|sting)\b"
        r"(?=.*\bv(?:s\.?)?\b))"
        r"|(?:\bv(?:s\.?)?\b(?=.*\b(?:volleyball|basketball|soccer|hockey"
        r"|baseball|football|lacrosse|rugby|softball|tennis|wrestling"
        r"|bulls|blackhawks|bears|cubs|white sox|sky|fire|red stars|sting)\b))",
    ),
    ("Comedy", r"\bcomedy\b|\bstand[- ]?up\b|\bimprov\b"),
    ("Karaoke/Trivia/Open Mics", r"\b(karaoke|trivia|bingo|open[- ]mic)\b"),
    ("Arts & Crafts", r"\b(sewing|knit|crochet|quilt|pottery|ceramics?|life drawing)\b"),
    (
        "Food & Drink",
        r"\b(wine wednesday|happy hour|bottomless|drag brunch|supper club)\b"
        r"|\bhalf[- ]price[d]?\s+(wine|beer|drink)"
        r"|\b(beer|whiskey|wine) tasting\b",
    ),
]


def infer_category(title: str | None, fallback: str) -> str:
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


def classify_from_title(
    title: str | None, fallback: str = "Events", hint: str | None = None
) -> str:
    """Pick a category for an event that arrives without one.

    The external sources hand over a title, a date and a link - no category -
    and the chatbot was filing all of them under "Online Search", which
    describes where the event came from rather than what it is. Provenance is
    already recorded in `source`, so it does not belong here too.

    Tries the narrow title rules first, then the broader concept vocabulary,
    and falls back to the generic bucket rather than inventing something.

    `hint` is any other wording the source gives for what the event is -
    Google's "Live jazz concert", Ticketmaster's genre, a listing's blurb.
    Many titles are names and nothing more: "Jazz City" and "Tortilla Tales"
    are unclassifiable on their own and obvious next to "Live jazz concert"
    and "Cultural heritage workshop".

    The hint widens concept matching only. The narrow title rules stay on the
    title, because they are precision instruments aimed at a performer's
    billing - letting a venue's marketing blurb trigger them would undo the
    care in `_TITLE_CATEGORY_RULES`.
    """
    if not title and not hint:
        return fallback

    # The narrow rules are high precision, so they win.
    specific = infer_category(title, "")
    if specific:
        return specific

    for concept in extract_category_concepts(_with_hint(title, hint)):
        canonical = CATEGORY_CONCEPTS.get(concept, {}).get("canonical")
        if canonical:
            return canonical
    return fallback


def _with_hint(title: str | None, hint: str | None) -> str:
    """Title and hint as one string for concept matching."""
    return " ".join(part for part in (title, hint) if part)


# How many labels one event can carry. Three is enough for the real cases
# ("Music", "LGBTQ", "Community") and keeps a result card readable.
MAX_CATEGORIES = 3

# The bucket that means "nothing is known about what this is", as opposed to a
# genuine category. Named so the classifier can tell the difference: it is
# worth keeping a venue's "Community" as a second label, and not worth keeping
# "Events".
GENERIC_CATEGORY = "Events"


def classify_all(title: str | None, fallback: str = "Events", hint: str | None = None) -> list[str]:
    """Every category an event plausibly belongs to, primary first.

    One event genuinely belongs to several: a trans pride festival is both
    LGBTQ and Community, a drag show at a music venue is both Music and LGBTQ,
    and a Python user group meeting is both Tech and Community. Storing only
    one label meant the event was findable under one of those and invisible
    under the others.

    The primary stays whatever the single-label path would have chosen, so
    nothing that displays `category` had to change. The rest are the other
    concepts the title names, plus the venue's own category where the title
    overrode it.

    `hint` is the source's own wording for what the event is - see
    `classify_from_title`. It is especially worth having here: "Live jazz
    concert" against the title "Jazz City" supplies the Music label that the
    name alone never would, and a second label is exactly what multi-category
    filtering needs.
    """
    # The venue's own category stays the primary where it has one, because it
    # is a fact about the booking rather than a guess from wording: a drag
    # show at a music hall is primarily Music and also LGBTQ, in that order.
    # A narrow title rule still outranks it.
    primary = infer_category(title, fallback)

    # Only when that leaves us with the generic bucket - which is every event
    # from an external search, where no venue category exists - fall through
    # to the concepts. Otherwise "Jazz City" came out primarily "Events"
    # while `classify_from_title` called the same event Music, and the two
    # entry points disagreed about the same row.
    if primary == GENERIC_CATEGORY:
        primary = classify_from_title(title, fallback, hint=hint)

    # A fixture is only a fixture. When the title rule identified one, the
    # other concepts in the title are team names colliding with the
    # vocabulary rather than a second thing to do: "Blackhawks vs. St. Louis
    # Blues" is not also a blues gig, and "Chicago Fire vs Orlando" is not a
    # festival. Conditioned on the rule having fired - an event the venue
    # merely labelled Sports keeps its other labels.
    if primary == "Sports" and primary != fallback:
        return [normalize_category(primary)]

    labels = [primary]

    for concept in extract_category_concepts(_with_hint(title, hint)):
        canonical = CATEGORY_CONCEPTS.get(concept, {}).get("canonical")
        if canonical and canonical not in labels:
            labels.append(canonical)

    # The venue's own category is kept as a secondary label - a pride picnic
    # listed by a community org is both LGBTQ and Community, and that second
    # label is the entire point of the multi-label column.
    #
    # Two exceptions, both load-bearing:
    #
    # Not when a narrow title rule overrode it. A sewing class at a music hall
    # is Arts & Crafts and nothing else; keeping Music would put it straight
    # back into "music tonight in Avondale", which is what prompted
    # `infer_category` in the first place.
    #
    # Not when it is the generic bucket and the event classified as something
    # real. "Events" means "no category known", so tagging an event
    # Music *and* Events adds a label that says nothing and spends one of the
    # three slots.
    overridden_by_title = infer_category(title, fallback) != fallback
    worth_keeping = fallback != GENERIC_CATEGORY or primary == fallback
    if fallback and not overridden_by_title and worth_keeping and fallback not in labels:
        labels.append(fallback)

    normalized = []
    for label in labels:
        clean = normalize_category(label)
        if clean and clean not in normalized:
            normalized.append(clean)
    return normalized[:MAX_CATEGORIES]


def normalize_category(value: str | None) -> str | None:
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


def category_filter(column, concepts: list[str], all_column=None):
    """A SQLAlchemy condition matching any stored category for these concepts.

    Returns None when no concept was recognized, so a caller can tell "no
    category was named" apart from "a category was named and nothing has it".

    `all_column` is the JSON array of every applicable label. Passing it makes
    an event findable under its secondary categories too - a drag show stored
    primarily as Music still answers a search for LGBTQ. Matched with LIKE on
    the quoted label, so "Arts" cannot match "Arts & Crafts".
    """
    clauses = [column.ilike(f"{prefix}%") for prefix in category_prefixes(concepts)]
    clauses += [column.ilike(label) for label in category_labels(concepts)]

    if all_column is not None:
        for concept in concepts:
            canonical = CATEGORY_CONCEPTS.get(concept, {}).get("canonical")
            # Cast because the column is JSON: on SQLite that is text
            # underneath, and the quoted label makes "Arts" unable to match
            # "Arts & Crafts".
            as_text = cast(all_column, String)
            if canonical:
                clauses.append(as_text.ilike(f'%"{canonical}"%'))
            for label in CATEGORY_CONCEPTS.get(concept, {}).get("labels", []):
                clauses.append(as_text.ilike(f'%"{label}"%'))

    if not clauses:
        return None
    return or_(*clauses)
