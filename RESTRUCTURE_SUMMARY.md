# Project Restructure Summary

## What Changed
EventLoop was reorganized from a single `src/` directory into a clean monorepo structure with separate packages for the backend app, web scraper, and shared utilities.

## Before (Old Structure)
```
eventloop/
├── src/              # Everything mixed together
│   ├── api/
│   ├── database/
│   ├── ai/
│   ├── models/
│   ├── scrapers/
│   ├── scraper/
│   ├── logging.py
│   ├── security.py
│   └── ...
├── main.py           # Root level entry point
├── tests/
└── ...
```

## After (New Structure)
```
eventloop/
├── app/              # FastAPI Backend (Python 3.15)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── ai/
│   │   └── ...
│   ├── tests/
│   └── pyproject.toml
│
├── parser/           # Web Scraper (Python 3.14)
│   ├── parser/
│   │   ├── scraper/
│   │   └── scrapers/
│   ├── tests/
│   └── pyproject.toml
│
├── shared/           # Database & Models (Both use)
│   ├── database/
│   └── models/
│
├── frontend/         # React UI (unchanged)
├── scripts/          # Utilities
├── benchmarks/       # Performance tests
└── pyproject.toml    # Root monorepo config
```

## Key Improvements

### 1. **Clear Separation of Concerns**
- `app/` - FastAPI backend with AI features
- `parser/` - Web scraping and data extraction
- `shared/` - Database and models shared by both

### 2. **Independent Deployment**
Each package can be deployed separately:
- Backend can scale independently from scraper
- Different Python versions (3.15 for app, 3.14 for parser)
- Different dependencies per package

### 3. **Better Package Management**
- Each has own `pyproject.toml` with specific dependencies
- Clear import paths (no more `src.*` confusion)
- Easier to extract into separate repositories later

## Import Changes

### App Code
**Before**: `from src.database import init_db`
**After**: `from shared.database import init_db`

### Parser Code
**Before**: `from src.scrapers.chicago_events_scraper import scrape_chicago_events`
**After**: `from parser.scrapers.chicago_events_scraper import scrape_chicago_events`

## Files Deleted

- `src/` - Entire directory (moved to app/, parser/, shared/)
- `main.py` - Moved to `app/app/main.py`
- `src/backend_server_315.py` - Old experimental dual-version file
- `src/parser_client_314.py` - Old experimental client

## Running the Project

### Start Backend (3.15)
```bash
cd app/
uv run --python 3.15 python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Start Parser (3.14)
```bash
cd parser/
uv run --python 3.14 python -m parser.scrapers.chicago_events_scraper
```

### Start Frontend
```bash
cd frontend/
npm run dev
```

## Database Sharing

Both `app/` and `parser/` import from `shared/`:
- `shared.database` - SQLAlchemy models, engine setup
- `shared.models` - Pydantic schemas

The database file remains centralized: `data/events.db`

## Next Steps

1. **Test the restructured code**:
   ```bash
   pytest tests/
   pytest app/tests/
   pytest parser/tests/
   ```

2. **Update IDE/Editor settings** to recognize new package structure

3. **Deploy**: Each package can be deployed as:
   - Docker container
   - Systemd service
   - Kubernetes pod

4. **Document in team wiki/docs** the new layout

## Notes

- All imports have been updated to use new paths
- Database and models are shared (in `shared/`)
- Python version requirements are separated per package
- The old `src/` directory is completely removed
