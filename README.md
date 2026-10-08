# 🏙️ EventLoop: Chicago Events Chatbot

**An event discovery app for Chicago, with a Python backend, SQLite event catalog, and a TypeScript/Vite frontend.** The backend and scrapers share one Python package and database; the checked-in backend environment currently uses Python 3.15.0rc3.

## 📁 Project Structure

```
eventloop/
├── backend/
│   ├── src/app/                # FastAPI API, chatbot, retrieval, security
│   ├── src/scrapers/           # External APIs and venue scrapers
│   ├── src/shared/             # Database, schemas, categories, geo helpers
│   ├── tests/                  # App, scraper, and shared tests
│   ├── data/                   # Local SQLite database and boundary data
│   ├── additive_scrape.py      # Additive scrape runner
│   └── pyproject.toml          # Backend dependencies and test config
├── frontend/                  # TypeScript + Vite browser application
├── benchmarks/                # Small interpreter microbenchmarks
├── tasks.py                   # Invoke development tasks
├── DEVELOPMENT.md
├── PROJECT_STRUCTURE.md
├── RAG_PIPELINE.md
└── README.md
```

## 📐 How retrieval works

[**RAG_PIPELINE.md**](RAG_PIPELINE.md) maps the chatbot onto the four stages of a
retrieval pipeline — pre-retrieval, retrieval, fine-tuning, evaluation — as an
audit rather than a design doc, so it records what the code does today and where
a stage is thin or deliberately absent.

