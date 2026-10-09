# EventLoop Project Structure

EventLoop is a monorepo. The Python API, chatbot, scrapers, and shared data
models live in one backend package and use the same SQLite database. The browser
client is a TypeScript/Vite application.

## Backend (`backend/`)

The backend package uses Python 3.15 in the current local environment; its
`pyproject.toml` declares Python 3.15 or newer. Scrapers are not a separate
runtime/package: they use the backend's Python environment and database.

### `src/app/` — FastAPI server

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI application, lifespan hooks, middleware |
| `app/api/routes.py` | Event, search, and admin endpoints |
| `app/api/chat.py` | SSE chat streaming endpoint |
| `app/api/analytics.py` | Telemetry and audit log endpoints |
| `app/api/sse.py` | SSE event types and wire formatter |
| `app/chat/agent.py` | PydanticAI REACT agent and system prompt |
| `app/chat/chatbot.py` | search_local_db tool, SearchPolicy, scoring |
| `app/chat/executor.py` | Chat state machine and SSE orchestration |
| `app/chat/intent_classifier.py` | Three-tier intent routing (Haiku) |
| `app/chat/persona.py` | Loopara's voice, Chicago facts, greeting |
| `app/chat/search_query.py` | Keyword and date extraction (shared) |
| `app/chat/search_ranking.py` | Relevance scoring and ScoredEvent |
| `app/chat/semantic_index.py` | model2vec in-memory embedding index |
| `app/chat/threads.py` | Thread lifecycle, context summary, history loading |
| `app/chat/web_search.py` | SerpAPI tool and event persistence pipeline |
| `app/security.py` | Prompt injection detection, admin key dependency |
| `app/resilience.py` | Circuit breaker, retry, error classification |
| `app/telemetry.py` | OpenTelemetry counters and persistence |
| `app/logging.py` | structlog configuration |

### `src/scrapers/` — Data ingestion

| Path | Purpose |
|---|---|
| `scrapers/venue/chicago_events_scraper.py` | Orchestrator; re-exports helpers |
| `scrapers/venue/venue_scraper.py` | VenueScraper engine, VenueConfig, parse_cost |
| `scrapers/venue/venues.py` | CHICAGO_VENUES — canonical venue catalog |
| `scrapers/venue/extractors.py` | Reusable extractors (extract_tribe_events, etc.) |
| `scrapers/venue/venue_parsing.py` | Date, title, and price parsing helpers |
| `scrapers/sources/do312.py` | do312.com (primary Chicago aggregator) |
| `scrapers/sources/eventbrite.py` | Eventbrite API |
| `scrapers/sources/ticketmaster.py` | Ticketmaster API |
| `scrapers/sources/chicago_park_district.py` | Chicago Park District API |
| `scrapers/sources/broadway_in_chicago.py` | broadwayinchicago.com HTML |
| `scrapers/sources/bandsintown.py` | Bandsintown API |
| `scrapers/sources/yourchicagoguide.py` | yourchicagoguide.com HTML |
| `scrapers/sources/eventscom.py` | events.com (unscheduled; uses Playwright, not wired into scheduled runs) |
| `scrapers/sources/timeoutchicago.py` | Time Out Chicago (unscheduled) |

See [SCRAPERS.md](SCRAPERS.md) for the active / unscheduled / retired inventory.

### `src/shared/` — Used by both app and scrapers

| Path | Purpose |
|---|---|
| `shared/database/` | SQLAlchemy async engine, models, session factory, filters |
| `shared/geo/` | Neighborhood boundary polygons, point-in-polygon resolver, alias tables |
| `shared/categories.py` | Category taxonomy, keyword rules, classify_all |
| `shared/semantic_categories.py` | Embedding-based category fallback (model2vec) |
| `shared/schemas.py` | Pydantic API contracts: Event, EventCreate, EventSearch |
| `shared/enrichment.py` | Regex extraction for cost, age range, indoor/outdoor |
| `shared/pricing.py` | Per-venue price parsing from origination pages |
| `shared/locality.py` | Chicago vs suburban address detection |
| `shared/localtime.py` | Chicago timezone constant |

### `tests/` — Test suite (569 tests)

```
tests/
|-- app/        # API endpoints, chat pipeline, intent routing, security, resilience,
|               #   persona, chatbot scoring, thread lifecycle, background tasks, etc.
|-- scrapers/   # Extractor logic and scraper parsing
|-- shared/     # Category taxonomy, pricing, enrichment, locality
`-- scripts/    # Ops script tests (prune_dead_links)
```

Run with:

```bash
cd backend
PYTHONPATH=src:. .venv/bin/python -m pytest tests/
```

### `scripts/` — Operational tools

See [`scripts/README.md`](scripts/README.md). Run from `backend/` with `PYTHONPATH=src:.`.

### `eval/` — Evaluation harnesses

| File | What it measures |
|---|---|
| `evaluate_categorization.py` | Category classification accuracy (73 hand-labelled titles) |
| `evaluate_retrieval.py` | Retrieval quality (20 hand-labelled queries; baseline 18/20) |

## Frontend (`frontend/`)

TypeScript with Vite, not React. `frontend/src/main.ts` starts the event search
UI and chat widget. Run with `npm run dev` from `frontend/`.

## Tasks (`tasks.py`)

Root-level Invoke tasks call the backend's `.venv`:

```bash
invoke test      # all tests + coverage
invoke lint      # ruff check
invoke format    # ruff format
invoke backend   # start uvicorn dev server
invoke frontend  # start Vite dev server
```

## Benchmarks (`benchmarks/`)

`perf_compare.py` contains small Python interpreter microbenchmarks for imports,
dict/list ops, JSON, and async task scheduling. These are not API, chatbot,
database, or scraper throughput measurements; saved result files are individual
runs, not controlled performance evidence.
