"""
FastAPI application factory with full instrumentation.
"""

from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from src.api.middleware.auth import JWTAuthMiddleware
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.routes import backtest, health, strategies, trading
from src.core.config import settings
from src.core.events import get_event_bus
from src.core.logging_config import configure_logging, get_logger
from src.core.lifecycle import LifecycleManager
from src.infrastructure.cache import close_cache, get_cache
from src.infrastructure.database import close_db, init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    configure_logging(
        log_level=settings.log_level.value,
        json_output=settings.is_production,
        log_file=settings.logs_dir / "api.log"
    )
    
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    
    # Initialize Sentry in production
    if settings.is_production:
        sentry_sdk.init(
            dsn="https://examplePublicKey@o0.ingest.sentry.io/0",  # Replace with actual DSN
            traces_sample_rate=0.1,
        )
    
    # Initialize infrastructure
    await init_db()
    await get_cache()
    
    # Start event bus
    event_bus = get_event_bus()
    await event_bus.start()
    
    lifecycle = LifecycleManager()
    await lifecycle.initialize()
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await event_bus.stop()
    await lifecycle.shutdown()
    await close_cache()
    await close_db()


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Institutional-grade XAUUSD AI Trading Platform",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan
    )
    
    # Middleware (order matters)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://hopefx.trading"] if settings.is_production else ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(JWTAuthMiddleware)
    
    # Routes
    app.include_router(health.router, prefix="/health", tags=["Health"])
    app.include_router(trading.router, prefix="/api/v1/trading", tags=["Trading"])
    app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["Backtest"])
    app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["Strategies"])
    
    # Metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "request_id": getattr(request.state, "request_id", "unknown")}
        )
    
    return app


app = create_app()
