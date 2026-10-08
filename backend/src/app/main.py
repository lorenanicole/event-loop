import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from app.api import analytics_router, router
from app.logging import configure_logging, get_logger
from shared.database import AsyncSessionLocal, init_db

load_dotenv()

configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

# Global scraper instance
scraper_task = None


async def startup_event():
    """Initialize database on startup"""
    await init_db()
    logger.info("Database initialized")

    # The two startup backfills that used to live here are gone. They
    # imported `scripts.backfill_events` and `scripts.backfill_locations`,
    # which import `from src.*` - a layout that stopped existing when the
    # project moved into backend/ - so every boot logged "No module named
    # 'scripts'" and skipped them. They had not run in a very long time.
    #
    # They are not reinstated here either way: a web server should not run
    # data migrations while it starts. Cost now has its own tool,
    # backfill_event_costs.py, which fetches each event's page rather than
    # re-reading text we already have.

    # Close conversations nobody came back to. At startup rather than on a
    # timer: a restart is a natural moment to tidy, and a sweep that only ran
    # while the app was up could never reach threads left by the previous run.
    try:
        from app.chat.threads import sweep_stale_threads
        from shared.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            closed = await sweep_stale_threads(session)
        if closed:
            logger.info(f"Closed {closed} stale chat threads")
    except Exception as e:
        logger.warning(f"Stale thread sweep skipped: {e}")

    # Warm the semantic search index in the background. The first call loads a
    # model from disk (downloading it once), so doing it here keeps that cost
    # off the first user query without delaying startup.
    asyncio.create_task(_warm_semantic_index())  # noqa: RUF006

    # For telemetry, we'll use AsyncSessionLocal when metrics are accessed


async def _warm_semantic_index() -> None:
    """Build the event embedding index without blocking startup."""
    try:
        from app.chat.semantic_index import event_index

        async with AsyncSessionLocal() as session:
            count = await event_index.rebuild(session)
        logger.info(f"Semantic index ready ({count} events)")
    except Exception as e:
        # Keyword search still works without it.
        logger.warning(f"Semantic index warm-up failed: {e}")


async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle"""
    await startup_event()
    yield
    await shutdown_event()


app = FastAPI(
    title="EventLoop: Async Event Discovery in the 312",
    description=(
        "AI-powered event discovery for Chicago. REACT agents + semantic search"
        " + production resilience patterns. Python 3.15 showcase."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
# FRONTEND_URL can be set to the Railway frontend domain to restrict CORS.
# Falls back to wildcard so the API works before the frontend is deployed.
_frontend_url = os.getenv("FRONTEND_URL", "")
_cors_origins = [_frontend_url] if _frontend_url else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)
app.include_router(analytics_router)


@app.get("/")
async def root():
    """API root — returns service info."""
    return {
        "name": "EventLoop",
        "tagline": "Async Event Discovery in the 312",
        "description": "AI-powered event discovery for Chicago with REACT agents and semantic search",  # noqa: E501
        "blog": "EventLoop: Building Production AI Apps with Python 3.15",
        "docs": "/docs",
        "features": {
            "ai_search": "REACT agent with Claude + PydanticAI",
            "semantic_matching": "Static embedding similarity (model2vec)",
            "resilience": "Circuit breaker + exponential backoff",
            "observability": "OpenTelemetry metrics + audit trails",
            "security": "Prompt injection defense + rate limiting",
        },
        "endpoints": {
            "events": "/api/events",
            "search": "/api/search",
            "chat": "/api/chat (SSE streaming)",
            "analytics": "/analytics/summary",
            "security": "/analytics/security",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")  # noqa: S104

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
    )
