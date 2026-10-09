# ── EventLoop API ────────────────────────────────────────────────────────────
# Python 3.15 + uv, no Playwright (scrapers run in a separate service).
# The SQLite database is expected on a Railway volume mounted at /data.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.15.0rc3-slim

WORKDIR /app

# System deps + uv in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    curl \
    && pip install --no-cache-dir uv==0.12.24 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first so Docker caches this layer
COPY pyproject.toml uv.lock ./

# Install third-party dependencies only — skip building the local package
# so Docker can cache this layer independently of source changes.
RUN uv sync --frozen --extra app --no-dev --no-install-project

# Copy source + README (README is required by pyproject.toml for package build)
COPY src/ ./src/
COPY README.md ./

# Now install the local eventloop package itself
RUN uv sync --frozen --extra app --no-dev

# The data directory is where Railway will mount the persistent volume.
# Create it so the app can start without a volume attached (e.g. local dev).
RUN mkdir -p /data

# Railway injects PORT; default to 8000 for local runs
ENV PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DATABASE_URL=sqlite+aiosqlite:////data/events.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
