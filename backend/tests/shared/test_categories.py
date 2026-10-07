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
    classify_all,
    classify_from_title,
    extract_category_concepts,
    infer_category,
    normalize_category,
)

Base = declarative_base()


class Row(Base):
    __tablename__ = "row"
    id = Column(Integer, primary_key=True)
    category = Column(String)


class TestNormalizeCategory:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("music", "Music"),
            ("Music", "Music"),
            ("comedy", "Comedy"),
            ("arts", "Arts"),
            ("theater", "Theater"),
            ("community", "Community"),
        ],
    )
    def test_casing_is_settled(self, raw, expected):
        assert normalize_category(raw) == expected

    def test_trailing_whitespace_goes(self):
        assert normalize_category("Poetry & Literary ") == "Poetry & Literary"

    def test_internal_whitespace_collapses(self):
        assert normalize_category("Food  &   Drink") == "Food & Drink"

    def test_acronyms_survive(self):
        """ "LGBTQ" must not become "Lgbtq"."""
        assert normalize_category("lgbtq") == "LGBTQ"
        assert normalize_category("LGBTQ") == "LGBTQ"
        assert normalize_category("TV & Film") == "TV & Film"

    def test_deliberate_internal_capital_survives(self):
        """ "DJs" is spelled that way on purpose, and is not an acronym."""
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
    @pytest.mark.parametrize(
        "query,concept",
        [
            ("jazz tonight", "music"),
            ("stand up comedy show", "comedy"),
            ("broadway play drama", "theater"),
            ("art gallery exhibition", "art"),
            ("chicago bears game", "sports"),
            ("film screening", "film"),
            ("drag show", "lgbtq"),
        ],
    )
    def test_concept_is_recognized(self, query, concept):
        assert concept in extract_category_concepts(query)

    def test_regular_plural_matches(self):
        """ "workshops" has to find the "workshop" keyword."""
        assert "community" in extract_category_concepts("plant workshops this weekend")

    def test_no_concept_named(self):
        assert extract_category_concepts("random words") == []

    def test_a_word_inside_another_word_does_not_match(self):
        """ "art" inside "Bartlett" is not a category reference."""
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
        assert sorted(category_labels(["art"])) == ["Arts", "Arts & Crafts", "Arts & Culture"]

    def test_art_does_not_claim_the_theater_segment(self):
        """Otherwise "art galleries" answers with 185 Broadway shows."""
        assert "Arts & Theatre" not in category_labels(["art"])

    def test_art_uses_no_bare_prefix(self):
        """ "art%" would sweep in every Arts label, theater included."""
        assert category_prefixes(["art"]) == []


class TestCategoryFilter:
    def test_none_when_no_concepts(self):
        """Distinguishes "no category named" from "none matched"."""
        assert category_filter(Row.category, []) is None

    def test_art_matches_its_named_labels(self):
        clause = str(
            category_filter(Row.category, ["art"]).compile(compile_kwargs={"literal_binds": True})
        )
        assert "arts & crafts" in clause.lower()
        assert "arts & culture" in clause.lower()

    def test_theater_spans_all_three_stored_labels(self):
        clause = str(
            category_filter(Row.category, ["theater"]).compile(
                compile_kwargs={"literal_binds": True}
            )
        ).lower()
        assert "theater%" in clause and "theatre%" in clause
        assert "arts & theatre" in clause

    def test_prefix_not_substring(self):
        """ "%music%" would also match "Music & Film Fest" mid-string."""
        clause = str(
            category_filter(Row.category, ["music"]).compile(compile_kwargs={"literal_binds": True})
        )
        assert "%music%" not in clause.lower()
        assert "music%" in clause.lower()


class TestInferCategory:
    """Venue scrapers label every event with the venue's own category."""

    def test_wine_special_at_a_music_pub(self):
        """The case that prompted this: "music tonight" returning a wine deal."""
        assert (
            infer_category("Wine Wednesday Half-Priced Wine by the Bottle", "Music")
            == "Food & Drink"
        )

    def test_sewing_class_at_a_music_hall(self):
        assert infer_category("SEWING FREAK", "Music") == "Arts & Crafts"

    def test_comedy_wins_over_open_mic(self):
        """Ordered rules: a comedy open mic is comedy, not an open mic night."""
        assert infer_category("Comedy Open Mic", "Music") == "Comedy"

    def test_a_music_open_mic_is_an_open_mic(self):
        assert infer_category("Schubas Open Mic", "Music") == "Karaoke/Trivia/Open Mics"

    def test_comedy_jam_under_ticketmasters_segment(self):
        assert infer_category("Sweetest Day Comedy Jam", "Arts & Theatre") == "Comedy"

    def test_an_ordinary_gig_is_left_alone(self):
        assert infer_category("Kiefer w/ Shibo", "Music") == "Music"

    def test_a_concert_billed_live_to_film_stays_a_concert(self):
        """Why "film" is not a rule: it matched concerts, not screenings."""
        assert infer_category("Disney's Encanto In Concert Live to Film", "Theater") == "Theater"

    def test_craft_beer_is_not_arts_and_crafts(self):
        """Why "craft" is not a rule."""
        assert infer_category("Craft Beer Fest", "Music") == "Music"

    def test_a_workshop_is_not_assumed_to_be_crafts(self):
        """Why "workshop" is not a rule - it is far too broad."""
        assert infer_category("Songwriting Workshop", "Music") == "Music"

    def test_missing_title_returns_the_fallback(self):
        assert infer_category(None, "Music") == "Music"
        assert infer_category("", "Music") == "Music"


