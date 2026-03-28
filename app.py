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
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
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
from auth.router import router as auth_router  # noqa: E402
from api.trading import router as trading_router  # noqa: E402
from api.monetization import router as monetization_router  # noqa: E402
from api.backtesting import router as backtesting_router  # noqa: E402
from api.online_learner import router as online_learner_router  # noqa: E402
from api.chat import router as chat_router  # noqa: E402
from api.prop_firm import router as prop_firm_router  # noqa: E402
from api.performance import router as performance_router  # noqa: E402
from api.explain import router as explain_router  # noqa: E402
from api.macro import router as macro_router  # noqa: E402
from api.broker import router as broker_router  # noqa: E402
from api.landing import router as landing_router  # noqa: E402
from api.payments import router as payments_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402
from api.status import router as status_router  # noqa: E402
from api.brain import router as brain_router  # noqa: E402
from api.two_factor import router as two_factor_router  # noqa: E402
from api.calendar import router as calendar_router  # noqa: E402
from api.watchlist import router as watchlist_router  # noqa: E402
from api.journal import router as journal_router  # noqa: E402
from api.profiles import router as profiles_router  # noqa: E402
from api.social_feed import (  # noqa: E402
    router as social_feed_router,
    leaderboard_router as social_leaderboard_router,
)
from api.mobile import router as mobile_router  # noqa: E402
from api.whitelabel_admin import router as whitelabel_router  # noqa: E402
from api.billing import router as billing_router  # noqa: E402
from api.platform import router as platform_router, setup_rate_limiting, init_sentry  # noqa: E402
from api.advanced_trading import router as advanced_router  # noqa: E402
from api.ml import router as ml_router  # noqa: E402
from api.alerts import router as alerts_router  # noqa: E402
from api.signals import create_signals_router as _create_signals_router  # noqa: E402

_signals_router = _create_signals_router()

# GraphQL — strawberry-graphql (api/graphql_schema.py avoids shadowing graphql-core)
try:
    from api.graphql_schema import graphql_router as _graphql_router

    _graphql_available = True
except Exception as _gql_err:
    _graphql_router = None
    _graphql_available = False
    logger.warning("GraphQL router not loaded: %s", _gql_err)
from config.feature_flags import flags as feature_flags  # noqa: E402
from kill_switch import KillSwitch, create_kill_switch_router  # noqa: E402

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

# Include routers
app.include_router(auth_router)
app.include_router(trading_router)
app.include_router(admin_router)
app.include_router(monetization_router)
app.include_router(backtesting_router)
app.include_router(online_learner_router)
app.include_router(chat_router)
app.include_router(prop_firm_router)
app.include_router(performance_router)
app.include_router(explain_router)
app.include_router(macro_router)
app.include_router(broker_router)
app.include_router(landing_router)
app.include_router(payments_router)
app.include_router(settings_router)
app.include_router(status_router)
app.include_router(brain_router)

# Two-factor authentication — gated: FEATURE_TWO_FACTOR_AUTH
if feature_flags.TWO_FACTOR_AUTH:
    app.include_router(two_factor_router)
    logger.info("Two-factor auth router registered (/api/2fa)")
else:
    logger.debug("TWO_FACTOR_AUTH disabled — set FEATURE_TWO_FACTOR_AUTH=true to enable")

app.include_router(calendar_router)

# Watchlist — gated: FEATURE_WATCHLIST
if feature_flags.WATCHLIST:
    app.include_router(watchlist_router)
    logger.info("Watchlist router registered (/api/watchlist)")
else:
    logger.debug("WATCHLIST disabled — set FEATURE_WATCHLIST=true to enable")

# Trade journal — gated: FEATURE_TRADE_JOURNAL
if feature_flags.TRADE_JOURNAL:
    app.include_router(journal_router)
    logger.info("Trade journal router registered (/api/journal)")
else:
    logger.debug("TRADE_JOURNAL disabled — set FEATURE_TRADE_JOURNAL=true to enable")

app.include_router(profiles_router)
app.include_router(social_feed_router)
app.include_router(social_leaderboard_router)
app.include_router(mobile_router)
app.include_router(whitelabel_router)

# Billing subscription endpoint — gated: FEATURE_BILLING_SUBSCRIPTION
if feature_flags.BILLING_SUBSCRIPTION:
    app.include_router(billing_router)
    logger.info("Billing router registered (/api/billing)")
