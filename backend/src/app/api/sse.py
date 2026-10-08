"""
SSE event types and formatter for the chat streaming API.

These types are the transport contract between the chat executor and the
client. They belong here (the API layer) rather than in executor.py (the
orchestration layer): the executor emits them as objects; this module defines
what they look like on the wire.

All event classes also live in executor.py as re-exports for the duration of
the migration, so nothing breaks if it still imports from there.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class StreamEvent(BaseModel):
    """Base class for all SSE events emitted during a chat turn."""

    event: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatStartedEvent(StreamEvent):
    """Emitted when a chat thread is created or resumed."""

    event: str = "chat_started"
    thread_id: str | None = None


class ThinkingEvent(StreamEvent):
    """Emitted while the agent is reasoning, to show progress to the user."""

    event: str = "thinking"
    status: str


class ToolCallEvent(StreamEvent):
    """Emitted when the agent calls a search tool."""

    event: str = "tool_call"
    tool: str
    args: dict


class ResponseEvent(StreamEvent):
    """Emitted with the final natural-language reply."""

    event: str = "response"
    message: str
    tokens: int


class ConversationStatusEvent(StreamEvent):
    """Emitted when the conversation is approaching its turn or token limit."""

    event: str = "conversation_status"
    status: str
    remaining_tokens: int
    remaining_turns: int


class CompleteEvent(StreamEvent):
    """Emitted as the last event of every turn, carrying accounting metadata."""

    event: str = "complete"
    thread_id: str
    tokens_used: int


def sse_event_formatter(event: StreamEvent) -> str:
    """Serialise a StreamEvent to the SSE wire format.

    Returns a string of the form::

        event: <type>\\ndata: <json>\\n\\n

    The double newline is the SSE message boundary the browser EventSource
    API expects.
    """
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
