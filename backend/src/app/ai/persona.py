"""Who the assistant is, and what it knows about Chicago.

Kept apart from the agent and the tools because it is content, not logic: the
name, the voice, and a set of facts worth telling somebody. Changing any of it
should not mean touching the search path.

The facts are keyed by the category they belong to, so an answer about blues
can mention Chess Records rather than deep-dish. A fact attached to what
somebody just asked for reads as local knowledge; the same fact at random
reads as filler.

Every fact here is checkable. A guide that makes things up is worse than one
with nothing to say, and these sit next to real event listings where a
confident invention would be taken as seriously as the listing.
"""

import random
import re
from typing import Optional

# One constant, because the name appears in the prompt, the greeting, the API
# docs and three places in the UI. Changing it should be this line.
ASSISTANT_NAME = "Loopara"

# Spoken once, in the greeting, to say what the name means. A name nobody can
# place is just a noise.
NAME_MEANING = "for the Loop, and for the event loop it runs on"

# Facts worth volunteering, by the category of event they relate to. Several
# per category so a repeated question does not get a repeated fact.
CHICAGO_FACTS: dict[str, list[str]] = {
    "Music": [
        "Chicago blues came north with the Great Migration - Chess Records at "
        "2120 S. Michigan recorded Muddy Waters and Howlin' Wolf in the 1950s.",
        "House music takes its name from the Warehouse, the South Jefferson "
        "club where Frankie Knuckles was resident DJ from 1977.",
        "The blues circuit still runs nightly - Buddy Guy's Legends, Kingston "
        "Mines and Rosa's Lounge all book seven days a week.",
        "Maxwell Street was where Delta musicians first plugged in to be heard "
        "over the market crowd, which is roughly how electric blues happened.",
    ],
    "Theater": [
        "The Second City opened in 1959, and most of what the world calls "
        "improv traces back through it.",
        "Chicago storefront theater is its own tradition - dozens of companies "
        "running in rooms of under 100 seats, which is why a Tuesday night has "
        "options.",
        "Steppenwolf began in a church basement in Highland Park in 1974, with "
        "a young John Malkovich and Gary Sinise among the founders.",
    ],
    "Arts": [
        "The Picasso in Daley Plaza, unveiled in 1967, was the city's first "
        "big piece of public art - the artist refused payment and gave it to "
        "Chicago.",
        "The city motto is Urbs in Horto, 'City in a Garden', which is also why "
        "there are over 600 parks to hold events in.",
        "Gwendolyn Brooks, who wrote from Bronzeville, was the first Black "
        "author to win a Pulitzer, in 1950.",
    ],
    "Comedy": [
        "The Second City, iO and the Annoyance all run within a few miles of "
        "each other, which is an unusual density of stages for one city.",
        "Improv's 'yes, and' rule was shaped here by Viola Spolin's theater "
        "games, taught in Chicago parks in the 1930s and 40s.",
    ],
    "Food & Drink": [
        "Deep-dish dates to 1943 at Pizzeria Uno - and locals eat thin-crust "
        "tavern style, cut into squares, far more often.",
        "The Maxwell Street Polish came off the market stalls on the Near West "
        "Side and never really left.",
    ],
    "Sports": [
        "Wrigley Field opened in 1914 and still has a hand-turned scoreboard.",
        "The Chicago Marathon runs through 29 neighborhoods, which is a decent "
        "tour of the city if you are watching rather than running.",
    ],
    "Film": [
        "Before Hollywood, Chicago was the film capital - Essanay Studios in "
        "Uptown made Charlie Chaplin pictures in 1915.",
    ],
    "Community": [
        "Chicago's 77 community areas were drawn in the 1920s by University of "
        "Chicago sociologists, and the boundaries have barely moved since.",
        "Jean Baptiste Point du Sable, a Haitian trader, settled at the mouth "
        "of the Chicago River in the 1780s as the city's first permanent "
        "non-Indigenous resident.",
    ],
    "Holiday & Seasonal": [
        "The first Ferris wheel turned in Jackson Park at the 1893 World's "
        "Columbian Exposition, built to out-do the Eiffel Tower.",
    ],
    "Tech / Educational": [
        "The world's first skyscraper, the Home Insurance Building, went up "
        "here in 1885 - steel frame, ten storeys, since demolished.",
        "The Chicago River was reversed in 1900 so it flows away from Lake "
        "Michigan instead of into the city's drinking water.",
    ],
}

# For a greeting or an answer with no particular category.
GENERAL_FACTS: list[str] = [
    "The Loop is named for the elevated tracks that circle it, completed in 1897.",
    "The four red stars on the flag are Fort Dearborn, the Great Fire of 1871, "
    "the 1893 World's Columbian Exposition and the 1933 Century of Progress.",
    "'Windy City' is usually said to be about boastful politicians rather than "
    "the weather, though the lake does its part.",
    "Chicago has 77 community areas and well over 200 named neighborhoods, "
    "which is why 'where in Chicago' is a real question.",
]


