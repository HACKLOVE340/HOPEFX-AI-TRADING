# src/hopefx/api/main.py
"""
Production FastAPI application with full middleware stack.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from hopefx.api.routes import health, trading, backtest, ml, websocket
from hopefx.config.settings import settings
from hopefx.core.events import get_event_bus
from hopefx.infrastructure.monitoring import get_metrics_exporter
from hopefx.infrastructure.redis import get_redis_pool

logger = structlog.get_logger()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    logger.info("api_startup", version=settings.version, environment=settings.environment.value)
    
    # Initialize connections
    await get_redis_pool()
    event_bus = await get_event_bus()
    await event_bus.start()
    
    metrics = get_metrics_exporter()
    metrics.health.set_ready("redis", True)
    
    yield
    
    # Shutdown
    logger.info("api_shutdown")
    await event_bus.stop()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],  # ✅ EXPLICIT
        expose_headers=["X-Request-ID"],
        max_age=600
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        max_age=600
    )
    
    # Compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Request logging
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = asyncio.get_event_loop().time()
        
        response = await call_next(request)
        
        duration = (asyncio.get_event_loop().time() - start) * 1000
        
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration,
            client=request.client.host if request.client else None
        )
        
        return response
    
    # Routes
    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(trading.router, prefix="/api/v1/trading", tags=["trading"])
    app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["backtest"])
    app.include_router(ml.router, prefix="/api/v1/ml", tags=["ml"])
    app.include_router(websocket.router, prefix="/ws")
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            error=str(exc),
            exc_info=True
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"}
        )
    
    return app


app = create_app()


@app.get("/")
async def root():
    """API root."""
    return {
        "name": "HOPEFX API",
        "version": settings.version,
        "environment": settings.environment.value,
        "status": "operational"
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    exporter = get_metrics_exporter()
    content, content_type = exporter.get_prometheus_metrics()
    return PlainTextResponse(content=content, media_type=content_type)
