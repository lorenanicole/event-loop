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
- 🧠 **Semantic Search** - NLTK-powered similarity matching (find "events like that")
- 📝 **Natural Language** - Understands "concerts this weekend" → filters by date/category
- 🎯 **Smart Ranking** - Events scored by relevance (keyword + category + date proximity)

### **Data at Scale**
- 📊 **4,959 Events** - Normalized from 5 external APIs + 28 Chicago neighborhoods with 68 venues
- 🗄️ **SQLite** - Fully indexed for fast queries
- 🔄 **Async Scraping** - httpx + BeautifulSoup for concurrent data collection
- ⚡ **Real-time SSE** - Server-Sent Events for streaming chat responses

### **Resilience & Observability**
- 🔌 **Circuit Breaker** - Automatic fallback when LLM/DB fails
- ⏳ **Exponential Backoff** - Retry transient failures smartly
- 📊 **OpenTelemetry** - Counters, histograms, audit trails
- 🔐 **Prompt Injection Defense** - Pattern detection, rate limiting, output validation
- 🧪 **118+ Tests** - Security, resilience, database, API, scraper coverage

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
- **Custom Web Scrapers**: Chicago venue listings, Timeout Chicago, Events.com
- **Framework**: VenueScraper base class with config-driven extraction

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
