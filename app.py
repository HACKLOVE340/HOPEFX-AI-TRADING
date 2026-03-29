#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.

# Load .env before any other imports so all env vars are available at module load
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(override=False)  # override=False: real env vars take precedence
except ImportError:
    pass

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

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

# Logger must be defined before any module-level try/except blocks that use it.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request, status  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
import uvicorn  # noqa: E402

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# ── Dev bootstrap — auto-generate .env + seed admin when missing ──────────────
# Runs only when APP_ENV=development (the default) and .env does not exist.
# In production this block is skipped entirely.
_is_dev_env = os.getenv("APP_ENV", "development").lower() in ("development", "dev")
_env_file = project_root / ".env"
if _is_dev_env and not _env_file.exists():
    try:
        from scripts.bootstrap_dev import bootstrap as _bootstrap  # noqa: E402

        _bootstrap(verbose=True)
        # Reload env vars from the newly created .env
        try:
            from dotenv import load_dotenv as _ld

            _ld(_env_file, override=False)
        except ImportError:
            pass
    except Exception as _be:
        logger.warning("Dev bootstrap failed (non-fatal): %s", _be)

# ── Startup validation — fail loud before any connections are opened ──────────
# Import here so the check runs before broker/DB/Redis init.
from config.startup_validator import validate_environment  # noqa: E402

validate_environment(strict=True)  # calls sys.exit(1) on failure

from api.admin import (  # noqa: E402
    router as admin_router,
    log_activity,
    apply_persisted_risk_settings,
)
from api.platform import setup_rate_limiting, init_sentry  # noqa: E402
from api.signals import create_signals_router as _create_signals_router  # noqa: E402
from config.feature_flags import flags as feature_flags  # noqa: E402
from kill_switch import KillSwitch, create_kill_switch_router  # noqa: E402

_signals_router = _create_signals_router()

# GraphQL — optional dependency
try:
    from api.graphql_schema import graphql_router as _graphql_router
    _graphql_available = True
except Exception as _gql_err:
    _graphql_router = None
    _graphql_available = False
    logger.warning("GraphQL router not loaded: %s", _gql_err)

# (logging and logger already configured at module top)

# Initialize FastAPI app — lifespan is wired below after it is defined
app = FastAPI(
    title="HOPEFX AI Trading API",
    description=(
        "REST API for the HOPEFX AI Trading Framework.\n\n"
        "## Authentication\n"
        "All trading and user endpoints require a **Bearer JWT** token.\n"
        "Obtain a token via `POST /api/auth/login`, then pass it as:\n"
        "`Authorization: Bearer <token>`\n\n"
        "## Rate limits\n"
        "Auth endpoints: 10 req/60 s per IP. Trading endpoints: 60 req/min per user.\n\n"
        "## Environments\n"
        "Set `BROKER_TYPE=paper` (default) for paper trading. "
        "Set `BROKER_TYPE=oanda` + `OANDA_PRACTICE=true` for OANDA practice.\n\n"
        "## Shared response schemas\n"
        "See `api/schemas.py` for `AccountResponse`, `TradeOut`, `RiskMetricsResponse`, "
        "`RegimeResponse`, `SystemStatusResponse`, `SignalOut`, and `BrokerStatusResponse`."
    ),
    version="11.0.0",
    docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
    redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
    # Disable /openapi.json in production — prevents endpoint enumeration
    # even when /docs and /redoc are already gated.
    openapi_url=None if os.getenv("APP_ENV") == "production" else "/openapi.json",
    openapi_tags=[
        {"name": "Auth", "description": "Login, logout, token refresh, 2FA"},
        {"name": "Trading", "description": "Orders, positions, account, prices"},
        {"name": "Signals", "description": "AI signal generation and history"},
        {
            "name": "Watchlist",
            "description": "Per-user symbol watchlists (auth required)",
        },
        {
            "name": "AI Chat",
            "description": "LLM assistant (auth required — OpenAI-backed)",
        },
        {"name": "Risk", "description": "Risk metrics, kill switch, CVaR"},
        {
            "name": "Admin",
            "description": "System status, logs, KYC (admin role required)",
        },
        {"name": "Monetization", "description": "Subscriptions, payments, marketplace"},
        {"name": "Calendar", "description": "Economic calendar events"},
        {"name": "Performance", "description": "Backtest and live performance metrics"},
        {"name": "Broker", "description": "Broker connection status and management"},
        {
            "name": "ML",
            "description": "Model inference, training status, feature importance",
        },
    ],
)

