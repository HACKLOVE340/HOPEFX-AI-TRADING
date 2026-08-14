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
except Exception:  # nosec B110 — non-fatal; yfinance may not be installed  # noqa: S110
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
import concurrent.futures as concurrent_futures
import contextlib
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

    # ── Windows DNS fix for aiohttp ───────────────────────────────────────────
    # When aiodns (c-ares) is installed, aiohttp uses it for DNS by default. On
    # Windows c-ares frequently cannot read the system's configured DNS servers
    # and fails every outbound request with "Could not contact DNS servers" —
    # even though the machine is online (the browser works fine). This breaks the
    # gold/news/market feeds. Force aiohttp to use the OS resolver
    # (ThreadedResolver → socket.getaddrinfo), which always honours Windows DNS.
    # connector.py imports DefaultResolver at import time, so patch both modules.
    try:
        import aiohttp.connector as _aioconn
        import aiohttp.resolver as _aiores

        _aiores.DefaultResolver = _aiores.ThreadedResolver
        _aioconn.DefaultResolver = _aiores.ThreadedResolver
    except Exception:  # noqa: S110  # nosec B110 — non-fatal; aiohttp may be unavailable
        pass

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

# ── Observability ─────────────────────────────────────────────────────────────
# Make invisible failures visible. Installed AFTER the logging block above so the
# console/file handlers stay intact; this only ADDS logs/hopefx_all.log +
# logs/hopefx_events.jsonl plus process-wide hooks for uncaught / thread /
# asyncio exceptions. Idempotent and best-effort — never blocks boot.
try:
    from hopefx_observability import install as _install_observability

    _install_observability(log_dir=os.getenv("LOG_DIR", "logs"))
except Exception as _obs_err:
    logging.getLogger(__name__).warning("Observability install skipped: %s", _obs_err)

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter as _APIRouter
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
from kill_switch import create_kill_switch_router
from kill_switch import kill_switch as kill_switch

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

# Strawberry GraphQL uses `from __future__ import annotations` internally, which
# turns Request/Response params into ForwardRef strings that pydantic v2 cannot
# resolve during OpenAPI schema generation.  Mark those routes as excluded from
# the schema so /openapi.json succeeds.  GraphQL is self-documenting via GraphiQL.
from fastapi.routing import APIRoute as _APIRoute

for _route in app.routes:
    if isinstance(_route, _APIRoute) and _route.path.startswith("/graphql"):
        _route.include_in_schema = False

# Kill switch — instantiated at module level so it can be imported by other
# components (risk manager, order router, etc.) via:
#   from app import kill_switch
#
# The Redis EventBus is wired in here so that:
#   1. activate() publishes to CH_BREACH (Redis pub/sub) — all pods receive it
#   2. _redis_breach_listener() subscribes to CH_BREACH — this pod receives
#      activations triggered on other pods
# Without this wiring, the kill switch only works within a single process.
#
# There is exactly ONE KillSwitch: the module singleton in kill_switch.py.
# This file used to construct a second one and start *that* (poll loop, flag
# file, Redis latch) while the money path — risk/pre_trade_gate.py — read the
# singleton. The two never synchronised, so `POST /api/kill-switch/activate`
# reported success while orders kept flowing, the documented kill_switch.flag
# runbook never blocked a trade, and health routes showed the opposite state to
# whichever instance was actually active. See docs/HARDENING_BACKLOG.md S2-01
# and tests/unit/test_kill_switch_single_instance.py.
#
# The event bus is attached to the singleton rather than passed to a new
# constructor, so cross-pod propagation reaches the instance that gates trades.
try:
    from core.event_bus import bus as _event_bus

    kill_switch.set_event_bus(_event_bus)
    logger.info("KillSwitch wired to Redis EventBus for cross-pod propagation")
except Exception as _ks_bus_err:
    logger.warning(
        "KillSwitch: could not wire Redis EventBus (%s) — kill switch will only work within this pod",
        _ks_bus_err,
    )

