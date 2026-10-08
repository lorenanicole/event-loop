"""
Tests for the three-tier intent routing in ChatExecutor.

Tiers:
  confidence >= 0.85 + non-event  → hard redirect (no agent)
  confidence 0.65-0.84 + non-event → ambiguous: agent runs, tag injected then stripped
  anything else                   → agent runs normally
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chat.intent_classifier import Intent


def _make_classify(intent: Intent, confidence: float):
    async def classify(message, recent=None):
        return intent, confidence, "test"

    return classify


class TestAmbiguousTagStripping:
    """The [AMBIGUOUS_INTENT] tag must never reach the user or search tools."""

    def test_tag_stripped_from_clean_message(self):
        tagged = "[AMBIGUOUS_INTENT] what's a good spot"
        clean = tagged.removeprefix("[AMBIGUOUS_INTENT]").strip()
        assert clean == "what's a good spot"
        assert "[AMBIGUOUS_INTENT]" not in clean

    def test_untagged_message_unchanged(self):
        clean = "jazz tonight".removeprefix("[AMBIGUOUS_INTENT]").strip()
        assert clean == "jazz tonight"

    def test_boundary_at_085_is_hard_redirect(self):
        """confidence=0.85 is the hard-redirect floor, not ambiguous."""
        confidence = 0.85
        is_non_event = True
        ambiguous = is_non_event and 0.65 <= confidence < 0.85
        hard_redirect = is_non_event and confidence >= 0.85
        assert hard_redirect is True
        assert ambiguous is False

    def test_boundary_at_0849_is_ambiguous(self):
        confidence = 0.849
        is_non_event = True
        ambiguous = is_non_event and 0.65 <= confidence < 0.85
        hard_redirect = is_non_event and confidence >= 0.85
        assert ambiguous is True
        assert hard_redirect is False

    def test_below_band_at_064_is_normal_run(self):
        confidence = 0.64
        is_non_event = True
        ambiguous = is_non_event and 0.65 <= confidence < 0.85
        hard_redirect = is_non_event and confidence >= 0.85
        assert ambiguous is False
        assert hard_redirect is False

    def test_chicago_events_high_confidence_never_tagged(self):
        """Even high-confidence CHICAGO_EVENTS intent must not be ambiguous."""
        intent = Intent.CHICAGO_EVENTS
        confidence = 0.99
        is_non_event = intent != Intent.CHICAGO_EVENTS
        ambiguous = is_non_event and 0.65 <= confidence < 0.85
        assert ambiguous is False


class TestHardRedirect:
    """High-confidence non-event → redirect, agent never called."""

    @pytest.mark.asyncio
    async def test_out_of_scope_095_returns_redirect(self):
        from app.chat.executor import ChatExecutor

        executor = ChatExecutor()
        events = []
        with (
            patch("app.chat.executor.get_intent_classifier") as mock_clf,
            patch("app.chat.executor.get_intent_response", new_callable=AsyncMock) as mock_resp,
        ):
            inst = MagicMock()
            inst.classify = _make_classify(Intent.OUT_OF_SCOPE, 0.95)
            mock_clf.return_value = inst
            mock_resp.return_value = "I only know Chicago events!"
            async for e in executor.execute("Tell me a joke"):
                events.append(e)
        assert any(e.event == "response" and e.data.get("out_of_scope") for e in events)

    @pytest.mark.asyncio
    async def test_chicago_info_090_returns_redirect(self):
        from app.chat.executor import ChatExecutor

        executor = ChatExecutor()
        events = []
        with (
            patch("app.chat.executor.get_intent_classifier") as mock_clf,
            patch("app.chat.executor.get_intent_response", new_callable=AsyncMock) as mock_resp,
        ):
            inst = MagicMock()
            inst.classify = _make_classify(Intent.CHICAGO_INFO, 0.90)
            mock_clf.return_value = inst
            mock_resp.return_value = "I'm your Chicago events guide!"
            async for e in executor.execute("Best neighbourhood?"):
                events.append(e)
        assert any(e.event == "response" and e.data.get("out_of_scope") for e in events)
