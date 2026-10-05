"""
Test harness for chat SSE responses with mock data.
Allows testing chat widget without hitting the backend.
"""

import json
from datetime import datetime


# Intent classifier responses (from system prompt spec)
INTENT_CLASSIFIER_RESPONSES = {
    "chicago_events": {
        "intent": "chicago_events",
        "confidence": 0.95,
        "reasoning": "User is asking for events in Chicago. Direct event search request."
    },
    "chicago_events_free": {
        "intent": "chicago_events",
        "confidence": 0.85,
        "reasoning": "The user is asking for free events happening tonight, which is a request for event listings."
    },
    "chicago_info": {
        "intent": "chicago_info",
        "confidence": 0.9,
        "reasoning": "User asking about Chicago but not specifically about events."
    },
    "events_general": {
        "intent": "events_general",
        "confidence": 0.8,
        "reasoning": "User asking about events but not Chicago-specific."
    },
    "out_of_scope": {
        "intent": "out_of_scope",
        "confidence": 0.99,
        "reasoning": "User request is unrelated to Chicago events."
    }
}


# Mock SSE response payloads from successful chat flow
MOCK_CHAT_RESPONSES = {
    "thinking_start": {
        "event": "thinking",
        "data": {
            "event": "thinking",
            "data": {"status": "Analyzing your question..."},
            "timestamp": datetime.now().isoformat(),
            "status": "Analyzing your question..."
        }
    },
    "chat_started": {
        "event": "chat_started",
        "data": {
            "event": "chat_started",
            "data": {"thread_id": "9f2b691b-3898-4de7-b6f8-4ebde07c21ef"},
            "timestamp": datetime.now().isoformat(),
            "thread_id": "9f2b691b-3898-4de7-b6f8-4ebde07c21ef"
        }
    },
    "thinking_analyze": {
        "event": "thinking",
        "data": {
            "event": "thinking",
            "data": {"status": "Analyzing your request..."},
            "timestamp": datetime.now().isoformat(),
            "status": "Analyzing your request..."
        }
    },
    "tool_call_search": {
        "event": "tool_call",
        "data": {
            "event": "tool_call",
            "data": {
                "tool": "search_local_db",
                "args": {"query": "free events tonight"}
            },
            "timestamp": datetime.now().isoformat(),
            "tool": "search_local_db",
            "args": {"query": "free events tonight"}
        }
    },
    "tool_result_events": {
        "event": "tool_result",
        "data": {
            "event": "tool_result",
            "data": {
                "result_count": 3,
                "snippet": "Found concerts and theater"
            },
            "timestamp": datetime.now().isoformat(),
            "result_count": 3,
            "snippet": "Found concerts and theater"
        }
    },
    "response_success": {
        "event": "response",
        "data": {
            "event": "response",
            "data": {
                "message": "🎉 Found **3 great matches** for free events tonight!\n\n1. **Underground Madness** 🎸\n   📅 Oct 3, 11:00 PM\n   📌 Reggies Rock Club\n\n2. **Jazz Night** 🎷\n   📅 Oct 3, 9:00 PM\n   📌 Green Mill\n\n3. **Comedy Showcase** 😂\n   📅 Oct 3, 8:30 PM\n   📌 Second City",
                "tokens": 156,
                "tool_calls": 1
            },
            "timestamp": datetime.now().isoformat(),
            "message": "🎉 Found **3 great matches** for free events tonight!",
            "tokens": 156
        }
    },
    "response_no_results": {
        "event": "response",
        "data": {
            "event": "response",
            "data": {
                "message": "❌ Something went wrong. Please try again.",
                "tokens": 20,
                "tool_calls": 0
            },
            "timestamp": datetime.now().isoformat(),
            "message": "❌ Something went wrong. Please try again.",
            "tokens": 20
        }
    },
    "complete_success": {
        "event": "complete",
        "data": {
            "event": "complete",
            "data": {
                "thread_id": "9f2b691b-3898-4de7-b6f8-4ebde07c21ef",
                "tokens_used": 176,
                "tool_calls": 1,
                "remaining_tokens": 3824,
                "remaining_turns": 4
            },
            "timestamp": datetime.now().isoformat(),
            "thread_id": "9f2b691b-3898-4de7-b6f8-4ebde07c21ef",
            "tokens_used": 176,
            "tool_calls": 1,
            "remaining_tokens": 3824,
            "remaining_turns": 4
        }
    },
    "complete_no_results": {
        "event": "complete",
        "data": {
            "event": "complete",
            "data": {
                "thread_id": "9f2b691b-3898-4de7-b6f8-4ebde07c21ef",
                "tokens_used": 20,
                "tool_calls": 0,
                "remaining_tokens": 3980,
                "remaining_turns": 4
            },
            "timestamp": datetime.now().isoformat(),
            "thread_id": "9f2b691b-3898-4de7-b6f8-4ebde07c21ef",
            "tokens_used": 20,
            "tool_calls": 0,
            "remaining_tokens": 3980,
            "remaining_turns": 4
        }
    }
}


