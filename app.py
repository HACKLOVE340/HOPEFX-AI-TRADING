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
    ...  # nosec B110

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

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Logger must be defined before any module-level try/except blocks that use it.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
        from scripts.bootstrap_dev import bootstrap as _bootstrap

        _bootstrap(verbose=True)
        # Reload env vars from the newly created .env
        try:
            from dotenv import load_dotenv as _ld

            _ld(_env_file, override=False)
        except ImportError:
            ...  # nosec B110
    except Exception as _be:
        logger.warning("Dev bootstrap failed (non-fatal): %s", _be)

# ── Startup validation — fail loud before any connections are opened ──────────
# Import here so the check runs before broker/DB/Redis init.
from config.startup_validator import validate_environment

validate_environment(strict=True)  # calls sys.exit(1) on failure

from api.admin import (
    apply_persisted_risk_settings,
    log_activity,
)
from api.platform import init_sentry, setup_rate_limiting
from api.signals import create_signals_router as _create_signals_router
from config.feature_flags import flags as feature_flags
from kill_switch import KillSwitch, create_kill_switch_router

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
        {
            "name": "Portfolio",
            "description": "Factor attribution, dynamic rebalancer, tick feed status",
        },
    ],
)

# All router registrations extracted to core/router_registry.py
from core.router_registry import register_routers as _register_routers

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
        "KillSwitch: could not wire Redis EventBus (%s) — kill switch will only work within this pod",
        _ks_bus_err,
    )
    kill_switch = KillSwitch()

_ks_router = create_kill_switch_router(kill_switch)
if _ks_router is not None:
    app.include_router(_ks_router)

# Nuclear supervisor + kill switch control endpoints
try:
    from api.nuclear import router as _nuclear_router

    app.include_router(_nuclear_router, prefix="/nuclear", tags=["nuclear"])
except Exception as _nuclear_err:
    logger.warning("Nuclear router failed to register: %s", _nuclear_err)

# Data layer REST endpoints
try:
    from api.data_layer import router as _dl_router

    app.include_router(_dl_router)
except Exception as _dl_router_err:
    logger.warning("Data layer router failed to register: %s", _dl_router_err)

# KYC/AML endpoints (Sumsub/Onfido + sanctions screening)
try:
    from api.kyc import router as _kyc_router

    app.include_router(_kyc_router, prefix="/api")
except Exception as _kyc_router_err:
    logger.warning("KYC router failed to register: %s", _kyc_router_err)

# TCA endpoints (slippage stats, fill quality, alerts)
try:
    from api.tca import router as _tca_router

    app.include_router(_tca_router, prefix="/api")
except Exception as _tca_router_err:
    logger.warning("TCA router failed to register: %s", _tca_router_err)

# Live P&L dashboard — auditable trade log, equity curve, Sharpe, drawdown
try:
    from api.pnl_dashboard import router as _pnl_router

    app.include_router(_pnl_router)
except Exception as _pnl_router_err:
    logger.warning("P&L dashboard router failed to register: %s", _pnl_router_err)

# Chaos engineering + mutation testing endpoints
try:
    from api.chaos import router as _chaos_router

    app.include_router(_chaos_router)
except Exception as _chaos_router_err:
    logger.warning("Chaos router failed to register: %s", _chaos_router_err)

# SuperAdmin master control endpoints (superadmin role required for all)
try:
    from api.superadmin import router as _superadmin_router

    app.include_router(_superadmin_router)
    logger.info("SuperAdmin router registered at /api/superadmin")
except Exception as _superadmin_router_err:
    logger.warning("SuperAdmin router failed to register: %s", _superadmin_router_err)

# Prometheus /metrics endpoint + background sync to MetricsRegistry
try:
    from prometheus_monitoring import setup_prometheus_monitoring

    setup_prometheus_monitoring(app)
except Exception as _prom_err:
    logger.warning("Prometheus monitoring setup failed: %s", _prom_err)

# OpenTelemetry distributed tracing — instruments FastAPI, SQLAlchemy, Redis,
# aiohttp and enables W3C trace context propagation through Redis messages.
# Configured via OTEL_* env vars; gracefully no-ops when SDK is not installed.
try:
    from tracing.setup import setup_tracing as _setup_tracing

    _setup_tracing(app)
except Exception as _otel_err:
    logger.debug("OpenTelemetry setup skipped: %s", _otel_err)


# AppState extracted to core/app_state.py — re-exported here for backwards compat
from core.app_state import app_state


class ErrorResponse(BaseModel):
    """Error response"""

    error: str
    detail: str | None = None


