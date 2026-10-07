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


def greeting(rng: Optional[random.Random] = None) -> str:
    """The first message in a new chat.

    Short on purpose. The first draft opened with "I'll tell you what I
    actually know, and say so when I don't", which read like terms of service;
    the second ran 25 lines, said "77 community areas" in the body and then
    again in the fact two lines down, and asked what you wanted twice. A
    greeting is a hello, not a homepage.

    Sandburg earns his place - "City of the Big Shoulders" sets a register no
    amount of "I'm your AI assistant" can - and the three concrete things
    happening tonight do more than any adjective would.
    """
    picker = rng or random
    fact = picker.choice(GENERAL_FACTS)
    return f"""🏙️ **I'm {ASSISTANT_NAME}**, your guide to what's on in Chicago. Named {NAME_MEANING}.

Sandburg called this the City of the Big Shoulders. Somewhere tonight there's
a blues set on the South Side, a play in a room with sixty seats, and a street
fest nobody told you about. Ask me and I'll find it.

💡 **Try:**
• "blues tonight on the South Side"
• "free things to do in Pilsen this weekend"
• "jazz at the Green Mill this month"
• "something for the kids in Albany Park"

🗺️ *{fact}*

⚙️ **Under the hood:** {UNDER_THE_HOOD}

So - what are we doing tonight? ⚡"""
