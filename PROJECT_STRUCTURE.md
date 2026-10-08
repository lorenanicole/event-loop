# EventLoop Project Structure

EventLoop is a monorepo. The Python API, chatbot, scrapers, and shared data
models live in one backend package and use the same SQLite database. The browser
client is a TypeScript/Vite application.

```text
eventloop/
├── backend/
│   ├── src/app/                 # FastAPI routes, AI/chat, security, telemetry
│   ├── src/scrapers/            # External API and venue scrapers
│   ├── src/shared/              # SQLAlchemy models, schemas, categories, geo
│   ├── tests/                   # App, parser/scraper, and shared tests
│   ├── data/                    # Local database and neighborhood source data
│   ├── additive_scrape.py       # Additive scraper runner
│   └── pyproject.toml           # Python requirements and pytest config
├── frontend/
│   ├── src/                     # TypeScript UI, API client, and chat
│   ├── public/
│   └── package.json
├── benchmarks/                  # Interpreter microbenchmarks and saved results
├── tasks.py                     # Root Invoke tasks
├── DEVELOPMENT.md
├── README.md
├── RAG_PIPELINE.md
└── PROJECT_STRUCTURE.md
```

## Backend

The backend package uses Python 3.15 in the current local environment; its
`pyproject.toml` declares Python 3.14 or newer. Scrapers are not a separate
runtime/package: they use the backend's Python environment and database.

Important modules:

- `backend/src/app/main.py`: FastAPI application and startup lifecycle
- `backend/src/app/api/routes.py`: event, search, chat, and analytics endpoints
- `backend/src/app/ai/`: intent classification, retrieval, chatbot, persona, and
  conversation execution
- `backend/src/scrapers/external/`: external event sources
- `backend/src/scrapers/custom/venue/`: venue scraper framework and configs
- `backend/src/shared/database/`: SQLAlchemy models, filters, and DB setup
- `backend/src/shared/geo/`: neighborhood boundary and location resolution
- `backend/data/events.db`: default local SQLite database

`additive_scrape.py` runs configured venue scrapers and a set of external
sources without deleting existing event rows. It accepts venue-name filters or
`--only external` / `--only venues`; it does not currently select one external
source from the command line.

## Frontend

The frontend is TypeScript with Vite, not React. `frontend/src/main.ts` starts
the event search UI and chat widget. Run its development server from
`frontend/` with `npm run dev`.

## Tests And Tasks

Tests are under `backend/tests/` and run with:

```bash
cd backend
.venv/bin/python -m pytest
```

Root-level Invoke tasks are defined in `tasks.py`; they call the backend's
`.venv` for test and coverage tasks. The available development commands are
listed by `uv run --with invoke invoke --list` from the repository root.

## Benchmarks

`benchmarks/perf_compare.py` contains small Python interpreter microbenchmarks
for imports, dictionary/list operations, JSON operations, and async task
scheduling. These are not measurements of the API, chatbot, database, or
scraper throughput; saved result files are individual runs, not controlled
performance evidence.
