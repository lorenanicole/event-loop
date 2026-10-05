"""
EventLoop Backend Server - Python 3.15 RC3
Uses 3.15 features: lazy imports, upgraded JIT, better async support
Runs independently from parser, communicates via HTTP API
"""

import sys
import logging
from contextlib import asynccontextmanager

lazy import json
lazy import asyncio

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"EventLoop Backend starting on Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


# ===== MODELS =====

class SearchRequest(BaseModel):
    query: str
    neighborhood: str | None = None


class SearchResult(BaseModel):
    query: str
    results: list[dict]
    count: int


# ===== DATABASE SETUP =====

DATABASE_URL = "sqlite+aiosqlite:///./events.db"

engine = None
async_session_maker = None


async def init_db():
    """Initialize database connection."""
    global engine, async_session_maker
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
    )
    logger.info("Database initialized")


async def close_db():
    """Close database connection."""
    if engine:
        await engine.dispose()
        logger.info("Database closed")


# ===== LIFECYCLE =====

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager using 3.15 async patterns."""
    logger.info("Backend starting up...")
    await init_db()
    yield
    logger.info("Backend shutting down...")
    await close_db()


# ===== APP SETUP =====

app = FastAPI(
    title="EventLoop Backend",
    description="Event discovery backend (Python 3.15 RC3)",
    version="3.15",
    lifespan=lifespan,
)


# ===== ROUTES =====

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "features": ["lazy_imports", "frozendict", "sentinel", "upgraded_jit"]
    }


@app.post("/search")
async def search(request: SearchRequest) -> SearchResult:
    """
    Search for events using REACT agent.
    Uses lazy import of json and asyncio only when needed.
    """
    try:
        # Lazy imports already triggered by this point if model needs them
        logger.info(f"Search request: {request.query}")

        # TODO: Call REACT agent for search
        return SearchResult(
            query=request.query,
            results=[],
            count=0
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/events/neighborhood/{neighborhood}")
async def get_neighborhood_events(neighborhood: str, limit: int = 100):
    """Get events for a specific neighborhood."""
    if not async_session_maker:
        return JSONResponse(status_code=503, content={"error": "Database not initialized"})

    try:
        async with async_session_maker() as session:
            # TODO: Query events from database
            return {
                "neighborhood": neighborhood,
                "events": [],
                "total": 0
            }
    except Exception as e:
        logger.error(f"Database error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/venues")
async def get_all_venues():
    """Get all configured venues."""
    if not async_session_maker:
        return JSONResponse(status_code=503, content={"error": "Database not initialized"})

    try:
        async with async_session_maker() as session:
            # TODO: Query venues from database
            return {
                "venues": [],
                "total": 0
            }
    except Exception as e:
        logger.error(f"Database error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ===== STARTUP =====

if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("EventLoop Backend Server - Python 3.15 RC3")
    logger.info("Features: Lazy Imports, Upgraded JIT, frozendict, sentinels")
    logger.info("=" * 70)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
        log_level="info",
    )
