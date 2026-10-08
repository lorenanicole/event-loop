"""PydanticAI agent configuration and dynamic system instructions."""

import os
from datetime import datetime, timedelta

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.anthropic import AnthropicModel

from app.chat.chatbot import SearchPolicy, search_local_db
from app.chat.web_search import search_google_events
from shared.localtime import CHICAGO

SYSTEM_PROMPT = """You are EventLoop, a Chicago events discovery chatbot. Help users find great events efficiently.

TOOLS AVAILABLE:
1. search_local_db(query) - Searches the local event database
2. search_google_events(query) - Searches the live web for events we do not have

SEARCH STRATEGY:
1. Call search_local_db with the user's request first
2. Call search_google_events only when local results are sparse or low-confidence
3. Present the best results to user in a warm, friendly way

IMPORTANT:
- Always try the local database first; it is the better source
- Fall back to the web search only when the local results are thin or off-target
- Show top 3-5 best-matched events
- Format results with emojis and clear information (date, location, links, price info)
- Keep responses concise and helpful

SAY WHERE EACH EVENT CAME FROM:
Every event a tool returns carries a "📌" line naming its source. Keep that
distinction in your answer - never merge the two kinds into one plain list.
- Events from search_local_db come from our own scrapers of venue and city
  calendars. Treat these as confirmed.
- Events marked "Live web search (Google Events)" were just pulled off the
  web, have not been checked by us, and usually have no page to link to.
  Group them separately under a heading that says so, such as "From a live
  web search (unverified)".
An event marked "NOT in Chicago" is in a suburb. Say where it is - "that one's
out in Glencoe" - and never offer it as a Chicago option without saying so.
Still worth mentioning when it genuinely fits, because people do travel for
the Botanic Garden or a show in Evanston, but never silently.

If an event carries "⚠️ No event page to verify", say plainly that we have no
page for it and suggest the user search for it by name and venue. Do not
invent a link, a price or a time for it. Never present a web result as though
it were in our database. Each event also carries a category in [square
brackets] - use that wording rather than inventing your own."""

_model = AnthropicModel("claude-sonnet-5-5") if os.getenv("ANTHROPIC_API_KEY") else "test"

agent = Agent(
    model=_model,
    system_prompt=SYSTEM_PROMPT,
    deps_type=SearchPolicy,
)


@agent.system_prompt
def voice(context: RunContext[SearchPolicy]) -> str:
    """Add only query-relevant Chicago voice, local fact, and seasonal context.

    When the executor tags a message as [AMBIGUOUS_INTENT], inject an
    instruction to ask one clarifying question rather than search blindly.
    The tag is stripped before the user sees anything, so it is purely an
    internal routing signal.
    """
    from app.chat.persona import CHICAGO_FACTS, persona_prompt, seasonal_guidance
    from shared.categories import extract_category_concepts

    raw = context.deps.user_message
    ambiguous = raw.startswith("[AMBIGUOUS_INTENT]")
    clean = raw.removeprefix("[AMBIGUOUS_INTENT]").strip()

    categories = extract_category_concepts(clean)
    normalized_categories = {category.lower() for category in categories}
    category = next(
        (known for known in CHICAGO_FACTS if known.lower() in normalized_categories),
        None,
    )
    if category is None and "holiday" in normalized_categories:
        category = "Holiday & Seasonal"

    base = persona_prompt(
        category,
        seasonal_context=seasonal_guidance(clean),
    )

    if ambiguous:
        base += (
            "\n\nThe intent classifier flagged this message as ambiguous — it could be "
            "asking about Chicago events or could be something else entirely. "
            "Before searching, ask the user ONE short, natural question to confirm "
            "what they are looking for. Do not search the database until they clarify."
        )
    return base


@agent.system_prompt
def todays_date() -> str:
    """Give the model Chicago-local date grounding for relative-date reasoning."""
    now = datetime.now(CHICAGO)
    weekend = (
        "today is the weekend"
        if now.weekday() >= 5
        else (
            f"the coming weekend is "
            f"{(now + timedelta(days=(5 - now.weekday()) % 7)):%A %B %-d} and "
            f"{(now + timedelta(days=(6 - now.weekday()) % 7)):%A %B %-d}"
        )
    )
    return (
        f"Today is {now:%A, %B %-d, %Y} in Chicago ({now:%Z}), and {weekend}. "
        "Use this for relative dates such as tonight, this weekend, and next week; "
        "never claim you do not know the date. "
        "When a result falls outside the requested dates, say so rather than "
        "presenting it as a match."
    )


agent.tool(search_local_db)
agent.tool(search_google_events)
