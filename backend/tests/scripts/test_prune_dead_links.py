"""Tests for what counts as "this event's page is gone".

Deleting events is the one irreversible thing this project does, so the rule
has to be narrow. Only the venue's own server saying the page is gone counts;
bot protection, server trouble and network failures never do.
"""

import pytest

from scripts.prune_dead_links import GONE


class TestGoneCodes:
    def test_404_is_gone(self):
        assert 404 in GONE

    def test_410_is_gone(self):
        """410 Gone is the explicit version of the same statement."""
        assert 410 in GONE

    @pytest.mark.parametrize("code", [401, 403, 405, 406])
    def test_bot_protection_is_not_gone(self, code):
        """These serve fine in a browser - Ticketmaster, Songkick and several
        venues reject a scripted request. 14 of 18 sources flagged by the
        link audit were this, not dead links."""
        assert code not in GONE

    @pytest.mark.parametrize("code", [500, 502, 503, 504])
    def test_server_trouble_is_not_gone(self, code):
        """A bad day at the venue's host is not evidence about the event."""
        assert code not in GONE

    @pytest.mark.parametrize("code", [200, 301, 302, 307, 308])
    def test_success_and_redirects_are_not_gone(self, code):
        assert code not in GONE

    def test_rate_limiting_is_not_gone(self):
        assert 429 not in GONE

    def test_nothing_else_crept_in(self):
        """A whitelist, so a future edit cannot widen this by accident."""
        assert {404, 410} == GONE
