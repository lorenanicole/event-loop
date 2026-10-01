"""
Chat executor with SSE streaming and PEP 649 deferred annotations.
Manages REACT agent execution and state transitions for streaming responses.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime
from typing import AsyncGenerator
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.database.models import ChatThreadModel, ChatMessageModel, AuditLogModel, EventModel
from src.ai.chatbot import agent
from src.ai.intent_classifier import get_intent_classifier, Intent, get_intent_response
from src import telemetry
from src.security import (
    validate_and_sanitize,
    OutputValidator,
    rate_limiter,
)
from src.resilience import (
    llm_circuit_breaker,
    db_circuit_breaker,
    ErrorClassifier,
    default_retry_policy,
)
import time

logger = logging.getLogger(__name__)


class StreamEvent(BaseModel):
    """Base class for all SSE events emitted during chat execution."""
    event: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatStartedEvent(StreamEvent):
    """Emitted when chat thread is created."""
    event: str = "chat_started"
    thread_id: str | None = None


class ThinkingEvent(StreamEvent):
    """Emitted when agent is reasoning."""
    event: str = "thinking"
    status: str


class ToolCallEvent(StreamEvent):
    """Emitted when agent calls a tool."""
    event: str = "tool_call"
    tool: str
    args: dict


class ToolResultEvent(StreamEvent):
    """Emitted when tool returns results."""
    event: str = "tool_result"
    tool: str
    result_count: int
    snippet: str


class ResponseEvent(StreamEvent):
    """Emitted with the final response."""
    event: str = "response"
    message: str
    tokens: int


class ConversationStatusEvent(StreamEvent):
    """Emitted when conversation is approaching limits."""
    event: str = "conversation_status"
    status: str
    remaining_tokens: int
    remaining_turns: int


class CompleteEvent(StreamEvent):
    """Emitted when execution is complete."""
    event: str = "complete"
    thread_id: str
    tokens_used: int


class ChatExecutor:
    """
    Executes chat requests with REACT agent and streams events via SSE.
    Manages conversation state, database persistence, and event emission.
    """

    # MVP Limits: Keep conversations focused and cost-efficient
    MAX_TOKENS_PER_CONVERSATION = 4000
    MAX_TURNS_PER_CONVERSATION = 5
    TOKEN_WARNING_THRESHOLD = 0.75  # Warn when 75% of tokens used

    def __init__(self):
        pass  # DB session created per async operation

    async def execute(
        self,
        message: str,
        thread_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Execute a chat message through the REACT agent and yield SSE events.

        State machine transitions:
        chat_started -> thinking -> (tool_call -> tool_result)* -> response -> complete

        Enforces token and turn limits for MVP focus.
        Records telemetry and audit logs for observability.
        """
        start_time = time.time()
        temp_thread_id = thread_id or "new_session"
        db = None

        try:
            # 1. SECURITY: Validate input against prompt injection attacks
            is_safe, sanitized_message, threat_reason = validate_and_sanitize(
                message, temp_thread_id
            )

            if not is_safe:
                logger.warning(f"Security check failed: {threat_reason}")
                yield StreamEvent(
                    event="error",
                    data={"error": "⚠️ Request blocked for security. Please try a different question."},
                )
                return

            message = sanitized_message

            # Create async database session
            async with AsyncSessionLocal() as db:
                # Create or load chat thread
                if thread_id:
                    result = await db.execute(
                        select(ChatThreadModel).filter(ChatThreadModel.id == thread_id)
                    )
                    thread = result.scalar_one_or_none()
                    if not thread:
                        raise ValueError(f"Thread {thread_id} not found")
                else:
                    thread = ChatThreadModel()
                    db.add(thread)
                    await db.flush()  # Get ID without committing
                    thread_id = thread.id

                    # Record new session
                    telemetry.record_session_created()

                # Classify intent before running expensive LLM
                yield ThinkingEvent(
                    status="Analyzing your question...",
                    data={"status": "Analyzing your question..."},
                )

                classifier = get_intent_classifier()
                intent, confidence, reasoning = await classifier.classify(message)

                # Reject out-of-scope questions early
                if intent != Intent.CHICAGO_EVENTS and confidence > 0.7:
                    response = await get_intent_response(intent, reasoning)
                    tokens_count = int(len(response.split()) * 1.3)
                    yield ResponseEvent(
                        message=response,
                        tokens=tokens_count,
                        data={
                            "message": response,
                            "tokens": tokens_count,
                            "out_of_scope": True,
                        },
                    )
                    yield CompleteEvent(
                        thread_id=thread_id,
                        tokens_used=0,
                        data={
                            "thread_id": thread_id,
                            "tokens_used": 0,
                            "out_of_scope": True,
                        },
                    )
                    return

                # Record question (only if in-scope)
                telemetry.record_question_asked()

                # Check conversation limits
                remaining_tokens = self.MAX_TOKENS_PER_CONVERSATION - thread.total_tokens
                remaining_turns = self.MAX_TURNS_PER_CONVERSATION - thread.turn_count

                if remaining_turns <= 0 or remaining_tokens <= 0:
                    yield ConversationStatusEvent(
                        status="Conversation limit reached. Please start a new chat.",
                        remaining_tokens=0,
                        remaining_turns=0,
                        data={
                            "status": "limit_reached",
                            "message": "This conversation has reached its limit. Start a new one!"
                        }
                    )
                    return

                yield ChatStartedEvent(thread_id=thread_id, data={"thread_id": thread_id})

                # Store user message
                user_msg = ChatMessageModel(
                    thread_id=thread_id,
                    role="user",
                    content=message,
                    token_count=len(message.split()),  # Simple estimate
                )
                db.add(user_msg)
                await db.flush()

                # State 2: Thinking
                yield ThinkingEvent(
                    status="Analyzing your request...",
                    data={"status": "Analyzing your request..."}
                )

                # Run REACT agent with event interception
                full_response = ""
                tool_calls_made = 0
                total_tokens = 0

                async for event in self._run_agent_with_events(message):
                    if event.event == "tool_call":
                        tool_calls_made += 1
                        yield event
                    elif event.event == "tool_result":
                        yield event
                    elif event.event == "response":
                        full_response = event.data.get("message", "")
                        total_tokens = event.data.get("tokens", 0)

                # State Final: Response and Complete
                yield ResponseEvent(
                    message=full_response,
                    tokens=total_tokens,
                    data={
                        "message": full_response,
                        "tokens": total_tokens,
                        "tool_calls": tool_calls_made,
                    }
                )

                # Store assistant message
                assistant_msg = ChatMessageModel(
                    thread_id=thread_id,
                    role="assistant",
                    content=full_response,
                    token_count=total_tokens,
                    tool_calls_made=tool_calls_made,
                )
                db.add(assistant_msg)

                # Update thread totals
                thread.total_tokens += total_tokens
                thread.turn_count += 1
                await db.commit()

                # Record telemetry for this interaction
                telemetry.record_tool_call("agent_run", 0, total_tokens)

                # Check if approaching limits and emit status
                new_remaining_tokens = self.MAX_TOKENS_PER_CONVERSATION - thread.total_tokens
                new_remaining_turns = self.MAX_TURNS_PER_CONVERSATION - thread.turn_count
                is_session_complete = new_remaining_turns <= 0 or new_remaining_tokens <= 0

                if new_remaining_tokens < (self.MAX_TOKENS_PER_CONVERSATION * (1 - self.TOKEN_WARNING_THRESHOLD)):
                    yield ConversationStatusEvent(
                        status="One more question available",
                        remaining_tokens=max(0, new_remaining_tokens),
                        remaining_turns=max(0, new_remaining_turns),
                        data={
                            "status": "limit_approaching",
                            "remaining_tokens": max(0, new_remaining_tokens),
                            "remaining_turns": max(0, new_remaining_turns),
                        }
                    )

                # Record completion metrics if session is done
                if is_session_complete:
                    duration_ms = (time.time() - start_time) * 1000
                    telemetry.record_session_completed(
                        tokens=thread.total_tokens,
                        question_count=thread.turn_count,
                        duration_ms=duration_ms,
                    )
                    thread.status = "completed"
                    await db.commit()

                yield CompleteEvent(
                    thread_id=thread_id,
                    tokens_used=total_tokens,
                    data={
                        "thread_id": thread_id,
                        "tokens_used": total_tokens,
                        "tool_calls": tool_calls_made,
                        "remaining_tokens": max(0, new_remaining_tokens),
                        "remaining_turns": max(0, new_remaining_turns),
                    }
                )

        except Exception as e:
            logger.error(f"Execution error: {e}")

            # Classify and audit the error
            if isinstance(e, Exception):
                try:
                    error_type, is_retryable = ErrorClassifier.classify_llm_error(e)
                except:
                    pass

            # Return user-friendly error
            error_message = self._get_user_friendly_error(str(e))
            yield StreamEvent(
                event="error",
                data={"error": error_message}
            )

    def _get_user_friendly_error(self, error_str: str) -> str:
        """Convert technical errors into user-friendly messages."""
        error_lower = error_str.lower()

        if any(x in error_lower for x in ["invalid_api_key", "unauthorized"]):
            return "⚠️ Service configuration issue. Please contact support."

        if any(x in error_lower for x in ["rate_limit", "quota"]):
            return "⏳ Too many requests. Please try again in a moment."

        if any(x in error_lower for x in ["unavailable", "503", "timeout"]):
            return "🔧 Service temporarily unavailable. Please try again."

        if any(x in error_lower for x in ["connection", "database"]):
            return "💾 Database issue. We're working on it!"

        return "❌ Something went wrong. Please try again."

    async def _run_agent_with_events(
        self,
        message: str,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Run PydanticAI agent with circuit breaker and graceful degradation.
        If LLM fails: fall back to simple database search.
        """
        try:
            print(f"\n🔍 DEBUG: Agent model = {agent.model}")
            print(f"🔍 DEBUG: Agent has _tools attr? {hasattr(agent, '_tools')}")
            if hasattr(agent, '_tools'):
                print(f"🔍 DEBUG: Agent._tools = {agent._tools}")
            logger.info(f"Agent model: {agent.model}")

            # Check LLM circuit breaker
            if not llm_circuit_breaker.is_available():
                logger.warning("LLM circuit breaker OPEN - degraded mode")
                yield ThinkingEvent(
                    status="LLM service degraded - database only...",
                    data={"status": "degraded_mode"},
                )
                async for event in self._fallback_db_search(message):
                    yield event
                return

            yield ThinkingEvent(
                status="Searching local database...",
                data={"status": "Searching local database..."},
            )

            try:
                print(f"\n🔍 DEBUG: Calling agent.run() with message: {message[:50]}...")
                result = await default_retry_policy.execute(
                    lambda: agent.run(message),
                    operation_name="llm_agent_run",
                )
                response_text = result.output
                print(f"🔍 DEBUG: agent.run() returned: {response_text[:100]}")
                print(f"🔍 DEBUG: result type: {type(result)}, result.data: {result.data if hasattr(result, 'data') else 'N/A'}")

                # If agent returned raw tool outputs (dict-like), extract and format nicely
                if response_text.startswith('{"') and '"search_local_db"' in response_text:
                    try:
                        import json
                        tool_outputs = json.loads(response_text)
                        if "search_local_db" in tool_outputs and tool_outputs["search_local_db"] != "NO_RESULTS":
                            # Use the formatted results from search_local_db
                            response_text = tool_outputs["search_local_db"]
                    except (json.JSONDecodeError, KeyError):
                        # If parsing fails, use the original response
                        pass

                llm_circuit_breaker.record_success()

                # SECURITY: Validate LLM output doesn't leak sensitive info
                is_safe_output, leaked_pattern = OutputValidator.validate(response_text)
                if not is_safe_output:
                    logger.error(
                        f"Output validation failed - potential info disclosure: {leaked_pattern}"
                    )
                    response_text = OutputValidator.sanitize(response_text)
                    self._audit_log(
                        "output_sanitized",
                        thread_id,
                        "success",
                        0,
                        {"reason": "information_disclosure_risk"},
                    )

                if "🌐" in response_text:
                    yield ThinkingEvent(
                        status="Expanding search online...",
                        data={"status": "Expanding search online..."},
                    )

                tokens_count = int(len(response_text.split()) * 1.3)
                yield ResponseEvent(
                    message=response_text,
                    tokens=tokens_count,
                    data={
                        "message": response_text,
                        "tokens": tokens_count,
                    },
                )

            except Exception as e:
                error_type, is_retryable = ErrorClassifier.classify_llm_error(e)
                logger.warning(f"LLM error: {error_type} (retryable={is_retryable})")
                llm_circuit_breaker.record_failure()

                if not is_retryable:
                    logger.error(f"Permanent LLM error: {error_type}")
                    async for event in self._fallback_db_search(message):
                        yield event
                    return

                raise

        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            yield ResponseEvent(
                message=self._get_user_friendly_error(str(e)),
                tokens=20,
                data={
                    "message": self._get_user_friendly_error(str(e)),
                    "tokens": 20,
                    "error": True,
                },
            )

    async def _fallback_db_search(self, query: str) -> AsyncGenerator[ResponseEvent, None]:
        """
        Fallback: Search database only when LLM is unavailable.
        Simple keyword search without AI enhancement.
        """
        if not db_circuit_breaker.is_available():
            yield ResponseEvent(
                message="🔧 Both AI and database services are unavailable. Try again later.",
                tokens=20,
                data={"message": "Services unavailable.", "tokens": 20, "error": True},
            )
            return

        # DB fallback search disabled during async migration
        yield ResponseEvent(
            message="Database fallback search temporarily unavailable. Please try again.",
            tokens=15,
            data={"message": "DB search unavailable", "tokens": 15, "error": True},
        )
        return


    def _audit_log(
        self,
        operation: str,
        thread_id: str,
        status: str,
        tokens: int,
        metadata: dict,
        duration_ms: float = 0.0,
        error_message: str | None = None,
    ):
        """Record an audit log entry for observability (async migration pending)."""
        # Audit logging disabled during async database migration
        # Will be re-enabled when database layer is fully async
        pass


def sse_event_formatter(event: StreamEvent) -> str:
    """Format a StreamEvent for SSE transmission."""
    event_data = event.model_dump_json()
    return f"event: {event.event}\ndata: {event_data}\n\n"
