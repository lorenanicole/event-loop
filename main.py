import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.database import init_db, AsyncSessionLocal
from src.api import router, analytics_router
from src.scraper import DO312Scraper
from src.logging import configure_logging, get_logger
from src import telemetry

load_dotenv()

configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

# Global scraper instance
scraper_task = None


async def startup_event():
    """Initialize database on startup"""
    await init_db()
    logger.info("Database initialized")
    # For telemetry, we'll use AsyncSessionLocal when metrics are accessed


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
    description="AI-powered event discovery for Chicago. REACT agents + semantic search + production resilience patterns. Python 3.15 showcase.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)
app.include_router(analytics_router)


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "EventLoop",
        "tagline": "Async Event Discovery in the 312",
        "description": "AI-powered event discovery for Chicago with REACT agents and semantic search",
        "blog": "EventLoop: Building Production AI Apps with Python 3.15",
        "docs": "/docs",
        "features": {
            "ai_search": "REACT agent with Claude + PydanticAI",
            "semantic_matching": "NLTK-powered similarity matching",
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


# Serve frontend (if built)
if os.path.exists("frontend/dist"):
    app.mount("/static", StaticFiles(directory="frontend/dist"), name="static")

    @app.get("/{path_name:path}")
    async def serve_frontend(path_name: str):
        """Serve frontend files"""
        file_path = f"frontend/dist/{path_name}"
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # Fallback to index.html for SPA routing
        return FileResponse("frontend/dist/index.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", 8000))
    host = os.getenv("API_HOST", "0.0.0.0")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
    )
