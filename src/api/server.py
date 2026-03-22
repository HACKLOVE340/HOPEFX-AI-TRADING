"""
Production FastAPI server with all middleware and routes.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
import structlog
import time

from src.config.settings import get_settings
from src.config.logging_config import configure_logging
from src.infrastructure.database import init_db, close_db
from src.infrastructure.redis_cache import RedisCache
from src.api.routes import health, trading, backtest, strategies, marketplace
from src.api.middleware.rate_limit import RateLimitMiddleware

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown sequences.
    """
    # Startup
    configure_logging(
        log_level=settings.log_level,
        json_format=settings.environment == "production"
    )
    
    logger.info("application_starting", 
               version=settings.app_version,
               environment=settings.environment)
    
    # Initialize database
    await init_db()
    logger.info("database_initialized")
    
    # Initialize Redis cache
    app.state.cache = RedisCache()
    await app.state.cache.connect()
    logger.info("cache_connected")
    
    yield
    
    # Shutdown
    logger.info("application_shutting_down")
    await close_db()
    await app.state.cache.disconnect()
    logger.info("shutdown_complete")


def create_application() -> FastAPI:
    """Application factory pattern."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Institutional-grade XAUUSD AI Trading Platform",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan
    )
    
    # Middleware (order matters)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://hopefx.app", "http://localhost:3000"] if settings.environment == "production" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    
    # Prometheus metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", 
                    path=request.url.path,
                    error=str(exc),
                    exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "request_id": getattr(request.state, "request_id", None)}
        )
    
    # Request timing middleware
    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        start = time.time()
        request.state.request_id = os.urandom(8).hex()
        response = await call_next(request)
        duration = time.time() - start
        
        logger.info("request_completed",
                   path=request.url.path,
                   method=request.method,
                   duration_ms=round(duration * 1000, 2),
                   status_code=response.status_code)
        
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    
    # Include routers
    app.include_router(health.router)
    app.include_router(trading.router, prefix="/api/v1")
    app.include_router(backtest.router, prefix="/api/v1")
    app.include_router(strategies.router, prefix="/api/v1")
    app.include_router(marketplace.router, prefix="/api/v1")
    
    return app


app = create_application()