else:
    logger.debug("BILLING_SUBSCRIPTION disabled — set FEATURE_BILLING_SUBSCRIPTION=true to enable")

app.include_router(platform_router)

# Advanced trading (OCO, trailing stops, iceberg) — gated: FEATURE_ADVANCED_TRADING
if feature_flags.ADVANCED_TRADING:
    app.include_router(advanced_router)
    logger.info("Advanced trading router registered (/api/advanced)")
else:
    logger.debug("ADVANCED_TRADING disabled — set FEATURE_ADVANCED_TRADING=true to enable")

app.include_router(ml_router)

# Price alerts — gated: FEATURE_PRICE_ALERTS
if feature_flags.PRICE_ALERTS:
    app.include_router(alerts_router)
    logger.info("Price alerts router registered (/api/alerts)")
else:
    logger.debug("PRICE_ALERTS disabled — set FEATURE_PRICE_ALERTS=true to enable")

if _signals_router is not None:
    app.include_router(_signals_router)
    logger.info("Signals router registered (/api/signals)")

# GraphQL — gated: FEATURE_GRAPHQL_API
# GraphiQL playground available at GET /graphql when enabled
if feature_flags.GRAPHQL_API and _graphql_available and _graphql_router is not None:
    app.include_router(_graphql_router, prefix="/graphql")
    logger.info("GraphQL endpoint mounted at /graphql")
elif _graphql_available and not feature_flags.GRAPHQL_API:
    logger.debug("GRAPHQL_API disabled — set FEATURE_GRAPHQL_API=true to enable")

# Live WebSocket endpoint (/ws/live) — matches frontend useWebSocket hook
try:
    from api.ws_live import router as ws_live_router

    app.include_router(ws_live_router)
    logger.info("✓ Live WebSocket router registered (/ws/live)")
except Exception as _ws_live_err:
    logger.warning("Live WebSocket router not registered: %s", _ws_live_err)

# Kill switch — instantiated at module level so it can be imported by other
# components (risk manager, order router, etc.) via:
#   from app import kill_switch
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
        self.auth_service = None
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
        # Price engine — set during startup, used by /api/trading/ohlcv and /prices
        self.price_engine = None
        # Core trading components from main.py
        self.event_store = None
        self.brain = None
        self.position_tracker = None
        self.trade_executor = None
        self.order_book = None
        # Regime-aware strategy router
        self.regime_router = None
        # Background asyncio tasks — populated at startup, cancelled at shutdown
        self.background_tasks: list = []


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
            detail="Database not initialized",
        )

    db = app_state.db_session_factory()
    try:
        yield db
    finally:
        db.close()


# CORS + security headers configuration
def setup_cors(app: FastAPI):
    """Setup CORS middleware with restricted origins.

    In production set ALLOWED_ORIGINS to your frontend domain(s):
        ALLOWED_ORIGINS=https://app.hopefx.io,https://hopefx.io

    The default (localhost:3000) is intentionally restrictive so the app
    starts safely without any .env file, but it will block browser requests
    from any non-localhost origin.
    """
    import logging as _logging

    _cors_logger = _logging.getLogger(__name__)

    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
    allowed_origins = [o.strip() for o in raw.split(",") if o.strip()]

    app_env = os.getenv("APP_ENV", "development")
    if app_env == "production":
        import sys as _sys

        # Reject wildcard — credentials + wildcard is forbidden by the CORS spec
        # and would allow any origin to send authenticated requests.
        if "*" in allowed_origins:
            _cors_logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS contains '*' with "
                "allow_credentials=True. This is a CORS misconfiguration that "
                "exposes authenticated endpoints to any origin. Set explicit "
                "HTTPS origins, e.g.: ALLOWED_ORIGINS=https://app.yourdomain.com"
            )
            _sys.exit(1)

        # Reject plain http:// origins in production — credentials must only
        # travel over TLS to prevent session-hijacking via network interception.
        insecure = [o for o in allowed_origins if o.startswith("http://")]
        if insecure:
            _cors_logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS contains insecure http:// "
                "origins in production: %s. Use https:// only.",
                insecure,
            )
            _sys.exit(1)

        # Reject localhost-only config — the frontend can never reach the API
        # from a real domain if only loopback addresses are allowed.
        if all("localhost" in o or "127." in o for o in allowed_origins):
            _cors_logger.critical(
                "STARTUP BLOCKED: ALLOWED_ORIGINS is restricted to localhost in "
                "production. Set ALLOWED_ORIGINS to your frontend domain(s), e.g.: "
                "ALLOWED_ORIGINS=https://app.yourdomain.com"
            )
            _sys.exit(1)

    _cors_logger.info("CORS allowed origins: %s", allowed_origins)

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


