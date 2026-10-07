# 🏙️ EventLoop: Chicago Events Chatbot

**An AI-powered event discovery platform for Chicago, built with dual Python versions (3.15 + 3.14) showcasing modern async patterns, lazy imports, and production-grade resilience.**

This project demonstrates real-world Python 3.15 adoption:
- **Backend**: Python 3.15 with lazy imports, upgraded JIT compiler (+10% performance)
- **Parser**: Python 3.14 stable for proven scraping reliability  
- **Communication**: Shared database for seamless data integration

**Blog post theme**: "Python 3.15 in Production: Real Performance Gains & Dual-Version Architecture" - with measured benchmarks, dual-version patterns, and comprehensive testing at scale.

## 📁 Project Structure

```
eventloop/
├── backend/                    # Python Backend (3.15 + 3.14)
│   ├── src/
│   │   ├── app/               # FastAPI (Python 3.15)
│   │   │   ├── main.py        # Entry point
│   │   │   ├── api/           # REST endpoints
│   │   │   ├── ai/            # Chat agent, search, enrichment
│   │   │   ├── logging.py
│   │   │   ├── security.py
│   │   │   ├── telemetry.py
│   │   │   └── resilience.py
│   │   ├── shared/            # Cross-cutting
│   │   │   ├── database/      # Models, filters, neighborhoods
│   │   │   ├── geo/           # Boundary lookup + geocoding resolver
│   │   │   └── models/
│   │   ├── scrapers/          # Data collection
│   │   │   ├── external/      # Third-party APIs (5)
│   │   │   │   ├── do312.py
│   │   │   │   ├── ticketmaster.py
│   │   │   │   ├── eventbrite.py
│   │   │   │   ├── bandsintown.py
│   │   │   │   └── yourchicagoguide.py
│   │   │   └── custom/        # Custom web scrapers
│   │   │       ├── venue/     # Venue scraper framework (15 files)
│   │   │       │   ├── venue_scraper.py     # Base class
│   │   │       │   ├── chicago_events_scraper.py
│   │   │       │   └── ...
│   │   │       ├── eventscom.py
│   │   │       ├── timeoutchicago.py
│   │   │       └── venue_*.py
│   │   └── shared/            # Shared Models & Database
│   │       ├── database/      # SQLAlchemy ORM
│   │       ├── models/        # Pydantic schemas
│   │       └── __init__.py
│   ├── tests/                 # Unit & integration tests
│   │   ├── app/               # FastAPI tests
│   │   ├── parser/            # Scraper tests
│   │   └── shared/            # Database tests
│   └── pyproject.toml
│
├── frontend/                  # React UI (Vite)
│   ├── src/
│   │   ├── app.ts
│   │   ├── chat.ts
│   │   ├── api.ts
│   │   └── main.ts
│   ├── package.json
│   └── vite.config.js
│
├── benchmarks/                # Performance tests
│   ├── perf_compare.py
│   └── results/
│
├── scripts/                   # Utilities
│   ├── migrate_scraper_to_main.py
│   └── backfill_*.py
│
└── data/
    └── events.db             # SQLite database (4,959 events)
```

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
- 🗺️ **Events placed in 33 Chicago neighborhoods** - 95% of upcoming events
- 📐 **Point-in-polygon, not geocoding** - the city's 98 neighborhood boundaries are
  stored in the database, so placing a venue is a local geometry test: no API calls,
  no rate limits, ~3 ms
- 🏷️ **Vernacular names** - Pilsen, not "Lower West Side"; Bronzeville, not "Douglas"
- 📍 **Geocoding only as a last resort** - addresses with no coordinates are looked up
  once, rate limited, and cached permanently in `geocode_cache`

### **Data at Scale**
- 📊 **2,400+ upcoming events** - 6 external sources plus 51 venue scrapers across
  22 neighborhoods, North Side to South Side
