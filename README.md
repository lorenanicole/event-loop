# 🏙️ EventLoop: Chicago Events Chatbot

**An AI-powered event discovery platform for Chicago, built with dual Python versions (3.15 RC3 + 3.14) showcasing modern async patterns, lazy imports, and production-grade resilience.**

This project demonstrates real-world Python 3.15 adoption:
- **Backend**: Python 3.15 RC3 with lazy imports, upgraded JIT compiler (+10% performance)
- **Parser**: Python 3.14 stable for proven scraping reliability  
- **Communication**: HTTP API bridge for clean separation of concerns

**Blog post theme**: "Python 3.15 in Production: Real Performance Gains & Dual-Version Architecture" - with measured benchmarks, dual-version patterns, and comprehensive testing at scale.

## ✨ Key Features

### **Smart Event Discovery**
- 🔍 **REACT Agent** - Multi-step reasoning with Claude + PydanticAI
- 🧠 **Semantic Search** - NLTK-powered similarity matching (find "events like that")
- 📝 **Natural Language** - Understands "concerts this weekend" → filters by date/category
- 🎯 **Smart Ranking** - Events scored by relevance (keyword + category + date proximity)

### **Data at Scale**
- 📊 **1,000+ Events** - Normalized from 5 sources (DO312, Ticketmaster, Your Chicago Guide, Timeout Chicago, Eventbrite)
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

### **Full Stack (Backend + Frontend)**

**Terminal 1: Backend**
```bash
# 1. Clone and setup
git clone https://github.com/lorenanicole/event-loop.git
cd python315

# 2. Create Python environment
uv venv

# 3. Install Python dependencies
uv pip install -e ".[dev,test]"

# 4. Setup environment
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY

# 5. Initialize database
python -c "from src.database import init_db; import asyncio; asyncio.run(init_db())"

# 6. Start backend
python main.py
# Backend running at http://localhost:8000
```

**Terminal 2: Frontend**
```bash
# From python315 directory:
cd frontend
npm install
npm run dev
# Frontend running at http://localhost:5173
```

### **Access the App**
- 🎯 **Chat UI**: http://localhost:5173
- 🔌 **API**: http://localhost:8000
- 📊 **Analytics**: http://localhost:8000/analytics
- ✅ **Health Check**: http://localhost:8000/health

## 📋 Tech Stack

**Language & Runtime**
- Python 3.15 (PEP 649 deferred annotations, modern async)
- uv (fast package manager)

**Backend**
- FastAPI (async web framework)
- SQLAlchemy + SQLite (ORM + database)
- PydanticAI (Claude + REACT agent loop)

**NLP & Search**
- NLTK (semantic similarity, tokenization)
- scikit-learn (TF-IDF vectorization)
- Claude Sonnet 5.5 (reasoning + semantic understanding)

**Quality & Reliability**
- pytest + pytest-asyncio (118+ tests)
- ruff (linting + formatting)
- OpenTelemetry (observability)
- pre-commit (git hooks)

## 🏗️ System Architecture

### Dual-Version Design (3.15 Backend + 3.14 Parser)

```
┌────────────────────────────────────────────────────────────────────┐
│                   EventLoop: Dual-Version Stack                    │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────────────┐      ┌──────────────────────────┐   │
│  │  Backend Server (3.15)   │      │  Parser Client (3.14)    │   │
│  │                          │      │                          │   │
│  │  • FastAPI + async/await │      │  • Web Scraper           │   │
│  │  • REACT Agent (Claude)  │ HTTP │  • BeautifulSoup         │   │
│  │  • Lazy imports          │◄────►│  • Playwright            │   │
│  │  • JIT compiler (+10%)   │      │  • Proven stable version │   │
│  │  • Chat SSE streaming    │      │  • Low risk              │   │
│  │  • frozendict, sentinels │      │                          │   │
│  │                          │      │                          │   │
│  └──────────────────────────┘      └──────────────────────────┘   │
│           │                                      │                 │
│           │ (Query API)                          │ (Scrapes)       │
│           └──────────────┬───────────────────────┘                 │
│                          ▼                                         │
│              ┌───────────────────────┐                             │
│              │   SQLite Database     │                             │
│              │  (4,578 events)       │                             │
│              │  (37 active venues)   │                             │
│              │  (14 neighborhoods)   │                             │
│              └───────────────────────┘                             │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

User Flow: Browser → FastAPI (3.15) → REACT Agent → Tools → DB/API
           Parser (3.14) → Scraper → DB (HTTP bridge)
```

## 📁 Project Structure

