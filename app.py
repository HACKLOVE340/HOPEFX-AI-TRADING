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

# Suppress yfinance "possibly delisted" / GC=F roll-window warnings globally.
# Must run before any yfinance import so the warning filters are in place.
try:
    from utils.yfinance_compat import suppress_yfinance_warnings as _suppress_yf

    _suppress_yf()
except Exception:  # nosec B110 — non-fatal; yfinance may not be installed
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

import asyncio
import concurrent.futures as _concurrent_futures
import logging
import os
import platform
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── Windows asyncio/Redis compatibility ───────────────────────────────────────
# On Windows, Python 3.8+ defaults to ProactorEventLoop which is incompatible
# with redis-py's asyncio client (uses SelectorEventLoop internally).
# Force SelectorEventLoop on Windows so Redis, aiohttp, and uvicorn all work.
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

# ── Logging setup ─────────────────────────────────────────────────────────────
# Bootstrap with basicConfig first so any import-time log calls have a handler.
# HOPEFXLogger.setup() then replaces it with the full production configuration
# (JSON formatting, rotating file handlers, async queue, optional Graylog).
#
# Env vars:
#   LOG_LEVEL          — DEBUG / INFO / WARNING / ERROR (default: INFO)
#   LOG_DIR            — directory for log files (default: logs)
#   LOG_JSON           — true/false — JSON structured output (default: false in dev, true in prod)
#   LOG_ASYNC          — true/false — async queue handler (default: true)
#   LOG_GRAYLOG_HOST   — Graylog GELF UDP host (optional)
#   LOG_GRAYLOG_PORT   — Graylog GELF UDP port (default: 12201)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

try:
    from infrastructure.logging import HOPEFXLogger as _HOPEFXLogger

    _log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    _log_dir = os.getenv("LOG_DIR", "logs")
    _app_env_for_log = os.getenv("APP_ENV", "development").lower()
    # Default JSON on in production, off in development (plain text is easier to read locally)
    _log_json = os.getenv("LOG_JSON", "true" if _app_env_for_log == "production" else "false").lower() == "true"
    _log_async = os.getenv("LOG_ASYNC", "true").lower() == "true"
    _graylog_host = os.getenv("LOG_GRAYLOG_HOST") or None
    try:
        _graylog_port = int(os.getenv("LOG_GRAYLOG_PORT", "12201"))
    except ValueError:
        _graylog_port = 12201

    _HOPEFXLogger().setup(
        level=_log_level,
        log_dir=_log_dir,
        app_name="hopefx",
        json_format=_log_json,
        async_mode=_log_async,
        enable_console=True,
        enable_graylog=bool(_graylog_host),
        graylog_host=_graylog_host,
        graylog_port=_graylog_port,
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "Logging initialised: level=%s json=%s async=%s dir=%s",
        _log_level,
        _log_json,
        _log_async,
        _log_dir,
    )
except Exception as _log_setup_err:
    # Non-fatal — basicConfig fallback remains active
    logging.getLogger(__name__).warning("HOPEFXLogger setup failed (using basicConfig fallback): %s", _log_setup_err)

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

