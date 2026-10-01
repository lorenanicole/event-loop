"""
Intent classifier: Quickly determine if user is asking about Chicago events.
Rejects out-of-scope questions early before running expensive REACT agent.
"""

from enum import Enum
import logging
from pydantic_ai.models.anthropic import AnthropicModel

logger = logging.getLogger(__name__)


class Intent(Enum):
    """User intent classification."""
    CHICAGO_EVENTS = "chicago_events"  # "Show me concerts this weekend"
    CHICAGO_INFO = "chicago_info"  # "What's the best neighborhood?"
    EVENTS_GENERAL = "events_general"  # "Events" but not Chicago-specific
    OUT_OF_SCOPE = "out_of_scope"  # "Tell me a joke", "What's the weather?"


class IntentClassifier:
    """
    Fast intent classifier using Claude.
    One quick API call determines if question is about Chicago events.
    """

    def __init__(self):
        self.model = AnthropicModel("claude-sonnet-5-5")
        self.classifier_agent = self._build_agent()

    def _build_agent(self):
        """Build a fast intent classification agent."""
        from pydantic_ai import Agent
        from pydantic import BaseModel, Field

        class IntentResult(BaseModel):
            intent: str = Field(
                description="One of: chicago_events, chicago_info, events_general, out_of_scope"
            )
            confidence: float = Field(
                description="Confidence 0.0-1.0 that this is the correct intent"
            )
            reasoning: str = Field(description="Why we classified it this way")

        agent = Agent(
            model=self.model,
            result_type=IntentResult,
            system_prompt="""You are an intent classifier for a Chicago events chatbot.
Classify the user's message into one of these categories:

1. **chicago_events**: User asking about events/things to do in Chicago
   - Examples: "Show me concerts", "What's happening this weekend?", "Comedy shows in Chicago"

2. **chicago_info**: User asking about Chicago (but not events)
   - Examples: "What neighborhoods should I visit?", "Best pizza in Chicago?"

3. **events_general**: Asking about events but NOT Chicago-specific
   - Examples: "Where can I find events?", "Event recommendation engine"

4. **out_of_scope**: Anything else entirely
   - Examples: "Tell me a joke", "What's the weather?", "Help with Python", "Write a poem"

Be strict: If it's not clearly about Chicago events, classify as out_of_scope.
Return JSON with: intent, confidence (0.0-1.0), reasoning.""",
        )
        return agent

    async def classify(self, user_message: str) -> tuple[Intent, float, str]:
        """
        Classify user intent.
        Returns: (intent, confidence, reasoning)
        """
        try:
            result = await self.classifier_agent.run(user_message)

            intent_str = result.data.intent.lower()
            intent_map = {
                "chicago_events": Intent.CHICAGO_EVENTS,
                "chicago_info": Intent.CHICAGO_INFO,
                "events_general": Intent.EVENTS_GENERAL,
                "out_of_scope": Intent.OUT_OF_SCOPE,
            }

            intent = intent_map.get(intent_str, Intent.OUT_OF_SCOPE)
            confidence = result.data.confidence
            reasoning = result.data.reasoning

            logger.info(
                f"Intent: {intent.value} (confidence: {confidence:.2f}) - {reasoning[:60]}"
            )
            return intent, confidence, reasoning

        except Exception as e:
            logger.error(f"Intent classification error: {e}")
            # Default to chicago_events on error (fail open for events)
            return Intent.CHICAGO_EVENTS, 0.5, f"Classification error: {str(e)}"


# Singleton instance
_classifier_instance = None


def get_intent_classifier() -> IntentClassifier:
    """Get or create the singleton intent classifier."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = IntentClassifier()
    return _classifier_instance


async def get_intent_response(intent: Intent, reasoning: str) -> str:
    """Get a friendly response for out-of-scope intents."""

    responses = {
        Intent.OUT_OF_SCOPE: (
            f"🎭 Interesting question! But I'm specifically built to help find Chicago events. "
            f"Try asking me about concerts, theater, sports, food events, or things to do this weekend!\n\n"
            f"💡 **Examples I can help with:**\n"
            f"• \"What's happening this weekend?\"\n"
            f"• \"Show me free events in Chicago\"\n"
            f"• \"Jazz concerts this month\"\n"
            f"• \"Family-friendly activities\""
        ),
        Intent.EVENTS_GENERAL: (
            f"🎯 Great question, but I'm specifically designed for **Chicago events**. "
            f"Try asking me what's happening in the city this weekend!"
        ),
        Intent.CHICAGO_INFO: (
            f"📍 I'd love to help with that, but I'm specifically built for finding **Chicago events**. "
            f"For neighborhood tips or general Chicago info, try a search engine. "
            f"But ask me about events and I'm your bot! 🎪"
        ),
        Intent.CHICAGO_EVENTS: (
            f"🎉 Found it! I'm ready to help you discover Chicago events."
        ),
    }

    return responses.get(
        intent,
        "🎭 I'm not sure how to help with that. I'm a Chicago event finder! "
        "Ask me about concerts, shows, or things to do this weekend.",
    )