Start with **[Explain it like I'm five](RAG_PIPELINE.md#explain-it-like-im-five)**
if you just want the shape of it — a friend who knows Chicago, a very large
notebook, and the four things that have to go right.

The short version for everyone else: retrieval is hybrid and structured-first
(dates and neighborhoods are SQL, not embeddings), nothing is fine-tuned and the
file says why, and evaluation covers categorization with a scored harness but
does not yet cover retrieval.

## ✨ Key Features

### **Smart Event Discovery**
- 🔍 **REACT Agent** - Multi-step reasoning with Claude + PydanticAI
- 🧠 **Semantic Search** - Static embeddings (model2vec) match on meaning, not keywords:
  "plant workshops" finds "foraging wild plants" with no shared word. Indexes the
  whole corpus in under a second and queries in ~0.3 ms, with no torch dependency
- 📝 **Natural Language** - Understands "concerts this weekend" → filters by date/category
- 🎯 **Smart Ranking** - Keyword, semantic similarity, category and date proximity,
  with whole-word matching so "class" does not match "Classic"
- 🧭 **Fill-in-the-blank UI** - "Let's explore ___ ___ ___" with comboboxes you can
  browse or type into; selecting is the search, so there is no submit step

### **Neighborhoods**
- 🗺️ **Neighborhood-aware event search** - event locations are assigned from stored boundaries, coordinates, venue mappings, and cached geocoding where needed
- 📐 **Point-in-polygon, not geocoding** - the city's 98 neighborhood boundaries are
  stored in the database, so placing a venue is a local geometry test: no API calls,
  no rate limits, ~3 ms
- 🏷️ **Vernacular names** - Pilsen, not "Lower West Side"; Bronzeville, not "Douglas"
- 📍 **Geocoding only as a last resort** - addresses with no coordinates are looked up
  once, rate limited, and cached permanently in `geocode_cache`

### **Data at Scale**
- 📊 **SQLite event catalog** - event and source totals change as data is refreshed
- 💵 **Prices where venues publish them** - one `parse_cost()` normalizes "$25",
  "$20-$25", "Starting at $64", "No cover" and "Donation", and rejects the
  near-misses ("21+", "Show 9:30PM")
- ♻️ **Reusable extractors over per-venue code** - `extract_tribe_events` covers
  every venue on The Events Calendar; `extract_dated_list_items` keys off date
  text rather than class names, so it survives Wix's obfuscated classes
- 🗄️ **SQLite** - Fully indexed for fast queries
- 🔄 **Async Scraping** - httpx + BeautifulSoup, per-venue timeouts so one slow site
  cannot stall a run
- 💾 **Additive refreshes** - `additive_scrape.py` upserts and never deletes, so a
  venue that fails or gets bot-blocked on a run costs nothing
- 💾 **Safe rescrapes** - `db_safety.py` snapshots the database and diffs counts by
  source and neighborhood afterwards, flagging any source that *lost* events
- ⚡ **SSE chat transport** - Server-Sent Events carry chat progress and completed responses

### **Resilience & Observability**
- 🔌 **Circuit Breaker** - Automatic fallback when LLM/DB fails
- ⏳ **Exponential Backoff** - Retry transient failures smartly
- 📊 **OpenTelemetry** - Counters, histograms, audit trails
- 🔐 **Prompt Injection Defense** - Pattern detection, rate limiting, output validation
- 🧪 **Backend test suite** - app, security, resilience, database, scraper and chatbot coverage

### **Production-Ready**
- 🛡️ **Security** - Blocks prompt injections, validates outputs, sanitizes inputs
- 🎯 **Intent Classification** - Clear Chicago event searches use a no-model fast path; ambiguous and contextual requests retain model classification
- 💰 **Cost Optimization** - DB-first search minimizes Claude API calls
- ✅ **Development tasks** - Invoke tasks are defined in the root `tasks.py`
- 📈 **Usage Limits** - Provider-reported model usage; 20,000 agent tokens and 12 turns per conversation, with per-turn request, tool-call and output caps

## 🚀 Quick Start (5 minutes)

### **Prerequisites**
- Python 3.15 (for backend)
- Python 3.14 (for parser - optional if not running scrapers)
- Node.js 18+ (for frontend)
- `uv` package manager (`pip install uv`)

### **Full Stack Setup**

**Terminal 1: Backend (Python 3.15)**
```bash
cd backend

# Reuse the existing local environment when present. To recreate it instead:
# uv sync --all-extras
source .venv/bin/activate

# Configure ANTHROPIC_API_KEY in the environment or backend/.env.
# SERPAPI_KEY is optional and enables online event fallback.

PYTHONPATH=src python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The app initializes its SQLite schema on startup. The default database path is
`backend/data/events.db`.

**Terminal 2: Frontend (TypeScript + Vite)**
```bash
# From project root, navigate to frontend
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
# Frontend running at http://localhost:5173
```

### **Access the Application**
- 🎯 **Chat UI**: http://localhost:5173
- 🔌 **API**: http://localhost:8000
- 📊 **Analytics**: http://localhost:8000/analytics
- ✅ **Health Check**: http://localhost:8000/health
- 📚 **API Docs**: http://localhost:8000/docs

### **Scraping & data operations**

All run from `backend/`.

```bash
# Snapshot the database before a scrape, and compare after.
.venv/bin/python db_safety.py backup

# Refresh every venue in parallel. Additive: matched events are updated in
# place, new ones inserted, nothing deleted - so a venue that fails or gets
# bot-blocked leaves its existing events alone. Prefer this to clean_rescrape.py,
# which deletes a venue's rows before reinserting them.
.venv/bin/python additive_scrape.py                   # venues and external sources
.venv/bin/python additive_scrape.py Metro Thalia      # only matching venues
.venv/bin/python additive_scrape.py --only external    # external source set

.venv/bin/python db_safety.py compare
.venv/bin/python db_safety.py restore data/backups/events-<stamp>.db   # if needed

# Report stored venue coverage, or probe configured venue pages live.
.venv/bin/python health.py venues --db
.venv/bin/python health.py venues

# Check one sample link per source, or all links for one source.
.venv/bin/python health.py links
.venv/bin/python health.py links --source chicago_venue_den_theatre

# Remove events whose own page is gone. Only a 404 or 410 counts as gone;
# bot protection, server errors and timeouts never do, and every URL is
# confirmed twice before anything is deleted.
.venv/bin/python prune_dead_links.py --dry-run
.venv/bin/python prune_dead_links.py

# Collapse rows that are the same event stored twice. Identity is source +
# name + date + time; undated rows are skipped because nothing distinguishes
# them, and cross-source overlaps are reported rather than merged.
.venv/bin/python dedupe_events.py --dry-run
.venv/bin/python dedupe_events.py

# Place Park District events without geocoding: the city's open data portal
# publishes all 617 parks with boundary polygons, so one request replaces
# hundreds of rate-limited geocodes.
.venv/bin/python place_park_district.py

# One-time: load Chicago's neighborhood boundaries into the database.
# After this, placing a coordinate is a local point-in-polygon test.
.venv/bin/python load_neighborhood_boundaries.py

# Place any events still missing a neighborhood.
.venv/bin/python backfill_neighborhoods.py            # coordinates + known venues only
.venv/bin/python backfill_neighborhoods.py --geocode  # also geocode unknown addresses
```

Backups and the boundary cache live in `backend/data/backups/`, which is gitignored.

To smoke-test only the first DO312 API page without saving anything, run from
`backend/`:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import asyncio
import httpx
from scrapers.external.do312 import DO312Scraper

async def main():
  scraper = DO312Scraper()
  async with httpx.AsyncClient(timeout=scraper.REQUEST_TIMEOUT,
                 follow_redirects=True) as client:
    response = await client.get(
      scraper.API_ENDPOINT,
      params={"page": 1},
      headers={"User-Agent": scraper.USER_AGENT},
    )
    response.raise_for_status()
    events = response.json().get("events", [])[:10]
  parsed = [scraper._parse_event_data(item) for item in events]
  print(f"parsed {sum(event is not None for event in parsed)} of {len(events)}")

asyncio.run(main())
PY
```

This verifies the live fetch and parser only. `additive_scrape.py` writes to the
local database; it supports venue-name matching and the `--only external` group,
not a single external-source selector.

### **Alternative: Using Invoke Task Automation**

```bash
# Run from the repository root; tasks.py invokes the backend .venv for tests.

# List available tasks
uv run --with invoke invoke --list

# Common tasks:
uv run --with invoke invoke test
uv run --with invoke invoke lint
uv run --with invoke invoke format
uv run --with invoke invoke coverage
```

## 📦 Dependencies & Architecture

### **Backend (app/)**
- **FastAPI** - REST API framework
- **SQLAlchemy** - Async ORM
- **PydanticAI** - LLM agent framework
- **model2vec** - Local static event embeddings
- **httpx** - Async HTTP client for APIs and scrapers

### **Scrapers (scrapers/)**
- **External sources run by `additive_scrape.py`**: Ticketmaster, DO312, Chicago Park District, Broadway In Chicago
- **Additional scraper modules**: Eventbrite, Bandsintown, and Your Chicago Guide are present, but are not in the scheduled source list
- **Multi-venue sources**: Broadway In Chicago, which programs five Loop-area
  theaters that publish no calendar of their own; the Chicago Park District,
  which is the broadest source on the South and West Sides where commercial
  venues are thin
- **Custom Web Scrapers**: Chicago venue listings, Timeout Chicago, Events.com
- **Framework**: VenueScraper base class with config-driven extraction, plus
  `extractor_fn` for custom parsing and `page_extractor_fn` for venues whose
  events only exist after JS runs (lazy lists, calendar pagination)

### **Database (shared/)**
- **EventModel**: Event records; totals change with refreshes
- **VenueModel**: Venue configuration and information
- **NeighborhoodModel**: Boundary and neighborhood records
- **ChatThreadModel**: Conversation sessions
- **AuditLogModel**: Security events

## 🧪 Testing

### **Run All Tests**
```bash
cd backend
.venv/bin/python -m pytest                           # Run all tests
.venv/bin/python -m pytest tests/app -v              # Run app tests with verbose output
.venv/bin/python -m pytest tests/app/test_api.py     # Run specific test file
.venv/bin/python -m pytest --cov=src/app             # Run with coverage report
```

### **Test Coverage**
- **API Tests** (test_api.py): REST endpoints, error handling
- **Chat Tests** (test_chatbot.py): REACT agent, streaming SSE
- **Database Tests** (test_database.py): ORM, models, queries
- **Security Tests** (test_security.py): Prompt injection, rate limiting
- **Resilience Tests** (test_resilience.py): Circuit breaker, retries
- **Scraper Tests** (test_scrapers.py): Venue extraction, API scraping

## 📊 Performance Benchmarks

The repository includes small interpreter microbenchmarks for imports, basic
dictionary/list operations, JSON serialization, and async task scheduling.
They are not chatbot, database, or scraper benchmarks. The checked-in JSON
files are individual historical runs, not repeated or controlled measurements;
they do not support a general Python 3.15 performance claim.

Run from the repository root, with the requested interpreters available to `uv`:
```bash
cd backend
uv run --python 3.14 ../benchmarks/perf_compare.py
uv run --python 3.15 ../benchmarks/perf_compare.py
cd ..
python benchmarks/compare_results.py
```

## 🔧 Development Workflow

### **Code Organization**

**App code**:
```python
from app.main import app
from app.api import router
from app.ai.executor import ChatExecutor
from app.logging import get_logger
```

**Scraper code**:
```python
from scrapers.external.do312 import DO312Scraper
from scrapers.custom.venue.venue_scraper import VenueScraper, VenueConfig
```

**Shared code** (used by both):
```python
from shared.database import init_db, AsyncSessionLocal
from shared.database.models import EventModel, VenueModel
from shared.models import Event, EventCreate
```

### **Adding a New API Endpoint**

1. Create route in `backend/src/app/api/routes.py`:
```python
@router.get("/events/by-category/{category}")
async def get_events_by_category(category: str, db: AsyncSession = Depends(get_db)):
    # Your implementation
    pass
```

2. Include router in `backend/src/app/main.py`:
```python
from app.api import router

app.include_router(router)
```

3. Write tests in `backend/tests/app/test_api.py`

### **Adding a New Event Scraper**

1. For API-based scraper: Create `backend/src/scrapers/external/newsource.py`
2. For website scraper: Create `backend/src/scrapers/custom/newsource.py`
3. Implement scraper class with `fetch_events()` method
4. Write tests in `backend/tests/parser/test_scrapers.py`

## 🗄️ Database

### **Initialization**
```bash
cd backend
python -c "from app.main import app; import asyncio; asyncio.run(app.lifespan.__aenter__())"
```

### **Schema**
- **events**: event name, dates, category, source, price, location, and related fields
- **venues**: venue configuration and neighborhood/address information
- **neighborhoods**: neighborhood names and boundary data
- **chat_threads / chat_messages**: conversation state and history
- **audit_logs / metrics / geocode_cache**: operational records and cached lookups

Event and neighborhood counts are data-snapshot-dependent; query the local
database for current totals rather than relying on fixed README numbers.

### **Querying**
```python
import asyncio

from shared.database import AsyncSessionLocal
from shared.database.models import EventModel
from sqlalchemy import select


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(EventModel))
        events = result.scalars().all()
        print(f"loaded {len(events)} events")


asyncio.run(main())
```

## 🚢 Deployment

No Dockerfiles or deployment manifests are currently included. For a local
production-style frontend build, run `npm run build` from `frontend/`; run the
backend with Uvicorn and configure its environment variables in the deployment
environment.

### **Environment Variables**
```
ANTHROPIC_API_KEY=sk-...
DATABASE_URL=sqlite+aiosqlite:///./data/events.db
LOG_LEVEL=INFO
```

## 📝 License

MIT License - See LICENSE file for details

## 👥 Contributing

1. Make changes and write tests.
2. Run `cd backend && .venv/bin/python -m pytest` to verify.
3. Commit and open a pull request through the project’s normal workflow.

## 📧 Contact

Built by [Lorena Mesa](https://github.com/lorenanicole)

Questions? Open an issue or reach out at me@lorenamesa.com
