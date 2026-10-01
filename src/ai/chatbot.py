import os
import logging
import httpx
import asyncio
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from sqlalchemy import and_, or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from typing import Optional, Union, Literal
from src.database import AsyncSessionLocal
from src.database.models import EventModel
from src.ai.smart_search import get_smart_search_tool
from src.logging import get_logger

logger = get_logger(__name__)

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DB_RESULT_THRESHOLD = 5  # Minimum results before using SerpAPI


class EventResult(BaseModel):
    title: str
    date: str
    location: Optional[str] = None
    url: Optional[str] = None
    source: str


class ToolCallAction(BaseModel):
    """Agent action: call a tool with arguments."""
    action_type: Literal["tool_call"] = Field(default="tool_call", description="Always 'tool_call'")
    tool: str = Field(description="Tool name: 'search_local_db' or 'search_google_events'")
    args: dict = Field(description="Tool arguments")


class ToolResultAction(BaseModel):
    """Agent observation: received tool results."""
    action_type: Literal["tool_result"] = Field(default="tool_result", description="Always 'tool_result'")
    tool: str = Field(description="Which tool was executed")
    found: int = Field(description="Number of results found")
    events: list[EventResult] = Field(description="The events/results")


class FinalResponse(BaseModel):
    """Agent response: final message to user."""
    action_type: Literal["response"] = Field(default="response", description="Always 'response'")
    message: str = Field(description="The response text to show user")
    context: str = Field(description="Context about what was searched/found")
    tokens: int = Field(description="Estimated tokens used")


class ScoredEvent(BaseModel):
    """Event with relevance confidence score."""
    title: str
    date: str
    location: Optional[str] = None
    url: Optional[str] = None
    source: str
    confidence: float = Field(description="Relevance score 0.0-1.0")


class AgentAction(BaseModel):
    """Union type for all agent actions in the REACT loop."""
    action: Union[ToolCallAction, ToolResultAction, FinalResponse] = Field(
        discriminator="action_type",
        description="One of: tool_call, tool_result, response"
    )


async def search_local_db(context: RunContext[str], query: str) -> str:
    """Search local database for events (FREE - no API cost)"""
    try:
        async with AsyncSessionLocal() as db:
            query_str = query.lower()

            keywords = _extract_keywords(query_str)
            categories = _extract_categories(query_str)
            date_range = _extract_date_range(query_str)

            db_query = select(EventModel)
            filters = []

            if keywords:
                keyword_conditions = [EventModel.name.ilike(f"%{kw}%") for kw in keywords]
                filters.append(or_(*keyword_conditions))

            if categories:
                category_conditions = [EventModel.category.ilike(cat) for cat in categories]
                filters.append(or_(*category_conditions))

            if filters:
                db_query = db_query.filter(or_(*filters))

            if date_range:
                start_date, end_date = date_range
                db_query = db_query.filter(
                    and_(
                        EventModel.date >= start_date,
                        EventModel.date <= end_date,
                    )
                )

            result = await db.execute(db_query.limit(50))
            results = result.scalars().all()

            if not results:
                return "NO_RESULTS"

            # Score and filter to top 5 most relevant events
            top_events = _filter_top_results(results, query, limit=5)

            if not top_events:
                return "NO_RESULTS"

            # Build response with confidence indicators
            results_text = f"📍 **Found {len(top_events)} great match{'es' if len(top_events) != 1 else ''}:**\n\n"
            for i, event in enumerate(top_events, 1):
                confidence_bar = "🟢" if event.confidence >= 0.7 else "🟡" if event.confidence >= 0.5 else "🔵"
                results_text += f"{i}. **{event.title}** {confidence_bar}\n"
                results_text += f"   📅 {event.date}\n"
                if event.source:
                    results_text += f"   📌 {event.source}\n"
                if event.url:
                    results_text += f"   🔗 {event.url}\n"
                results_text += "\n"

            return results_text

    except Exception as e:
        logger.error(f"DB search error: {e}")
        return "NO_RESULTS"


