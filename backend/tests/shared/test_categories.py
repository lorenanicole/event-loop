"""Tests for the shared category vocabulary.

Casing is normalized because sources disagree meaninglessly ("music" vs
"Music"); wording is not, because "Arts & Crafts" and "Arts & Culture" are
genuinely different. Matching therefore has to span the variants by prefix.
"""

import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

from shared.categories import (
    category_filter,
    category_labels,
    category_prefixes,
    extract_category_concepts,
    normalize_category,
)

Base = declarative_base()


class Row(Base):
    __tablename__ = "row"
    id = Column(Integer, primary_key=True)
    category = Column(String)


class TestNormalizeCategory:
    @pytest.mark.parametrize("raw,expected", [
        ("music", "Music"),
        ("Music", "Music"),
        ("comedy", "Comedy"),
        ("arts", "Arts"),
        ("theater", "Theater"),
        ("community", "Community"),
    ])
    def test_casing_is_settled(self, raw, expected):
        assert normalize_category(raw) == expected

    def test_trailing_whitespace_goes(self):
        assert normalize_category("Poetry & Literary ") == "Poetry & Literary"

    def test_internal_whitespace_collapses(self):
        assert normalize_category("Food  &   Drink") == "Food & Drink"

    def test_acronyms_survive(self):
        """"LGBTQ" must not become "Lgbtq"."""
        assert normalize_category("lgbtq") == "LGBTQ"
        assert normalize_category("LGBTQ") == "LGBTQ"
        assert normalize_category("TV & Film") == "TV & Film"

    def test_deliberate_internal_capital_survives(self):
        """"DJs" is spelled that way on purpose, and is not an acronym."""
        assert normalize_category("Parties & DJs") == "Parties & DJs"

    def test_slash_separated_words_each_capitalized(self):
        assert normalize_category("karaoke/trivia/open mics") == "Karaoke/Trivia/Open Mics"

    def test_wording_is_never_changed(self):
        """Two Arts categories are two categories, not one to be merged."""
        assert normalize_category("Arts & Crafts") == "Arts & Crafts"
        assert normalize_category("Arts & Culture") == "Arts & Culture"

    def test_empty_and_none(self):
        assert normalize_category("") is None
        assert normalize_category("   ") is None
        assert normalize_category(None) is None


class TestExtractCategoryConcepts:
    @pytest.mark.parametrize("query,concept", [
        ("jazz tonight", "music"),
        ("stand up comedy show", "comedy"),
        ("broadway play drama", "theater"),
        ("art gallery exhibition", "art"),
        ("chicago bears game", "sports"),
        ("film screening", "film"),
        ("drag show", "lgbtq"),
    ])
    def test_concept_is_recognized(self, query, concept):
        assert concept in extract_category_concepts(query)

    def test_regular_plural_matches(self):
        """"workshops" has to find the "workshop" keyword."""
        assert "community" in extract_category_concepts("plant workshops this weekend")

    def test_no_concept_named(self):
        assert extract_category_concepts("random words") == []

    def test_a_word_inside_another_word_does_not_match(self):
        """"art" inside "Bartlett" is not a category reference."""
        assert "art" not in extract_category_concepts("show at bartlett hall")

    def test_both_theatre_spellings_reach_one_concept(self):
        assert extract_category_concepts("theatre") == extract_category_concepts("theater")


class TestCategoryPrefixes:
    def test_theater_covers_both_spellings(self):
        """Sources store both, so one concept needs both prefixes."""
        assert sorted(category_prefixes(["theater"])) == ["theater", "theatre"]

    def test_film_also_covers_tv(self):
        assert "tv" in category_prefixes(["film"])

    def test_unknown_concept_contributes_nothing(self):
        assert category_prefixes(["nonsense"]) == []


class TestConceptLabels:
    """Labels a concept claims outright, where a prefix cannot reach them."""

    def test_theater_claims_ticketmasters_segment(self):
        """Ticketmaster files its theater under "Arts & Theatre"."""
        assert "Arts & Theatre" in category_labels(["theater"])

    def test_art_names_the_genuine_arts_labels(self):
        assert sorted(category_labels(["art"])) == [
            "Arts", "Arts & Crafts", "Arts & Culture"
        ]

    def test_art_does_not_claim_the_theater_segment(self):
        """Otherwise "art galleries" answers with 185 Broadway shows."""
        assert "Arts & Theatre" not in category_labels(["art"])

    def test_art_uses_no_bare_prefix(self):
        """"art%" would sweep in every Arts label, theater included."""
        assert category_prefixes(["art"]) == []


class TestCategoryFilter:
    def test_none_when_no_concepts(self):
        """Distinguishes "no category named" from "none matched"."""
        assert category_filter(Row.category, []) is None

    def test_art_matches_its_named_labels(self):
        clause = str(category_filter(Row.category, ["art"]).compile(
            compile_kwargs={"literal_binds": True}))
        assert "arts & crafts" in clause.lower()
        assert "arts & culture" in clause.lower()

    def test_theater_spans_all_three_stored_labels(self):
        clause = str(category_filter(Row.category, ["theater"]).compile(
            compile_kwargs={"literal_binds": True})).lower()
        assert "theater%" in clause and "theatre%" in clause
        assert "arts & theatre" in clause

    def test_prefix_not_substring(self):
        """"%music%" would also match "Music & Film Fest" mid-string."""
        clause = str(category_filter(Row.category, ["music"]).compile(
            compile_kwargs={"literal_binds": True}))
        assert "%music%" not in clause.lower()
        assert "music%" in clause.lower()