def fact_for(category: Optional[str] = None, rng: Optional[random.Random] = None) -> str:
    """A Chicago fact, matched to a category where one exists."""
    picker = rng or random
    pool = CHICAGO_FACTS.get(category or "", []) or GENERAL_FACTS
    return picker.choice(pool)


def persona_prompt() -> str:
    """How the assistant should sound, as a system prompt fragment.

    Deliberately specific about when NOT to add colour. A guide that comments
    on everything stops being useful, and the thing somebody asked for - what
    is on, where, and what it costs - has to come first.
    """
    return f"""
YOUR VOICE:
You are {ASSISTANT_NAME}, a Chicago events guide - {NAME_MEANING}. You have
lived here a long time and you are genuinely pleased somebody asked. Warm,
direct, a bit of swagger. Say "we" about the city. Sound like a friend with
opinions, not a brochure and not a search engine.

Warm does not mean padded. "Rosa's is a small room and the sets run late" is
warmth; "What a fantastic choice!" is not.

Chicago knowledge is what you add that a listings site cannot:
- Place an event. "Thalia Hall went up as a public hall in 1892" or "those
  three venues are a walk apart on Milwaukee" is worth more than a sentence
  of enthusiasm.
- Volunteer one fact, at most, when it genuinely fits what was asked. A blues
  question can hear about Chess Records; it should not also hear about
  deep-dish.
- Use the city's own frame: the L and which line, the neighborhood rather than
  the street address, North and South Side, lakefront, the Loop.
- When you have nothing specific, say nothing. Filler is worse than brevity.
- Never invent a fact, a date, a venue or a price. If you are not certain,
  leave it out - you sit next to real listings, and a confident invention will
  be believed. Being straight about what you do not have is part of the voice,
  not an apology for it.

The answer comes first and the colour second. Someone asking what is on
tonight wants the events, with dates, neighborhoods and prices; one line of
local context after that is a gift, and three paragraphs of it is noise.

When you suggest what else they could ask, make the suggestions Chicago
specific - a neighborhood, a venue, an L line, a scene - rather than generic
categories.
""".strip()


# What the thing is built out of. Kept in the greeting on purpose: this is a
# Python 3.15 showcase as much as an events app, and the stack is part of why
# anybody is looking at it. It goes last, though - somebody who opened a chat
# to find a show should meet the guide before the architecture.
# What the thing is built out of. Kept on purpose: this is a Python 3.15
# showcase as much as an events app, and the stack is part of why anybody is
# looking at it. One line rather than five bullets, though - as a list it was
# a third of the greeting, and the greeting is a hello.
UNDER_THE_HOOD = (
    "Python 3.15, a ReAct agent on PydanticAI, semantic search over static "
    "model2vec embeddings, point-in-polygon neighborhood lookup, and replies "
    "streamed over SSE."
)


def reads_like_a_title(name: str) -> bool:
    """Whether a stored name is worth putting in a greeting.

    Stricter than `_looks_like_an_event`, which decides whether to store a row
    at all. This decides whether to lead with it, so a scrape artefact that is
    harmless in a list is disqualifying here: the first draft opened with
    "Closed in Lincoln Park" and "doing our literal speed in Woodlawn", which
    are a venue status and a sentence fragment.

    Wants a short title of at least two words that starts like a title and is
    not obviously a price, a fragment or a status.
    """
    name = (name or "").strip()
    if not (4 <= len(name) <= 44):
        return False
    if name[0] in "$(&\"'":                       # a price or a fragment
        return False
    if len(name.split()) < 2:                     # "Closed", "Cancelled"
        return False
    if not (name[0].isalpha() or name[0].isdigit()):
        return False
    # Starts mid-sentence: a real title does not begin with a verb participle
    # or a conjunction.
    if re.match(r"^(and|but|or|doing|featuring|with|plus|see|click)\b", name, re.I):
        return False
    if re.search(r"\b(closed|cancelled|canceled|sold out|tba|tbd|multiple days"
                 r"|coming soon|more info)\b", name, re.I):
        return False
    return True


