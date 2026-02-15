#!/usr/bin/env python3
"""
HOPEFX AI Trading Framework - API Server

FastAPI-based REST API server for the trading framework.
Provides endpoints for:
- Trading operations
- Market data access
- Portfolio management
- Backtesting
- System status and health checks
- Admin panel
- Paper Trading Dashboard
"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import uvicorn

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from api.admin import router as admin_router
from api.trading import router as trading_router
from cache import MarketDataCache
from config import initialize_config
from database.models import Base

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="HOPEFX AI Trading API",
    description="REST API for HOPEFX AI Trading Framework",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Include routers
app.include_router(trading_router)
app.include_router(admin_router)

# Global application state
class AppState:
    """Application state container"""
    def __init__(self):
        self.config = None
        self.db_engine = None
        self.db_session_factory = None
        self.cache = None
        self.initialized = False

app_state = AppState()


# Pydantic models
class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    environment: str
    components: Dict[str, str]


class StatusResponse(BaseModel):
    """System status response"""
    application: str
    version: str
    environment: str
    config_loaded: bool
    database_connected: bool
    cache_connected: bool
    api_configs: int


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None


# Dependency to get database session
def get_db() -> Session:
    """Get database session"""
    if not app_state.db_session_factory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized"
        )

    db = app_state.db_session_factory()
    try:
        yield db
    finally:
        db.close()


# CORS configuration
def setup_cors(app: FastAPI):
    """Setup CORS middleware"""
    allowed_origins = os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info("=" * 70)
    logger.info("HOPEFX AI TRADING API - STARTING")
    logger.info("=" * 70)

    try:
        # Initialize configuration
        logger.info("Loading configuration...")
        encryption_key = os.getenv('CONFIG_ENCRYPTION_KEY')
        if not encryption_key:
            logger.warning("CONFIG_ENCRYPTION_KEY not set. Using default for development.")
            os.environ['CONFIG_ENCRYPTION_KEY'] = 'dev-key-minimum-32-characters-long-for-testing'

        app_state.config = initialize_config()
        logger.info(f"✓ Configuration loaded: {app_state.config.environment}")

        # Initialize database
        logger.info("Initializing database...")
        connection_string = app_state.config.database.get_connection_string()
        app_state.db_engine = create_engine(
            connection_string,
            pool_size=app_state.config.database.connection_pool_size,
            max_overflow=app_state.config.database.max_overflow,
        )
        try:
            Base.metadata.create_all(app_state.db_engine)
            logger.info("✓ Database initialized")
        except Exception as e:
            logger.warning(f"⚠ Database initialization had issues: {e}")
            # Continue anyway - database might already exist or have compatibility issues
            logger.info("Continuing with existing database state...")
        
        app_state.db_session_factory = sessionmaker(bind=app_state.db_engine)

        # Initialize cache
        logger.info("Initializing cache...")
        try:
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            app_state.cache = MarketDataCache(
                host=redis_host,
                port=redis_port,
                max_retries=3,
            )
            logger.info("✓ Cache initialized")
        except Exception as e:
            logger.warning(f"⚠ Cache initialization failed: {e}")
            app_state.cache = None

        app_state.initialized = True
        logger.info("=" * 70)
        logger.info("API SERVER READY")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down API server...")

    if app_state.db_engine:
        app_state.db_engine.dispose()
        logger.info("✓ Database engine disposed")

    if app_state.cache:
        app_state.cache.close()
        logger.info("✓ Cache connection closed")

    logger.info("Shutdown complete.")


# Health check endpoint
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint

    Returns the health status of all system components
    """
    components = {
        "api": "healthy",
        "config": "healthy" if app_state.config else "unavailable",
        "database": "healthy" if app_state.db_engine else "unavailable",
    }
    
    # Cache is optional for health check
    if app_state.cache:
        try:
            cache_healthy = app_state.cache.health_check() if hasattr(app_state.cache, 'health_check') else True
            components["cache"] = "healthy" if cache_healthy else "degraded"
        except Exception as e:
            logger.warning(f"Cache health check failed: {e}")
            components["cache"] = "degraded"
    else:
        components["cache"] = "unavailable"

    # Consider system healthy if API and config are available
    # Database and cache are optional for basic health
    critical_components = ["api", "config"]
    overall_status = "healthy" if all(
        components.get(c) == "healthy" for c in critical_components
    ) else "degraded"

    return HealthResponse(
        status=overall_status,
        version="1.0.0",
        environment=app_state.config.environment if app_state.config else "unknown",
        components=components,
    )


# Status endpoint
@app.get("/status", response_model=StatusResponse, tags=["System"])
async def get_status():
    """
    Get system status

    Returns detailed information about the system state
    """
    # Don't raise 503 - return status even if not fully initialized
    # This allows health checks to work in test environments
    
    # Safe cache health check
    cache_connected = False
    if app_state.cache is not None:
        try:
            cache_connected = app_state.cache.health_check() if hasattr(app_state.cache, 'health_check') else True
        except Exception as e:
            logger.warning(f"Cache health check failed: {e}")
            cache_connected = False

    return StatusResponse(
        application="HOPEFX AI Trading",
        version="1.0.0",
        environment=app_state.config.environment if app_state.config else "unknown",
        config_loaded=app_state.config is not None,
        database_connected=app_state.db_engine is not None,
        cache_connected=cache_connected,
        api_configs=len(app_state.config.api_configs) if app_state.config else 0,
    )


# Root endpoint
@app.get("/", tags=["System"])
async def root():
    """
    API root endpoint

    Returns basic API information
    """
    return {
        "application": "HOPEFX AI Trading API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "status": "/status",
        "paper_trading": "/paper-trading",
    }


# Paper Trading Dashboard
@app.get("/paper-trading", response_class=HTMLResponse, tags=["Trading"])
async def paper_trading_dashboard():
    """
    Paper Trading Dashboard

    Interactive visual interface for paper trading simulation.
    Features:
    - Real-time chart visualization
    - Order placement (buy/sell)
    - Position tracking
    - P&L monitoring
    """
    template_path = Path(__file__).parent / "templates" / "paper_trading.html"
    if template_path.exists():
        with open(template_path, 'r') as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(
            content="""
            <html>
            <head><title>Paper Trading</title></head>
            <body style="background:#131722;color:#d1d4dc;font-family:sans-serif;padding:40px;text-align:center;">
                <h1>📊 Paper Trading Dashboard</h1>
                <p>Template not found. Please ensure templates/paper_trading.html exists.</p>
                <a href="/docs" style="color:#26a69a;">Go to API Docs</a>
            </body>
            </html>
            """,
            status_code=200
        )


# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# Setup CORS
setup_cors(app)


def run_server():
    """Run the API server"""
    # Default to localhost for security, use 0.0.0.0 only when explicitly set
    # Set API_HOST=0.0.0.0 in production environment to bind to all interfaces
    host = os.getenv('API_HOST', '127.0.0.1')
    port = int(os.getenv('API_PORT', 5000))
    workers = int(os.getenv('API_WORKERS', 4))
    reload = os.getenv('ENVIRONMENT', 'development') == 'development'

    logger.info(f"Starting API server on {host}:{port}")
    logger.info(f"Workers: {workers}, Reload: {reload}")

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == '__main__':
    run_server()