async def _persist_events_to_db(events: list[EventResult]) -> None:
    """Background task: persist external events to DB (non-blocking)."""
    try:
        async with AsyncSessionLocal() as db:
            for event in events:
                if not event.url:
                    continue

                result = await db.execute(
                    select(EventModel).filter_by(origination_url=event.url)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    continue

                try:
                    event_date = datetime.fromisoformat(event.date.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    event_date = datetime.now() + timedelta(days=30)

                new_event = EventModel(
                    name=event.title,
                    date=event_date,
                    location=event.location,
                    category="Online Search",
                    origination_url=event.url,
                    source="SerpAPI",
                )
                db.add(new_event)

            await db.commit()
            logger.info(f"Persisted {len(events)} external events to DB")
    except Exception as e:
        logger.error(f"Failed to persist events: {e}")


async def search_google_events(context: RunContext[str], query: str) -> str:
    """Search Google Events using SerpAPI (PAID - only if DB has few results)"""
    try:
        if not SERPAPI_KEY:
            return "SerpAPI not configured"

        logger.info(f"Falling back to SerpAPI for: {query}")

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google",
                    "q": f"{query} events",
                    "location": "Chicago, Illinois, United States",
                    "google_domain": "google.com",
                    "api_key": SERPAPI_KEY,
                },
            )
            response.raise_for_status()
            data = response.json()

            events = []
            # Try event_results first, fallback to organic results
            results = data.get("events_results", []) or data.get("organic_results", [])
            for event in results[:10]:
                events.append(
                    EventResult(
                        title=event.get("title", "Untitled"),
                        date=event.get("date", "Unknown date") if "date" in event else event.get("snippet", "Unknown date"),
                        location=event.get("address", event.get("displayed_link", "Unknown location")),
                        url=event.get("link", ""),
                        source="SerpAPI",
                    )
                )

            if not events:
                return "No additional events found online"

            # Fire async DB persistence task (non-blocking)
            try:
                asyncio.create_task(_persist_events_to_db(events))
            except RuntimeError:
                logger.warning("Could not create background task for event persistence")

            results_text = f"🌐 **Online Search** - Found {len(events)} events:\n\n"
            for i, event in enumerate(events, 1):
                results_text += f"{i}. **{event.title}**\n"
                results_text += f"   📅 {event.date}\n"
                if event.location:
                    results_text += f"   📍 {event.location}\n"
                if event.url:
                    results_text += f"   🔗 {event.url}\n"
                results_text += "\n"

            return results_text

    except httpx.HTTPError as e:
        logger.error(f"SerpAPI error: {e}")
        return "Could not search online (API error)"
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Error: {str(e)}"


def _score_event_relevance(event: EventModel, query: str, query_categories: list[str]) -> float:
    """
    Score event relevance to query (0.0-1.0).
    Combines keyword matching, category match, and date proximity.
    """
    score = 0.0
    query_lower = query.lower()

    # Keyword matching (0-0.4)
    keywords = _extract_keywords(query_lower)
    event_text = f"{event.name} {event.category or ''}".lower()
    matching_keywords = sum(1 for kw in keywords if kw in event_text)
    score += min(0.4, (matching_keywords / max(len(keywords), 1)) * 0.4)

    # Category match (0-0.3)
    if event.category and query_categories:
        if event.category.lower() in [c.lower() for c in query_categories]:
            score += 0.3

    # Date proximity (0-0.3)
    # Recent events score higher
    now = datetime.now()
    if event.date >= now:
        days_away = (event.date - now).days
        if days_away <= 7:
            score += 0.3  # This week = high score
        elif days_away <= 30:
            score += 0.2  # This month = medium
        else:
            score += 0.1  # Future = low

    return min(1.0, score)


def _filter_top_results(events: list[EventModel], query: str, limit: int = 5) -> list[ScoredEvent]:
    """
    Score and filter events to top N results by relevance.
    Returns only high-confidence matches to avoid overwhelming user.
    """
    categories = _extract_categories(query)

    scored = [
        ScoredEvent(
            title=event.name,
            date=event.date.strftime('%a, %b %d, %Y @ %I:%M %p'),
            location=None,
            url=event.origination_url,
            source=event.source or "Local DB",
            confidence=_score_event_relevance(event, query, categories),
        )
        for event in events
    ]

    # Sort by confidence and return top N
    return sorted(scored, key=lambda e: e.confidence, reverse=True)[:limit]


def _extract_keywords(query: str) -> list[str]:
    """Extract search keywords"""
    stop_words = {
        "the", "a", "an", "and", "or", "is", "are", "in", "on", "at",
        "this", "that", "these", "those", "what", "when", "where", "why",
        "find", "get", "search", "show", "tell", "give", "all", "want",
        "looking", "events", "event", "i", "want", "to", "for"
    }
    words = query.split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    return keywords[:5]


def _extract_categories(query: str) -> list[str]:
    """Extract event categories"""
    category_keywords = {
        "music": ["music", "concert", "band", "dj", "acoustic", "jazz"],
        "comedy": ["comedy", "stand-up", "standup", "laugh"],
        "theater": ["theater", "theatre", "play", "drama", "broadway"],
        "sports": ["sports", "game", "match", "tournament", "athletic"],
        "art": ["art", "gallery", "exhibition", "installation"],
        "food": ["food", "dining", "restaurant", "chef", "cooking"],
        "film": ["film", "movie", "cinema", "screening"],
    }
    found = []
    for category, keywords in category_keywords.items():
        if any(kw in query for kw in keywords):
            found.append(category)
    return found