_ks_router = create_kill_switch_router(kill_switch)
if _ks_router is not None:
    app.include_router(_ks_router)

# ── Health check endpoints (/health, /health/ready, /health/detailed) ─────────
try:
    from health_check_service import health_router as _health_router

    app.include_router(_health_router)
    logger.info("Health check router registered at /health")
except Exception as _hc_exc:
    logger.warning("Health check router not registered: %s", _hc_exc)

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

        from fastapi import Depends as _Depends
        from api.auth import require_role as _require_role

        _decision_deferred = _APIRouter(
            prefix="/api/decision",
            tags=["Decision Engine"],
            dependencies=[_Depends(_require_role("admin"))],
        )

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

# ── Replay / stress-test router (/api/replay) ────────────────────────────────
try:
    from backtesting.replay_connector import create_replay_router as _create_replay_router

    app.include_router(_create_replay_router())
    logger.info("Replay backtest router registered at /api/replay")
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

# Startup helpers extracted to core/startup_helpers.py
from core.startup_helpers import (
    init_kyc_gateway as _init_kyc_gateway,
    mount_gateway as _mount_gateway,
    prewarm_ml_predictor as _prewarm_ml_predictor,
    push_state_to_api_modules as _push_state_to_api_modules,
    start_data_layer_orchestrator as _start_data_layer_orchestrator,
    start_l2_feed as _start_l2_feed,
    start_nuclear_price_bridge as _start_nuclear_price_bridge,
)


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
    _io_executor = concurrent_futures.ThreadPoolExecutor(
        max_workers=int(os.getenv("IO_THREAD_POOL_SIZE", "64")), thread_name_prefix="hopefx-io"
    )
    asyncio.get_running_loop().set_default_executor(_io_executor)

    # Log which safety gates this process is actually running with. Several
    # Round 3 audit findings were invisible in production because a gate wired
    # to state nothing writes, or a blocking mode left at its warn-only
    # default, logs identically to a gate that is passing legitimately.
    # See docs/HARDENING_BACKLOG.md S11-03.
    try:
        from core.safety_config_report import log_safety_config

        log_safety_config()
    except Exception as _safety_exc:  # never block startup on a report
        logger.warning("Could not log safety config: %s", _safety_exc)

    await kill_switch.start()

    # Expose app_state on app.state BEFORE the startup task runs so that
    # StartupGateMiddleware can find the object immediately and return 503
    # (instead of passing all requests through because app_state is None).
    # initialized=False at this point — the gate will block data endpoints
    # until startup_event() sets initialized=True.
    _app.state.app_state = app_state

    # Run startup_event as a background task so the lifespan yields immediately
    # and uvicorn starts accepting HTTP requests without waiting for all feeds
    # (FRED, CFTC, IMF, Yahoo, gold) to connect.  The server returns 503 on
    # data-dependent endpoints until app_state.initialized is True.
    _startup_task = asyncio.create_task(startup_event(), name="startup_event")

    def _on_startup_task_done(task: "asyncio.Task[None]") -> None:
        """Log a failed startup_event — and hard-exit if it demanded exit.

        A BaseException that is not an Exception (SystemExit from a startup gate
        such as core.env_validator.validate_and_report, or KeyboardInterrupt)
        escapes this task, cancels the ASGI lifespan, and closes uvicorn's
        listening socket. The process then does NOT exit: the 64-worker
        ThreadPoolExecutor installed above and OpenTelemetry's
        BatchSpanProcessor are non-daemon threads, so the interpreter blocks in
        shutdown indefinitely.

        The result is the worst possible failure mode — `docker ps` reports the
        container as running, the process is alive, and nothing is listening on
        the port. No shutdown message is logged either, because the JSON logging
        setup replaces uvicorn's handlers. Production spent hours in exactly
        that state before this was tracked down.

        Honour the gate's intent (never serve a misconfigured trading system),
        but make the failure terminal and visible: exit non-zero so the restart
        policy applies and the container is reported as failed.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error("startup_event failed: %s", exc)
        if isinstance(exc, Exception):
            # An ordinary error — startup is degraded but the API stays up and
            # StartupGateMiddleware keeps returning 503 on data endpoints.
            return
        code = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        logger.critical(
            "STARTUP GATE DEMANDED EXIT (%r) — terminating the process. Without this the "
            "container would stay 'running' with no listening socket. Fix the reported "
            "configuration errors above and restart.",
            exc,
        )
        for _handler in logging.getLogger().handlers:
            # Never let a flush error mask the exit — the log above is the only
            # record of why the process died.
            with contextlib.suppress(Exception):
                _handler.flush()
        # os._exit, not sys.exit: sys.exit only raises in this callback's frame
        # and would leave the non-daemon threads blocking interpreter shutdown.
        os._exit(code or 1)

    _startup_task.add_done_callback(_on_startup_task_done)
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


def _enable_stack_dump_signal() -> None:
    """Let SIGUSR1 dump every thread's stack to stderr.

    Written after a production hang that could not be diagnosed at all. The
    container's health probe timed out with **zero bytes received** — curl
    connected and the server never wrote a response — repeatedly, every 30
    seconds. ``/api/health/live`` returns a literal dict and cannot block, so
    something upstream was not letting it run; but with no way to see what the
    process was doing, every explanation was a guess.

    There was no way in: ``faulthandler`` was never registered, ``py-spy`` is
    not in the image, and ``docker exec … python -c 'faulthandler.dump_traceback()'``
    only dumps the *new* process, which says nothing about PID 1.

    Now one signal answers it, with nothing to install:

        docker kill -s USR1 hopefx-ai-trading-app-1
        docker logs --tail 100 hopefx-ai-trading-app-1

    The traceback of every thread, including whatever is holding the event
    loop, goes to stderr. SIGUSR1 is used because nothing else in this stack
    claims it and the default disposition would otherwise kill the process.
    """
    import faulthandler
    import signal

    try:
        # keep the file open for the process lifetime — faulthandler writes to
        # the fd directly, so a closed handle would silently produce nothing.
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
        logger.info("Stack-dump signal armed: `docker kill -s USR1 <container>` dumps all thread stacks to stderr")
    except (AttributeError, ValueError, OSError) as exc:
        # SIGUSR1 does not exist on Windows, and faulthandler refuses if stderr
        # has been replaced with an object that has no fileno().
        logger.debug("Stack-dump signal not armed: %s", exc)


async def startup_event():
    """Initialize application on startup via ComponentRegistry.

    Component registration is in core/startup_factories.build_component_registry().
    Factory implementations are in core/startup_factories.
    """
    logger.info("=" * 70)
    logger.info("HOPEFX AI TRADING API - STARTING")
    logger.info("=" * 70)

    _enable_stack_dump_signal()

    _registry = _build_component_registry(app, feature_flags)
    _tasks_done: list[str] = []
    _tasks_failed: list[str] = []

    try:
        _components = await _registry.start_all(app_state)
        _registry.print_table()
        _push_state_to_api_modules(app_state)

        # Initialise the async DB pool so get_async_db() and the /api/health/ready
        # db_pool check work correctly.  Must run after the registry (which runs
        # alembic migrations) so the schema is guaranteed to exist.
        try:
            from database.async_connection import AsyncConnectionPool, set_default_pool as _set_pool

            _async_pool = AsyncConnectionPool()
            await _async_pool.connect()
            _set_pool(_async_pool)
            app_state.async_db_pool = _async_pool
            logger.info("Async DB pool initialised and registered as default pool")
        except Exception as _pool_err:
            # The old message was "Async DB pool init failed (non-fatal): %s"
            # with nothing but the exception's own text. On the deployed box
            # that read as a shrug, and left the reader with no way to tell
            # whether the DSN, the driver or the database was at fault — the
            # three causes need three different fixes. It also asserted
            # "non-fatal" without saying what stops working, which is the same
            # habit as reporting an empty backtest as a 0% return.
            from database.async_connection import _resolve_async_db_url as _dsn
            from utils.redaction import redact_url as _redact

            logger.warning(
                "Async DB pool init failed — %s: %s (resolved DSN: %s). "
                "/api/health/ready will report db_pool degraded and anything "
                "depending on get_async_db() will raise until this is fixed. "
                "A sync driver in the DSN is the usual cause; set "
                "ASYNC_DATABASE_URL to a postgresql+asyncpg:// URL to override.",
                type(_pool_err).__name__,
                _pool_err,
                _redact(_dsn()),
            )

        # Populate _tasks_done / _tasks_failed from the registry results so
        # mark_startup_complete() and the health endpoint report accurate state.
        for _cname, _comp in _components.items():
            if _comp.status == "ok":
                _tasks_done.append(_cname)
            elif _comp.status in ("failed", "skipped"):
                _tasks_failed.append(f"{_cname}: {_comp.error or _comp.status}")

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

        _start_nuclear_price_bridge(app_state, _nuclear_price_bridge)
        _tasks_done.append("nuclear_price_bridge")

        await _prewarm_ml_predictor(app_state)
        _tasks_done.append("ml_predictor")

        _mount_gateway(app)
        _tasks_done.append("api_gateway")

        # Wire roadmap components to event bus channels
        try:
            from core.roadmap_event_wiring import wire_roadmap_events

            _roadmap_wired = await wire_roadmap_events(app_state)
            _tasks_done.append("roadmap_event_wiring")
            logger.info("Roadmap event wiring: %s", _roadmap_wired)
        except Exception as _rw_err:
            logger.warning("Roadmap event wiring failed (non-fatal): %s", _rw_err)
            _tasks_failed.append(f"roadmap_event_wiring: {_rw_err}")

        app_state.initialized = True
        # app.state.app_state was already set in lifespan() before this task
        # started so StartupGateMiddleware could return 503 during boot.
        # Re-assign here to confirm the reference is current after all
        # components have been attached to app_state.
        app.state.app_state = app_state
        log_activity("API server ready")
        logger.info("=" * 70)
        logger.info("API SERVER READY")
        logger.info("=" * 70)

        # Re-run broker-level CoD check now that the broker is connected.
        # The first check in kill_switch.start() runs before the broker
        # connects and is silently deferred; this second check runs after
        # all components are initialised so the broker is guaranteed to be
        # available.  Failure is non-fatal — logged at WARNING only.
        try:
            await kill_switch.check_broker_cod()
            _tasks_done.append("kill_switch_cod_check")
        except Exception as _cod_err:
            logger.warning("kill_switch CoD post-startup check failed (non-fatal): %s", _cod_err)
            _tasks_failed.append(f"kill_switch_cod_check: {_cod_err}")

        # Mark startup probe as complete so /api/health/startup returns 200
        try:
            from api.health import mark_startup_complete as _mark_startup_complete

            _mark_startup_complete(tasks_done=_tasks_done, tasks_failed=_tasks_failed)
        except Exception as _hc_err:
            logger.warning("Could not mark startup complete: %s", _hc_err)

    except Exception:
        logger.exception("Startup failed: %s")
        raise


async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down API server...")

    # Cancel all tracked background tasks and wait for them to finish.
    # Guard against tasks created on a different event loop (e.g. TestClient teardown).
    tasks = getattr(app_state, "background_tasks", [])
    if tasks:
        logger.info("Cancelling %d background task(s)...", len(tasks))
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        same_loop_tasks = []
        for task in tasks:
            if task.done():
                continue
            try:
                # asyncio.Task.get_loop() available in Python 3.7+
                if current_loop is not None and hasattr(task, "get_loop") and task.get_loop() is not current_loop:
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

    # Stop the trading engine (auto-started in init_trading_engine) + its task
    _trading_engine = getattr(app_state, "engine", None)
    if _trading_engine is not None and hasattr(_trading_engine, "stop"):
        try:
            await _trading_engine.stop()
            logger.info("[OK] Trading engine stopped")
        except Exception as _te_err:
            logger.warning("Trading engine stop error: %s", _te_err)

    # Per-user trading accounts (core.account_registry). Each is a live broker
    # instance with its own Redis-backed state; leaving them connected on
    # shutdown leaks connections and can hold the interpreter open.
    try:
        from core.account_registry import get_account_registry

        await get_account_registry().close_all()
        logger.info("[OK] Per-user trading accounts closed")
    except Exception as _acct_err:
        logger.warning("Account registry shutdown error: %s", _acct_err)
    _engine_task = getattr(app_state, "engine_task", None)
    if _engine_task is not None and not _engine_task.done():
        _engine_task.cancel()

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

    # ── Shutdown roadmap components ───────────────────────────────────────────
    # Advanced Order Manager
    _aom = getattr(app_state, "advanced_order_manager", None)
    if _aom is not None and hasattr(_aom, "stop"):
        try:
            await _aom.stop()
            logger.info("[OK] Advanced Order Manager stopped")
        except Exception as _aom_err:
            logger.warning("Advanced Order Manager stop error: %s", _aom_err)

    # Continuous Learning Pipeline
    _clp = getattr(app_state, "continuous_learning", None)
    if _clp is not None and hasattr(_clp, "stop"):
        try:
            await _clp.stop()
            logger.info("[OK] Continuous Learning Pipeline stopped")
        except Exception as _clp_err:
            logger.warning("Continuous Learning Pipeline stop error: %s", _clp_err)

    # Secrets Vault
    _sv = getattr(app_state, "secrets_vault", None)
    if _sv is not None and hasattr(_sv, "close"):
        try:
            await _sv.close()
            logger.info("[OK] Secrets Vault closed")
        except Exception as _sv_err:
            logger.warning("Secrets Vault close error: %s", _sv_err)

    # OpenTelemetry
    try:
        from tracing.opentelemetry_setup import shutdown_telemetry

        await shutdown_telemetry()
        logger.info("[OK] OpenTelemetry shut down")
    except Exception as _otel_err:
        logger.warning("OpenTelemetry shutdown error: %s", _otel_err)

    logger.info("Shutdown complete.")


# /health and /status extracted to core/health.py
from core.health import register_health_routes as _register_health_routes

_register_health_routes(app, app_state, kill_switch)

# /metrics is registered by setup_prometheus_monitoring(app) above — no duplicate here.

# ── Convenience alias endpoints ───────────────────────────────────────────────
# Extracted to core/compat_router.py. Each alias delegates to the canonical
# API layer via 307 redirect — no synthetic data is returned here.
from core.compat_router import compat_router as _compat_router

app.include_router(_compat_router)

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
    import uvicorn  # Deferred: only needed when actually starting the server process.

    # Default to 0.0.0.0 so the server is reachable inside containers/Gitpod.
    # Override with API_HOST env var for production deployments.
    host = os.getenv("API_HOST", "0.0.0.0")
    try:
        port = int(os.getenv("API_PORT", "8000"))
    except ValueError:
        port = 8000

    # Reload is controlled explicitly via UVICORN_RELOAD env var.
    # Default: off — watchfiles reload causes restart loops when source files
    # are written during startup (log files, .env, generated assets).
    # Enable with UVICORN_RELOAD=true only when actively developing.
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"

    # On Windows, uvicorn must use a single worker with SelectorEventLoop.
    # Multiple workers via fork() are not supported on Windows.
    # With reload=True, uvicorn ignores the workers flag (uses 1 internally).
    if platform.system() == "Windows" or reload:
        workers = 1
        loop = "asyncio" if platform.system() == "Windows" else "auto"
    else:
        workers = int(os.getenv("API_WORKERS", "1"))
        loop = "auto"

    logger.info("Starting API server on %s:%s (workers=%d, reload=%s)", host, port, workers, reload)

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