def setup_metrics_middleware(app: FastAPI):
    """Add Prometheus HTTP metrics middleware."""
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from core.metrics import make_metrics_middleware

        app.add_middleware(BaseHTTPMiddleware, dispatch=make_metrics_middleware())
        logger.info("Prometheus metrics middleware registered")
    except Exception as exc:
        logger.warning("Metrics middleware not available: %s", exc)


# Startup event
async def _oanda_price_poller(state):
    """
    Background task: polls OANDA's pricing endpoint and writes real bid/ask
    into the active broker's price table via update_market_price().

    Only runs when BROKER_OANDA_TOKEN and BROKER_OANDA_ACCOUNT are set.
    Falls back silently if OANDA is unreachable so paper trading still works.
    """
    import asyncio as _asyncio

    _SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
    _SYMBOLS = [s.strip().upper() for s in _SYMBOLS]
    _INTERVAL = float(os.getenv("OANDA_POLL_INTERVAL", "1.0"))

    oanda_token = os.getenv("BROKER_OANDA_TOKEN", "")
    oanda_account = os.getenv("BROKER_OANDA_ACCOUNT", "")
    oanda_env = os.getenv("BROKER_OANDA_ENVIRONMENT", "practice")

    if not oanda_token or not oanda_account:
        logger.info("OANDA price poller disabled — BROKER_OANDA_TOKEN/ACCOUNT not set")
        return

    try:
        from brokers.oanda import OANDAConnector

        oanda = OANDAConnector(
            api_key=oanda_token,
            account_id=oanda_account,
            practice=(oanda_env != "live"),
        )
        if not oanda.connect():
            logger.warning(
                "OANDA price poller: connection failed — using static prices"
            )
            return
        logger.info(
            "OANDA price poller connected — symbols=%s interval=%.1fs",
            _SYMBOLS,
            _INTERVAL,
        )
    except Exception as exc:
        logger.warning("OANDA price poller init failed: %s", exc)
        return

    from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

    _cb = CircuitBreaker.get("oanda_poller", failure_threshold=5, reset_timeout=60.0)
    _backoff = 1.0
    _MAX_BACKOFF = 300.0

    while True:
        try:
            async with _cb:
                prices = oanda.get_live_prices(_SYMBOLS)
            broker = getattr(state, "broker", None)
            if broker is not None and prices:
                for sym, tick in prices.items():
                    mid = tick.get("mid", 0.0)
                    if mid > 0 and hasattr(broker, "update_market_price"):
                        broker.update_market_price(sym, mid)
            _backoff = 1.0  # reset on success
        except _asyncio.CancelledError:
            logger.info("OANDA price poller stopped")
            oanda.disconnect()
            return
        except CircuitBreakerOpen as cbo:
            logger.warning(
                "OANDA price poller: circuit OPEN — sleeping %.0fs", cbo.retry_after
            )
            await _asyncio.sleep(min(cbo.retry_after, _MAX_BACKOFF))
            continue
        except Exception as exc:
            logger.warning(
                "OANDA price poller error (backoff=%.0fs): %s", _backoff, exc
            )
            await _asyncio.sleep(_backoff)
            _backoff = min(_backoff * 2, _MAX_BACKOFF)
            continue

        await _asyncio.sleep(_INTERVAL)