# ── Decision Engine router (/api/decision) ───────────────────────────────────
try:
    from core.decision.HOPEFXDecisionEngine import create_decision_router
    from core.app_state import app_state as _app_state

    _decision_engine = getattr(_app_state, "decision_engine", None)
    if _decision_engine is not None:
        app.include_router(create_decision_router(_decision_engine))
        logger.info("Decision engine router registered at /api/decision")
    else:
        # Engine not yet initialised at import time (startup not complete).
        # Register a deferred router that resolves the engine from app_state
        # at request time so routes are available immediately and work once
        # startup completes.  Uses the same TickRequest schema as the real
        # router so the API contract is identical regardless of init order.
        from fastapi import APIRouter as _APIRouter, HTTPException as _HTTPException
        from pydantic import BaseModel as _BaseModel

        class _TickRequest(_BaseModel):
            symbol: str = "XAUUSD"
            close: float
            open: float
            high: float
            low: float
            volume: float = 0.0

        _decision_deferred = _APIRouter(prefix="/api/decision", tags=["Decision Engine"])

        @_decision_deferred.get("/status", summary="Decision engine health and metrics")
        async def _decision_status():
            eng = getattr(_app_state, "decision_engine", None)
            if eng is None:
                return {"engine": "HOPEFXDecisionEngine", "status": "not_initialised"}
            return eng.status()

        @_decision_deferred.post("/tick", summary="Inject a single tick through the decision pipeline")
        async def _decision_tick(req: _TickRequest):
            eng = getattr(_app_state, "decision_engine", None)
            if eng is None:
                raise _HTTPException(503, "Decision engine not initialised")
            data = {
                "close": req.close,
                "open": req.open,
                "high": req.high,
                "low": req.low,
                "volume": req.volume,
                "prices": [req.close],
                "highs": [req.high],
                "lows": [req.low],
                "volumes": [req.volume],
            }
            result = await eng.process_tick(data, symbol=req.symbol)
            return result.to_dict()

        @_decision_deferred.post("/reset", summary="Reset engine cycle metrics")
        async def _decision_reset():
            eng = getattr(_app_state, "decision_engine", None)
            if eng is None:
                raise _HTTPException(503, "Decision engine not initialised")
            eng.reset_metrics()
            return {"reset": True}

        app.include_router(_decision_deferred)
        logger.info("Decision engine deferred router registered at /api/decision (engine pending init)")
except Exception as _decision_router_err:
    logger.warning("Decision engine router failed to register: %s", _decision_router_err)

# ── Hyperopt router (/api/hyperopt) ──────────────────────────────────────────
try:
    from backtesting.hyperopt import create_hyperopt_router as _create_hyperopt_router

    app.include_router(_create_hyperopt_router(), prefix="/api")
    logger.info("Hyperopt router registered at /api/hyperopt")
except Exception as _hyperopt_router_err:
    logger.warning("Hyperopt router failed to register: %s", _hyperopt_router_err)

# ── Replay / stress-test router (/replay) ────────────────────────────────────
try:
    from backtesting.replay_connector import create_replay_router as _create_replay_router

    app.include_router(_create_replay_router())
    logger.info("Replay backtest router registered at /replay")
except Exception as _replay_router_err:
    logger.warning("Replay router failed to register: %s", _replay_router_err)

# ── Research notebook router (/api/research) ─────────────────────────────────
try:
    from research import router as _research_router

    app.include_router(_research_router)
    logger.info("Research router registered at /api/research")
except Exception as _research_router_err:
    logger.warning("Research router failed to register: %s", _research_router_err)

# ── Teams router (/api/teams) ─────────────────────────────────────────────────
try:
    from teams import router as _teams_router

    app.include_router(_teams_router)
    logger.info("Teams router registered at /api/teams")
except Exception as _teams_router_err:
    logger.warning("Teams router failed to register: %s", _teams_router_err)

# Prometheus /metrics endpoint + background sync to MetricsRegistry
# NOTE: Explainability (/api/explainability), No-Code Builder (/api/nocode),
# and Transparency (/api/transparency) routers are registered by
# core/router_registry.py under their respective feature flags
# (EXPLAINABILITY, NOCODE_BUILDER, TRANSPARENCY_REPORTS).  Do not add them
# here — duplicate registration causes FastAPI route-matching conflicts.
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

# Register TracingMiddleware so every HTTP request is captured in the
# in-memory span ring buffer (_SPAN_BUFFER) and X-Trace-ID / X-Span-ID
# headers are injected into every response.
try:
    from api.tracing import TracingMiddleware as _TracingMiddleware

    app.add_middleware(_TracingMiddleware)
    logger.info("TracingMiddleware registered — span buffer active")