# All router registrations extracted to core/router_registry.py
from core.router_registry import register_routers as _register_routers  # noqa: E402

_register_routers(
    app,
    feature_flags,
    graphql_router=_graphql_router,
    graphql_available=_graphql_available,
    signals_router=_signals_router,
)

# Kill switch — instantiated at module level so it can be imported by other
# components (risk manager, order router, etc.) via:
#   from app import kill_switch
#
# The Redis EventBus is wired in here so that:
#   1. activate() publishes to CH_BREACH (Redis pub/sub) — all pods receive it
#   2. _redis_breach_listener() subscribes to CH_BREACH — this pod receives
#      activations triggered on other pods
# Without this wiring, the kill switch only works within a single process.
try:
    from core.event_bus import bus as _event_bus
    kill_switch = KillSwitch(event_bus=_event_bus)
    logger.info("KillSwitch wired to Redis EventBus for cross-pod propagation")
except Exception as _ks_bus_err:
    logger.warning(
        "KillSwitch: could not wire Redis EventBus (%s) — "
        "kill switch will only work within this pod",
        _ks_bus_err,
    )
    kill_switch = KillSwitch()

_ks_router = create_kill_switch_router(kill_switch)
if _ks_router is not None:
    app.include_router(_ks_router)

# Prometheus /metrics endpoint + background sync to MetricsRegistry
try:
    from prometheus_monitoring import setup_prometheus_monitoring

    setup_prometheus_monitoring(app)
except Exception as _prom_err:
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "Prometheus monitoring setup failed: %s", _prom_err
    )


# AppState extracted to core/app_state.py
from core.app_state import AppState, app_state  # noqa: E402


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
            detail="Database not initialized",
        )

    db = app_state.db_session_factory()
    try:
        yield db
    finally:
        db.close()


# CORS + security headers configuration
# Middleware helpers extracted to core/middleware.py
from core.middleware import setup_cors, setup_security_headers, setup_metrics_middleware  # noqa: E402