class TestClassifyFromTitle:
    """External sources hand over a title and no category."""

    def test_online_search_is_not_a_category(self):
        """The case that prompted this: it describes where, not what."""
        assert classify_from_title("Chicago Jazz Festival") == "Music"

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Chicago Jazz Festival", "Music"),
            ("Comedy Open Mic Night", "Comedy"),
            ("Art Gallery Opening Reception", "Arts"),
            ("Yoga in Millennium Park", "Health & Wellness"),
            ("Pride Parade 2026", "LGBTQ"),
            ("Film Screening: Casablanca", "Film"),
            ("Astronomy on Tap", "Tech / Educational"),
            ("In Conversation with Neil deGrasse Tyson", "Tech / Educational"),
        ],
    )
    def test_classified_from_the_title(self, title, expected):
        assert classify_from_title(title) == expected

    def test_narrow_rules_take_precedence(self):
        """infer_category is higher precision, so it wins over the concepts."""
        assert classify_from_title("Wine Wednesday at the Jazz Club") == "Food & Drink"

    def test_falls_back_rather_than_inventing(self):
        assert classify_from_title("Some Unclassifiable Happening") == "Events"

    def test_missing_title_falls_back(self):
        assert classify_from_title(None) == "Events"
        assert classify_from_title("") == "Events"

    def test_fallback_is_overridable(self):
        assert classify_from_title("", fallback="Other") == "Other"


class TestClassifyAll:
    """One event often belongs to several categories.

    Storing a single label made an event findable under one and invisible
    under the others: a trans pride festival was Community and not LGBTQ, a
    drag show at a music venue was Music and not LGBTQ.
    """

    def test_trans_pride_is_community_and_lgbtq(self):
        assert classify_all(
            "Transilience: Chicago Trans Pride Festival at Eckhart", "Community"
        ) == ["Community", "LGBTQ"]

    def test_a_drag_show_at_a_music_venue_is_both(self):
        assert classify_all("MALL DRAG CHICAGO", "Music") == ["Music", "LGBTQ"]

    def test_a_drag_show_at_a_theater_is_both(self):
        assert classify_all("Kiki Queens - Drag to the Future", "Theater") == ["Theater", "LGBTQ"]

    def test_a_user_group_meeting_is_tech_and_community(self):
        assert classify_all("CHIPY __MAIN__ MEETING", "Tech / Educational") == [
            "Tech / Educational",
            "Community",
        ]

    def test_the_primary_is_whatever_single_label_would_have_chosen(self):
        """Nothing that displays `category` had to change."""
        for title, fallback in [
            ("MALL DRAG CHICAGO", "Music"),
            ("SEWING FREAK", "Music"),
            ("Kiefer w/ Shibo", "Music"),
        ]:
            assert classify_all(title, fallback)[0] == infer_category(title, fallback)

    def test_an_overridden_venue_category_does_not_come_back_as_a_secondary(self):
        """The crux: a sewing class at a music hall is not also Music.

        Keeping it would put the class straight back into "music tonight in
        Avondale", which is the complaint infer_category exists to fix.
        """
        assert classify_all("SEWING FREAK", "Music") == ["Arts & Crafts"]
        assert classify_all("Wine Wednesday Half-Priced Wine", "Music") == ["Food & Drink"]

    def test_an_ordinary_event_keeps_one_label(self):
        assert classify_all("Kiefer w/ Shibo", "Music") == ["Music"]

    def test_capped(self):
        from shared.categories import MAX_CATEGORIES

        labels = classify_all("Drag Comedy Yoga Film Brunch Workshop Gallery Concert", "Music")
        assert len(labels) <= MAX_CATEGORIES

    def test_no_duplicates(self):
        labels = classify_all("Comedy Comedy Comedy Show", "Comedy")
        assert len(labels) == len(set(labels))

    def test_labels_are_normalized(self):
        assert classify_all("a gig", "music")[0] == "Music"

    def test_missing_title_still_yields_the_venue_category(self):
        assert classify_all(None, "Music") == ["Music"]
