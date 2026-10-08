# EventLoop: Chicago Events Chatbot

**An event discovery app for Chicago, with a Python backend, SQLite event catalog, and a TypeScript/Vite frontend.** The backend and scrapers share one Python package and database; the current environment uses Python 3.15.

## Project Structure

```
eventloop/
|-- backend/
|   |-- src/app/                # FastAPI server
|   |   |-- api/                # HTTP routes, SSE transport
|   |   |-- chat/               # REACT agent, intent classification, retrieval,
|   |   |                       #   persona, search tools, thread lifecycle
|   |   |-- main.py
|   |   |-- security.py         # Prompt injection defense, admin key check
|   |   |-- resilience.py       # Circuit breaker, retry, error classification
|   |   `-- telemetry.py        # OpenTelemetry metrics
|   |-- src/scrapers/
|   |   |-- venue/              # VenueScraper engine, extractors, date/price parsing
|   |   `-- sources/            # do312, eventbrite, ticketmaster, park district,
|   |                           #   broadway, bandsintown, yourchicagoguide,
|   |                           #   plus unscheduled: eventscom, timeoutchicago
|   |-- src/shared/             # Used by both app and scrapers
|   |   |-- database/           # SQLAlchemy models, engine, filters
|   |   |-- geo/                # Neighborhood boundaries, resolver, alias tables
|   |   |-- categories.py       # Category taxonomy and classification
|   |   |-- schemas.py          # Pydantic API contracts (Event, EventCreate, ...)
|   |   |-- enrichment.py       # Cost, age range, indoor/outdoor extraction
|   |   |-- pricing.py          # Per-venue price page parsing
|   |   |-- locality.py         # Chicago vs suburban address detection
|   |   `-- semantic_categories.py
|   |-- tests/
|   |   |-- app/                # API, chat, intent routing, security, resilience
|   |   |-- scrapers/           # Extractor and scraper tests
|   |   |-- shared/             # Category, pricing, enrichment, locality tests
|   |   `-- scripts/            # Ops script tests
|   |-- scripts/                # Operational tools (see scripts/README.md)
|   |-- eval/                   # Eval harnesses + labelled data
|   |-- data/                   # Local SQLite database and boundary data
|   |-- Dockerfile              # API service (Python 3.15, uv, no Playwright)
|   |-- Dockerfile.scraper      # Scraper cron service (Python 3.14 + Playwright)
|   |-- railway.toml            # Railway config for API service
|   |-- railway.scraper.toml    # Railway config for scraper cron service
|   |-- .env.example            # Required environment variables
|   `-- pyproject.toml          # Dependencies, pytest config, ruff lint config
|-- frontend/                   # TypeScript + Vite browser application
|-- benchmarks/                 # Interpreter microbenchmarks
|-- tasks.py                    # Invoke development tasks
|-- DEPLOY.md                   # Railway deployment guide
|-- DEVELOPMENT.md
|-- PROJECT_STRUCTURE.md
|-- RAG_PIPELINE.md
|-- SCRAPERS.md                 # Active / unscheduled / retired scraper inventory
`-- README.md
```

## How retrieval works

[**RAG_PIPELINE.md**](RAG_PIPELINE.md) maps the chatbot onto the four stages of a retrieval pipeline as an audit: what the code does today, where stages are thin, and where they are deliberately absent.