# Dependency to get database session
def get_db() -> Session:
    """Get database session"""
    if not app_state.db_session_factory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    db = app_state.db_session_factory()  # pylint: disable=not-callable
    try:
        yield db
    finally:
        db.close()


# CORS + security headers configuration
# Middleware helpers extracted to core/middleware.py


# Background task implementations extracted to core/background_tasks.py
from core.background_tasks import nuclear_price_bridge as _nuclear_price_bridge


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

        _prom_interval = float(os.getenv("PROMETHEUS_SCRAPE_INTERVAL_SECONDS", "15"))
        _t = asyncio.create_task(_prom_sync_loop(_prom_interval))
        _t.add_done_callback(lambda _: None)
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

    # Mount nuclear dashboard WebSocket + REST routes (/ws/nuclear, /api/nuclear/*)
    try:
        from charting.nuclear_ai_chart_engine import (
            get_chart_engine as _get_chart_engine,
        )
        from charting.websocket_server import mount_nuclear_routes

        _nuclear_engine = _get_chart_engine()
        mount_nuclear_routes(app, _nuclear_engine)
        _t = asyncio.create_task(_nuclear_engine.start(), name="nuclear-chart-engine")
        _t.add_done_callback(lambda _: None)
        logger.info("✓ Nuclear dashboard routes mounted (/ws/nuclear, /api/nuclear/*)")
    except Exception as _nuclear_err:
        logger.warning("Nuclear dashboard routes not mounted: %s", _nuclear_err)

    yield
    await shutdown_event()
    await kill_switch.stop()


# Wire lifespan now that the function is defined
app.router.lifespan_context = lifespan


