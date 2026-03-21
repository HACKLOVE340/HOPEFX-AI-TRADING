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

from api.admin import router as admin_router, log_activity, apply_persisted_risk_settings
from api.trading import router as trading_router
from api.monetization import router as monetization_router
from cache import MarketDataCache
from config import initialize_config
from config.feature_flags import flags as feature_flags
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
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Include routers
app.include_router(trading_router)
app.include_router(admin_router)
app.include_router(monetization_router)

# Global application state
class AppState:
    """Application state container"""
    def __init__(self):
        self.config = None
        self.db_engine = None
        self.db_session_factory = None
        self.cache = None
        self.initialized = False
        # Core trading components
        self.broker = None
        self.risk_manager = None
        self.compliance_manager = None
        self.strategy_brain = None
        self.ws_manager = None
        self.alert_engine = None
        self.wallet_manager = None
        # Social
        self.copy_trading_engine = None
        self.marketplace = None
        self.leaderboard_manager = None
        # Experimental module instances (populated at startup when flags are on)
        self.research_engine = None
        self.explainer = None
        self.transparency_engine = None
        self.teams_manager = None
        self.nocode_builder = None
        self.replay_engine = None
        self.ml_feature_engineer = None

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


# CORS + security headers configuration
def setup_cors(app: FastAPI):
    """Setup CORS middleware with restricted origins."""
    raw = os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000')
    allowed_origins = [o.strip() for o in raw.split(',') if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


def setup_security_headers(app: FastAPI):
    """Add security response headers to every reply."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as _Req

    class _SecurityHeaders(BaseHTTPMiddleware):
        _HEADERS = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self' wss:;"
            ),
        }

        async def dispatch(self, request: _Req, call_next):
            response = await call_next(request)
            for header, value in self._HEADERS.items():
                response.headers[header] = value
            return response

    app.add_middleware(_SecurityHeaders)


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

        # Register optional routers with graceful degradation
        try:
            from api.websocket_server import WebSocketManager, create_websocket_router
            ws_manager = WebSocketManager()
            app.include_router(create_websocket_router(ws_manager))
            app_state.ws_manager = ws_manager
            logger.info("✓ WebSocket router registered")
            log_activity("WebSocket router registered")
        except Exception as e:
            logger.warning(f"⚠ WebSocket router not available: {e}")
            log_activity(f"WebSocket router unavailable: {e}")

        try:
            from notifications.alert_engine import AlertEngine, create_alert_router
            alert_engine = AlertEngine()
            app.include_router(create_alert_router(alert_engine))
            app_state.alert_engine = alert_engine
            logger.info("✓ Alert router registered")
            log_activity("Alert router registered")
        except Exception as e:
            logger.warning(f"⚠ Alert router not available: {e}")
            log_activity(f"Alert router unavailable: {e}")

        try:
            from analysis.order_flow import OrderFlowAnalyzer, create_order_flow_router
            order_flow_analyzer = OrderFlowAnalyzer()
            app.include_router(create_order_flow_router(order_flow_analyzer))
            app_state.order_flow_analyzer = order_flow_analyzer
            logger.info("✓ Order Flow router registered")
            log_activity("Order Flow router registered")
        except Exception as e:
            logger.warning(f"⚠ Order Flow router not available: {e}")
            log_activity(f"Order Flow router unavailable: {e}")

        try:
            from analysis.market_scanner import MarketScanner, create_scanner_router
            market_scanner = MarketScanner()
            app.include_router(create_scanner_router(market_scanner))
            app_state.market_scanner = market_scanner
            logger.info("✓ Market Scanner router registered")
            log_activity("Market Scanner router registered")
        except Exception as e:
            logger.warning(f"⚠ Market Scanner router not available: {e}")
            log_activity(f"Market Scanner router unavailable: {e}")

        try:
            from data.depth_of_market import DepthOfMarketService, create_dom_router
            dom_service = DepthOfMarketService()
            app.include_router(create_dom_router(dom_service))
            app_state.dom_service = dom_service
            logger.info("✓ DOM router registered")
            log_activity("DOM router registered")
        except Exception as e:
            logger.warning(f"⚠ DOM router not available: {e}")
            log_activity(f"DOM router unavailable: {e}")

        try:
            from api.signals import create_signals_router
            signals_router = create_signals_router()
            if signals_router is not None:
                app.include_router(signals_router)
                logger.info("✓ Real-Time Signals router registered")
                log_activity("Signals router registered")
        except Exception as e:
            logger.warning(f"⚠ Signals router not available: {e}")
            log_activity(f"Signals router unavailable: {e}")

        try:
            from news import create_news_router
            news_router = create_news_router()
            if news_router is not None:
                app.include_router(news_router)
                logger.info("✓ News & Geopolitical Intelligence router registered")
                log_activity("News router registered")
        except Exception as e:
            logger.warning(f"⚠ News router not available: {e}")
            log_activity(f"News router unavailable: {e}")

        # ── Risk Manager ─────────────────────────────────────────────────────
        try:
            from risk.manager import RiskManager, RiskConfig
            risk_config = RiskConfig(
                max_position_size_pct=float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.02")),
                max_drawdown_pct=float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
                daily_loss_limit_pct=float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")),
            )
            app_state.risk_manager = RiskManager(config=risk_config)
            logger.info("✓ Risk Manager initialized")
            log_activity("Risk Manager initialized")
        except Exception as e:
            logger.warning(f"⚠ Risk Manager not available: {e}")
            app_state.risk_manager = None

        # ── Compliance Manager ───────────────────────────────────────────────
        try:
            from compliance.compliance_manager import ComplianceManager
            app_state.compliance_manager = ComplianceManager(
                session_factory=app_state.db_session_factory
            )
            logger.info("✓ Compliance Manager initialized (DB-backed)")
            log_activity("Compliance Manager initialized")
        except Exception as e:
            logger.warning(f"⚠ Compliance Manager not available: {e}")
            app_state.compliance_manager = None

        # ── Strategy Brain ───────────────────────────────────────────────────
        try:
            from strategies.strategy_brain import StrategyBrain
            from strategies.ma_crossover import MovingAverageCrossover
            from strategies.rsi_strategy import RSIStrategy
            from strategies.macd_strategy import MACDStrategy
            from strategies.bollinger_bands import BollingerBandsStrategy
            brain = StrategyBrain()
            brain.register_strategy(MovingAverageCrossover())
            brain.register_strategy(RSIStrategy())
            brain.register_strategy(MACDStrategy())
            brain.register_strategy(BollingerBandsStrategy())
            app_state.strategy_brain = brain
            logger.info("✓ Strategy Brain initialized with 4 strategies")
            log_activity("Strategy Brain initialized")
        except Exception as e:
            logger.warning(f"⚠ Strategy Brain not available: {e}")
            app_state.strategy_brain = None

        # ── Wallet Manager ───────────────────────────────────────────────────
        try:
            from payments.wallet import WalletManager
            app_state.wallet_manager = WalletManager(
                session_factory=app_state.db_session_factory
            )
            logger.info("✓ Wallet Manager initialized (DB-backed)")
            log_activity("Wallet Manager initialized")
        except Exception as e:
            logger.warning(f"⚠ Wallet Manager not available: {e}")
            app_state.wallet_manager = None

        # ── Social / Copy Trading ────────────────────────────────────────────
        try:
            from social import copy_trading_engine, marketplace, leaderboard_manager
            app_state.copy_trading_engine = copy_trading_engine
            app_state.marketplace = marketplace
            app_state.leaderboard_manager = leaderboard_manager
            logger.info("✓ Social trading initialized")
            log_activity("Social trading initialized")
        except Exception as e:
            logger.warning(f"⚠ Social trading not available: {e}")

        # ── Signal Engine (StrategyBrain → broker loop) ──────────────────────
        try:
            from core.signal_engine import run_signal_engine
            asyncio.create_task(run_signal_engine(app_state))
            logger.info("✓ Signal engine started")
            log_activity("Signal engine started")
        except Exception as e:
            logger.warning(f"⚠ Signal engine not started: {e}")

        # Apply any risk settings persisted from a previous run
        apply_persisted_risk_settings()

        # ── Experimental modules (gated by feature flags) ────────────────────
        if feature_flags.RESEARCH_MODULE:
            try:
                from research import ResearchNotebookEngine, create_research_router
                research_engine = ResearchNotebookEngine()
                app.include_router(create_research_router(research_engine))
                app_state.research_engine = research_engine
                logger.info("✓ Research Notebooks router registered")
                log_activity("Research Notebooks router registered")
            except Exception as e:
                logger.warning(f"⚠ Research Notebooks router not available: {e}")
                log_activity(f"Research Notebooks router unavailable: {e}")

        if feature_flags.EXPLAINABILITY:
            try:
                from explainability import AIExplainer, create_explainability_router
                explainer = AIExplainer()
                app.include_router(create_explainability_router(explainer))
                app_state.explainer = explainer
                logger.info("✓ Explainability router registered")
                log_activity("Explainability router registered")
            except Exception as e:
                logger.warning(f"⚠ Explainability router not available: {e}")
                log_activity(f"Explainability router unavailable: {e}")

        if feature_flags.TRANSPARENCY_REPORTS:
            try:
                from transparency import ExecutionTransparencyEngine, create_transparency_router
                transparency_engine = ExecutionTransparencyEngine()
                app.include_router(create_transparency_router(transparency_engine))
                app_state.transparency_engine = transparency_engine
                logger.info("✓ Transparency router registered")
                log_activity("Transparency router registered")
            except Exception as e:
                logger.warning(f"⚠ Transparency router not available: {e}")
                log_activity(f"Transparency router unavailable: {e}")

        if feature_flags.TEAMS_MODULE:
            try:
                from teams import TeamManager, create_teams_router
                teams_manager = TeamManager()
                app.include_router(create_teams_router(teams_manager))
                app_state.teams_manager = teams_manager
                logger.info("✓ Teams router registered")
                log_activity("Teams router registered")
            except Exception as e:
                logger.warning(f"⚠ Teams router not available: {e}")
                log_activity(f"Teams router unavailable: {e}")

        if feature_flags.NOCODE_BUILDER:
            try:
                from nocode import NoCodeStrategyBuilder, create_nocode_router
                nocode_builder = NoCodeStrategyBuilder()
                app.include_router(create_nocode_router(nocode_builder))
                app_state.nocode_builder = nocode_builder
                logger.info("✓ No-Code Builder router registered")
                log_activity("No-Code Builder router registered")
            except Exception as e:
                logger.warning(f"⚠ No-Code Builder router not available: {e}")
                log_activity(f"No-Code Builder router unavailable: {e}")

        if feature_flags.REPLAY_ENGINE:
            try:
                from replay import ChartReplayEngine, create_replay_router
                replay_engine = ChartReplayEngine()
                app.include_router(create_replay_router(replay_engine))
                app_state.replay_engine = replay_engine
                logger.info("✓ Replay Engine router registered")
                log_activity("Replay Engine router registered")
            except Exception as e:
                logger.warning(f"⚠ Replay Engine router not available: {e}")
                log_activity(f"Replay Engine router unavailable: {e}")

        if feature_flags.ML_PREDICTIONS:
            try:
                from ml import TechnicalFeatureEngineer, create_ml_router
                ml_feature_engineer = TechnicalFeatureEngineer()
                app.include_router(create_ml_router(ml_feature_engineer))
                app_state.ml_feature_engineer = ml_feature_engineer
                logger.info("✓ ML Predictions router registered")
                log_activity("ML Predictions router registered")
            except Exception as e:
                logger.warning(f"⚠ ML Predictions router not available: {e}")
                log_activity(f"ML Predictions router unavailable: {e}")

        app_state.initialized = True
        log_activity("API server ready")
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
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "status": "/status",
        "paper_trading": "/paper-trading",
        "pricing": "/pricing",
        "admin_dashboard": "/admin",
        "component_map": "/api/trading/component-map",
        "monetization_api": "/api/monetization",
    }


# Pricing Page
@app.get("/pricing", response_class=HTMLResponse, tags=["Monetization"])
async def pricing_page():
    """
    Pricing Page

    Display pricing tiers and subscription options.
    Features:
    - All subscription tiers (Free to Elite)
    - Monthly and annual billing
    - Feature comparison
    - FAQ section
    """
    template_path = Path(__file__).parent / "templates" / "pricing.html"
    if template_path.exists():
        with open(template_path, 'r') as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(
            content="""
            <html>
            <head><title>HOPEFX Pricing</title></head>
            <body style="background:#0a0f1c;color:#ffffff;font-family:sans-serif;padding:40px;text-align:center;">
                <h1>💰 Pricing</h1>
                <p>Pricing page template not found. Please ensure templates/pricing.html exists.</p>
                <a href="/docs" style="color:#00d4aa;">Go to API Docs</a>
            </body>
            </html>
            """,
            status_code=200
        )


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


# Setup CORS and security headers
setup_cors(app)
setup_security_headers(app)


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
