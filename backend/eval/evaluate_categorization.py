"""Score the categorization strategies against a hand-labelled set.

This exists because the alternative was what it replaced: noticing a
misfiled event, adding a keyword, noticing another, adding another keyword.
That grows a word list nobody can reason about and never says whether the
last change helped or hurt.

So each strategy is scored on the same 69 titles - the ones that arrived with
no category at all, which is where classification actually has to work:

  rules     the keyword vocabulary in `shared.categories`
  semantic  nearest category exemplar by embedding, above a floor
  hybrid    rules first, semantic where the rules are silent

Three numbers per strategy, and all three matter:

  coverage   how many titles it labelled at all
  precision  of those, how many matched the hand label
  correct    labelled and right, as a share of everything

Precision is weighted above coverage on purpose. A wrong category is worse
than none: it puts an event under a filter where somebody will not expect it
and hides it from the one where they would. Declining to answer is a valid
move, which is why titles labelled `null` in the set - genuinely ambiguous -
are excluded from scoring rather than counted as failures.

Usage:
    python evaluate_categorization.py
    python evaluate_categorization.py --sweep     # try every floor
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from shared.categories import classify_all, to_parents

LABELS = Path(__file__).parent / "category_labels.json"
GENERIC = {"Other", "Events"}


def load_labels() -> dict[str, str]:
    data = json.loads(LABELS.read_text())["labels"]
    return {title: expected for title, expected in data.items() if expected}


def rules_label(title: str) -> str | None:
    """What the keyword vocabulary alone makes of a title."""
    parents = [p for p in to_parents(classify_all(title, "Events")) if p not in GENERIC]
    return parents[0] if parents else None


def semantic_label(title: str, floor: float) -> str | None:
    from shared import semantic_categories

    original = semantic_categories.SIMILARITY_FLOOR
    semantic_categories.SIMILARITY_FLOOR = floor
    try:
        found = semantic_categories.semantic_category(title)
    finally:
        semantic_categories.SIMILARITY_FLOOR = original
    return found[0] if found else None


def score(predictions: dict[str, str | None], expected: dict[str, str]) -> dict:
    labelled = {t: p for t, p in predictions.items() if p}
    right = sum(1 for t, p in labelled.items() if p == expected[t])
    total = len(expected)
    return {
        "coverage": len(labelled) / total if total else 0.0,
        "precision": right / len(labelled) if labelled else 0.0,
        "correct": right / total if total else 0.0,
        "n_labelled": len(labelled),
        "n_right": right,
        "n_total": total,
    }


def report(name: str, result: dict) -> None:
    print(
        f"{name:26} coverage {result['coverage']:5.0%}  "
        f"precision {result['precision']:5.0%}  "
        f"correct {result['correct']:5.0%}   "
        f"({result['n_right']}/{result['n_labelled']} of {result['n_total']})"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true", help="score every similarity floor")
    parser.add_argument(
        "--floor", type=float, default=None, help="similarity floor for the single run"
    )
    parser.add_argument(
        "--errors", action="store_true", help="list what the chosen hybrid gets wrong"
    )
    args = parser.parse_args()

    expected = load_labels()
    titles = list(expected)
    print(f"{len(titles)} hand-labelled titles (ambiguous ones excluded from scoring)\n")

    rules = {t: rules_label(t) for t in titles}
    report("rules only", score(rules, expected))

    from shared import semantic_categories

    default_floor = args.floor or semantic_categories.SIMILARITY_FLOOR

    floors = (
        [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55] if args.sweep else [default_floor]
    )

    print()
    print(f"{'strategy':26} {'':10}")
    best = None
    for floor in floors:
        sem = {t: semantic_label(t, floor) for t in titles}
        hybrid = {t: rules[t] or sem[t] for t in titles}
        sem_score = score(sem, expected)
        hyb_score = score(hybrid, expected)
        report(f"semantic  floor {floor:.2f}", sem_score)
        report(f"hybrid    floor {floor:.2f}", hyb_score)
        if best is None or hyb_score["correct"] > best[1]["correct"]:
            best = (floor, hyb_score, hybrid)
        print()

    floor, hyb_score, hybrid = best
    print(
        f"best hybrid floor: {floor:.2f}  "
        f"({hyb_score['correct']:.0%} of all titles correct, "
        f"{hyb_score['precision']:.0%} precision)"
    )

    if args.errors:
        print("\nwhat the hybrid gets wrong:")
        for title in titles:
            got = hybrid[title]
            if got and got != expected[title]:
                print(f"  {title[:48]:50} got {got:20} want {expected[title]}")
        print("\nwhat it declines:")
        for title in titles:
            if not hybrid[title]:
                print(f"  {title[:48]:50} want {expected[title]}")


if __name__ == "__main__":
    main()
