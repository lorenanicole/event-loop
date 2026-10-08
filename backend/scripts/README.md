# Scripts

Operational tools for the EventLoop backend. All are run from `backend/` with
`PYTHONPATH=src python scripts/<name>.py [args]`.

---

## Scheduled / automated

| Script | What it does | When to run |
|---|---|---|
| `additive_scrape.py` | Runs all active scrapers (venue + external), upserts new events | Nightly cron or on-demand refresh |
| `prune_dead_links.py` | HTTP-checks every `origination_url`, removes 404s | Weekly |

---

## One-off data fixes (run manually after schema or source changes)

| Script | What it does |
|---|---|
| `backfill_event_costs.py` | Fetches each event page and extracts prices not in the original scrape |
| `backfill_neighborhoods.py` | Re-runs neighborhood placement for events that have coordinates but no neighborhood |
| `load_neighborhood_boundaries.py` | Loads the 98 Chicago neighborhood boundary polygons into the DB (run once or after boundary updates) |
| `place_park_district.py` | Assigns Park District neighborhood to events scraped from Chicago Park District |
| `recategorize.py` | Re-runs category classification over existing events; useful after taxonomy changes |
| `dedupe_events.py` | Finds and removes duplicate rows (same URL, same date) |

---

## Rescrape / safety tools

| Script | What it does |
|---|---|
| `clean_rescrape.py` | Drops venue-sourced events and re-scrapes from scratch (destructive — check `db_safety.py` first) |
| `db_safety.py` | Snapshots event counts by source and neighborhood before a run; diffs afterwards and flags sources that lost events |

---

## Diagnostics

| Script | What it does |
|---|---|
| `health.py` | Prints scraper config summary and DB row counts; useful for a quick sanity check |

---

## Eval harnesses

Eval harnesses live in `../eval/` alongside their labelled data:

| Script | What it measures |
|---|---|
| `../eval/evaluate_categorization.py` | Category classification accuracy against 73 hand-labelled titles |
| `../eval/evaluate_retrieval.py` | Retrieval quality against 20 hand-labelled queries (baseline: 18/20) |