async def _price_stream_loop(ws_manager):
    """
    Background task: polls the paper broker for current prices and broadcasts
    tick updates to all connected WebSocket clients.

    Uses the broker's in-memory price table so no external feed is required for
    paper trading. When a real broker (OANDA, etc.) is wired in, replace the
    polling loop with the broker's native streaming callback.
    """
    _STREAM_SYMBOLS = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD").split(",")
    _POLL_INTERVAL = float(os.getenv("PRICE_STREAM_INTERVAL", "1.0"))

    logger.info(
        "Price stream loop started — symbols=%s interval=%.1fs",
        _STREAM_SYMBOLS,
        _POLL_INTERVAL,
    )

    while True:
        try:
            broker = getattr(app_state, "broker", None)
            if broker is not None:
                for sym in _STREAM_SYMBOLS:
                    sym = sym.strip().upper()
                    price = broker.get_market_price(sym)
                    if price:
                        # Use a tiny synthetic spread for paper trading
                        spread = price * 0.0001
                        await ws_manager.broadcast_price_update(
                            symbol=sym,
                            price=price,
                            bid=round(price - spread / 2, 5),
                            ask=round(price + spread / 2, 5),
                        )
        except asyncio.CancelledError:
            logger.info("Price stream loop stopped")
            return
        except Exception as exc:
            logger.warning("Price stream error: %s", exc)

        await asyncio.sleep(_POLL_INTERVAL)


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


def _run_startup_stress_tests(risk_manager: Any) -> None:
    """
    Run standard stress scenarios against the risk manager at startup.
    Logs a WARNING for any scenario that projects >20% portfolio loss.
    Called immediately after RiskManager is initialised (Area 2).
    """
    try:
        from risk.advanced_analytics import AdvancedRiskAnalytics

        AdvancedRiskAnalytics()

        scenarios = [
            {
                "name": "2008 Financial Crisis",
                "equity_shock": -0.38,
                "vol_multiplier": 3.5,
            },
            {
                "name": "COVID-19 March 2020",
                "equity_shock": -0.34,
                "vol_multiplier": 4.0,
            },
            {"name": "Gold Flash Crash", "equity_shock": -0.15, "vol_multiplier": 2.5},
            {"name": "USD Spike +10%", "equity_shock": -0.12, "vol_multiplier": 2.0},
            {"name": "Liquidity Crunch", "equity_shock": -0.20, "vol_multiplier": 3.0},
        ]

        portfolio_value = risk_manager.current_balance or 100_000.0
        threshold = 0.20  # 20% loss threshold

        for scenario in scenarios:
            projected_loss_pct = abs(scenario["equity_shock"])
            projected_loss = portfolio_value * projected_loss_pct
            if projected_loss_pct > threshold:
                logger.warning(
                    "Startup stress test — scenario '%s' projects %.1f%% portfolio loss "
                    "(%.2f on %.2f balance) — review risk limits",
                    scenario["name"],
                    projected_loss_pct * 100,
                    projected_loss,
                    portfolio_value,
                )
            else:
                logger.info(
                    "Startup stress test — scenario '%s': projected loss %.1f%% — within threshold",
                    scenario["name"],
                    projected_loss_pct * 100,
                )
    except Exception as exc:
        logger.warning("Startup stress tests could not run: %s", exc)


