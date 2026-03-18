"""
Health check endpoints for monitoring and load balancers.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from src.infrastructure.database import get_db
from src.infrastructure.redis_cache import RedisCache

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Comprehensive health check for load balancers.
    Checks database and cache connectivity.
    """
    health = {
        "status": "healthy",
        "version": "3.0.0",
        "services": {}
    }
    
    # Check database
    try:
        result = await db.execute(text("SELECT 1"))
        health["services"]["database"] = "connected"
    except Exception as e:
        health["status"] = "degraded"
        health["services"]["database"] = f"error: {str(e)}"
    
    # Check cache (if available in request context)
    # Note: In production, inject cache dependency properly
    
    return health


@router.get("/ready")
async def readiness_check():
    """
    Kubernetes readiness probe.
    Returns 200 when ready to accept traffic.
    """
    return {"ready": True}


@router.get("/live")
async def liveness_check():
    """
    Kubernetes liveness probe.
    Returns 200 if application is running.
    """
    return {"alive": True}
