"""Tests for the guide's character and city knowledge.

The persona started as five sections of rules about tone and nothing about
what the guide knows, which is why it read as a polite search engine. These
pin the knowledge, because it is the part that is easy to delete by accident
while editing the rules around it.
"""

import random

import pytest

from app.ai.persona import (
    ASSISTANT_NAME,
    CHICAGO_FACTS,
    GENERAL_FACTS,
    SIGN_OFFS,
    fact_for,
    farewell,
    greeting,
    persona_prompt,
    reads_like_a_title,
)


class TestCharacterAndKnowledge:
    def test_it_describes_who_the_guide_is(self):
        assert "WHO YOU ARE:" in persona_prompt()

    def test_it_knows_the_city_geography(self):
        prompt = persona_prompt()
        for side in ("North Side", "South Side", "Northwest Side", "West Side"):
            assert side in prompt, side

    @pytest.mark.parametrize(
        "line,neighborhood",
        [
            ("Blue", "Logan Square"),
            ("Blue", "Wicker Park"),
            ("Brown", "Lincoln Square"),
            ("Pink", "Pilsen"),
            ("Red", "Uptown"),
            ("Orange", "Bridgeport"),
        ],
    )
    def test_it_knows_which_l_line_serves_where(self, line, neighborhood):
        """Naming the line and stop is what makes an answer local. Three
        different stations are called Damen, so a line without its stop - or a
        stop without its line - is worse than saying nothing."""
        prompt = persona_prompt()
        assert line in prompt and neighborhood in prompt

    def test_it_knows_the_season(self):
        """What is on in Chicago depends heavily on the month."""
        prompt = persona_prompt()
        assert "October is Halloween" in prompt
        assert "Christkindlmarket" in prompt

    def test_it_knows_how_rooms_behave(self):
        prompt = persona_prompt()
        assert "Doors at 8" in prompt
        assert "21+" in prompt


class TestTheRulesSurvive:
    """The hard-won ones, each added after seeing it get this wrong."""

    @pytest.mark.parametrize(
        "rule",
        [
            "NEVER MENTION HOW YOU WORK:",
            "DO NOT NARRATE YOUR OWN STANDARDS:",
            "BE SHORT ABOUT WHAT YOU DID NOT FIND:",
            "BE INFORMATIVE, NOT PRESCRIPTIVE:",
        ],
    )
    def test_rule_is_present(self, rule):
        assert rule in persona_prompt()

    def test_it_forbids_talking_about_cost(self):
        """It offered to run "a paid Google search" and asked permission to
        spend money, which is not the reader's decision."""
        assert "costs" in persona_prompt()

    def test_it_still_requires_provenance(self):
        """Dropping internals must not drop where an event came from."""
        assert "unverified" in persona_prompt()


class TestFacts:
    def test_a_category_gets_its_own_fact(self):
        assert fact_for("Music") in CHICAGO_FACTS["Music"]

    def test_an_unknown_category_falls_back_to_general(self):
        assert fact_for("Nonsense") in GENERAL_FACTS

    def test_no_category_falls_back_to_general(self):
        assert fact_for(None) in GENERAL_FACTS

    def test_facts_rotate(self):
        """Two chats opened back to back should not show the same fact."""
        picks = {fact_for(None, random.Random(seed)) for seed in range(12)}
        assert len(picks) > 1

    def test_there_are_enough_facts_to_rotate_through(self):
        """Four was the original list and felt repetitive within a session."""
        assert len(GENERAL_FACTS) >= 20

    def test_counted_facts_join_the_rotation(self):
        """The database-derived ones are what make the pool refresh itself."""
        counted = ["Right now I'm tracking 3,304 upcoming events."]
        seen = {greeting(random.Random(seed), extra_facts=counted) for seed in range(40)}
        assert any(counted[0] in text for text in seen)

    def test_the_greeting_works_with_no_counted_facts(self):
        """The database lookup can fail; the written ones still carry it."""
        assert "Did you know?" in greeting(extra_facts=[])


class TestGreetingAndFarewell:
    def test_the_greeting_names_the_assistant(self):
        assert ASSISTANT_NAME in greeting()

    def test_the_greeting_works_without_live_events(self):
        """The database lookup can fail; the chat still has to open."""
        assert ASSISTANT_NAME in greeting(tonight=None)

    def test_the_greeting_uses_live_events_when_given(self):
        text = greeting(tonight=[("Want comedy?", "Some Show in Old Town")])
        assert "Some Show in Old Town" in text
        assert "Want comedy?" in text

    def test_the_farewell_says_why_and_how_to_continue(self):
        text = farewell("turns")
        assert "start" in text.lower() or "New Chat" in text
        assert "questions" in text.lower()

    def test_the_farewell_names_the_right_limit(self):
        assert "questions" in farewell("turns").lower()
        assert "say in one conversation" in farewell("tokens")

    def test_the_farewell_signs_off_with_the_flag(self):
        """The Chicago flag's four six-pointed stars, which is also the logo."""
        assert "✶ ✶ ✶ ✶" in farewell()

    def test_every_sign_off_is_local(self):
        assert SIGN_OFFS
        assert all(line.strip() for line in SIGN_OFFS)


class TestTitleQuality:
    @pytest.mark.parametrize(
        "title,ok",
        [
            ("A WRINKLE IN TIME", True),
            ("Best of The Second City", True),
            ("Closed", False),
            ("doing our literal speed", False),
            ("Multiple Days", False),
            ("$10 cover", False),
            ("TBA", False),
        ],
    )
    def test_only_real_titles_reach_the_greeting(self, title, ok):
        assert reads_like_a_title(title) is ok
