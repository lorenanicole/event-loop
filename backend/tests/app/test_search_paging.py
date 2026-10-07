"""Tests for paging through search results.

The UI showed the first 20 of 3,000+ events with no way to reach the rest,
because POST /api/search took a limit but no offset.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

SEARCH = "/api/search"


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
        first = await client.post(SEARCH, json={"query": "events", "limit": 20, "skip": 0})
        second = await client.post(SEARCH, json={"query": "events", "limit": 20, "skip": 20})
        dates = [e["date"] for e in first.json()] + [e["date"] for e in second.json()]
        assert dates == sorted(dates)
