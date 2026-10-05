"""
EventLoop Parser Client - Python 3.14
Stable scraper/parser that calls backend server via HTTP API
Runs independently on proven 3.14 version
"""

import sys
import logging
import asyncio
import httpx
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_URL = "http://127.0.0.1:8001"


class ParserClient:
    """Client for calling EventLoop backend server."""

    def __init__(self, backend_url: str = BACKEND_URL):
        self.backend_url = backend_url
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient()
        await self.check_backend_health()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def check_backend_health(self):
        """Verify backend server is running."""
        try:
            response = await self.client.get(f"{self.backend_url}/health")
            response.raise_for_status()
            health = response.json()
            logger.info(f"✓ Backend healthy (Python {health['python_version']})")
            logger.info(f"  Features: {', '.join(health['features'])}")
            return health
        except Exception as e:
            logger.error(f"✗ Cannot connect to backend: {e}")
            logger.error(f"  Is backend running on {self.backend_url}?")
            raise

    async def search_events(self, query: str, neighborhood: Optional[str] = None) -> dict:
        """Search for events using backend."""
        try:
            payload = {"query": query}
            if neighborhood:
                payload["neighborhood"] = neighborhood

            response = await self.client.post(
                f"{self.backend_url}/search",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"error": str(e)}

    async def get_neighborhood_events(self, neighborhood: str, limit: int = 100) -> dict:
        """Get events for a neighborhood from backend."""
        try:
            response = await self.client.get(
                f"{self.backend_url}/events/neighborhood/{neighborhood}",
                params={"limit": limit}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Neighborhood query error: {e}")
            return {"error": str(e)}

    async def get_all_venues(self) -> dict:
        """Get all venues from backend."""
        try:
            response = await self.client.get(f"{self.backend_url}/venues")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Venues query error: {e}")
            return {"error": str(e)}


async def main():
    """Demo parser client connecting to 3.15 backend."""
    logger.info("=" * 70)
    logger.info(f"EventLoop Parser Client - Python {sys.version_info.major}.{sys.version_info.minor}")
    logger.info("Connecting to Python 3.15 RC3 backend server...")
    logger.info("=" * 70)

    try:
        async with ParserClient() as client:
            logger.info("\n1. Searching for events...")
            result = await client.search_events("live music", neighborhood="Wicker Park")
            logger.info(f"   Results: {result}")

            logger.info("\n2. Getting venues...")
            venues = await client.get_all_venues()
            logger.info(f"   Total venues: {venues.get('total', 0)}")

            logger.info("\n✓ Parser-Backend communication successful!")
            logger.info("  - Parser: Python 3.14 (stable)")
            logger.info("  - Backend: Python 3.15 RC3 (new features)")
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
