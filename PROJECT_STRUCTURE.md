# EventLoop Project Structure

## Overview
EventLoop is organized as a monorepo with separate packages for the backend app (Python 3.15) and web scraper/parser (Python 3.14).

```
eventloop/
├── app/                      # FastAPI Backend (Python 3.15+)
│   ├── app/
│   │   ├── main.py          # FastAPI app entry point
│   │   ├── api/             # API routes and endpoints
│   │   ├── ai/              # AI/chatbot logic with PydanticAI
│   │   ├── scraper/         # DO312 external event scraper
│   │   ├── logging.py       # Logging configuration
│   │   ├── security.py      # Security & rate limiting
│   │   ├── telemetry.py     # OpenTelemetry metrics
│   │   ├── resilience.py    # Circuit breaker patterns
│   │   └── __init__.py
│   ├── tests/               # App-specific tests
│   ├── pyproject.toml       # App dependencies
│   └── requirements.txt     # Pinned versions (optional)
│
├── parser/                   # Web Scraper (Python 3.14 LTS)
│   ├── parser/
│   │   ├── scrapers/        # Chicago venue scrapers
│   │   │   ├── chicago_events_scraper.py
│   │   │   ├── venue_scraper.py
│   │   │   └── ...
│   │   ├── scraper/         # External API scrapers
│   │   │   ├── scraper.py (DO312 base)
│   │   │   ├── ticketmaster.py
│   │   │   ├── eventbrite.py
│   │   │   └── ...
│   │   └── __init__.py
│   ├── tests/               # Parser-specific tests
│   ├── pyproject.toml       # Parser dependencies
│   └── requirements.txt     # Pinned versions (optional)
│
├── shared/                   # Shared Models & Database
│   ├── database/            # SQLAlchemy models
│   │   ├── models.py        # EventModel, VenueModel, NeighborhoodModel, etc.
│   │   └── __init__.py
│   ├── models/              # Pydantic schemas
│   │   └── __init__.py
│   └── __init__.py
│
├── frontend/                # React/Vite Frontend
│   ├── src/
│   ├── package.json
│   └── vite.config.js
│
├── scripts/                 # Utility scripts
│   └── backfill_*.py
│
├── benchmarks/              # Performance benchmarks
│   ├── perf_compare.py
│   ├── compare_results.py
│   └── results/
│
├── tests/                   # Integration tests
│   └── test_core_functionality.py
│
├── data/                    # Runtime data
│   └── events.db           # SQLite database
│
├── pyproject.toml          # Root project config (monorepo)
├── README.md               # Documentation
└── PROJECT_STRUCTURE.md    # This file
```

## Package Structure

### `app/` - FastAPI Backend (Python 3.15)
- **Python Version**: 3.15.0 RC3+
- **Features**: Lazy imports, JIT compiler, improved async
- **Entry Point**: `uvicorn app.main:app`
- **Port**: 8000

Features:
- FastAPI REST API with async endpoints
- SSE streaming for real-time chat
- PydanticAI REACT agent for intelligent search
- SQLAlchemy async ORM
- OpenTelemetry telemetry
- Rate limiting & security

### `parser/` - Web Scraper (Python 3.14)
- **Python Version**: 3.14.3+
- **Stability**: LTS release (no breaking changes)
- **Focus**: Web scraping and data extraction

Scrapers:
- **Chicago Venues** (VenueScraper class) - 28 neighborhoods, 68 venues
- **External APIs**: Ticketmaster, DO312, Eventbrite, Timeout Chicago, etc.

### `shared/` - Shared Models & Database
- **database/models.py**: SQLAlchemy ORM models
- **models/**: Pydantic schemas for validation
- Used by both app and parser

## Running the Project

### Start Backend (Python 3.15)
```bash
cd app/
uv run --python 3.15 python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Or from root:
```bash
uv run --python 3.15 python -m uvicorn app.app.main:app --host 0.0.0.0 --port 8000
```

### Run Parser (Python 3.14)
```bash
cd parser/
uv run --python 3.14 python -m parser.scrapers.chicago_events_scraper
```

### Start Frontend
```bash
cd frontend/
npm run dev
```

### Run Tests
```bash
# App tests
cd app/
pytest tests/

# Parser tests
cd ../parser/
pytest tests/

# Integration tests
cd ..
pytest tests/
```

## Database Structure

**Shared SQLite database**: `data/events.db`

Tables:
- `events` - Event records from all sources
- `venues` - Chicago venue information
- `neighborhoods` - Chicago neighborhood definitions
- `chat_threads` - Conversation sessions
- `chat_messages` - Chat message history
- `audit_logs` - Security & operation logs
- `metrics` - Performance metrics

## Import Paths

### From App Code
```python
from shared.database import init_db, AsyncSessionLocal
from shared.database.models import EventModel, VenueModel
from shared.models import EventCreate, Event
from app.api import router
from app.logging import get_logger
```

### From Parser Code
```python
from shared.database import AsyncSessionLocal
from shared.database.models import EventModel
from shared.models import EventCreate
from parser.scrapers.chicago_events_scraper import scrape_chicago_events
```

## Development

### Add a New Scraper
1. Create `parser/parser/scraper/newsource.py`
2. Extend `BaseScraper` class
3. Implement `fetch_events()` method
4. Import in `parser/parser/__init__.py`
5. Add tests in `parser/tests/`

### Add an API Endpoint
1. Create route in `app/app/api/routes.py` or new file
2. Import router in `app/app/main.py`
3. Include in app: `app.include_router(router)`
4. Write tests in `app/tests/`

### Migrate Database Schema
```bash
```

## Configuration

- `.env` - Environment variables (API keys, database URL, etc.)
- `app/pyproject.toml` - App dependencies
- `parser/pyproject.toml` - Parser dependencies
- Root `pyproject.toml` - Monorepo configuration

## Deployment

### Docker (Future)
Each package can be containerized separately:
- `app/Dockerfile` for FastAPI backend
- `parser/Dockerfile` for scraper worker
- `frontend/Dockerfile` for React UI

### Scaling Strategy
1. **Backend**: Scale API instances (FastAPI + Uvicorn)
2. **Parser**: Run scraper jobs on schedule (cron, Kubernetes, etc.)
3. **Database**: Centralized SQLite or upgrade to PostgreSQL
4. **Frontend**: Static hosting (Vercel, Netlify, etc.)
