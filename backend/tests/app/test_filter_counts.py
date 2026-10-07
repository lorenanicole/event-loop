"""Tests for the faceted filter counts.

The counts used to be lifetime totals fetched once at startup, so with
"Arts & Crafts tonight" selected the Lake View tile still read 204 while the
search returned nothing. These pin down the two properties that fixes:
a tile's number equals what clicking it returns, and each facet stays
comparable to itself.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

ENDPOINT = "/api/events/filter-counts"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestFilterCounts:
    async def test_returns_both_facets(self, client):
        body = (await client.get(ENDPOINT)).json()
        assert "categories" in body and "neighborhoods" in body

    async def test_counts_are_positive_integers(self, client):
        body = (await client.get(ENDPOINT)).json()
        for facet in ("categories", "neighborhoods"):
            for row in body[facet]:
                assert isinstance(row["event_count"], int)
                # A zero would be a tile leading nowhere, so they are omitted.
                assert row["event_count"] > 0

    async def test_busiest_first(self, client):
        body = (await client.get(ENDPOINT)).json()
        counts = [r["event_count"] for r in body["neighborhoods"]]
        assert counts == sorted(counts, reverse=True)

    async def test_a_category_narrows_the_neighborhoods(self, client):
        """The whole point: neighborhood tiles reflect the chosen category."""
        everything = (await client.get(ENDPOINT)).json()
        narrowed = (await client.get(ENDPOINT, params={"category": "Theater"})).json()
        assert len(narrowed["neighborhoods"]) <= len(everything["neighborhoods"])

    async def test_a_neighborhood_does_not_narrow_the_neighborhoods(self, client):
        """Faceted: a facet never constrains itself, or every other tile
        would read zero and the grid would be unusable."""
        everything = (await client.get(ENDPOINT)).json()
        with_hood = (await client.get(ENDPOINT, params={"neighborhood": "Loop"})).json()
        assert len(with_hood["neighborhoods"]) == len(everything["neighborhoods"])

    async def test_a_neighborhood_narrows_the_categories(self, client):
        everything = (await client.get(ENDPOINT)).json()
        with_hood = (await client.get(ENDPOINT, params={"neighborhood": "Loop"})).json()
        assert len(with_hood["categories"]) <= len(everything["categories"])

    async def test_a_category_does_not_narrow_the_categories(self, client):
        everything = (await client.get(ENDPOINT)).json()
        with_cat = (await client.get(ENDPOINT, params={"category": "Theater"})).json()
        assert len(with_cat["categories"]) == len(everything["categories"])

    async def test_a_timeframe_narrows_both(self, client):
        everything = (await client.get(ENDPOINT)).json()
        tonight = (await client.get(ENDPOINT, params={"timeframe": "tonight"})).json()
        assert len(tonight["neighborhoods"]) <= len(everything["neighborhoods"])
        assert len(tonight["categories"]) <= len(everything["categories"])

    async def test_an_unrecognized_timeframe_applies_no_window(self, client):
        """Better to show everything than to fail on a word we cannot parse."""
        everything = (await client.get(ENDPOINT)).json()
        odd = (await client.get(ENDPOINT, params={"timeframe": "whenever"})).json()
        assert len(odd["neighborhoods"]) == len(everything["neighborhoods"])

    async def test_an_unknown_category_yields_no_neighborhoods(self, client):
        body = (await client.get(ENDPOINT, params={"category": "Nonexistent"})).json()
        assert body["neighborhoods"] == []

    async def test_the_count_matches_what_a_search_returns(self, client):
        """A tile's number has to equal the result of clicking it."""
        counts = (await client.get(
            ENDPOINT, params={"category": "Theater", "timeframe": "this weekend"}
        )).json()
        if not counts["neighborhoods"]:
            pytest.skip("no theater this weekend to compare against")
        top = counts["neighborhoods"][0]
        found = (await client.post("/api/search", json={
            "query": "events this weekend",
            "limit": 100,
            "neighborhood": top["name"],
            "category": "Theater",
        })).json()
        assert len(found) == top["event_count"]

    async def test_does_not_collide_with_the_event_id_route(self, client):
        """"filter-counts" must not be read as an event id."""
        response = await client.get(ENDPOINT)
        assert response.status_code == 200
