from types import SimpleNamespace

import pytest

from app.chat.intent_classifier import Intent, IntentClassifier


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Find concerts in Chicago this weekend",
        "Chicago comedy shows tonight",
        "What festivals are happening in Chicago?",
        "Chicago live music this week",
    ],
)
async def test_explicit_chicago_event_requests_skip_the_model(monkeypatch, message):
    classifier = IntentClassifier()

    async def unexpected_model_call(_prompt):
        raise AssertionError("clear Chicago event requests should use the fast path")

    monkeypatch.setattr(classifier.classifier_agent, "run", unexpected_model_call)

    intent, confidence, _ = await classifier.classify(message)

    assert intent is Intent.CHICAGO_EVENTS
    assert confidence == 0.99


@pytest.mark.asyncio
async def test_ambiguous_chicago_question_still_uses_the_model(monkeypatch):
    classifier = IntentClassifier()
    prompts = []

    async def classify_with_model(prompt):
        prompts.append(prompt)
        return SimpleNamespace(
            output='{"intent":"chicago_info","confidence":0.9,"reasoning":"about the city"}',
            usage=SimpleNamespace(input_tokens=20, output_tokens=5, requests=1),
        )

    monkeypatch.setattr(classifier.classifier_agent, "run", classify_with_model)

    intent, _, _ = await classifier.classify("Where is the best pizza in Chicago?")

    assert intent is Intent.CHICAGO_INFO
    assert prompts == ["Where is the best pizza in Chicago?"]


@pytest.mark.asyncio
async def test_follow_up_with_context_still_uses_the_model(monkeypatch):
    classifier = IntentClassifier()
    prompts = []

    async def classify_with_model(prompt):
        prompts.append(prompt)
        return SimpleNamespace(
            output='{"intent":"chicago_events","confidence":0.9,"reasoning":"follow-up"}',
            usage=SimpleNamespace(input_tokens=20, output_tokens=5, requests=1),
        )

    monkeypatch.setattr(classifier.classifier_agent, "run", classify_with_model)

    await classifier.classify("What about comedy?", recent=["assistant: Here are music events."])

    assert len(prompts) == 1
    assert "Classify ONLY this latest message" in prompts[0]
