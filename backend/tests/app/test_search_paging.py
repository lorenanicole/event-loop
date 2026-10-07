"""Tests for paging through search results.

The UI showed the first 20 of 3,000+ events with no way to reach the rest,
because POST /api/search took a limit but no offset.
"""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

SEARCH = "/api/search"
TODAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def effective(event: dict) -> str:
    """The date the feed sorts on: the later of the start date and today.

    An event already under way is on today, so it sorts with today rather than
    with the month it opened in. Mirrors `feed_order`.
    """
    return max(event["date"], TODAY)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def ids(client, **body):
    payload = {"query": "events", "limit": 20, **body}
    response = await client.post(SEARCH, json=payload)
    assert response.status_code == 200, response.text
    return [e["id"] for e in response.json()]


@pytest.mark.asyncio
class TestPaging:
    async def test_skip_defaults_to_the_first_page(self, client):
        assert await ids(client) == await ids(client, skip=0)

    async def test_consecutive_pages_do_not_overlap(self, client):
        """The bug this guards: date alone is not unique, so without an id
        tiebreak a row could land on two pages or on neither."""
        first, second = await ids(client), await ids(client, skip=20)
        assert set(first).isdisjoint(second)

    async def test_pages_are_stable_across_identical_requests(self, client):
        assert await ids(client, skip=20) == await ids(client, skip=20)

    async def test_a_page_overlapping_by_one_shifts_by_one(self, client):
        """Offsets are row offsets, not page numbers."""
        first = await ids(client)
        shifted = await ids(client, skip=1)
        assert shifted[:-1] == first[1:]

    async def test_paging_past_the_end_is_empty_not_an_error(self, client):
        response = await client.post(SEARCH, json={"query": "events", "limit": 20, "skip": 100000})
        assert response.status_code == 200
        assert response.json() == []

    async def test_a_negative_skip_is_rejected(self, client):
        response = await client.post(SEARCH, json={"query": "events", "skip": -1})
        assert response.status_code == 422

    async def test_paging_respects_a_filter(self, client):
        """Paging a filtered list must stay inside the filter."""
        page = await client.post(SEARCH, json={
            "query": "events", "limit": 5, "skip": 5, "category": "Music",
        })
        assert page.status_code == 200
        assert all(
            e["category"] == "Music" or "Music" in (e.get("categories") or [])
            for e in page.json()
        )

    async def test_results_stay_in_date_order_across_pages(self, client):
        """Soonest first, and the sequence continues across the page boundary."""
        first = await client.post(SEARCH, json={"query": "events", "limit": 20, "skip": 0})
        second = await client.post(SEARCH, json={"query": "events", "limit": 20, "skip": 20})
        dates = [effective(e) for e in first.json()] + [effective(e) for e in second.json()]
        assert dates == sorted(dates)

    async def test_an_event_already_under_way_sorts_as_today(self, client):
        """A multi-day run that opened months ago is on today, so it belongs in
        today's slot - not ahead of everything on its original start date,
        which pushed tonight's shows eight pages down."""
        page = await client.post(SEARCH, json={"query": "events", "limit": 40})
        started_earlier = [e for e in page.json() if e["date"] < TODAY]
        assert all(e.get("date_end", "") >= TODAY for e in started_earlier), started_earlier

    async def test_one_day_reads_alphabetically(self, client):
        """Within a date, name ascending.

        Name was tried as the primary key and is wrong here: punctuation sorts
        ahead of letters, so page one filled with mis-scraped "$10 cover"
        titles while tonight's events sat pages deep. It belongs behind date.
        """
        page = await client.post(SEARCH, json={"query": "events", "limit": 100})
        by_date: dict[str, list[str]] = {}
        for event in page.json():
            by_date.setdefault(effective(event), []).append((event["name"] or "").lower())
        for names in by_date.values():
            assert names == sorted(names)

    async def test_the_first_page_is_not_all_punctuation(self, client):
        """The regression that prompted the reorder: an alphabetical feed
        opened on rows whose title is a cover charge."""
        page = await client.post(SEARCH, json={"query": "events", "limit": 20})
        titles = [(e["name"] or "") for e in page.json()]
        leading_junk = [t for t in titles if t[:1] in "$(&\"'"]
        assert len(leading_junk) < len(titles) / 2, titles
