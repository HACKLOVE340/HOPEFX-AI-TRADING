"""FastAPI application."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from src.api.routers import health, trades, ml, ws
from src.api.middleware.auth import JWTAuthMiddleware
from src.core.bus import event_bus

logger = structlog.get_logger()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan."""
    # Startup
    await event_bus.start()
    logger.info("API starting up")
    
    yield
    
    # Shutdown
    await event_bus.stop()
    logger.info("API shutting down")


app = FastAPI(
    title="HOPEFX v2 - XAUUSD AI Trading Platform",
    version="2.0.0",
    docs_url="/docs" if __debug__ else None,
    lifespan=lifespan,
)

# Middleware
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(trades.router, prefix="/api/v1/trades", tags=["trades"])
app.include_router(ml.router, prefix="/api/v1/ml", tags=["ml"])

# WebSocket
app.include_router(ws.router, prefix="/ws")

# OpenTelemetry
FastAPIInstrumentor.instrument_app(app)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "HOPEFX v2",
        "version": "2.0.0",
        "status": "operational",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "trades": "/api/v1/trades",
            "ml": "/api/v1/ml",
            "websocket": "/ws/stream"
        }
    }