Start with **[Explain it like I'm five](RAG_PIPELINE.md#explain-it-like-im-five)** for the shape of it.

The short version: retrieval is hybrid and structured-first (dates and neighborhoods are SQL, not embeddings), nothing is fine-tuned and the file says why, and evaluation covers categorization with a scored harness and retrieval with a 20-query harness (baseline 18/20, 90%).

## Key Features

### Smart Event Discovery
- **REACT Agent** - Multi-step reasoning with Claude + PydanticAI
- **Semantic Search** - Static embeddings (model2vec): "plant workshops" finds "foraging wild plants" with no shared keyword. Indexes the whole corpus in under a second, queries in ~0.3 ms, no torch dependency
- **Natural Language** - "concerts this weekend" -> date + category SQL filters
- **Smart Ranking** - Keyword, semantic, category, and date-proximity scores; whole-word matching so "class" does not match "Classic"
- **Fill-in-the-blank UI** - "Let's explore ___ ___ ___" with comboboxes; selecting is the search

### Neighborhoods
- **Neighborhood-aware search** - locations placed from stored boundaries, coordinates, venue mappings, and cached geocoding
- **Point-in-polygon, not geocoding** - 98 neighborhood boundaries in the database; placing a venue is a local geometry test (~3 ms, no API calls)
- **Vernacular names** - Pilsen not "Lower West Side"; Wrigleyville -> Lake View
- **Suburban flag** - do312 covers the whole metro; suburban venues are marked so the agent never silently presents a Naperville show as a Chicago option

### Chat Pipeline
- **Three-tier intent routing** - explicit event requests skip the classifier; ambiguous messages get a clarification prompt; off-topic gets a redirect in Loopara's voice
- **Haiku for classification, Sonnet for the agent** - classifier cost ~10x lower
- **Context compression** - after turn 8 a one-sentence Haiku summary is prepended to the history window so early context survives
- **Admin endpoint protection** - POST /api/venue-events/refresh requires X-Admin-Key and is hidden from the public OpenAPI schema

### Data
- **Prices where venues publish them** - parse_cost() normalises "$25", "$20-$25", "No cover", "Donation"
- **Reusable extractors** - extract_tribe_events covers every venue on The Events Calendar; extract_dated_list_items keys off date text not class names
- **Async scraping** - httpx + BeautifulSoup, per-venue timeouts so one slow site cannot stall a run
- **Additive refreshes** - upserts only, never deletes; a failing venue costs nothing on a run
- **Safe rescrapes** - scripts/db_safety.py snapshots counts and flags any source that lost events

## Quick Start

```bash
# Backend
cd backend
uv sync --extra app --extra test --extra dev
PYTHONPATH=src uv run uvicorn app.main:app --reload   # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

Required environment variables (copy `backend/.env.example` to `backend/.env`):

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=sqlite+aiosqlite:///./data/events.db
ADMIN_KEY=...            # protects POST /api/venue-events/refresh
SERPAPI_KEY=...          # optional: web search fallback
LOG_LEVEL=INFO
```

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for the full Railway deployment guide (two services — API + scraper cron — sharing a persistent SQLite volume).

## Tests

```bash
cd backend
PYTHONPATH=src:. .venv/bin/python -m pytest tests/           # 569 tests
PYTHONPATH=src:. .venv/bin/python -m ruff check src/ tests/ scripts/ eval/
```

Or via Invoke from the repo root:

```bash
invoke test     # all tests + coverage
invoke lint     # ruff check
invoke format   # ruff format
```

## Eval harnesses

```bash
cd backend
PYTHONPATH=src python eval/evaluate_categorization.py        # 73 labelled titles
PYTHONPATH=src python eval/evaluate_retrieval.py             # 20 labelled queries
PYTHONPATH=src python eval/evaluate_retrieval.py --verbose   # show all details
```

## Code organisation

```python
# App server
from app.main import app
from app.api import router
from app.chat.executor import ChatExecutor
from app.chat.chatbot import SearchPolicy, search_local_db
from app.chat.intent_classifier import Intent, get_intent_classifier

# Scrapers
from scrapers.venue.chicago_events_scraper import scrape_chicago_events
from scrapers.venue.venue_scraper import VenueScraper, VenueConfig
from scrapers.sources.do312 import DO312Scraper

# Shared (used by both)
from shared.database import init_db, AsyncSessionLocal
from shared.database.models import EventModel, VenueModel
from shared.schemas import Event, EventCreate
from shared.categories import classify_all
from shared.geo.neighborhoods import resolve_neighborhood_id
```

## Database schema

| Table | Purpose |
|---|---|
| `events` | Event name, dates, category, source, price, location |
| `venues` | Venue configuration and neighborhood mapping |
| `neighborhoods` | Names and boundary polygons (98 Chicago neighborhoods) |
| `chat_threads` | Conversation state, token/turn budget, context summary |
| `chat_messages` | Per-turn message history |
| `audit_logs` | Per-operation telemetry |
| `metrics` | OpenTelemetry snapshots |
| `geocode_cache` | Cached coordinate lookups |

## Operational scripts

See [`backend/scripts/README.md`](backend/scripts/README.md) for the full inventory.

```bash
cd backend
PYTHONPATH=src:. python scripts/additive_scrape.py    # run all scrapers
PYTHONPATH=src:. python scripts/prune_dead_links.py   # remove dead URLs
PYTHONPATH=src:. python scripts/health.py             # DB + scraper health check
PYTHONPATH=src:. python scripts/db_safety.py          # snapshot + diff event counts
```

## Benchmarks

`benchmarks/perf_compare.py` contains small Python interpreter microbenchmarks (imports, dict/list ops, JSON, async tasks). These are not API, chatbot, database, or scraper throughput measurements.

## License

MIT - see `LICENSE`.

## Author

Built by [Lorena Mesa](https://github.com/lorenanicole) - me@lorenamesa.com