def format_sse_stream(responses: list[dict]) -> str:
    """Format mock responses as SSE stream."""
    lines = []
    for resp in responses:
        lines.append(f"event: {resp['event']}")
        lines.append(f"data: {json.dumps(resp['data'])}")
        lines.append("")
    return "\n".join(lines)


def get_successful_chat_flow() -> str:
    """Get mock SSE response for successful chat with events found."""
    responses = [
        MOCK_CHAT_RESPONSES["thinking_start"],
        MOCK_CHAT_RESPONSES["chat_started"],
        MOCK_CHAT_RESPONSES["thinking_analyze"],
        MOCK_CHAT_RESPONSES["tool_call_search"],
        MOCK_CHAT_RESPONSES["tool_result_events"],
        MOCK_CHAT_RESPONSES["response_success"],
        MOCK_CHAT_RESPONSES["complete_success"],
    ]
    return format_sse_stream(responses)


def get_no_results_chat_flow() -> str:
    """Get mock SSE response for chat with no results."""
    responses = [
        MOCK_CHAT_RESPONSES["thinking_start"],
        MOCK_CHAT_RESPONSES["chat_started"],
        MOCK_CHAT_RESPONSES["thinking_analyze"],
        MOCK_CHAT_RESPONSES["response_no_results"],
        MOCK_CHAT_RESPONSES["complete_no_results"],
    ]
    return format_sse_stream(responses)


def test_sse_response_format():
    """Verify SSE response format is valid."""
    stream = get_successful_chat_flow()
    lines = stream.split("\n")

    # Should have event/data pairs
    event_count = sum(1 for line in lines if line.startswith("event: "))
    data_count = sum(1 for line in lines if line.startswith("data: "))
    assert event_count == data_count, f"Event/data mismatch: {event_count} events, {data_count} data"

    # All data lines should be valid JSON
    for line in lines:
        if line.startswith("data: "):
            json_str = line[6:]  # Remove "data: " prefix
            data = json.loads(json_str)
            assert "event" in data, f"Missing 'event' in: {data}"


def test_successful_flow_events():
    """Verify successful flow contains expected events."""
    responses = [
        MOCK_CHAT_RESPONSES["thinking_start"],
        MOCK_CHAT_RESPONSES["chat_started"],
        MOCK_CHAT_RESPONSES["thinking_analyze"],
        MOCK_CHAT_RESPONSES["tool_call_search"],
        MOCK_CHAT_RESPONSES["tool_result_events"],
        MOCK_CHAT_RESPONSES["response_success"],
        MOCK_CHAT_RESPONSES["complete_success"],
    ]

    events = [r["event"] for r in responses]
    assert events == [
        "thinking",
        "chat_started",
        "thinking",
        "tool_call",
        "tool_result",
        "response",
        "complete",
    ], f"Unexpected event sequence: {events}"


def test_intent_classifier_responses():
    """Verify intent classifier responses match prompt spec."""
    for name, response in INTENT_CLASSIFIER_RESPONSES.items():
        # Must have required fields from system prompt
        assert "intent" in response, f"Missing 'intent' in {name}"
        assert "confidence" in response, f"Missing 'confidence' in {name}"
        assert "reasoning" in response, f"Missing 'reasoning' in {name}"

        # Intent must be one of the defined categories
        valid_intents = ["chicago_events", "chicago_info", "events_general", "out_of_scope"]
        assert response["intent"] in valid_intents, f"Invalid intent: {response['intent']}"

        # Confidence must be 0-1
        assert 0.0 <= response["confidence"] <= 1.0, f"Invalid confidence: {response['confidence']}"


if __name__ == "__main__":
    print("Testing intent classifier response format...")
    test_intent_classifier_responses()
    print("✅ Intent classifier responses valid")

    print("Testing SSE mock data format...")
    test_sse_response_format()
    print("✅ SSE format valid")

    test_successful_flow_events()
    print("✅ Event sequence valid")

    print("\n📋 Intent Classifier Test Cases:")
    for name, resp in INTENT_CLASSIFIER_RESPONSES.items():
        print(f"  {name}: {resp['intent']} (confidence: {resp['confidence']})")

    print("\nSuccessful chat flow:")
    print(get_successful_chat_flow()[:200] + "...")

    print("\nNo results flow:")
    print(get_no_results_chat_flow()[:200] + "...")
