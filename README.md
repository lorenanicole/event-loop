# 🏙️ Chicago Events Chatbot

**An AI-powered event discovery platform for Chicago, built with Python 3.15, async/await, and production-grade resilience patterns.**

This project showcases modern Python 3.15 features in a real-world application: PEP 649 deferred annotations, async-everywhere architecture, semantic NLP with NLTK, and defensive security against prompt injection attacks.

**Blog post theme**: "Building Production AI Apps with Python 3.15" - demonstrating resilience, observability, security, and testing at scale.

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

## 🚀 Quick Start

```bash
# 1. Clone and setup
git clone <repo>
cd python315
uv venv
source .venv/bin/activate

# 2. Install dependencies
uv pip install -e ".[dev,test]"

# 3. Setup environment
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

# 4. Install git hooks
invoke setup-hooks

# 5. Run tests
invoke test

# 6. Start server
python main.py

# 7. Chat
# Open http://localhost:8000 in browser
```

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
│   │   └── init.py              # DB initialization
│   ├── api/
│   │   └── routes.py            # FastAPI endpoints
│   ├── security.py              # Prompt injection defense
│   ├── resilience.py            # Circuit breaker + retry
│   └── telemetry.py             # OpenTelemetry setup
├── tests/                        # 118+ tests
│   ├── test_security.py         # Injection detection
│   ├── test_resilience.py       # Circuit breaker
│   ├── test_chatbot.py          # NLP utilities
│   ├── test_database.py         # SQLAlchemy models
│   ├── test_api.py              # FastAPI endpoints
│   └── test_scrapers.py         # Event extraction
├── frontend/
│   ├── chat-widget.html         # Chat UI
│   └── src/chat.ts              # SSE client
├── main.py                       # FastAPI app
├── tasks.py                      # Invoke task automation
├── pyproject.toml               # Dependencies & config
├── pytest.ini                   # Test config
├── .ruff.toml                   # Linting rules
├── .pre-commit-config.yaml      # Git hooks
└── DEVELOPMENT.md               # Dev setup guide
```

## 🧪 Testing

```bash
# Run all tests
invoke test

# By category
invoke test-category --category security
invoke test-category --category database
invoke test-category --category api

# Coverage report
invoke coverage
```

**Coverage**: 118+ tests across 6 modules (80%+ coverage target)

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

## 🎯 Python 3.15 Features Showcased

✨ **PEP 649** - Deferred evaluation of annotations
- Used in `src/ai/executor.py` for clean async typing
- Enables `async def execute(...) -> AsyncGenerator[StreamEvent, None]` without forward refs

✨ **Async/Await** - Async-everywhere architecture
- httpx.AsyncClient for concurrent scraping
- SQLAlchemy async_session for DB ops
- FastAPI for native async endpoints

✨ **Type Hints** - Modern union syntax (`X | Y`)
- Clean, readable type annotations
- Full type checking support

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

## 📊 Current State

✅ **1,022 Events** from 5 sources
✅ **118+ Tests** (security, resilience, database, API, scrapers)
✅ **Production-ready** git workflow (auto linting + testing)
✅ **Resilience patterns** (circuit breaker, retry, graceful degradation)
✅ **Security hardened** (prompt injection defense, output validation)
✅ **Fully observable** (OpenTelemetry, audit trails, analytics endpoints)

## 📄 License

MIT License - See LICENSE file

---

**Built for Python 3.15 with ❤️ and async/await**

🏙️ Forged in the 312, for the 312.