```
python315/
├── src/
│   ├── ai/
│   │   ├── chatbot.py           # REACT agent with tools
│   │   ├── executor.py          # SSE streaming + telemetry
│   │   ├── intent_classifier.py # Intent detection
│   │   └── smart_search.py      # NLTK semantic search
│   ├── database/
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── database.py          # DB initialization
│   │   └── __init__.py
│   ├── api/
│   │   ├── routes.py            # FastAPI endpoints
│   │   └── analytics_router.py  # Analytics endpoints
│   ├── scrapers/
│   │   ├── chicago_events_scraper.py    # Main unified scraper
│   │   ├── venue_scraper.py             # Core VenueScraper framework
│   │   ├── sprint*.py                   # Venue discovery scripts
│   │   └── chicago_venues_master.py     # Venue database
│   ├── security.py              # Prompt injection defense
│   ├── resilience.py            # Circuit breaker + retry
│   ├── telemetry.py             # OpenTelemetry setup
│   ├── logging.py               # Structured logging
│   ├── backend_server_315.py    # Python 3.15 backend (lazy imports, JIT)
│   └── parser_client_314.py     # Python 3.14 parser client
│
├── benchmarks/
│   ├── perf_compare.py          # Performance benchmarks
│   ├── compare_results.py       # Benchmark comparison tool
│   ├── README.md                # Benchmarking guide
│   └── results/
│       ├── benchmark_py314.json # Python 3.14 results
│       └── benchmark_py315.json # Python 3.15 RC3 results
│
├── tests/                        # 40+ comprehensive tests
│   ├── test_core_functionality.py  # Cross-version compatibility
│   ├── test_security.py            # Injection detection
│   ├── test_resilience.py          # Circuit breaker
│   ├── test_chatbot.py             # REACT agent
│   ├── test_database.py            # SQLAlchemy models
│   ├── test_api.py                 # FastAPI endpoints
│   ├── test_chat_sse.py            # SSE streaming
│   └── conftest.py                 # Fixtures
│
├── frontend/
│   ├── index.html               # Chat widget
│   ├── src/
│   │   ├── chat.ts              # SSE client
│   │   └── app.ts               # Main app
│   └── style.css                # Styling
│
├── scripts/
│   ├── backfill_*.py            # Data backfill scripts
│   └── populate_*.py            # Database population
│
├── main.py                       # FastAPI app (unified)
├── run_dual_stack.sh            # Launch 3.14 parser + 3.15 backend
├── tasks.py                      # Invoke task automation
├── pyproject.toml               # Dependencies (3.14+ support)
├── pytest.ini                   # Test config
├── .ruff.toml                   # Linting rules
├── .pre-commit-config.yaml      # Git hooks
├── .env.example                 # Environment template
├── events.db                    # SQLite database (4,578 events)
├── DEVELOPMENT.md               # Dev setup guide
├── README.md                    # This file
└── LICENSE                      # MIT License
```

## 🧪 Testing & Benchmarking

### Unit Tests (40+ tests)

```bash
# Run all tests
pytest -v

# Run specific test module
pytest tests/test_core_functionality.py -v

# Run with coverage
pytest --cov=src tests/

# Run by marker
pytest -m "asyncio" -v
```

**Test Coverage:**
- ✅ Chat API endpoints (health checks, streaming)
- ✅ Database operations (connections, models, queries)
- ✅ Scraper functionality (VenueConfig, validation)
- ✅ Search & REACT agent integration
- ✅ Python 3.15 specific features (frozendict, sentinel)
- ✅ Async/await compatibility patterns
- ✅ Dual-version architecture (parser client, backend server)

### Performance Benchmarks (Real Data)

```bash
# Run benchmarks on Python 3.14
uv run --python 3.14 python benchmarks/perf_compare.py

# Run benchmarks on Python 3.15 RC3
uv run --python 3.15.0rc3 python benchmarks/perf_compare.py

# Compare results
uv run benchmarks/compare_results.py
```

**Benchmark Results:**

| Metric | Python 3.14 | Python 3.15 RC3 | Improvement |
|--------|-------------|-----------------|------------|
| List Comprehensions | 3.91ms | 2.59ms | **+33.8%** ⚡ |
| JSON Operations | 104.95ms | 76.78ms | **+26.8%** ⚡ |
| Async Operations | 201.85ms | 199.08ms | **+1.4%** ✓ |
| **Average** | - | - | **+10.1%** ⚡ |

**Key Insights:**
- List comprehensions 33.8% faster (JIT optimization)
- JSON operations 26.8% faster (serialization improvements)
- Async operations slightly faster (event loop improvements)
- Production recommendation: Upgrade for CPU-intensive workloads

See [benchmarks/README.md](benchmarks/README.md) for detailed methodology.

## 🔧 Development Workflow

```bash
# Format & lint
invoke format
invoke lint --fix

# Pre-commit checks (automatic on git commit)
invoke pre-commit

# See all commands
invoke info
```

**Git hooks automatically run on commit:**
1. Ruff linting + formatting
2. Security scan (Bandit)
3. Core tests (security + resilience)
4. All pass → commit succeeds

See [DEVELOPMENT.md](DEVELOPMENT.md) for complete setup guide.

## 📚 Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Dev environment setup, task automation, git workflow
- **[TESTING.md](TESTING.md)** - Comprehensive testing guide (118+ tests)
- **[Architecture Decisions](src/)** - Code comments explaining design choices

## 🚀 Dual-Version Architecture

This project demonstrates production-ready Python version mixing:

