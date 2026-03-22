from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hopefx.config.settings import settings
from hopefx.data.feed import feed_manager
from hopefx.execution.oms import oms

router = APIRouter()


class HealthStatus(BaseModel):
    status: str
    version: str
    environment: str
    components: dict[str, str]


@router.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    """System health check."""
    components = {
        "feed_manager": "up" if feed_manager._running else "down",
        "oms": "up" if oms._running else "down",
    }

    # Check all brokers
    from hopefx.execution.router import smart_router
    for name, broker in smart_router.brokers.items():
        components[f"broker_{name}"] = "connected" if broker.connected else "disconnected"

    return HealthStatus(
        status="healthy" if all(v == "up" or v == "connected" for v in components.values()) else "degraded",
        version="9.5.0",
        environment=settings.environment.value,
        components=components,
    )
