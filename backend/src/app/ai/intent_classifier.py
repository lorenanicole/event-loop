"""
Intent classifier: Quickly determine if user is asking about Chicago events.
Rejects out-of-scope questions early before running expensive REACT agent.
"""

import logging
from enum import Enum

from pydantic_ai.models.anthropic import AnthropicModel

logger = logging.getLogger(__name__)


class Intent(Enum):
    """User intent classification."""

    CHICAGO_EVENTS = "chicago_events"  # "Show me concerts this weekend"
    CHICAGO_INFO = "chicago_info"  # "What's the best neighborhood?"
    EVENTS_GENERAL = "events_general"  # "Events" but not Chicago-specific
    OUT_OF_SCOPE = "out_of_scope"  # "Tell me a joke", "What's the weather?"
    FAREWELL = "farewell"  # "Thanks, bye!", "That's it", "I'm done"


class IntentClassifier:
    """What a message is *doing*, decided in one quick Claude call.

    This is intent classification - dialogue acts - and deliberately not
    sentiment analysis, which is a tempting but wrong frame for it. Sentiment
    measures polarity; this asks what the message is for. The two come apart
    constantly at the farewell boundary:

        "👍"                                positive  -> farewell
        "no worries, I'll figure it out"    neutral   -> farewell
        "cool cool cool"                    positive  -> farewell
        "appreciate it - anything cheaper?" positive  -> NOT farewell
        "ugh, nothing good on then?"        negative  -> NOT farewell

    Two positives on opposite sides and a negative that is still a request:
    polarity cannot separate them, and a sentiment model would end
    conversations on a cheerful follow-up and keep going through a flat "k".

    Nor is it keyword matching. That was tried for farewells and lasted one
    round: a regex caught "bye" and "thanks" and missed "I'm done", and a
    phrase list is never finished. The model now judges "aight imma head out",
    "merci!" and a bare thumbs-up without any of them being written down.
    """

    def __init__(self):
        self.model = AnthropicModel("claude-sonnet-5-5")
        self.classifier_agent = self._build_agent()

    def _build_agent(self):
        """Build a fast intent classification agent."""
        from pydantic_ai import Agent

        agent = Agent(
            model=self.model,
            system_prompt="""You are a precise intent classifier for a Chicago events chatbot.
Classify the user's message into ONE of these categories:

1. **chicago_events**: User asking about events/activities in Chicago
   - EXPLICIT: "Show me concerts in Chicago", "What's happening in Chicago this weekend?"
   - IMPLICIT: "What's happening tonight?", "Show me free events this weekend"
     (Implicit = context suggests Chicago events, even if Chicago not mentioned)
   - Confidence: 0.95+ if explicit, 0.85+ if implicit context is clear

   - FOLLOW-UP: a short question continuing an events conversation is still
     chicago_events, even when its own words look like something else.
     "what about food?" after a list of venues means food events nearby, not
     restaurant reviews. When a conversation is given, weigh it heavily.
2. **chicago_info**: User asking about Chicago itself (NOT events)
   - Examples: "Best neighborhoods?", "Where's the best pizza?", "Tell me about Chicago"
   - Confidence: 0.90+

3. **events_general**: Generic event questions unrelated to Chicago
   - Examples: "How do I find events?", "Tell me about event planning"
   - Confidence: 0.80+

4. **farewell**: The user is finished and not asking for anything else.
   - Decide this from the message as a whole, not from any set of words.
     Ask yourself: are they closing the conversation, or still looking for
     something? Thanks, a sign-off, a note that they have what they needed,
     or a polite decline are all ways of being done, and people phrase it
     however they like - terse, warm, slangy, abbreviated.
   - The examples below are illustrations, not a list to match against.
     "Thanks, bye!", "that's everything I needed", "k thx", "nah I'm good".
     Something phrased unlike any of these is still a farewell if the person
     is done.
   - Still asking means NOT farewell, however polite the wrapping: "I'm done
     with theater, what about music?" and "thanks, any more in Pilsen?" are
     both chicago_events. A question mark is a strong signal they want more,
     but judge the intent rather than the punctuation.
   - Confidence: 0.90+ when the message is only a sign-off
5. **out_of_scope**: Unrelated to Chicago or events
   - Examples: "Tell me a joke", "What's the weather?", "Help with Python"
   - Confidence: 0.99 (should be very certain)

DECISION RULES, in order. Stop at the first that applies:
- If the user is done rather than asking → farewell. Check this FIRST, and
  judge it from the message, not from a vocabulary. Someone ending a
  conversation is not asking an off-topic question: answering "bye" with a
  description of what this bot is for is a strange thing to do, and that is
  what used to happen.
- If question is about events AND location is Chicago (explicit or implicit) → chicago_events
- If question is about Chicago but NOT events → chicago_info
- If question is about events but NOT Chicago → events_general
- Otherwise → out_of_scope
- When in doubt, lean toward chicago_events (this is a Chicago events bot)

RESPONSE FORMAT:
Return ONLY raw JSON object (no markdown, no code fences):
{
  "intent": "chicago_events|chicago_info|events_general|farewell|out_of_scope",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}""",
        )
        return agent

    async def classify(
        self, user_message: str, recent: list[str] | None = None
    ) -> tuple[Intent, float, str]:
        """Classify user intent, in the context of the conversation so far.

        `recent` is the last few messages. Without them a follow-up is judged
        on its own words and gets this wrong: mid-way through planning an
        evening, "what recommendations for food do we have in Wicker?" was
        classified as a restaurant question and answered with "I'm
        specifically built for finding Chicago events" - in a conversation
        that was already about Chicago events, and when the database has
        Food & Drink listings for that very neighborhood.

        Returns: (intent, confidence, reasoning)
        """
        try:
            import json

            prompt = user_message
            if recent:
                # The conversation is what makes "what about food?" an events
                # question rather than a restaurant one.
                context = "\n".join(recent[-4:])
                prompt = (
                    f"Conversation so far:\n{context}\n\n"
                    f"Classify ONLY this latest message: {user_message}"
                )

            # Run agent - it returns JSON text per system prompt
            result = await self.classifier_agent.run(prompt)

            # AgentRunResult has .output attribute with the model's response
            if hasattr(result, "output"):
                result_text = str(result.output).strip()
            elif hasattr(result, "data"):
                result_text = str(result.data).strip()
            else:
                result_text = str(result).strip()

            # Strip markdown code fences if present (agent returns ```json {...}```)
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                # Remove language identifier if present (e.g., "json")
                if result_text.startswith(("json", "python", "yaml")):
                    result_text = result_text.split("\n", 1)[1]

            result_text = result_text.strip()

            if not result_text:
                logger.warning(f"Empty response from intent classifier for: {user_message[:50]}")
                return Intent.CHICAGO_EVENTS, 0.5, "Empty classifier response"

            # Parse JSON response
            data = json.loads(result_text)

            intent_str = data.get("intent", "out_of_scope").lower()
            # Built from the enum rather than written out. The hand-written
            # map was missing "farewell" after it was added, so the model
            # returned it correctly and this quietly turned it into
            # out_of_scope - which is why "Cool, thanks! Bye!" was still being
            # told what the bot is for. A list that has to be kept in step
            # with an enum will eventually not be.
            intent_map = {member.value: member for member in Intent}

            intent = intent_map.get(intent_str, Intent.OUT_OF_SCOPE)
            confidence = float(data.get("confidence", 0.5))
            reasoning = str(data.get("reasoning", ""))

            logger.info(f"Intent: {intent.value} (confidence: {confidence:.2f}) - {reasoning[:60]}")
            return intent, confidence, reasoning

        except Exception as e:
            logger.error(f"Intent classification error: {e}", exc_info=True)
            # Default to chicago_events on error (fail open for events)
            return Intent.CHICAGO_EVENTS, 0.5, f"Classification error: {e!s}"


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
            "🎭 Interesting question! But I'm specifically built to help find Chicago events. "
            "Try asking me about concerts, theater, sports, food events, or things to do this weekend!\n\n"
            "💡 **Examples I can help with:**\n"
            '• "What\'s happening this weekend?"\n'
            '• "Show me free events in Chicago"\n'
            '• "Jazz concerts this month"\n'
            '• "Family-friendly activities"'
        ),
        Intent.EVENTS_GENERAL: (
            "🎯 Great question, but I'm specifically designed for **Chicago events**. "
            "Try asking me what's happening in the city this weekend!"
        ),
        Intent.CHICAGO_INFO: (
            "📍 I'd love to help with that, but I'm specifically built for finding **Chicago events**. "
            "For neighborhood tips or general Chicago info, try a search engine. "
            "But ask me about events and I'm your bot! 🎪"
        ),
        Intent.CHICAGO_EVENTS: ("🎉 Found it! I'm ready to help you discover Chicago events."),
    }

    return responses.get(
        intent,
        "🎭 I'm not sure how to help with that. I'm a Chicago event finder! "
        "Ask me about concerts, shows, or things to do this weekend.",
    )
