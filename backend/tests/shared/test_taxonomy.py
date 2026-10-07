"""Tests for the parent/subtag taxonomy and the hybrid classifier.

The taxonomy exists because sources label events in their own words: stored
verbatim that produced 24 categories, four spellings of theater, and a do312
bucket called "Activism & Community Events" that filed a library's Teen Anime
Night under activism.
"""

import pytest

from shared.categories import (
    CATEGORY_TAXONOMY,
    PARENT_CATEGORIES,
    informative_subtags,
    parents_of,
    to_parents,
    unmapped_labels,
)


class TestTaxonomyShape:
    def test_every_parent_lists_itself_as_a_subtag(self):
        """A parent must map to itself, or a row already stored under the
        parent name would be treated as an unmapped label."""
        for parent, subtags in CATEGORY_TAXONOMY.items():
            assert parent in subtags, parent

    def test_parents_are_unique(self):
        assert len(PARENT_CATEGORIES) == len(set(PARENT_CATEGORIES))

    def test_the_table_has_no_duplicate_key_shadowing(self):
        """A dict literal silently keeps only the last of a repeated key, which
        would drop every subtag declared on the earlier one."""
        assert len(CATEGORY_TAXONOMY) == len(PARENT_CATEGORIES)


class TestParentsOf:
    def test_a_source_label_maps_to_its_parent(self):
        assert parents_of("Theatre & Performing Arts") == ["Theater"]

    def test_the_do312_activism_bucket_is_just_community(self):
        """A teen anime night at a library is not activism."""
        assert parents_of("Activism & Community Events") == ["Community"]

    def test_ticketmaster_arts_and_theatre_spans_both(self):
        """One segment covering both, holding a quarter of the theater data -
        forcing it either way mislabels the other half."""
        assert parents_of("Arts & Theatre") == ["Theater", "Arts"]

    def test_a_finer_label_rolls_up(self):
        assert parents_of("Arts & Crafts") == ["Arts"]

    def test_placeholders_roll_up_to_other(self):
        assert parents_of("Miscellaneous") == ["Other"]
        assert parents_of("Events") == ["Other"]

    def test_casing_does_not_matter(self):
        assert parents_of("arts & crafts") == ["Arts"]

    def test_an_unknown_label_keeps_its_own_name(self):
        """Not forced into Other: a new label is a gap in the table, and
        silently bucketing it is how it would stay a gap."""
        assert parents_of("Esports") == ["Esports"]

    def test_nothing_in_nothing_out(self):
        assert parents_of(None) == []
        assert parents_of("  ") == []


class TestToParents:
    def test_order_is_preserved_and_duplicates_dropped(self):
        assert to_parents(["Arts & Theatre", "Music", "Theater"]) == [
            "Theater",
            "Arts",
            "Music",
        ]


class TestInformativeSubtags:
    def test_a_finer_label_is_kept(self):
        assert informative_subtags(["Arts & Crafts"], ["Arts"]) == ["Arts & Crafts"]

    def test_a_label_identical_to_its_parent_is_not_repeated(self):
        assert informative_subtags(["Music"], ["Music"]) == []

    def test_a_placeholder_is_never_kept_as_a_subtag(self):
        """ "Events" under Other is the absence of a category; printing it on a
        card as though it were finer-grained is worse than printing nothing."""
        assert informative_subtags(["Events"], ["Other"]) == []
        assert informative_subtags(["Miscellaneous"], ["Other"]) == []


class TestUnmappedLabels:
    def test_reports_a_label_with_no_entry(self):
        assert unmapped_labels(["Music", "Esports"]) == ["Esports"]

    def test_a_mapped_label_is_not_reported(self):
        assert unmapped_labels(["Arts & Crafts", "Activism & Community Events"]) == []

    def test_health_and_wellness_is_mapped(self):
        """It was the one real category missing from the first draft, found by
        this report rather than by reading the table."""
        assert unmapped_labels(["Health & Wellness"]) == []


class TestSemanticFloor:
    def test_the_floor_is_where_the_sweep_put_it(self):
        """Measured in evaluate_categorization.py: 0.45 is where the hybrid
        beats the keyword rules on coverage AND precision at once. Lowering it
        raises coverage and loses precision, which is the wrong trade."""
        from shared.semantic_categories import SIMILARITY_FLOOR

        assert SIMILARITY_FLOOR == 0.45

    def test_every_exemplar_group_names_a_real_parent(self):
        from shared.semantic_categories import CATEGORY_EXEMPLARS

        for parent in CATEGORY_EXEMPLARS:
            assert parent in PARENT_CATEGORIES, parent

    def test_nothing_in_nothing_out(self):
        from shared.semantic_categories import semantic_category

        assert semantic_category(None) is None
        assert semantic_category("  ") is None


@pytest.mark.parametrize(
    "title,expected",
    [
        # The model reaches these; no keyword matches any of them.
        ("Drunk Shakespeare Chicago", "Theater"),
        ("Renegade Craft Fair", "Shopping"),
        ("Oktoberfestiversary", "Food & Drink"),
    ],
)
def test_the_model_classifies_titles_the_rules_miss(title, expected):
    from shared.categories import classify_all
    from shared.semantic_categories import semantic_category

    rules = [p for p in to_parents(classify_all(title, "Events")) if p != "Other"]
    assert not rules, f"a keyword now matches {title!r}; pick another example"
    found = semantic_category(title)
    assert found and found[0] == expected, found