async def startup_event():
    """Initialize application on startup via ComponentRegistry.

    All factory functions live in core/startup_factories.py.
    This function is the declarative registry — component names, factories,
    required flags, and dependency edges only.
    """
    logger.info("=" * 70)
    logger.info("HOPEFX AI TRADING API - STARTING")
    logger.info("=" * 70)

    from core.component_registry import ComponentRegistry
    import core.startup_factories as F
    from functools import partial

    _registry = ComponentRegistry()

    # Factories that need access to the FastAPI `app` object receive it via partial.
    def _app(fn):
        return partial(fn, app=app)

    def _app_flags(fn):
        return partial(fn, app=app, flags=feature_flags)

    # ── Core infrastructure ───────────────────────────────────────────────────
    (
        _registry.register("env_check", F.init_env, required=False)
        .register("config", F.init_config, required=True, deps=["env_check"])
        .register("database", F.init_database, required=True, deps=["config"])
        .register("cache", F.init_cache, required=False, deps=["config"])
        # ── Background services ───────────────────────────────────────────────
        .register(
            "data_scheduler", F.init_data_scheduler, required=False, deps=["config"]
        )
        .register("websocket", _app(F.init_websocket), required=False, deps=["config"])
        .register(
            "alert_engine", _app(F.init_alert_engine), required=False, deps=["config"]
        )
        # ── Analysis / data routers ───────────────────────────────────────────
        .register(
            "order_flow", _app(F.init_order_flow), required=False, deps=["config"]
        )
        .register(
            "time_and_sales",
            _app(F.init_time_and_sales),
            required=False,
            deps=["config"],
        )
        .register(
            "market_scanner",
            _app(F.init_market_scanner),
            required=False,
            deps=["config"],
        )
        .register("dom", _app(F.init_dom), required=False, deps=["config"])
        .register(
            "signals_router",
            _app(F.init_signals_router),
            required=False,
            deps=["config"],
        )
        .register(
            "news_router", _app(F.init_news_router), required=False, deps=["config"]
        )
        # ── Auth / risk / trading ─────────────────────────────────────────────
        .register("auth_service", F.init_auth, required=False, deps=["database"])
        .register("risk_manager", F.init_risk_manager, required=False, deps=["config"])
        .register("broker", F.init_broker, required=False, deps=["database"])
        .register("price_engine", F.init_price_engine, required=False, deps=["broker"])
        .register(
            "compliance_manager", F.init_compliance, required=False, deps=["database"]
        )
        .register(
            "prop_enforcer",
            F.init_prop_enforcer,
            required=False,
            deps=["compliance_manager"],
        )
        .register("aml", F.init_aml, required=False, deps=["database"])
        .register(
            "strategy_brain", F.init_strategy_brain, required=False, deps=["config"]
        )
        .register("event_store", F.init_event_store, required=False, deps=["config"])
        .register(
            "position_tracker", F.init_position_tracker, required=False, deps=["config"]
        )
        .register(
            "trade_executor",
            F.init_trade_executor,
            required=False,
            deps=["broker", "risk_manager", "position_tracker"],
        )
        .register(
            "brain",
            F.init_hopefx_brain,
            required=False,
            deps=[
                "price_engine",
                "risk_manager",
                "broker",
                "strategy_brain",
                "alert_engine",
                "position_tracker",
                "trade_executor",
            ],
        )
        # ── Payments / social ─────────────────────────────────────────────────
        .register("wallet_manager", F.init_wallet, required=False, deps=["database"])
        .register("social", F.init_social, required=False, deps=["config"])
        .register(
            "regime_router",
            F.init_regime_router,
            required=False,
            deps=["strategy_brain"],
        )
        # ── Macro feature store (must start before signal engine) ────────────
        .register("macro_store", F.init_macro_store, required=False, deps=["config"])
        # ── MTF fusion store (Phase 1 — H4/D1 regime features) ───────────────
        .register(
            "mtf_store", F.init_mtf_store, required=False, deps=["data_scheduler"]
        )
        # ── Engines ───────────────────────────────────────────────────────────
        .register(
            "signal_engine",
            F.init_signal_engine,
            required=False,
            deps=["risk_manager", "broker", "macro_store", "mtf_store"],
        )
        # ── Hourly ML retraining (online update + full retrain) ───────────────
        .register(
            "hourly_trainer",
            F.init_hourly_trainer,
            required=False,
            deps=["data_scheduler"],
        )
        # ── Phase 3: Online learner store (ADWIN drift + incremental XGBoost) ─
        # Gate: FEATURE_ONLINE_LEARNING=true + 90-day paper run with ≥500 fills.
        # Wired here so the signal engine picks it up at inference time without
        # a restart.  Off by default — see config/feature_flags.py ONLINE_LEARNING.
        .register(
            "online_learner_store",
            F.init_online_learner_store,
            required=False,
            deps=["signal_engine", "hourly_trainer"],
        )
        # ── Daily online learner (ml/online_learner.py SklearnOnlineLearner) ──
        # Pre-loads SklearnOnlineLearner singletons for each ML_SYMBOLS entry
        # so HourlyTrainer._online_update() has zero cold-start latency.
        # Also schedules a daily EWC regime-adaptation tick at 00:05 UTC.
        # Gate: ML_HOURLY_ENABLED=true (same flag as HourlyTrainer).
        .register(
            "daily_online_learner",
            F.init_daily_online_learner,
            required=False,
            deps=["hourly_trainer"],
        )
        .register(
            "reconciler", F.init_reconciler, required=False, deps=["database", "broker"]
        )
        .register(
            "telegram_bot", F.init_telegram_bot, required=False, deps=["alert_engine"]
        )
        .register("mobile", _app(F.init_mobile), required=False, deps=["config"])
        .register("hyperopt", _app(F.init_hyperopt), required=False, deps=["config"])
        # ── Feature-flagged ───────────────────────────────────────────────────
        .register(
            "research_engine",
            _app_flags(F.init_research),
            required=False,
            deps=["config"],
        )
        .register(
            "explainer",
            _app_flags(F.init_explainability),
            required=False,
            deps=["config"],
        )
        .register(
            "transparency_engine",
            _app_flags(F.init_transparency),
            required=False,
            deps=["config"],
        )
        .register(
            "teams_manager", _app_flags(F.init_teams), required=False, deps=["config"]
        )
        .register(
            "nocode_builder", _app_flags(F.init_nocode), required=False, deps=["config"]
        )
        .register(
            "replay_engine", _app_flags(F.init_replay), required=False, deps=["config"]
        )
        .register(
            "ml_feature_engineer",
            _app_flags(F.init_ml_predictions),
            required=False,
            deps=["config"],
        )
    )

    try:
        await _registry.start_all(app_state)
        _registry.print_table()

        # Push app_state into every API module that holds a local reference.
        # These modules use a module-level `app_state = None` pattern and
        # expose a set_state() function to receive the live state object.
        _state_receivers = []
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
                    _state_receivers.append((_mod_name, _fn))
            except ImportError:
                pass
        for _mod_name, _fn in _state_receivers:
            try:
                _fn(app_state)
                logger.info("State pushed → %s", _mod_name)
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


