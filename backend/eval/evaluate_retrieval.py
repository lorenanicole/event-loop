#!/usr/bin/env python3
"""
Retrieval quality harness for EventLoop's search_local_db tool.

Runs each query in eval/retrieval_queries.json through the same search path
the chat agent uses and reports pass/fail against hand-labelled expectations.

Usage:
    cd backend
    PYTHONPATH=src python evaluate_retrieval.py
    PYTHONPATH=src python evaluate_retrieval.py --verbose
    PYTHONPATH=src python evaluate_retrieval.py --query "jazz tonight"

A query PASSES if:
  - It returns >= min_results events, AND
  - At least one top-5 result matches at least one must_match keyword
    (checked against event name + category + neighborhood, case-insensitive), AND
  - No top-5 result name contains any must_not_match keyword.

A query with min_results=0 that returns nothing passes vacuously.

Run before and after changing LOCAL_CONFIDENCE_FLOOR, MIN_SIMILARITY, or the
SQL candidate limit — those numbers have never been validated against real queries.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

EVAL_FILE = Path(__file__).parent / "retrieval_queries.json"
TOP_K = 5


async def run_search(query: str, db) -> list:
    """Mirror search_local_db: SQL candidates → semantic rerank → top-K."""
    from app.ai.search_query import (
        extract_date_range,
        extract_keywords,
        extract_neighborhoods,
        strip_neighborhoods,
    )
    from app.ai.search_ranking import filter_top_results
    from app.ai.semantic_index import event_index
    from sqlalchemy import and_, or_, select

    from shared.categories import category_filter, extract_category_concepts
    from shared.database import start_of_day, upcoming_events_filter
    from shared.database.models import EventModel, NeighborhoodModel

    ql = query.lower()
    neighborhoods = await extract_neighborhoods(db, ql)
    keywords = strip_neighborhoods(extract_keywords(ql), neighborhoods, query=ql)
    categories = extract_category_concepts(ql)
    date_range = extract_date_range(ql)

    q = select(EventModel)
    filters = []

    if neighborhoods:
        q = q.join(NeighborhoodModel, EventModel.neighborhood_id == NeighborhoodModel.id).filter(
            NeighborhoodModel.name.in_(neighborhoods)
        )

    if keywords:
        filters.append(or_(*[EventModel.name.ilike(f"%{kw}%") for kw in keywords]))
    if categories:
        cond = category_filter(EventModel.category, categories, EventModel.categories)
        if cond is not None:
            filters.append(cond)
    if filters:
        q = q.filter(or_(*filters))

    q = q.filter(upcoming_events_filter())

    if date_range:
        s, e = date_range
        ws = start_of_day(s)
        q = q.filter(
            and_(
                EventModel.date <= e,
                or_(
                    EventModel.date_end >= ws,
                    and_(EventModel.date_end.is_(None), EventModel.date >= ws),
                ),
            )
        )

    q = q.order_by(EventModel.date.asc()).limit(50)
    result = await db.execute(q)
    candidates = result.scalars().all()

    hood_ids = {e.neighborhood_id for e in candidates if e.neighborhood_id}
    if hood_ids:
        rows = await db.execute(
            select(NeighborhoodModel.id, NeighborhoodModel.name).where(
                NeighborhoodModel.id.in_(hood_ids)
            )
        )
        hood_map = dict(rows.all())
        for ev in candidates:
            ev.neighborhood_name = hood_map.get(ev.neighborhood_id)

    sem = event_index.scores_for(query, [e.id for e in candidates])
    return filter_top_results(
        candidates, query, keywords, categories, limit=TOP_K, semantic_scores=sem
    )


def _matches_any(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


def _evaluate(entry: dict, results: list) -> tuple[bool, str]:
    """Return (passed, reason)."""
    min_r = entry.get("min_results", 0)
    must = entry.get("must_match", [])
    must_not = entry.get("must_not_match", [])

    if len(results) < min_r:
        return False, f"got {len(results)} results, need >= {min_r}"

    if not results:
        return True, "0 results, min_results=0 (vacuous pass)"

    for ev in results:
        combined = f"{ev.title} {ev.category or ''}"
        for bad in must_not:
            if bad.lower() in combined.lower():
                return False, f"must_not '{bad}' found in '{ev.title}'"

    if must:
        for ev in results:
            combined = f"{ev.title} {ev.category or ''} {ev.neighborhood or ''}"
            if _matches_any(combined, must):
                hit = next(k for k in must if k.lower() in combined.lower())
                return True, f"matched '{hit}' in '{ev.title}'"
        return False, f"no top-{TOP_K} result matched any of {must}"

    return True, "no must_match required"


async def main(verbose: bool = False, single_query: str | None = None) -> int:
    from dotenv import load_dotenv

    env = next(
        (p / ".env" for p in Path(__file__).resolve().parents if (p / ".env").is_file()), None
    )
    if env:
        load_dotenv(env)

    from app.ai.semantic_index import event_index

    from shared.database import AsyncSessionLocal, init_db

    await init_db()

    async with AsyncSessionLocal() as db:
        print("Warming semantic index...", end=" ", flush=True)
        n = await event_index.rebuild(db)
        print(f"{n} events indexed.\n")

        queries = json.loads(EVAL_FILE.read_text())["queries"]
        if single_query:
            queries = [q for q in queries if single_query.lower() in q["query"].lower()]
            if not queries:
                print(f"No query matching '{single_query}'")
                return 0

        passed = failed = 0
        for entry in queries:
            q = entry["query"]
            try:
                results = await run_search(q, db)
            except Exception as exc:
                print(f"  ERROR  {q!r}: {exc}")
                failed += 1
                continue

            ok, reason = _evaluate(entry, results)
            label = "  PASS " if ok else "  FAIL "
            if ok:
                passed += 1
            else:
                failed += 1

            if verbose or not ok:
                print(f"{label} {q!r}")
                print(f"         → {reason}")
                for i, ev in enumerate(results, 1):
                    hood = f" [{ev.neighborhood}]" if ev.neighborhood else ""
                    print(
                        f"         {i}. {ev.title}{hood} ({ev.category}) conf={ev.confidence:.2f}"
                    )
                print()
            else:
                print(f"{label} {q!r}  ({reason})")

    total = passed + failed
    pct = 100 * passed // total if total else 0
    print(f"\nResults: {passed}/{total} passed ({pct}%)")
    if failed:
        print("Re-run with --verbose to see all result details.")
    return failed


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Retrieval quality harness")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--query", "-q", help="Run only queries matching this substring")
    args = p.parse_args()
    sys.exit(0 if not asyncio.run(main(args.verbose, args.query)) else 1)