### Backend (Python 3.15 RC3)
- **Lazy Imports** - Defer heavy dependencies (json, asyncio) until first use
- **Upgraded JIT** - Automatic compilation of hot loops (+7-12% speedup)
- **frozendict** - Immutable configs for hashability and caching
- **sentinel values** - Proper replacement for None-checking patterns
- **TaskGroup.cancel()** - Clean async cancellation patterns
- **Better Error Messages** - Improved tracebacks and AttributeError hints

### Parser (Python 3.14)
- **Proven Stability** - LTS version for production scraping
- **Web Scraping** - BeautifulSoup + Playwright for event extraction
- **HTTP Client** - Calls 3.15 backend via REST API
- **Low Risk** - Minimal version-specific dependencies

### Communication Bridge
- **HTTP API** - Clean REST boundary between versions
- **Async-Friendly** - Both versions speak httpx.AsyncClient
- **Scalable** - Can run on separate machines

## 🎯 Python 3.15 Features Showcased

✨ **Lazy Imports** (PEP 810)
- Used in `src/backend_server_315.py`: `lazy import json`
- Defers module loading until first use
- Reduces startup time for CLI tools with heavy dependencies
- Measured: ~0.7ms overhead per lazy import

✨ **Async/Await** - Async-everywhere architecture
- httpx.AsyncClient for concurrent scraping
- SQLAlchemy async_session for DB ops
- FastAPI for native async endpoints
- PydanticAI for reactive agent loops

✨ **Type Hints** - Modern union syntax (`X | Y`)
- Clean, readable type annotations
- Full type checking support
- Better IDE autocomplete

✨ **frozendict** (3.15)
- Immutable dictionary type
- Hashable (can use as dict key or in cache decorators)
- Used in config management
- Thread-safe by design

✨ **sentinel type** (3.15)
- Proper "missing value" indicator (not just object())
- Prints as `MISSING` instead of `<object object at 0x...>`
- Survives pickling for cross-process use
- Replaces decades-old `_sentinel = object()` pattern

## 🔐 Security Highlights

**Prompt Injection Defense**
- Detects: role override, system prompt extraction, SQL injection, code injection
- Rate limits: 3 attempts allowed, session blocked after 5
- Output validates: no API keys, system prompts, credentials leaked

**Resilience**
- Circuit breaker: auto-fallback when services fail
- Retry logic: exponential backoff (100ms → 400ms)
- Graceful degradation: DB-only search when LLM unavailable

**Observability**
- Every operation logged to audit trail
- OpenTelemetry metrics (sessions, tokens, latency)
- Security dashboard at `/analytics/security`

## 🛠️ Project Setup

### Prerequisites
- **Python**: 3.14 or 3.15 RC3+
- **Package Manager**: uv (auto-installs Python)
- **Database**: SQLite (bundled)
- **API Key**: ANTHROPIC_API_KEY for Claude Sonnet 5.5

### Installation

```bash
# 1. Clone repository
git clone <repo>
cd python315

# 2. Create virtual environment (uv does this automatically)
uv venv

# 3. Install dependencies
uv pip install -e ".[dev,test]"

# 4. Setup environment
cp .env.example .env
# Edit .env to add ANTHROPIC_API_KEY

# 5. Initialize database
python -c "from src.database import init_db; import asyncio; asyncio.run(init_db())"

# 6. Run tests to verify setup
pytest -v

# 7. Start development server
python main.py
# Server runs at http://localhost:8000
```

### Dual-Version Setup (Optional)

Run both Python 3.14 parser and 3.15 backend:

```bash
# Start both versions
bash run_dual_stack.sh

# Or manually:
# Terminal 1: Start 3.15 backend
uv run --python 3.15.0rc3 python src/backend_server_315.py

# Terminal 2: Start 3.14 parser
uv run --python 3.14 python src/parser_client_314.py
```

### Development Commands

```bash
# Format code
ruff format src/ tests/

# Lint code
ruff check src/ tests/ --fix

# Run tests
pytest -v
pytest --cov=src tests/

# Run benchmarks
uv run --python 3.14 python benchmarks/perf_compare.py
uv run --python 3.15.0rc3 python benchmarks/perf_compare.py
uv run benchmarks/compare_results.py
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for complete setup guide.

## 📊 Current State

✅ **4,578 Events** from 22 venues across 14 Chicago neighborhoods
✅ **37 Active Venues** with working event extraction
✅ **40+ Unit Tests** (chat, database, scraper, search, dual-version)
✅ **5 Performance Benchmarks** showing 10.1% avg improvement on 3.15
✅ **Dual-Version Architecture** (3.15 backend + 3.14 parser)
✅ **Production-ready** git workflow (auto linting + testing)
✅ **Resilience patterns** (circuit breaker, retry, graceful degradation)
✅ **Security hardened** (prompt injection defense, output validation)
✅ **Fully observable** (OpenTelemetry, audit trails, analytics endpoints)

**Blog Post Status**: Ready for "Python 3.15 in Production" with real performance data

## 📄 License

MIT License - See LICENSE file

---

**Built for Python 3.15 with ❤️ and async/await**

🏙️ Forged in the 312, for the 312.