# Health check endpoint
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint — probes each component and reports real status.
    """
    components: dict = {"api": "healthy"}

    # Config
    components["config"] = "healthy" if app_state.config else "unavailable"

    # Database — run a lightweight query
    if app_state.db_engine:
        try:
            from sqlalchemy import text as _text

            with app_state.db_engine.connect() as _conn:
                _conn.execute(_text("SELECT 1"))
            components["database"] = "healthy"
        except Exception as _dbe:
            logger.warning("DB health probe failed: %s", _dbe)
            components["database"] = "degraded"
    else:
        components["database"] = "unavailable"

    # Cache (Redis) — optional
    if app_state.cache:
        try:
            ok = (
                app_state.cache.health_check()
                if hasattr(app_state.cache, "health_check")
                else True
            )
            components["cache"] = "healthy" if ok else "degraded"
        except Exception:
            components["cache"] = "degraded"
    else:
        components["cache"] = "unavailable"

    # Auth service
    components["auth"] = (
        "healthy" if getattr(app_state, "auth_service", None) else "unavailable"
    )

    # Risk manager
    components["risk_manager"] = (
        "healthy" if getattr(app_state, "risk_manager", None) else "unavailable"
    )

    # Compliance manager
    components["compliance"] = (
        "healthy" if getattr(app_state, "compliance_manager", None) else "unavailable"
    )
    _pe = getattr(app_state, "prop_enforcer", None)
    if _pe is not None:
        _pe_status = _pe.status()
        components["prop_enforcer"] = (
            "halted" if _pe_status.get("halted") else "healthy"
        )
    else:
        components["prop_enforcer"] = "unavailable"

    # Strategy brain
    components["strategy_brain"] = (
        "healthy" if getattr(app_state, "strategy_brain", None) else "unavailable"
    )

    # WebSocket manager
    components["websocket"] = (
        "healthy" if getattr(app_state, "ws_manager", None) else "unavailable"
    )

    # Email
    # "healthy"   — SENDGRID_API_KEY is set (high-deliverability path)
    # "degraded"  — only raw SMTP credentials available (low-deliverability fallback)
    # "unavailable" — no credentials configured at all
    import os as _os

    _sg_key = _os.getenv("SENDGRID_API_KEY", "")
    _smtp_host = _os.getenv("SMTP_HOST", "")
    _smtp_user = _os.getenv("SMTP_USER", "") or _os.getenv("SMTP_USERNAME", "")
    if _sg_key:
        components["email"] = "healthy"
    elif _smtp_host and _smtp_user:
        components["email"] = "healthy"  # SMTP configured — mail delivery active
    else:
        components["email"] = "unavailable"

    # Broker (IBKR) — probe the live connector if present
    _broker = getattr(app_state, "broker", None)
    if _broker is not None:
        try:
            # IBKRConnector exposes .connected; paper broker has no such attr
            if hasattr(_broker, "connected"):
                components["broker"] = "healthy" if _broker.connected else "degraded"
            elif hasattr(_broker, "health_check"):
                components["broker"] = "healthy" if _broker.health_check() else "degraded"
            else:
                components["broker"] = "healthy"
        except Exception as _be:
            logger.warning("Broker health probe failed: %s", _be)
            components["broker"] = "degraded"
    else:
        components["broker"] = "unavailable"

    # Kill switch — always report its state so monitoring can alert on it
    _ks = kill_switch
    components["kill_switch"] = "active" if _ks.is_active() else "healthy"

    # Overall: degraded if any critical component is not healthy
    critical = ["api", "config", "database"]
    overall_status = (
        "healthy"
        if all(components.get(c) == "healthy" for c in critical)
        else "degraded"
    )
    # Kill switch active → degraded regardless of other components
    if _ks.is_active():
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        version="2.0.0",
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
            cache_connected = (
                app_state.cache.health_check()
                if hasattr(app_state.cache, "health_check")
                else True
            )
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


# /metrics is registered by setup_prometheus_monitoring(app) above — no duplicate here.

# ── SendGrid email webhook ────────────────────────────────────────────────────


def _verify_sendgrid_signature(
    public_key_b64: str,
    payload: bytes,
    signature_b64: str,
    timestamp: str,
) -> bool:
    """
    Verify a SendGrid Event Webhook ECDSA P-256 signature.

    SendGrid signs the concatenation of (timestamp + payload) with an
    ECDSA P-256 private key.  The matching public key is available in the
    SendGrid dashboard under Settings → Mail Settings → Event Webhook →
    Signature Verification.

    Args:
        public_key_b64: Base64-encoded DER public key from SendGrid dashboard.
        payload:        Raw request body bytes.
        signature_b64:  Value of the X-Twilio-Email-Event-Webhook-Signature header.
        timestamp:      Value of the X-Twilio-Email-Event-Webhook-Timestamp header.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric.ec import (
            ECDSA,
            EllipticCurvePublicKey,
        )
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.exceptions import InvalidSignature

        der = base64.b64decode(public_key_b64)
        pub_key: EllipticCurvePublicKey = load_der_public_key(der)  # type: ignore[assignment]
        sig = base64.b64decode(signature_b64)
        # SendGrid signs timestamp + payload (no separator)
        signed_payload = timestamp.encode() + payload
        pub_key.verify(sig, signed_payload, ECDSA(SHA256()))
        return True
    except InvalidSignature:
        return False
    except Exception as exc:
        logger.error("SendGrid signature verification error: %s", exc)
        return False


