"""
Chat executor with SSE streaming and PEP 649 deferred annotations.
Manages REACT agent execution and state transitions for streaming responses.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator

from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from app import telemetry
from app.api.sse import (  # noqa: F401 — re-exported for callers that import from here
    ChatStartedEvent,
    CompleteEvent,
    ConversationStatusEvent,
    ResponseEvent,
    StreamEvent,
    ThinkingEvent,
    ToolCallEvent,
    sse_event_formatter,
)
from app.chat.agent import SYSTEM_PROMPT, agent, todays_date
from app.chat.chatbot import (
    AGENT_OUTPUT_TOKEN_LIMIT,
    AGENT_REQUEST_LIMIT,
    AGENT_TOOL_CALL_LIMIT,
    SearchPolicy,
)
from app.chat.intent_classifier import Intent, get_intent_classifier, get_intent_response
from app.resilience import (
    ErrorClassifier,
    db_circuit_breaker,
    default_retry_policy,
    llm_circuit_breaker,
)
from app.security import (
    OutputValidator,
    validate_and_sanitize,
)
from shared.database import AsyncSessionLocal
from shared.database.models import AuditLogModel, ChatMessageModel, ChatThreadModel

logger = logging.getLogger(__name__)


def _tools_used(result) -> list[tuple[str, dict]]:
    """The tools an agent run actually called, in order.

    Read from the run's own message history rather than counted as the run
    goes along: `agent.run` is one awaited call and emits nothing in between,
    so anything watching for intermediate events sees none.

    Tolerant of the message shapes changing, because a wrong tool count is
    only a reporting detail and must never fail a reply that otherwise
    worked.
    """
    calls: list[tuple[str, dict]] = []
    try:
        messages = result.all_messages()
    except Exception:
        return calls

    for message in messages:
        for part in getattr(message, "parts", []) or []:
            name = getattr(part, "tool_name", None)
            # Only the request side has a tool_name AND args; the matching
            # return part would otherwise double every count.
            if not name or not hasattr(part, "args"):
                continue
            args = getattr(part, "args", None)
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError, TypeError:
                    args = {"raw": args}
            calls.append((name, args if isinstance(args, dict) else {}))
    return calls


class ChatExecutor:
    """
    Executes chat requests with REACT agent and streams events via SSE.
    Manages conversation state, database persistence, and event emission.
    """

    # Cumulative provider-reported agent tokens and turns per conversation.
    # Per-run request, tool, and output limits are defined with the agent.
    MAX_TOKENS_PER_CONVERSATION = 20000
    MAX_TURNS_PER_CONVERSATION = 12
    TOKEN_WARNING_THRESHOLD = 0.75  # Warn when 75% of tokens used

    def __init__(self):
        pass  # DB session created per async operation

    async def execute(
        self,
        message: str,
        thread_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent]:
        """
        Execute a chat message through the REACT agent and yield SSE events.

        State transitions:
        chat_started -> thinking -> tool_call* -> response -> complete

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
                    data={
                        "error": "⚠️ Request blocked for security. Please try a different question."
                    },
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
                    # Committed immediately, not merely flushed.
                    #
                    # A flush opens SQLite's write transaction and leaves it
                    # open, and the rest of this request is an agent run that
                    # takes 10-60 seconds. SQLite allows one writer, so every
                    # other chat - and the scraper - queued behind that lock
                    # for the whole LLM round trip and then failed with
                    # "database is locked". Six concurrent chats produced five
                    # failures; it was never really about the scraper, which
                    # is where the first two attempts at this went looking.
                    #
                    # The row is independent and needs no later rollback, so
                    # committing here costs nothing and releases the lock
                    # before the slow part starts.
                    await db.commit()
                    await db.refresh(thread)
                    thread_id = thread.id

                    # Record new session
                    telemetry.record_session_created()

                # Classify intent before running expensive LLM
                yield ThinkingEvent(
                    status="Analyzing your question...",
                    data={"status": "Analyzing your question..."},
                )

                classifier = get_intent_classifier()
                # The conversation so far, so a follow-up is not judged on
                # its own words alone. "What recommendations for food do we
                # have in Wicker?" was rejected as off-topic mid-way through
                # planning an evening in Wicker Park.
                recent_text = []
                if thread.turn_count:
                    rows = (
                        (
                            await db.execute(
                                select(ChatMessageModel)
                                .where(ChatMessageModel.thread_id == thread_id)
                                .order_by(ChatMessageModel.created_at.desc())
                                .limit(4)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    recent_text = [f"{r.role}: {(r.content or '')[:300]}" for r in reversed(rows)]
                intent, confidence, reasoning = await classifier.classify(
                    message, recent=recent_text
                )

                # Signing off ends the conversation. Judged by the
                # classifier rather than by matching phrases: the first
                # version was a regex, which needed "I'm done" added after it
                # missed one of the most obvious ways to say it, and would
                # have needed another entry every time somebody phrased it
                # differently. The classifier already runs on every turn, so
                # this costs nothing extra and generalises.
                #
                # This is also how a conversation is meant to end. The turn
                # budget is a backstop; people say goodbye.
                if intent == Intent.FAREWELL:
                    from app.chat.persona import goodbye_reply
                    from app.chat.threads import close_thread

                    farewell_text = goodbye_reply()
                    yield ResponseEvent(
                        message=farewell_text,
                        tokens=0,
                        data={"message": farewell_text, "conversation_ended": True},
                    )
                    db.add(
                        ChatMessageModel(
                            thread_id=thread_id,
                            role="assistant",
                            content=farewell_text,
                            token_count=0,
                        )
                    )
                    await db.commit()
                    await close_thread(db, thread_id)
                    yield ConversationStatusEvent(
                        status="Conversation ended.",
                        remaining_tokens=0,
                        remaining_turns=0,
                        data={
                            "status": "limit_reached",
                            "reason": "goodbye",
                            "message": farewell_text,
                        },
                    )
                    yield CompleteEvent(
                        thread_id=thread_id,
                        tokens_used=0,
                        data={
                            "thread_id": thread_id,
                            "tokens_used": 0,
                            "remaining_tokens": 0,
                            "remaining_turns": 0,
                        },
                    )
                    return

                # Route on (intent, confidence) — three tiers rather than a
                # single binary threshold:
                #
                #  confidence >= 0.85 + non-event   → hard redirect: don't run agent
                #  confidence 0.65-0.84 + non-event → soft: run agent with an
                #      ambiguity hint so it asks a clarifying question instead
                #      of searching blindly
                #  anything else                    → run agent normally
                #
                # The old code used a single cliff at 0.7 and discarded the
                # confidence number after that. The middle band stops the agent
                # from confidently answering a question it may have mis-read.
                is_non_event = intent != Intent.CHICAGO_EVENTS
                ambiguous = is_non_event and 0.65 <= confidence < 0.85

                if is_non_event and confidence >= 0.85:
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
                    # The budget is reported even though this question spent
                    # none of it. Leaving the fields out ended the whole
                    # conversation: the UI read a missing `remaining_turns` as
                    # zero and told the user "token limit reached" after a
                    # single off-topic question. An out-of-scope answer costs
                    # no turn, so the numbers are the ones going in.
                    yield CompleteEvent(
                        thread_id=thread_id,
                        tokens_used=0,
                        data={
                            "thread_id": thread_id,
                            "tokens_used": 0,
                            "out_of_scope": True,
                            "remaining_tokens": max(
                                0,
                                self.MAX_TOKENS_PER_CONVERSATION - thread.total_tokens,
                            ),
                            "remaining_turns": max(
                                0,
                                self.MAX_TURNS_PER_CONVERSATION - thread.turn_count,
                            ),
                        },
                    )
                    return

                # Ambiguous band: tag the message so the agent asks rather than
                # guesses. The tag is visible to the voice() system-prompt
                # function via SearchPolicy.user_message, which is already used
                # to select category facts. A tagged message makes the agent
                # treat the request as potentially ambiguous and ask the user to
                # confirm what they meant before searching.
                if ambiguous:
                    message = f"[AMBIGUOUS_INTENT] {message}"
                    logger.info(
                        "Ambiguous intent (%.2f confidence %s) — injecting clarification hint",
                        confidence,
                        intent.value,
                    )

                # Record question (only if in-scope)
                telemetry.record_question_asked()

                # Check conversation limits
                remaining_tokens = self.MAX_TOKENS_PER_CONVERSATION - thread.total_tokens
                remaining_turns = self.MAX_TURNS_PER_CONVERSATION - thread.turn_count

                if remaining_turns <= 0 or remaining_tokens <= 0:
                    from app.chat.persona import farewell

                    goodbye = farewell("turns" if remaining_turns <= 0 else "tokens")
                    # Sent as a message, not only a status chip: the person was
                    # talking to the assistant, so the assistant should be the
                    # one to say it is done and what to do next.
                    yield ResponseEvent(
                        message=goodbye,
                        tokens=0,
                        data={"message": goodbye, "conversation_ended": True},
                    )
                    yield ConversationStatusEvent(
                        status="Conversation limit reached. Please start a new chat.",
                        remaining_tokens=0,
                        remaining_turns=0,
                        data={
                            "status": "limit_reached",
                            "reason": "turns" if remaining_turns <= 0 else "tokens",
                            "message": goodbye,
                        },
                    )
                    yield CompleteEvent(
                        thread_id=thread_id,
                        tokens_used=0,
                        data={
                            "thread_id": thread_id,
                            "tokens_used": 0,
                            "remaining_tokens": 0,
                            "remaining_turns": 0,
                        },
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
                # Committed, not flushed, for the same reason as the thread
                # row above: a flush holds SQLite's single write lock, and the
                # agent run that follows takes 10-60 seconds. This was the
                # second of the two writes opening that window.
                await db.commit()

                # State 2: Thinking
                yield ThinkingEvent(
                    status="Analyzing your request...", data={"status": "Analyzing your request..."}
                )

                # Run REACT agent with event interception
                full_response = ""
                tool_calls_made = 0
                total_tokens = 0

                history = await self._load_history(db, thread_id, message)
                async for event in self._run_agent_with_events(message, history):
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
                    },
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

                if new_remaining_tokens < (
                    self.MAX_TOKENS_PER_CONVERSATION * (1 - self.TOKEN_WARNING_THRESHOLD)
                ):
                    yield ConversationStatusEvent(
                        status="One more question available",
                        remaining_tokens=max(0, new_remaining_tokens),
                        remaining_turns=max(0, new_remaining_turns),
                        data={
                            "status": "limit_approaching",
                            "remaining_tokens": max(0, new_remaining_tokens),
                            "remaining_turns": max(0, new_remaining_turns),
                        },
                    )

                # Record completion metrics if session is done
                if is_session_complete:
                    from app.chat.persona import farewell

                    goodbye = farewell("turns" if new_remaining_turns <= 0 else "tokens")
                    # Told on the turn that spends the last of the budget,
                    # rather than on the next one. Otherwise the person types a
                    # follow-up, waits, and only then learns the conversation
                    # was already over.
                    yield ResponseEvent(
                        message=goodbye,
                        tokens=0,
                        data={"message": goodbye, "conversation_ended": True},
                    )
                    duration_ms = (time.time() - start_time) * 1000
                    telemetry.record_session_completed(
                        tokens=thread.total_tokens,
                        question_count=thread.turn_count,
                        duration_ms=duration_ms,
                    )
                    thread.status = "completed"
                    await db.commit()

                await self._audit_log(
                    "turn_completed",
                    thread_id,
                    "success",
                    total_tokens,
                    {
                        "turn": thread.turn_count,
                        "tool_calls": tool_calls_made,
                        "remaining_turns": max(0, new_remaining_turns),
                    },
                    duration_ms=(time.time() - start_time) * 1000,
                )

                yield CompleteEvent(
                    thread_id=thread_id,
                    tokens_used=total_tokens,
                    data={
                        "thread_id": thread_id,
                        "tokens_used": total_tokens,
                        "tool_calls": tool_calls_made,
                        "remaining_tokens": max(0, new_remaining_tokens),
                        "remaining_turns": max(0, new_remaining_turns),
                    },
                )

        except Exception as e:
            logger.error(f"Execution error: {e}")

            # Classify the error (best-effort — never let this crash the error handler).
            import contextlib

            with contextlib.suppress(Exception):
                _error_type, _is_retryable = ErrorClassifier.classify_llm_error(e)

            # Return user-friendly error
            error_message = self._get_user_friendly_error(str(e))
            yield StreamEvent(event="error", data={"error": error_message})

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

    # How many past messages to replay. Six is three exchanges, which covers
    # "yes, that one" and "what about the Northwest side" without resending a
    # long transcript to the model on every turn.
    HISTORY_MESSAGES = 6

    async def _load_history(self, db, thread_id: str, exclude_content: str):
        """Delegate to threads.load_thread_history.

        The full implementation — message loading, system-prompt replay, and
        context-summary injection — lives in threads.py alongside the rest of
        the thread lifecycle code.
        """
        from app.chat.persona import persona_prompt
        from app.chat.threads import load_thread_history

        return await load_thread_history(
            db=db,
            thread_id=thread_id,
            exclude_content=exclude_content,
            history_limit=self.HISTORY_MESSAGES,
            system_prompt=SYSTEM_PROMPT,
            persona_fn=persona_prompt,
            date_fn=todays_date,
        )

    async def _run_agent_with_events(
        self,
        message: str,
        history: list | None = None,
    ) -> AsyncGenerator[StreamEvent]:
        """
        Run PydanticAI agent with circuit breaker and graceful degradation.
        If LLM fails: fall back to simple database search.
        """
        try:
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
                # Strip the internal routing tag before it reaches the agent
                # or the search-policy keyword extractor. The tag is only for
                # the system-prompt injection in voice(); the user turn and all
                # tool calls should see the plain message.
                clean_message = message.removeprefix("[AMBIGUOUS_INTENT]").strip()
                search_policy = SearchPolicy(user_message=clean_message)
                result = await default_retry_policy.execute(
                    lambda: agent.run(
                        clean_message,
                        message_history=history or None,
                        deps=search_policy,
                        usage_limits=UsageLimits(
                            request_limit=AGENT_REQUEST_LIMIT,
                            tool_calls_limit=AGENT_TOOL_CALL_LIMIT,
                            output_tokens_limit=AGENT_OUTPUT_TOKEN_LIMIT,
                        ),
                    ),
                    operation_name="llm_agent_run",
                )
                response_text = result.output
                usage = result.usage
                tokens_count = usage.total_tokens
                telemetry.record_model_usage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    requests=usage.requests,
                )

                # Report which tools actually ran.
                #
                # This used to be counted by watching for a "tool_call" event
                # from this generator, which never emits one: `agent.run` is a
                # single awaited call, not a stream, so the count was always
                # zero no matter how much work the agent did. A turn that had
                # just searched the web reported `tool_calls: 0`, which made
                # answers look like they came from nowhere and made it
                # impossible to tell a database answer from a web one.
                #
                # The run result carries the real history, so read it from
                # there instead.
                for name, args in _tools_used(result):
                    yield ToolCallEvent(
                        tool=name,
                        args=args,
                        data={"tool": name, "args": args},
                    )

                # If agent returned raw tool outputs (dict-like), extract and format nicely
                if response_text.startswith('{"') and '"search_local_db"' in response_text:
                    try:
                        import json

                        tool_outputs = json.loads(response_text)
                        if (
                            "search_local_db" in tool_outputs
                            and tool_outputs["search_local_db"] != "NO_RESULTS"
                        ):
                            # Use the formatted results from search_local_db
                            response_text = tool_outputs["search_local_db"]
                    except json.JSONDecodeError, KeyError:
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

                if "🌐" in response_text:
                    yield ThinkingEvent(
                        status="Expanding search online...",
                        data={"status": "Expanding search online..."},
                    )

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

    async def _fallback_db_search(self, query: str) -> AsyncGenerator[ResponseEvent]:
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

    async def _audit_log(
        self,
        operation: str,
        thread_id: str | None,
        status: str,
        tokens: int,
        metadata: dict,
        duration_ms: float = 0.0,
        error_message: str | None = None,
    ):
        """Record one line of what happened, for observability.

        This was a `pass` with the note "disabled during async database
        migration", and the migration finished long ago - so the audit_logs
        table had 258 conversations' worth of nothing in it. There is no point
        defining a table and then not writing to it.

        Writes on its own short-lived session rather than the request's, for
        two reasons: a failed turn has usually rolled its session back, and
        holding the request's session means holding SQLite's write lock across
        the agent run, which is the bug that made concurrent chats fail.

        Never raises. Observability that can break the thing it observes is
        worse than none.
        """
        from shared.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as session:
                session.add(
                    AuditLogModel(
                        thread_id=thread_id,
                        operation=operation,
                        status=status,
                        duration_ms=duration_ms,
                        tokens_used=tokens,
                        extra_metadata=json.dumps(metadata) if metadata else None,
                        error_message=error_message,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("audit log write failed: %s: %s", type(exc).__name__, exc)


# sse_event_formatter is imported from app.api.sse at the top of this file
# and re-exported via the noqa F401 import block.