async def whats_on_tonight(
    session, limit: int = 3, rng: Optional[random.Random] = None
) -> list[tuple[str, str]]:
    """A few real things happening soon, phrased for the greeting.

    Pulled from the database rather than written down, because the invented
    version ("a blues set on the South Side, a play in a room with sixty
    seats") was describing a city rather than this city tonight - and the
    whole point of the app is that it knows.
    """
    from sqlalchemy import select

    from shared.database.filters import feed_order, upcoming_events_filter
    from shared.database.models import EventModel, NeighborhoodModel

    rows = (await session.execute(
        select(EventModel.name, EventModel.category, NeighborhoodModel.name)
        .outerjoin(NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id)
        .filter(upcoming_events_filter())
        # A title that is a price or a sentence reads badly in a greeting.
        .filter(EventModel.name.isnot(None))
        .order_by(*feed_order())
        .limit(60)
    )).all()

    # How to pitch each kind of evening, and the order to offer them in.
    # A bare list of three titles ("Coming up: X; Y; Z") told you what was on
    # without telling you why you'd care - these lead with the appetite and
    # put a real event behind it, which is the thing a listings site cannot
    # do. Conferences and civic meetings are left out: real events, but not
    # the hook.
    PITCHES = [
        ("Comedy", "Want comedy?"),
        ("Music", "After live music?"),
        ("Theater", "In the mood for theater?"),
        ("Holiday & Seasonal", "Something seasonal?"),
        ("Arts", "Fancy a gallery?"),
        ("Film", "Film more your thing?"),
        ("Food & Drink", "Eating out?"),
        ("Festival", "Out in the street?"),
    ]
    APPEALING = tuple(category for category, _ in PITCHES)

    candidates: dict[str, list[str]] = {}
    for name, category, hood in rows:
        name = (name or "").strip()
        if category not in APPEALING:
            continue
        if not reads_like_a_title(name):
            continue
        label = name + (f" in {hood}" if hood else "")
        candidates.setdefault(category, []).append(label)

    # One per category so three picks are three different kinds of evening,
    # and shuffled so reopening the chat does not show the same three.
    picker = rng or random
    picks = []
    for category, pitch in PITCHES:
        options = candidates.get(category)
        if options:
            picks.append((pitch, picker.choice(options)))
        if len(picks) >= limit:
            break
    return picks


def greeting(
    rng: Optional[random.Random] = None,
    tonight: Optional[list[tuple[str, str]]] = None,
) -> str:
    """The first message in a new chat.

    Fourth pass, and the earlier ones are worth recording because each was
    wrong in a different way: it opened with a disclaimer; then ran 25 lines
    and said "77 community areas" twice; then hard-wrapped its prose so
    sentences broke mid-clause at panel width; then listed three event titles
    under "Coming up:", which said what was on without saying why anyone would
    care.

    It now leads with an appetite and puts a real event behind it - "Want
    comedy? Best of The Second City in Old Town" - because that is the thing a
    listings page cannot do. Sandburg is not named: "City of Big Shoulders" is
    the part people know, and attributing it adds a stranger to the opening
    sentence.
    """
    picker = rng or random
    fact = picker.choice(GENERAL_FACTS)

    if tonight:
        offers = " ".join(f"{pitch} **{event}**." for pitch, event in tonight)
        opener = (
            "They call this the City of Big Shoulders, and there's always "
            f"something on. {offers}"
        )
    else:
        opener = (
            "They call this the City of Big Shoulders, and there's always "
            "something on - a few thousand things across the city over the "
            "next few weeks."
        )

    return f"""🏙️ **I'm {ASSISTANT_NAME}**, your guide to what's on in Chicago. Named {NAME_MEANING}.

{opener}

💡 **So - what are you after?** Ask me like you'd ask a friend:
• "blues tonight on the South Side"
• "free things to do in Pilsen this weekend"
• "jazz at the Green Mill this month"
• "something for the kids in Albany Park"

🗺️ ***Did you know?** {fact}*

⚙️ **Under the hood:** {UNDER_THE_HOOD}"""


def farewell(reason: str = "turns", rng: Optional[random.Random] = None) -> str:
    """What to say when the conversation's budget runs out.

    There was nothing here, and it showed: the chat simply stopped accepting
    input behind a grey status chip reading "token limit reached", which is
    both jargon and - when the turn limit was what ran out - the wrong
    jargon. Ending a conversation without saying why or what to do next reads
    as a fault rather than a limit.

    Said in the assistant's own voice as a message, not a system notice,
    because the assistant is who the person was talking to.
    """
    why = {
        "turns": "that's all the questions I can take in one go",
        "tokens": "I've used up what I can say in one conversation",
    }.get(reason, "that's my limit for one conversation")

    return (
        f"\U0001F44B **Well, that's all the time I've got** - {why}. "
        "I keep conversations short so everyone gets a turn.\n\n"
        "Still need the 311 on Chicago? Hit **New Chat** and we'll pick it up "
        "fresh - though you'll have to catch me up, since I won't remember "
        "this one.\n\n" + sign_off(rng)
    )

# The four six-pointed stars of the Chicago flag, which is also the app's own
# logo. Drawn in text rather than shipped as an image so it survives anywhere
# the message is rendered - the chat bubble, a log, a copy-paste.
FLAG_STARS = "\u2736 \u2736 \u2736 \u2736"

# Rotating sign-offs. All local, none requiring you to pick a baseball team -
# the North/South rivalry is real and a farewell is the wrong place to take a
# side.
SIGN_OFFS = [
    "Doors closing.",                       # the CTA announcement, verbatim
    "See you on the L.",
    "Keep it between the lake and the expressway.",
    "Stay warm out there.",
    "Mind the gap at Clark and Lake.",
    "Go do something. It's a good city for it.",
]


def sign_off(rng: Optional[random.Random] = None) -> str:
    """A small visual goodbye: the flag's four stars and a local line."""
    picker = rng or random
    return f"{FLAG_STARS}\n\n*{picker.choice(SIGN_OFFS)}*"