except Exception as _tm_err:
    logger.warning("TracingMiddleware registration failed: %s", _tm_err)


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
    # Re-validate environment on every startup/restart (catches config drift on
    # hot-reload or container restart without a full process exit).
    validate_environment(strict=True)

    # Build the React frontend in the background if static/index.html is absent.
    # Runs as a fire-and-forget thread so the API starts immediately without
    # waiting for npm. The SPA placeholder page is served until the build finishes.
    _static_index = Path(__file__).parent / "static" / "index.html"
    if not _static_index.exists():
        import threading

        def _bg_build():
            try:
                from scripts.bootstrap_dev import build_frontend

                build_frontend(verbose=True)
                # Re-mount the SPA now that static/index.html exists
                from core.page_routes import register_page_routes as _rpr

                _rpr(_app)
                logger.info("Frontend build complete — SPA mounted at /")
            except Exception as _be:
                logger.warning("Background frontend build failed: %s", _be)

        threading.Thread(target=_bg_build, daemon=True, name="frontend-build").start()
        logger.info("Frontend not built — starting background build (API available immediately)")

    # Task 40: Sentry error tracking
    init_sentry()
    # Task 38: Redis-backed rate limiting
    setup_rate_limiting(_app)
    # Increase the default thread pool so yfinance / blocking I/O calls
    # don't starve when many background tasks are running.
    _io_executor = _concurrent_futures.ThreadPoolExecutor(
        max_workers=32, thread_name_prefix="hopefx-io"
    )
    asyncio.get_event_loop().set_default_executor(_io_executor)

    await kill_switch.start()
    await startup_event()
    # Start Sharpe circuit breaker as a top-level lifespan task so it always
    # runs even if startup_event() raises before reaching the call inside it.
    # Mirrors the pattern used for Prometheus, WS broadcasters, and nuclear engine.
    try:
        from ml.sharpe_circuit_breaker import get_sharpe_cb as _get_sharpe_cb

        _scb_task = asyncio.create_task(_get_sharpe_cb().run(), name="sharpe_circuit_breaker")
        _scb_task.add_done_callback(lambda _: None)
        if hasattr(app_state, "background_tasks"):
            app_state.background_tasks.append(_scb_task)
        logger.info("[OK] Sharpe circuit breaker task started (lifespan)")
    except Exception as _scb_err:
        logger.warning("Sharpe circuit breaker not started (non-fatal): %s", _scb_err)
    # Start Prometheus sync loop (replaces deprecated @app.on_event("startup"))
    try:
        from prometheus_monitoring import _sync_loop as _prom_sync_loop

        _prom_interval = float(os.getenv("PROMETHEUS_SCRAPE_INTERVAL_SECONDS", "15"))
        _t = asyncio.create_task(_prom_sync_loop(_prom_interval))

        def _on_prom_done(task: "asyncio.Task[None]") -> None:
            if not task.cancelled() and task.exception():
                logger.error("Prometheus sync loop died: %s", task.exception())

        _t.add_done_callback(_on_prom_done)
        logger.info("Prometheus sync loop started (interval=%.0fs)", _prom_interval)
    except Exception as _prom_err:
        logger.warning("Prometheus sync loop not started: %s", _prom_err)
    # Start transactional outbox relay — publishes queued compliance events to Redis.
    # Guarantees at-least-once delivery even if Redis was down when the event was
    # written (kill switch, AML block, order fill).
    try:
        from core.outbox import get_relay as _get_outbox_relay

        _outbox_task = asyncio.create_task(_get_outbox_relay().run(), name="outbox-relay")

        def _on_outbox_done(task: "asyncio.Task[None]") -> None:
            if not task.cancelled() and task.exception():
                logger.error("Outbox relay task died — compliance events may be lost: %s", task.exception())

        _outbox_task.add_done_callback(_on_outbox_done)
        logger.info(
            "✓ Outbox relay started (interval=%.1fs batch=%s)",
            float(os.getenv("OUTBOX_RELAY_INTERVAL_SECONDS", "2.0")),
            os.getenv("OUTBOX_BATCH_SIZE", "50"),
        )
    except Exception as _outbox_err:
        logger.warning("Outbox relay not started: %s", _outbox_err)

    # Start live WebSocket broadcasters
    try:
        from api.ws_live import start_broadcasters

        start_broadcasters()
        logger.info("[OK] Live WebSocket broadcasters started (/ws/live)")
    except Exception as _ws_err:
        logger.warning("Live WS broadcasters not started: %s", _ws_err)

    # Mount nuclear dashboard WebSocket + REST routes (/ws/nuclear, /api/nuclear/*)
    app.state.nuclear_available = False
    try:
        from charting.nuclear_ai_chart_engine import (
            get_chart_engine as _get_chart_engine,
        )
        from charting.websocket_server import mount_nuclear_routes

        _nuclear_engine = _get_chart_engine()
        mount_nuclear_routes(app, _nuclear_engine)
        _t = asyncio.create_task(_nuclear_engine.start(), name="nuclear-chart-engine")
        _t.add_done_callback(lambda _: None)
        app.state.nuclear_available = True
        logger.info("[OK] Nuclear dashboard routes mounted (/ws/nuclear, /api/nuclear/*)")
    except Exception as _nuclear_err:
        logger.warning(
            "Nuclear dashboard routes not mounted — /ws/nuclear will send "
            "'nuclear_unavailable' to clients instead of silently returning null data. "
            "Cause: %s",
            _nuclear_err,
        )

    # Warm up leaderboard cache so GET /api/leaderboard serves data immediately
    # rather than returning an empty list until the first 15-minute scheduler tick.
    try:
        from api.social_feed import refresh_leaderboard_cache as _refresh_lb

        _refresh_lb()
        logger.info("[OK] Leaderboard cache warmed up")
    except Exception as _lb_err:
        logger.debug("Leaderboard warm-up skipped (non-fatal): %s", _lb_err)

    # Seed signals:active key so db_get("signals:active") never returns None
    # on a fresh start before the signal engine has emitted its first signal.
    try:
        from api.db_store import db_get as _db_get, db_set as _db_set

        if _db_get("signals:active") is None:
            _db_set("signals:active", [], changed_by="startup")
            logger.info("[OK] signals:active key seeded in db_store")
    except Exception as _sig_err:
        logger.debug("signals:active seed skipped (non-fatal): %s", _sig_err)

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
    _tasks_done: list[str] = []
    _tasks_failed: list[str] = []

    try:
        await _registry.start_all(app_state)
        _registry.print_table()
        _push_state_to_api_modules(app_state)
        _tasks_done.append("component_registry")

        # Wire the global health checker to the running app so /api/status/json
        # can report real component states instead of "not configured".
        try:
            from infrastructure.health import get_health_checker as _get_hc

            _get_hc(app)
            logger.info("Health checker wired to app")
        except Exception as _hc_wire_err:
            logger.warning("Health checker wiring failed (non-fatal): %s", _hc_wire_err)

        if getattr(app_state, "alert_engine", None) is not None:
            app.state.alert_engine = app_state.alert_engine

        apply_persisted_risk_settings()
        _tasks_done.append("risk_settings")

        await _start_data_layer_orchestrator(app_state)
        _tasks_done.append("data_layer_orchestrator")

        _init_kyc_gateway(app_state)
        _tasks_done.append("kyc_gateway")

        await _start_l2_feed(app_state)
        _tasks_done.append("l2_feed")

        _start_sharpe_circuit_breaker(app_state)
        _tasks_done.append("sharpe_circuit_breaker")

        _start_nuclear_price_bridge(app_state)
        _tasks_done.append("nuclear_price_bridge")

        _mount_gateway(app)
        _tasks_done.append("api_gateway")

        app_state.initialized = True
        # Expose app_state on app.state so health checker and other middleware
        # can reach db_engine, cache, broker, price_engine, brain without
        # importing the module-level app_state directly.
        app.state.app_state = app_state
        log_activity("API server ready")
        logger.info("=" * 70)
        logger.info("API SERVER READY")
        logger.info("=" * 70)

        # Mark startup probe as complete so /api/health/startup returns 200
        try:
            from api.health import mark_startup_complete as _mark_startup_complete

            _mark_startup_complete(tasks_done=_tasks_done, tasks_failed=_tasks_failed)
        except Exception as _hc_err:
            logger.warning("Could not mark startup complete: %s", _hc_err)

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
                logger.info("State pushed _> %s", _mod_name)
        except ImportError:
            ...  # nosec B110
        except Exception as _e:
            logger.warning("Failed to push state to %s: %s", _mod_name, _e)