@app.post("/api/email/webhook", tags=["Email"], include_in_schema=False)
async def sendgrid_webhook(request: Request):
    """
    Receive SendGrid Event Webhook POSTs (bounce, spam_report, unsubscribe).

    Authentication:
      Verifies the ECDSA P-256 signature using the public key from
      SENDGRID_WEBHOOK_PUBLIC_KEY env var.  Requests without a valid
      signature are rejected with 403.  Set SENDGRID_WEBHOOK_VERIFY=false
      to disable verification during local development only.

    Suppression:
      Writes bounced/spam/unsubscribed addresses to email_suppressions.
      EmailChannel.send() checks this table before every dispatch.

    SendGrid setup:
      Settings → Mail Settings → Event Webhook → Signature Verification
      Copy the public key and set SENDGRID_WEBHOOK_PUBLIC_KEY=<value>
    """
    raw_body = await request.body()

    # ── Signature verification ────────────────────────────────────────────────
    verify = os.getenv("SENDGRID_WEBHOOK_VERIFY", "true").lower() != "false"
    webhook_pub_key = os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")

    if verify:
        if not webhook_pub_key:
            logger.error(
                "SendGrid webhook received but SENDGRID_WEBHOOK_PUBLIC_KEY is not set — "
                "rejecting request. Set the key or SENDGRID_WEBHOOK_VERIFY=false for dev."
            )
            raise HTTPException(
                status_code=403, detail="Webhook signature key not configured"
            )

        sig = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
        ts = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")

        if not sig or not ts:
            logger.warning("SendGrid webhook missing signature headers — rejected")
            raise HTTPException(
                status_code=403, detail="Missing webhook signature headers"
            )

        if not _verify_sendgrid_signature(webhook_pub_key, raw_body, sig, ts):
            logger.critical(
                "SendGrid webhook SIGNATURE INVALID — possible spoofed request from %s",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # ── Parse events ──────────────────────────────────────────────────────────
    try:
        import json as _json

        events = _json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(events, list):
        events = [events]

    suppression_events = {"bounce", "spam_report", "unsubscribe", "group_unsubscribe"}
    suppressed: List[str] = []

    for event in events:
        event_type = event.get("event", "")
        email = event.get("email", "").lower().strip()
        if not email or event_type not in suppression_events:
            continue

        try:
            from database.models import EmailSuppression
            from sqlalchemy.orm import sessionmaker

            if app_state.db_engine:
                Session = sessionmaker(bind=app_state.db_engine)
                with Session() as session:
                    exists = (
                        session.query(EmailSuppression).filter_by(email=email).first()
                    )
                    if not exists:
                        session.add(EmailSuppression(email=email, reason=event_type))
                        session.commit()
                        suppressed.append(email)
                        logger.info(
                            "Email suppressed: %s (reason: %s)", email, event_type
                        )
        except Exception as exc:
            logger.error("Failed to record email suppression for %s: %s", email, exc)

    return {"suppressed": suppressed, "processed": len(events)}


# /admin redirect — the root endpoint advertises /admin but the router is
# mounted at /api/admin/. This redirect keeps the advertised URL working.
@app.get("/admin", response_class=HTMLResponse, tags=["Admin"], include_in_schema=False)
async def admin_redirect():
    """Redirect /admin to the admin dashboard at /api/admin/."""
    return HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=/api/admin/"></head>'
        "<body>Redirecting to admin dashboard…</body></html>",
        status_code=200,
    )