- 💵 **Prices where venues publish them** - one `parse_cost()` normalises "$25",
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
- ⚡ **Real-time SSE** - Server-Sent Events for streaming chat responses

### **Resilience & Observability**
- 🔌 **Circuit Breaker** - Automatic fallback when LLM/DB fails
- ⏳ **Exponential Backoff** - Retry transient failures smartly
- 📊 **OpenTelemetry** - Counters, histograms, audit trails
- 🔐 **Prompt Injection Defense** - Pattern detection, rate limiting, output validation
- 🧪 **204 Tests** - Security, resilience, database, API, scraper coverage

### **Production-Ready**
- 🛡️ **Security** - Blocks prompt injections, validates outputs, sanitizes inputs
- 🎯 **Intent Classification** - Rejects out-of-scope requests ("Tell me a joke" → polite decline)
- 💰 **Cost Optimization** - DB-first search minimizes Claude API calls
- ✅ **Quality Gating** - Git hooks run tests + linting before commit
- 📈 **Token Budgets** - 4,000 tokens/session, 5 turns max (focused chats)

## 🚀 Quick Start (5 minutes)

### **Prerequisites**
- Python 3.15 (for backend)
- Python 3.14 (for parser - optional if not running scrapers)
- Node.js 18+ (for frontend)
- `uv` package manager (`pip install uv`)

### **Full Stack Setup**

**Terminal 1: Backend (Python 3.15)**
```bash
# Navigate to backend directory
cd backend

# Create Python 3.15 environment
uv venv --python 3.15

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev,test,all]"

# Setup environment variables
cp ../.env.example .env
# Edit .env and add ANTHROPIC_API_KEY

# Initialize database
python -c "from app.main import app; import asyncio; asyncio.run(app.lifespan.__aenter__())"

# Start backend server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2: Frontend (React + Vite)**
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
# Snapshot the database before a scrape, and diff it afterwards.
# `compare` flags any source that LOST events - a scrape that silently drops a
# venue looks fine in the logs and obvious here.
python db_safety.py backup

# Refresh every venue in parallel. Additive: matched events are updated in
# place, new ones inserted, nothing deleted - so a venue that fails or gets
# bot-blocked leaves its existing events alone. Prefer this to clean_rescrape.py,
# which deletes a venue's rows before reinserting them.
python additive_scrape.py                   # all venues
python additive_scrape.py Metro Thalia      # only venues matching these names

python db_safety.py compare
python db_safety.py restore data/backups/events-<stamp>.db   # if needed

# Which venues are actually yielding events, one line each.
python venue_health.py

# One-time: load Chicago's neighborhood boundaries into the database.
# After this, placing a coordinate is a local point-in-polygon test.
python load_neighborhood_boundaries.py

# Place any events still missing a neighborhood.
python backfill_neighborhoods.py            # coordinates + known venues only
python backfill_neighborhoods.py --geocode  # also geocode unknown addresses
```

Backups and the boundary cache live in `backend/data/backups/`, which is gitignored.

### **Alternative: Using Invoke Task Automation**

```bash
cd backend

# List available tasks
inv --list

# Common tasks:
inv test              # Run all tests
inv lint              # Check code style  
inv format            # Auto-format code
inv coverage          # Generate coverage report
```

## 📦 Dependencies & Architecture

### **Backend (app/)**
- **FastAPI** - REST API framework
- **SQLAlchemy** - Async ORM
- **PydanticAI** - LLM agent framework
- **Playwright** - Browser automation for JS-heavy sites
- **BeautifulSoup4** - HTML parsing
- **httpx** - Async HTTP client

### **Scrapers (scrapers/)**
- **External APIs**: Ticketmaster, Eventbrite, Bandsintown, DO312, Your Chicago Guide (WordPress)
- **Multi-venue sources**: Broadway In Chicago, which programmes five Loop-area
  theatres that publish no calendar of their own
