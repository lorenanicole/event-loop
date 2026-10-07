"""The agent must know what day it is.

Asked for "free theater this weekend", it answered "I don't know today's
date, so I can't tell you which ones fall on this weekend" and then listed
events on November 1 and November 14. Date filtering inside search_local_db
was never affected - that is Python - but everything the model reasons about
itself was guesswork.
"""

from datetime import datetime, timedelta

from app.ai.chatbot import todays_date
from shared.localtime import CHICAGO


class TestTodaysDate:
    def test_it_states_the_current_date(self):
        today = datetime.now(CHICAGO)
        prompt = todays_date()
        assert f"{today:%B}" in prompt
        assert str(today.day) in prompt
        assert str(today.year) in prompt

    def test_it_names_chicago_and_the_timezone(self):
        """An events app for one city should not reason in UTC."""
        prompt = todays_date()
        assert "Chicago" in prompt
        assert f"{datetime.now(CHICAGO):%Z}" in prompt

    def test_it_resolves_the_weekend(self):
        """ "This weekend" is the single most common thing asked, and it is a
        date calculation the model should not be doing from scratch."""
        prompt = todays_date()
        now = datetime.now(CHICAGO)
        if now.weekday() >= 5:
            assert "today is the weekend" in prompt
        else:
            saturday = now + timedelta(days=(5 - now.weekday()) % 7)
            assert f"{saturday:%A %B}" in prompt
            assert str(saturday.day) in prompt

    def test_it_forbids_claiming_ignorance(self):
        assert "never claim you do not know the date" in todays_date()

    def test_it_is_evaluated_per_call_not_frozen(self):
        """A server started on Friday must not still believe it is Friday a
        week later, which a string baked into the static prompt would."""
        from app.ai import chatbot

        assert callable(chatbot.todays_date)
        # Registered as a dynamic system prompt rather than concatenated in.
        assert (
            "Today is" not in chatbot.agent._instructions
            if hasattr(chatbot.agent, "_instructions")
            else True
        )
