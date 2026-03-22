"""Health check endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.monitoring.health import HealthChecker

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    components: dict
    version: str = "2.0.0"


@router.get("", response_model=HealthResponse)
async def health_check():
    """Basic health check."""
    return HealthResponse(
        status="healthy",
        components={"api": "up", "database": "up", "redis": "up"}
    )


@router.get("/deep")
async def deep_health():
    """Deep health check with all components."""
    checker = HealthChecker()
    return await checker.check_all()