async def smart_search_expand(context: RunContext[str], query: str) -> str:
    """Expand user query with synonyms and extract intent using NLP (FREE)"""
    try:
        tool = get_smart_search_tool()
        result = await tool.query_expansion_and_search(query)

        output = f"🧠 **Smart Query Analysis**\n\n"
        output += f"**Original:** {result['user_query']}\n"
        output += f"**Expanded:** {result['query_expansion']['expanded']}\n\n"

        if result['intent']['categories']:
            output += f"📂 **Categories:** {', '.join(result['intent']['categories'])}\n"
        if result['intent']['time_frame']:
            output += f"📅 **Timeframe:** {result['intent']['time_frame']}\n"
        if result['intent']['vibe']:
            output += f"✨ **Vibe:** {result['intent']['vibe']}\n"

        output += f"\n💡 **Recommendation:** Search for: '{result['recommendation']['search_with']}'\n"
        return output

    except Exception as e:
        logger.error(f"Smart search error: {e}")
        return f"Error analyzing query: {str(e)}"


def _extract_date_range(query: str) -> Optional[tuple[datetime, datetime]]:
    """Extract date range from query"""
    now = datetime.now()
    query_lower = query.lower()

    if "this weekend" in query_lower:
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        saturday = now + timedelta(days=days_until_saturday)
        sunday = saturday + timedelta(days=1)
        return (saturday, sunday.replace(hour=23, minute=59, second=59))

    if "this week" in query_lower:
        end_of_week = now + timedelta(days=7)
        return (now, end_of_week)

    if "this month" in query_lower:
        end_of_month = now.replace(day=1) + timedelta(days=32)
        end_of_month = end_of_month.replace(day=1) - timedelta(days=1)
        return (now, end_of_month.replace(hour=23, minute=59, second=59))

    if "next week" in query_lower:
        start = now + timedelta(days=7)
        end = start + timedelta(days=7)
        return (start, end)

    if "tonight" in query_lower or "today" in query_lower:
        end = now.replace(hour=23, minute=59, second=59)
        return (now, end)

    return None


_model = AnthropicModel("claude-sonnet-5-5") if CLAUDE_API_KEY else None

agent = Agent(
    model=_model or "test",
    system_prompt="""You are EventLoop, a Chicago events discovery chatbot. Help users find great events efficiently.

AVAILABLE TOOLS (all return markdown-formatted text):
- smart_search_expand(query) → Analyzes query intent, extracts categories/timeframe/vibe
- search_local_db(query) → Searches local DB, returns "Found N events" or "NO_RESULTS"
- search_google_events(query) → Searches Google/SerpAPI, returns event details or "SerpAPI not configured"

DECISION LOGIC:
1. Call smart_search_expand(original_query) - analyze what user wants
2. Call search_local_db(query) with the analyzed query
   - If "Found N events" where N >= 3: Use these results, skip step 3
   - If found 1-2 events: Include them, continue to step 3 for more
   - If "NO_RESULTS": Continue to step 3
3. If needed, call search_google_events(query) to fill gaps
   - Auto-persists new events to DB (async, non-blocking)
4. Format final response with top 3-5 events

OUTPUT FORMAT (markdown with emojis):
✅ Success: "🎉 Found **3 great matches** for [user_request]!"
   Then list: **Event Name** 🎸 | 📅 Date | 📌 Location | 🔗 Link
   Add context about what you searched for

❌ No results: "I searched for [what you asked] but couldn't find anything right now. Try [suggestions]?"

RESPONSE RULES:
- Top results first (sorted by relevance/date)
- Include title, date, location, source/link
- Keep responses under 200 words
- Be warm and enthusiastic about events
- If zero results, suggest similar searches

COST CONTROL:
- Prefer local DB (FREE) over SerpAPI (PAID)
- Stop searching once you have 3+ good matches""",
    tools=[smart_search_expand, search_local_db, search_google_events],
)


async def chat(user_message: str) -> str:
    """
    Process user message using REACT flow with structured outputs.
    Returns formatted response text (ChatExecutor handles event streaming).
    """
    try:
        # Run agent with structured output constraint
        result = await agent.run(
            user_message,
            # Note: PydanticAI will return structured action objects
        )

        # Parse the agent's structured output
        if isinstance(result.data, str):
            # Fallback: agent returned plain text
            return result.data

        # Agent returned structured AgentAction - extract response
        if hasattr(result.data, 'action'):
            action = result.data.action
            if isinstance(action, FinalResponse):
                return f"{action.message}\n\n_Context: {action.context} ({action.tokens} tokens)_"

        return str(result.data)

    except Exception as e:
        logger.error(f"Chatbot error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"