async def _start_data_layer_orchestrator(state) -> None:
    """Await the data layer orchestrator startup (non-fatal).

    Previously used asyncio.create_task() which fire-and-forgot the coroutine,
    meaning _started was never set before the health check ran and all
    /api/data-layer/* endpoints returned 503. Awaiting directly ensures the
    orchestrator is fully initialised before startup_event() returns.
    """
    try:
        from data_layer.orchestrator import orchestrator

        await orchestrator.start()
        state.data_layer_orchestrator = orchestrator
        logger.info("Data layer orchestrator started")
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

    # Cancel all tracked background tasks and wait for them to finish.
    # Guard against tasks created on a different event loop (e.g. TestClient teardown).
    tasks = getattr(app_state, "background_tasks", [])
    if tasks:
        logger.info("Cancelling %d background task(s)...", len(tasks))
        current_loop = asyncio.get_event_loop()
        same_loop_tasks = []
        for task in tasks:
            if task.done():
                continue
            try:
                # asyncio.Task.get_loop() available in Python 3.7+
                if hasattr(task, "get_loop") and task.get_loop() is not current_loop:
                    continue
                task.cancel()
                same_loop_tasks.append(task)
            except Exception as _task_err:
                logger.debug("shutdown: could not cancel task %s: %s", task, _task_err)
        if same_loop_tasks:
            await asyncio.gather(*same_loop_tasks, return_exceptions=True)
        logger.info("[OK] Background tasks cancelled")

    if app_state.event_store:
        try:
            await app_state.event_store.stop()
            logger.info("[OK] Event store stopped")
        except Exception as e:
            logger.warning("Event store stop error: %s", e)

    # Stop price engine (closes aiohttp ClientSession to avoid ResourceWarning)
    price_engine = getattr(app_state, "price_engine", None)
    if price_engine is not None and hasattr(price_engine, "stop"):
        try:
            await price_engine.stop()
            logger.info("[OK] Price engine stopped")
        except Exception as _pe_err:
            logger.warning("Price engine stop error: %s", _pe_err)

    if app_state.db_engine:
        app_state.db_engine.dispose()
        logger.info("[OK] Database engine disposed")

    if app_state.cache:
        app_state.cache.close()
        logger.info("[OK] Cache connection closed")

    # Stop data layer orchestrator
    try:
        from data_layer.orchestrator import orchestrator

        if orchestrator._started:
            await orchestrator.stop()
            logger.info("[OK] Data layer orchestrator stopped")
    except Exception as _dl_stop_exc:
        logger.warning("Data layer orchestrator stop error: %s", _dl_stop_exc)

    logger.info("Shutdown complete.")


# /health and /status extracted to core/health.py
from core.health import register_health_routes as _register_health_routes

_register_health_routes(app, app_state, kill_switch)

# /metrics is registered by setup_prometheus_monitoring(app) above — no duplicate here.

# ── Error handler ─────────────────────────────────────────────────────────────
# NOTE: GET / is registered by core/page_routes.py (serves the React SPA).
# GET /status is registered by api/status.py (system status page).
# Do not add duplicate registrations here.


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
    """Run the API server."""
    # Default to localhost for security; set API_HOST=0.0.0.0 in production.
    host = os.getenv("API_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("API_PORT", "8000"))
    except ValueError:
        port = 8000
    reload = os.getenv("ENVIRONMENT", "development") == "development"

    # On Windows, uvicorn must use a single worker with SelectorEventLoop.
    # Multiple workers via fork() are not supported on Windows.
    if platform.system() == "Windows":
        workers = 1
        loop = "asyncio"
    else:
        workers = int(os.getenv("API_WORKERS", "4"))
        loop = "auto"

    logger.info("Starting API server on %s:%s (workers=%d)", host, port, workers)

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        loop=loop,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