- **Custom Web Scrapers**: Chicago venue listings, Timeout Chicago, Events.com
- **Framework**: VenueScraper base class with config-driven extraction, plus
  `extractor_fn` for custom parsing and `page_extractor_fn` for venues whose
  events only exist after JS runs (lazy lists, calendar pagination)

### **Database (shared/)**
- **EventModel**: Event records (4,959 total)
- **VenueModel**: Venue information (68 venues)
- **NeighborhoodModel**: Chicago neighborhoods (28 total)
- **ChatThreadModel**: Conversation sessions
- **AuditLogModel**: Security events

## 🧪 Testing

### **Run All Tests**
```bash
cd backend
pytest                           # Run all tests
pytest tests/app -v              # Run app tests with verbose output
pytest tests/app/test_api.py     # Run specific test file
pytest --cov=src/app             # Run with coverage report
```

### **Test Coverage**
- **API Tests** (test_api.py): REST endpoints, error handling
- **Chat Tests** (test_chatbot.py): REACT agent, streaming SSE
- **Database Tests** (test_database.py): ORM, models, queries
- **Security Tests** (test_security.py): Prompt injection, rate limiting
- **Resilience Tests** (test_resilience.py): Circuit breaker, retries
- **Scraper Tests** (test_scrapers.py): Venue extraction, API scraping

## 📊 Performance Benchmarks

### **Python 3.15 vs 3.14**
```
Benchmark                    3.14         3.15        Improvement
─────────────────────────────────────────────────────────────────
Startup (imports)           45.2ms       38.1ms      ↓15.5%
Dict operations            125.3ms      119.2ms      ↓4.9%
List comprehension          89.4ms       59.1ms      ↓33.8%
Async operations           234.5ms      216.3ms      ↓7.7%
JSON encode/decode         145.2ms      106.4ms      ↓26.8%

Average Improvement:                              +10.1%
```

Run benchmarks:
```bash
cd backend
uv run --python 3.15 benchmarks/perf_compare.py
uv run --python 3.14 benchmarks/perf_compare.py
python benchmarks/compare_results.py
```

## 🔧 Development Workflow

### **Code Organization**

**App code** (Python 3.15):
```python
from app.main import app
from app.api import router
from app.ai.chatbot import create_event_search_agent
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
4. Write tests in `backend/tests/app/test_scrapers.py`

## 🗄️ Database

### **Initialization**
```bash
cd backend
python -c "from app.main import app; import asyncio; asyncio.run(app.lifespan.__aenter__())"
```

### **Schema**
- **events** (4,959 rows): event_id, name, date, category, details, venue_name, source, etc.
- **venues** (68 rows): venue_id, name, neighborhood_id, address, website_url
- **neighborhoods** (28 rows): neighborhood_id, name

### **Querying**
```python
from shared.database import AsyncSessionLocal
from shared.database.models import EventModel
from sqlalchemy import select

async with AsyncSessionLocal() as session:
    result = await session.execute(select(EventModel))
    events = result.scalars().all()
```

## 🚢 Deployment

### **Docker**
```bash
# Build backend
docker build -t eventloop-backend:latest backend/
docker run -p 8000:8000 eventloop-backend:latest

# Build frontend
docker build -t eventloop-frontend:latest frontend/
docker run -p 5173:5173 eventloop-frontend:latest
```

### **Environment Variables**
```
ANTHROPIC_API_KEY=sk-...
DATABASE_URL=sqlite:///./data/events.db
LOG_LEVEL=INFO
```

## 📝 License

MIT License - See LICENSE file for details

## 👥 Contributing

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make changes and write tests
3. Run `inv test` to verify
4. Commit: `git commit -m "feat: description"`
5. Push: `git push origin feature/my-feature`
6. Open a Pull Request

## 📧 Contact

Built by [Lorena Mesa](https://github.com/lorenanicole)

Questions? Open an issue or reach out at me@lorenamesa.com
