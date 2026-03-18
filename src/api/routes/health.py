"""
Health check endpoints.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.infrastructure.cache import get_cache
from src.infrastructure.database import get_db
from src.infrastructure.monitoring import HealthChecker

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict
    timestamp: str


@router.get("/", response_model=HealthResponse)
async def health_check():
    """Liveness probe."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "checks": {},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/ready")
async def readiness_check():
    """Readiness probe with dependency checks."""
    checker = HealthChecker()
    
    # Register checks
    async def check_db():
        async with get_db() as db:
            await db.execute("SELECT 1")
            return True
    
    async def check_cache():
        cache = await get_cache()
        return await cache.health_check()
    
    checker.register("database", check_db)
    checker.register("cache", check_cache)
    
    result = await checker.check()
    
    return result