# Stress tests and component registry builder extracted to core/startup_factories.py
from core.startup_factories import (
    build_component_registry as _build_component_registry,
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
        _push_state_to_api_modules(app_state)

        if getattr(app_state, "alert_engine", None) is not None:
            app.state.alert_engine = app_state.alert_engine

        apply_persisted_risk_settings()
        _start_data_layer_orchestrator(app_state)
        _init_kyc_gateway(app_state)
        await _start_l2_feed(app_state)
        _start_sharpe_circuit_breaker(app_state)
        _start_nuclear_price_bridge(app_state)
        _mount_gateway(app)

        app_state.initialized = True
        log_activity("API server ready")
        logger.info("=" * 70)
        logger.info("API SERVER READY")
        logger.info("=" * 70)
    except Exception:
        logger.exception("Startup failed: %s")
        raise


def _push_state_to_api_modules(state) -> None:
    """Push app_state into every API module that holds a local reference."""
    import importlib as _il

    _state_modules = [
        ("api.trading", "set_state"),
        ("api.admin", "set_state"),
        ("api.watchlist", "set_state"),
        ("api.advanced_trading", "set_state"),
    ]
    for _mod_name, _fn_name in _state_modules:
        try:
            _mod = _il.import_module(_mod_name)
            _fn = getattr(_mod, _fn_name, None)
            if _fn is not None:
                _fn(state)
                logger.info("State pushed → %s", _mod_name)
        except ImportError:
            ...  # nosec B110
        except Exception as _e:
            logger.warning("Failed to push state to %s: %s", _mod_name, _e)


def _start_data_layer_orchestrator(state) -> None:
    """Start the data layer orchestrator as a background task (non-fatal)."""
    try:
        from data_layer.orchestrator import orchestrator

        _t = asyncio.create_task(orchestrator.start(), name="data_layer_orchestrator")
        _t.add_done_callback(lambda _: None)
        logger.info("Data layer orchestrator starting in background")
    except Exception as _exc:
        logger.warning("Data layer orchestrator failed to start (non-fatal): %s", _exc)


def _init_kyc_gateway(state) -> None:
    """Wire KYCGateway with ComplianceManager (non-fatal)."""
    try:
        from compliance.kyc_provider import get_kyc_gateway, init_kyc_gateway

        _cm = getattr(state, "compliance_manager", None)
        if _cm is not None:
            init_kyc_gateway(_cm)
            logger.info("KYCGateway initialised with ComplianceManager")
        else:
            get_kyc_gateway()  # initialise with no-DB fallback
            logger.warning("KYCGateway initialised without ComplianceManager (no DB)")
    except Exception as _exc:
        logger.warning("KYCGateway init failed (non-fatal): %s", _exc)


async def _start_l2_feed(state) -> None:
    """Start L2 order book feed and depth bridge (non-fatal)."""
    try:
        from market_data.order_book import get_order_book_feed

        _l2_symbols = os.getenv("L2_SYMBOLS", "XAU_USD,EUR_USD").split(",")
        _l2_feed = get_order_book_feed()
        _l2_task = asyncio.create_task(
            _l2_feed.start([s.strip() for s in _l2_symbols]),
            name="l2_order_book_feed",
        )
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(_l2_task)
        logger.info("L2 order book feed starting for symbols: %s", _l2_symbols)

        _l2_bridge_task = asyncio.create_task(
            _run_l2_depth_bridge(_l2_feed, _l2_symbols),
            name="l2_depth_bridge",
        )
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(_l2_bridge_task)
    except Exception as _exc:
        logger.warning("L2 order book feed failed to start (non-fatal): %s", _exc)


async def _run_l2_depth_bridge(l2_feed, l2_symbols: list) -> None:
    """Push L2 snapshots into MicrostructureEngine on each interval tick."""
    from data_layer.orchestrator import orchestrator as _dl_orch

    _interval = float(os.getenv("L2_SNAPSHOT_INTERVAL", "1.0"))
    while True:
        try:
            for _sym in [s.strip() for s in l2_symbols]:
                _snap = l2_feed.get_snapshot(_sym)
                if _snap is not None:
                    _dl_orch._micro.inject_l2_depth(
                        symbol=_sym,
                        bid_depth=_snap.bid_depth,
                        ask_depth=_snap.ask_depth,
                    )
        except Exception as _exc:
            logger.debug("L2 depth bridge error: %s", _exc)
        await asyncio.sleep(_interval)


def _start_sharpe_circuit_breaker(state) -> None:
    """Start Sharpe circuit breaker background task (non-fatal)."""
    try:
        from ml.sharpe_circuit_breaker import get_sharpe_cb

        _scb_task = asyncio.create_task(get_sharpe_cb().run(), name="sharpe_circuit_breaker")
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(_scb_task)
        logger.info("Sharpe circuit breaker started")
    except Exception as _exc:
        logger.warning("Sharpe circuit breaker failed to start (non-fatal): %s", _exc)


def _start_nuclear_price_bridge(state) -> None:
    """Start NuclearStreamer price bridge background task (non-fatal)."""
    try:
        _bridge_task = asyncio.create_task(_nuclear_price_bridge(state), name="nuclear_price_bridge")
        if hasattr(state, "background_tasks"):
            state.background_tasks.append(_bridge_task)
        logger.info("nuclear_price_bridge task started")
    except Exception as _exc:
        logger.warning("nuclear_price_bridge failed to start (non-fatal): %s", _exc)


def _mount_gateway(fastapi_app) -> None:
    """Mount the APIGateway sub-application at /gateway (non-fatal).

    Called after startup_event so app_state is fully populated.
    Only mounts when ENABLE_GATEWAY=true is set — off by default to avoid
    exposing the extra surface area unless explicitly opted in.
    """
    if os.getenv("ENABLE_GATEWAY", "false").lower() != "true":
        return
    try:
        from api.gateway import build_gateway_app

        _gw_app = build_gateway_app()
        if _gw_app is not None:
            fastapi_app.mount("/gateway", _gw_app)
            logger.info("APIGateway mounted at /gateway")
    except Exception as _exc:
        logger.warning("APIGateway mount failed (non-fatal): %s", _exc)


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

    # Stop data layer orchestrator
    try:
        from data_layer.orchestrator import orchestrator

        if orchestrator._started:
            await orchestrator.stop()
            logger.info("✓ Data layer orchestrator stopped")
    except Exception as _dl_stop_exc:
        logger.warning("Data layer orchestrator stop error: %s", _dl_stop_exc)

    logger.info("Shutdown complete.")


# /health and /status extracted to core/health.py
from core.health import register_health_routes as _register_health_routes

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
    logger.exception("Unhandled exception: %s")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error"},
    )


# ── Middleware, page routes, and email webhook ────────────────────────────────
# Extracted to core/ modules to keep app.py under 300 lines.

from core.email_webhook import register_email_webhook
from core.middleware import register_all as _register_middleware
from core.page_routes import register_page_routes

_register_middleware(app)
register_email_webhook(app)
register_page_routes(app)  # mounts React dashboard LAST


def run_server():
    """Run the API server"""
    # Default to localhost for security, use 0.0.0.0 only when explicitly set
    # Set API_HOST=0.0.0.0 in production environment to bind to all interfaces
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    workers = int(os.getenv("API_WORKERS", "4"))
    reload = os.getenv("ENVIRONMENT", "development") == "development"

    logger.info("Starting API server on %s:%s", host, port)

    logger.info("Workers: %s, Reload: %s", workers, reload)

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
