"""The SerpAPI credential must not reach the logs.

httpx logs each request at INFO as a full URL. SerpAPI takes its key as a
query parameter, so the default level wrote the key into the log file in
plaintext on every search.
"""

import logging

import pytest

from app.logging import configure_logging


class TestHttpxIsQuiet:
    def test_httpx_does_not_log_request_urls(self):
        """INFO is the level at which httpx prints the URL and its query."""
        configure_logging("INFO")
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)

    def test_httpcore_is_quiet_too(self):
        configure_logging("INFO")
        assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)

    @pytest.mark.parametrize("name", ["httpx2", "httpcore2"])
    def test_the_vendored_copies_are_quiet(self, name):
        """pydantic-ai vendors its own httpx as "httpx2", which kept logging
        request URLs at INFO long after this was believed fixed."""
        configure_logging("INFO")
        assert not logging.getLogger(name).isEnabledFor(logging.INFO)

    def test_the_banner_is_suppressed(self):
        """pydantic-ai prints a five-line ASCII banner into the same log a
        scheduled run writes to."""
        import os

        configure_logging("INFO")
        assert os.environ.get("PYDANTIC_AI_NO_BANNER") == "1"

    def test_a_real_problem_in_httpx_still_gets_logged(self):
        """Silencing the request log must not hide genuine transport errors."""
        configure_logging("INFO")
        assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)

    def test_application_logging_is_unaffected(self):
        configure_logging("INFO")
        # Asserting the effective level would really be testing basicConfig,
        # which is a no-op once handlers exist. What matters is that this
        # module never sets a level on application loggers.
        assert logging.getLogger("app.ai.chatbot").level == logging.NOTSET

    def test_debug_level_does_not_reopen_the_leak(self):
        """Turning the app up to DEBUG is a normal thing to do while
        debugging, and must not start logging credentials."""
        configure_logging("DEBUG")
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