# Background task implementations extracted to core/background_tasks.py
from core.background_tasks import oanda_price_poller as _oanda_price_poller  # noqa: E402
from core.background_tasks import price_stream_loop as _price_stream_loop  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI lifespan handler — replaces deprecated @app.on_event."""
    # Task 40: Sentry error tracking
    init_sentry()
    # Task 38: Redis-backed rate limiting
    setup_rate_limiting(_app)
    await kill_switch.start()
    await startup_event()
    # Start Prometheus sync loop (replaces deprecated @app.on_event("startup"))
    try:
        from prometheus_monitoring import _sync_loop as _prom_sync_loop
        import os as _os

        _prom_interval = float(_os.getenv("PROMETHEUS_SCRAPE_INTERVAL_SECONDS", "15"))
        asyncio.create_task(_prom_sync_loop(_prom_interval))
        logger.info("Prometheus sync loop started (interval=%.0fs)", _prom_interval)
    except Exception as _prom_err:
        logger.warning("Prometheus sync loop not started: %s", _prom_err)
    # Start live WebSocket broadcasters
    try:
        from api.ws_live import start_broadcasters

        start_broadcasters()
        logger.info("✓ Live WebSocket broadcasters started (/ws/live)")
    except Exception as _ws_err:
        logger.warning("Live WS broadcasters not started: %s", _ws_err)
    yield
    await shutdown_event()
    await kill_switch.stop()


# Wire lifespan now that the function is defined
app.router.lifespan_context = lifespan


# Stress tests and component registry builder extracted to core/startup_factories.py
from core.startup_factories import (  # noqa: E402
    build_component_registry as _build_component_registry,
    run_startup_stress_tests as _run_startup_stress_tests,
)


async def startup_event():
    """Initialize application on startup via ComponentRegistry.

    Component registration is in core/startup_factories.build_component_registry().
    Factory implementations are in core/startup_factories.
    """
    logger.info("=" * 70)
    logger.info("HOPEFX AI TRADING API - STARTING")
    logger.info("=" * 70)

    _registry = _build_component_registry(app, feature_flags)

    try:
        await _registry.start_all(app_state)
        _registry.print_table()

        # Push app_state into every API module that holds a local reference.
        _state_modules = [
            ("api.trading", "set_state"),
            ("api.admin", "set_state"),
            ("api.watchlist", "set_state"),
            ("api.advanced_trading", "set_state"),
        ]
        for _mod_name, _fn_name in _state_modules:
            try:
                import importlib as _il
                _mod = _il.import_module(_mod_name)
                _fn = getattr(_mod, _fn_name, None)
                if _fn is not None:
                    _fn(app_state)
                    logger.info("State pushed → %s", _mod_name)
            except ImportError:
                pass
            except Exception as _e:
                logger.warning("Failed to push state to %s: %s", _mod_name, _e)

        # Mirror alert_engine onto request.app.state so both lookup paths work
        if getattr(app_state, "alert_engine", None) is not None:
            app.state.alert_engine = app_state.alert_engine

        apply_persisted_risk_settings()
        app_state.initialized = True
        log_activity("API server ready")
        logger.info("=" * 70)
        logger.info("API SERVER READY")
        logger.info("=" * 70)
    except Exception as exc:
        logger.error("Startup failed: %s", exc, exc_info=True)
        raise


async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down API server...")

    # Cancel all tracked background tasks and wait for them to finish
    tasks = getattr(app_state, "background_tasks", [])
    if tasks:
        logger.info("Cancelling %d background task(s)...", len(tasks))
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("✓ Background tasks cancelled")

    if app_state.event_store:
        try:
            await app_state.event_store.stop()
            logger.info("✓ Event store stopped")
        except Exception as e:
            logger.warning("Event store stop error: %s", e)

    # Stop price engine (closes aiohttp ClientSession to avoid ResourceWarning)
    price_engine = getattr(app_state, "price_engine", None)
    if price_engine is not None and hasattr(price_engine, "stop"):
        try:
            await price_engine.stop()
            logger.info("✓ Price engine stopped")
        except Exception as _pe_err:
            logger.warning("Price engine stop error: %s", _pe_err)

    if app_state.db_engine:
        app_state.db_engine.dispose()
        logger.info("✓ Database engine disposed")

    if app_state.cache:
        app_state.cache.close()
        logger.info("✓ Cache connection closed")

    logger.info("Shutdown complete.")


# /health and /status extracted to core/health.py
from core.health import register_health_routes as _register_health_routes  # noqa: E402
from core.health import HealthResponse, StatusResponse  # noqa: E402  (re-export for tests)

_register_health_routes(app, app_state, kill_switch)

# /metrics is registered by setup_prometheus_monitoring(app) above — no duplicate here.

# ── API root ──────────────────────────────────────────────────────────────────


@app.get("/", tags=["System"])
async def root():
    """API root — returns basic service information."""
    return {
        "application": "HOPEFX AI Trading API",
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "status": "/status",
        "paper_trading": "/paper-trading",
        "stream_dashboard": "/stream",
        "pricing": "/pricing",
        "admin_dashboard": "/admin",
        "component_map": "/api/trading/component-map",
        "monetization_api": "/api/monetization",
    }


# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Middleware, page routes, and email webhook ────────────────────────────────
# Extracted to core/ modules to keep app.py under 300 lines.

from core.middleware import register_all as _register_middleware  # noqa: E402
from core.email_webhook import register_email_webhook  # noqa: E402
from core.page_routes import register_page_routes  # noqa: E402

_register_middleware(app)
register_email_webhook(app)
register_page_routes(app)  # mounts React dashboard LAST


def run_server():
    """Run the API server"""
    # Default to localhost for security, use 0.0.0.0 only when explicitly set
    # Set API_HOST=0.0.0.0 in production environment to bind to all interfaces
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", 8000))
    workers = int(os.getenv("API_WORKERS", 4))
    reload = os.getenv("ENVIRONMENT", "development") == "development"

    logger.info(f"Starting API server on {host}:{port}")
    logger.info(f"Workers: {workers}, Reload: {reload}")

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
