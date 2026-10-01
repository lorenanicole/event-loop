import os
import logging
import httpx
import asyncio
from pathlib import Path
from dotenv import load_dotenv
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

try:
    from nltk.corpus import wordnet
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

# Load .env before using environment variables
_env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_env_path)

logger = get_logger(__name__)

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DB_RESULT_THRESHOLD = 5  # Minimum results before using SerpAPI

class EventResult(BaseModel):
    title: str
    date: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    source: str

    class Config:
        extra = "ignore"  # Ignore extra fields from API responses


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
    category: Optional[str] = None
    details: Optional[str] = None
    cost: Optional[str] = None
    age_range: Optional[str] = None
    is_outdoor: Optional[str] = None
    address: Optional[str] = None
    confidence: float = Field(description="Relevance score 0.0-1.0")


class AgentAction(BaseModel):
    """Union type for all agent actions in the REACT loop."""
    action: Union[ToolCallAction, ToolResultAction, FinalResponse] = Field(
        discriminator="action_type",
        description="One of: tool_call, tool_result, response"
    )


async def search_local_db(context: RunContext[str], query: str) -> str:
    """Search local database for events (FREE - no API cost)"""
    logger.info(f"search_local_db called with query: {query}")
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

            # Check confidence - if average < 0.4, suggest Google search
            avg_confidence = sum(e.confidence for e in top_events) / len(top_events)
            if avg_confidence < 0.4:
                return "LOW_CONFIDENCE_LOCAL_RESULTS"

            # Build response with event details
            results_text = f"📍 **Found {len(top_events)} great match{'es' if len(top_events) != 1 else ''}:**\n\n"
            for i, event in enumerate(top_events, 1):
                # Category label
                category_tag = f" `{event.category}`" if event.category else ""
                results_text += f"{i}. **{event.title}**{category_tag}\n"

                # Date
                results_text += f"   📅 {event.date}\n"

                # Address if available
                if event.address:
                    results_text += f"   📍 {event.address}\n"

                # Outdoor/Indoor designation
                if event.is_outdoor:
                    outdoor_emoji = "🌳" if event.is_outdoor == "outdoor" else "🏢"
                    results_text += f"   {outdoor_emoji} {event.is_outdoor.capitalize()}\n"

                # Cost and age range
                if event.cost or event.age_range:
                    details_parts = []
                    if event.cost:
                        details_parts.append(f"💰 {event.cost}")
                    if event.age_range:
                        details_parts.append(f"👥 {event.age_range}")
                    results_text += f"   {' | '.join(details_parts)}\n"

                # Source/Location
                if event.source:
                    results_text += f"   📌 {event.source}\n"

                # Summary
                if event.details:
                    results_text += f"   📝 {event.details}\n"

                # Clickable link
                if event.url:
                    results_text += f"   🔗 [View Event]({event.url})\n"

                results_text += "\n"

            return results_text

    except Exception as e:
        logger.error(f"DB search error: {e}")
        return "NO_RESULTS"


async def _persist_events_to_db(events: list[EventResult]) -> None:
    """Background task: persist external events to DB (non-blocking) with retry."""
    if not events:
        return

    max_retries = 3
    retry_delay = 0.5

    for attempt in range(max_retries):
        try:
            await asyncio.sleep(retry_delay)
            async with AsyncSessionLocal() as db:
                persisted_count = 0
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
                    except (ValueError, AttributeError, TypeError):
                        event_date = datetime.now() + timedelta(days=30)

                    new_event = EventModel(
                        name=event.title,
                        date=event_date,
                        address=event.location,
                        category="Online Search",
                        origination_url=event.url,
                        source="SerpAPI",
                    )
                    db.add(new_event)
                    persisted_count += 1

                if persisted_count > 0:
                    await db.commit()
                    logger.info(f"✅ Persisted {persisted_count} external events to DB")
                else:
                    logger.info(f"No new events to persist (all {len(events)} already existed)")
                return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                retry_delay *= 2
                logger.warning(f"DB locked (attempt {attempt + 1}/{max_retries}), retrying...")
            else:
                logger.error(f"❌ Failed to persist events: {e}", exc_info=True)
                return