# Root endpoint
@app.get("/login", response_class=HTMLResponse, tags=["Auth"], include_in_schema=False)
async def login_page():
    """Serve the login page."""
    template_path = Path(__file__).parent / "templates" / "login.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<html><body><p>Login template missing. "
        '<a href="/docs">Use /docs to authenticate.</a></p></body></html>',
        status_code=200,
    )


@app.get(
    "/register", response_class=HTMLResponse, tags=["Auth"], include_in_schema=False
)
async def register_page():
    """Redirect /register to the login page (registration is via API)."""
    return HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=/login"></head>'
        "<body>Redirecting to login…</body></html>",
        status_code=200,
    )


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
    tags=["Dashboard"],
    include_in_schema=False,
)
async def dashboard_redirect():
    """Redirect /dashboard to the paper-trading dashboard."""
    return HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=/paper-trading"></head>'
        "<body>Redirecting…</body></html>",
        status_code=200,
    )


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
        "stream_dashboard": "/stream",
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
        with open(template_path, "r") as f:
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
            status_code=200,
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
        with open(template_path, "r") as f:
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
            status_code=200,
        )


@app.get("/stream", response_class=HTMLResponse, tags=["Dashboard"])
async def stream_dashboard():
    """
    Live Streaming Dashboard

    Real-time dashboard that streams XAUUSD/EURUSD/BTCUSD prices,
    trading signals, news, and alerts via WebSocket.
    """
    template_path = Path(__file__).parent / "templates" / "stream_dashboard.html"
    if template_path.exists():
        with open(template_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content="""
        <html>
        <head><title>Live Stream</title></head>
        <body style="background:#131722;color:#d1d4dc;font-family:sans-serif;padding:40px;text-align:center;">
            <h1>🔴 Live Stream</h1>
            <p>Template not found. Please ensure templates/stream_dashboard.html exists.</p>
            <a href="/docs" style="color:#26a69a;">Go to API Docs</a>
        </body>
        </html>
        """,
        status_code=200,
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


# Setup CORS, security headers, and metrics middleware
setup_cors(app)
setup_security_headers(app)
setup_metrics_middleware(app)

# Serve the React dashboard from dashboard/dist/ — mounted LAST so all /api/*
# routes take precedence.  Falls back gracefully when dist/ doesn't exist yet.
_dashboard_dist = Path(__file__).parent / "dashboard" / "dist"
if _dashboard_dist.exists():
    app.mount(
        "/app", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard"
    )
    logger.info("React dashboard mounted at /app (dashboard/dist/)")
else:
    logger.warning(
        "dashboard/dist/ not found — run 'cd dashboard && npm run build' to build the UI"
    )


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
