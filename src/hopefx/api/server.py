from __future__ import annotations

import asyncio

import structlog
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import make_asgi_app

from hopefx.api.middleware.auth import JWTAuthMiddleware
from hopefx.api.middleware.rate_limit import RateLimitMiddleware
from hopefx.api.routes import health, trades, ws
from hopefx.config.settings import settings

logger = structlog.get_logger()


def create_app() -> FastAPI:
    """Create configured FastAPI application."""
    app = FastAPI(
        title="HOPEFX-GODMODE",
        description="Production-grade AI trading platform",
        version="9.5.0",
        docs_url="/docs" if not settings.is_production else None,
    )

    # Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else ["https://hopefx.io"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(JWTAuthMiddleware)
    app.add_middleware(RateLimitMiddleware)

    # Routes
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(trades.router, prefix="/api/v1")

    # Prometheus metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # WebSocket
    app.add_websocket_route("/ws", ws.websocket_endpoint)

    # OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)

    @app.on_event("startup")
    async def startup() -> None:
        logger.info("api.startup")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        logger.info("api.shutdown")

    return app


def run_server() -> None:
    """Run production server."""
    app = create_app()

    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        log_level=settings.log_level.lower(),
        access_log=False,  # Use structlog instead
    )