async def search_google_events(context: RunContext[str], query: str) -> str:
    """Search Google Events using SerpAPI (PAID - only if DB has few results)"""
    logger.info(f"search_google_events called with query: {query}")
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
                try:
                    # Handle address as list or string
                    address = event.get("address")
                    if isinstance(address, list):
                        address = ", ".join(address)

                    events.append(
                        EventResult(
                            title=event.get("title", "Untitled"),
                            date=event.get("date") or event.get("snippet"),
                            location=address or event.get("displayed_link"),
                            url=event.get("link", ""),
                            source="SerpAPI",
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse SerpAPI event: {e}, data: {event}")
                    continue

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
                    results_text += f"   🔗 [View Event]({event.url})\n"
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


def _truncate_summary(text: str, words: int = 10) -> str:
    """Truncate text to N words."""
    if not text:
        return ""
    return " ".join(text.split()[:words]) + ("..." if len(text.split()) > words else "")


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
            category=event.category,
            details=_truncate_summary(event.details) if event.details else None,
            cost=event.cost if hasattr(event, 'cost') else None,
            age_range=event.age_range if hasattr(event, 'age_range') else None,
            is_outdoor=event.is_outdoor if hasattr(event, 'is_outdoor') else None,
            address=event.address if hasattr(event, 'address') else None,
            confidence=_score_event_relevance(event, query, categories),
        )
        for event in events
    ]

    # Sort by confidence and return top N
    return sorted(scored, key=lambda e: e.confidence, reverse=True)[:limit]


def _extract_keywords(query: str) -> list[str]:
    """Extract search keywords with synonym expansion"""
    stop_words = {
        "the", "a", "an", "and", "or", "is", "are", "in", "on", "at",
        "this", "that", "these", "those", "what", "when", "where", "why",
        "find", "get", "search", "show", "tell", "give", "all", "want",
        "looking", "events", "event", "i", "want", "to", "for", "any"
    }

    words = query.split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    # Expand keywords with NLTK WordNet synonyms
    expanded_keywords = set(keywords)

    if NLTK_AVAILABLE:
        for kw in keywords:
            kw_lower = kw.lower()
            try:
                synsets = wordnet.synsets(kw_lower, lang='eng')
                for synset in synsets[:3]:  # Limit to top 3 synsets
                    for lemma in synset.lemmas():
                        synonym = lemma.name().replace('_', ' ')
                        if len(synonym) > 2:
                            expanded_keywords.add(synonym)
            except Exception:
                pass

    return list(expanded_keywords)[:15]


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
    logger.info(f"smart_search_expand called with query: {query}")
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


_model = AnthropicModel("claude-sonnet-5-5") if CLAUDE_API_KEY else None  # AnthropicModel wraps the model name

agent = Agent(
    model=_model or "test",
    system_prompt="""You are EventLoop, a Chicago events discovery chatbot. Help users find great events efficiently.

TOOLS AVAILABLE:
1. smart_search_expand(query) - Analyzes user intent and expands query
2. search_local_db(query) - Searches local event database (FREE)
3. search_google_events(query) - Searches Google/SerpAPI for events (PAID fallback)

SEARCH STRATEGY:
1. First, call smart_search_expand to understand what user wants
2. Then, call search_local_db with the original query
3. If local results don't look good enough, call search_google_events
4. Present the best results to user in a warm, friendly way

IMPORTANT:
- Always try local database first (no cost)
- Fall back to Google search only if local results are insufficient
- Show top 3-5 best-matched events
- Format results with emojis and clear information (date, location, links, price info)
- Keep responses concise and helpful""",
)

# Register tools with the agent
agent.tool(search_local_db)
agent.tool(search_google_events)
agent.tool(smart_search_expand)


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
