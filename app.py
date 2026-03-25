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

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

# Logger must be defined before any module-level try/except blocks that use it.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import uvicorn

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from api.admin import router as admin_router, log_activity, apply_persisted_risk_settings
from auth.router import router as auth_router, set_auth_service
from api.trading import router as trading_router
from api.monetization import router as monetization_router
from api.backtesting import router as backtesting_router
from api.chat import router as chat_router
from api.prop_firm import router as prop_firm_router
from api.performance import router as performance_router
from api.explain import router as explain_router
from api.macro import router as macro_router
from api.broker import router as broker_router
from api.landing import router as landing_router
from api.payments import router as payments_router
from api.settings import router as settings_router
from api.status import router as status_router
from api.brain import router as brain_router
from api.two_factor import router as two_factor_router
from api.calendar import router as calendar_router
from api.watchlist import router as watchlist_router
from api.journal import router as journal_router
from api.profiles import router as profiles_router
from api.social_feed import router as social_feed_router
from api.mobile import router as mobile_router
from api.whitelabel_admin import router as whitelabel_router
from api.billing import router as billing_router
from api.platform import router as platform_router, setup_rate_limiting, init_sentry
from api.advanced_trading import router as advanced_router
from api.ml import router as ml_router
from api.alerts import router as alerts_router

# GraphQL — strawberry-graphql (api/graphql_schema.py avoids shadowing graphql-core)
try:
    from api.graphql_schema import graphql_router as _graphql_router
    _graphql_available = True
except Exception as _gql_err:
    _graphql_router = None
    _graphql_available = False
    logger.warning("GraphQL router not loaded: %s", _gql_err)
from cache import MarketDataCache
from config import initialize_config
from config.feature_flags import flags as feature_flags
from database.models import Base
from kill_switch import KillSwitch, create_kill_switch_router

# (logging and logger already configured at module top)

# Initialize FastAPI app — lifespan is wired below after it is defined
app = FastAPI(
    title="HOPEFX AI Trading API",
    description="REST API for HOPEFX AI Trading Framework",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Include routers
app.include_router(auth_router)
app.include_router(trading_router)
app.include_router(admin_router)
app.include_router(monetization_router)
app.include_router(backtesting_router)
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
app.include_router(two_factor_router)
app.include_router(calendar_router)
app.include_router(watchlist_router)
app.include_router(journal_router)
app.include_router(profiles_router)
app.include_router(social_feed_router)
app.include_router(mobile_router)
app.include_router(whitelabel_router)
app.include_router(billing_router)
app.include_router(platform_router)
app.include_router(advanced_router)
app.include_router(ml_router)
app.include_router(alerts_router)

# Mount GraphQL at /graphql — GraphiQL playground available at GET /graphql
if _graphql_available and _graphql_router is not None:
    app.include_router(_graphql_router, prefix="/graphql")
    logger.info("GraphQL endpoint mounted at /graphql")

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
    _logging.getLogger(__name__).warning("Prometheus monitoring setup failed: %s", _prom_err)

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

    oanda_token   = os.getenv("BROKER_OANDA_TOKEN", "")
    oanda_account = os.getenv("BROKER_OANDA_ACCOUNT", "")
    oanda_env     = os.getenv("BROKER_OANDA_ENVIRONMENT", "practice")

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
            logger.warning("OANDA price poller: connection failed — using static prices")
            return
        logger.info("OANDA price poller connected — symbols=%s interval=%.1fs", _SYMBOLS, _INTERVAL)
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
            logger.warning("OANDA price poller: circuit OPEN — sleeping %.0fs", cbo.retry_after)
            await _asyncio.sleep(min(cbo.retry_after, _MAX_BACKOFF))
            continue
        except Exception as exc:
            logger.warning("OANDA price poller error (backoff=%.0fs): %s", _backoff, exc)
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
        _STREAM_SYMBOLS, _POLL_INTERVAL,
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


async def startup_event():
    """Initialize application on startup via ComponentRegistry."""
    logger.info("=" * 70)
    logger.info("HOPEFX AI TRADING API - STARTING")
    logger.info("=" * 70)

    from core.component_registry import ComponentRegistry
    _registry = ComponentRegistry()

    # ── Factory definitions (one per component) ───────────────────────────────

    async def _init_env(s):
        if not os.getenv('OPENAI_API_KEY'):
            logger.warning("OPENAI_API_KEY not set — /api/chat will return 503 until configured")
        if not os.getenv('CONFIG_ENCRYPTION_KEY'):
            logger.warning("CONFIG_ENCRYPTION_KEY not set — using dev default (not for production)")
            os.environ['CONFIG_ENCRYPTION_KEY'] = 'dev-key-minimum-32-characters-long-for-testing'
        if not os.getenv('SECURITY_JWT_SECRET'):
            logger.warning("SECURITY_JWT_SECRET not set — using dev default (not for production)")
            os.environ['SECURITY_JWT_SECRET'] = 'dev-jwt-secret-minimum-32-characters-long!!'
        try:
            from core.env_validator import validate_and_report
            validate_and_report(strict=False, exit_on_error=False)
        except Exception as _ve:
            logger.warning("Env validator unavailable: %s", _ve)
        return True

    async def _init_config(s):
        _raw_config = initialize_config()
        if isinstance(_raw_config, dict):
            class _DB:
                connection_pool_size = 5
                max_overflow = 10
                def get_connection_string(self):
                    return os.getenv('DATABASE_URL', 'sqlite:///hopefx.db')
            class _ConfigNS:
                def __init__(self, d):
                    for k, v in d.items():
                        setattr(self, k, v)
                    if not hasattr(self, 'environment'):
                        self.environment = os.getenv('APP_ENV', 'development')
                    self.database = _DB()
                    if not hasattr(self, 'api_configs'):
                        self.api_configs = {}
            cfg = _ConfigNS(_raw_config)
        else:
            cfg = _raw_config
        logger.info("Configuration loaded: %s", cfg.environment)
        return cfg

    async def _init_database(s):
        conn_str = s.config.database.get_connection_string()
        engine = create_engine(
            conn_str,
            pool_size=s.config.database.connection_pool_size,
            max_overflow=s.config.database.max_overflow,
        )
        try:
            from alembic.config import Config as AlembicConfig
            from alembic import command as alembic_command
            alembic_cfg = AlembicConfig("alembic.ini")
            alembic_cfg.set_main_option("sqlalchemy.url", conn_str)
            alembic_command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations applied (alembic upgrade head)")
        except Exception as e:
            logger.warning("Alembic migration failed (%s), falling back to create_all", e)
            try:
                Base.metadata.create_all(engine)
            except Exception as e2:
                logger.warning("create_all also failed: %s", e2)
        s.db_engine = engine
        s.db_session_factory = sessionmaker(bind=engine)
        return engine

    async def _init_cache(s):
        cache = MarketDataCache(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            max_retries=1,
            socket_connect_timeout=1,
            enable_fallback=True,
        )
        return cache

    async def _init_data_scheduler(s):
        from data.scheduler import DataScheduler
        ds = DataScheduler()
        t = asyncio.create_task(ds.start())
        s.background_tasks.append(t)
        s.data_scheduler = ds
        log_activity("Data scheduler started")
        return ds

    async def _init_websocket(s):
        from api.websocket_server import WebSocketManager, create_websocket_router
        ws = WebSocketManager()
        app.include_router(create_websocket_router(ws))
        s.ws_manager = ws
        log_activity("WebSocket router registered")
        t = asyncio.create_task(_price_stream_loop(ws))
        s.background_tasks.append(t)
        t2 = asyncio.create_task(_oanda_price_poller(s))
        s.background_tasks.append(t2)
        return ws

    async def _init_alert_engine(s):
        from notifications.alert_engine import AlertEngine, create_alert_router
        _smtp_to = [a.strip() for a in os.getenv("SMTP_TO", "").split(",") if a.strip()]
        cfg = {
            "smtp_host": os.getenv("SMTP_HOST", ""), "smtp_port": int(os.getenv("SMTP_PORT", "587")),
            "smtp_username": os.getenv("SMTP_USERNAME", ""), "smtp_password": os.getenv("SMTP_PASSWORD", ""),
            "smtp_from": os.getenv("SMTP_FROM", ""), "smtp_to": _smtp_to,
            "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
            "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL", ""),
        }
        ae = AlertEngine(config=cfg)
        app.include_router(create_alert_router(ae))
        log_activity("Alert router registered")
        return ae

    async def _init_order_flow(s):
        from analysis.order_flow import OrderFlowAnalyzer, create_order_flow_router
        ofa = OrderFlowAnalyzer()
        app.include_router(create_order_flow_router(ofa))
        return ofa

    async def _init_time_and_sales(s):
        from data.time_and_sales import TimeAndSalesService, create_time_and_sales_router
        svc = TimeAndSalesService()
        app.include_router(create_time_and_sales_router(svc))
        return svc

    async def _init_market_scanner(s):
        from analysis.market_scanner import MarketScanner, create_scanner_router
        ms = MarketScanner()
        app.include_router(create_scanner_router(ms))
        return ms

    async def _init_dom(s):
        from data.depth_of_market import DepthOfMarketService, create_dom_router
        dom = DepthOfMarketService()
        app.include_router(create_dom_router(dom))
        return dom

    async def _init_signals_router(s):
        from api.signals import create_signals_router
        r = create_signals_router()
        if r:
            app.include_router(r)
        return r

    async def _init_news_router(s):
        from news import create_news_router
        r = create_news_router()
        if r:
            app.include_router(r)
        return r

    async def _init_auth(s):
        from database.user_models import User, UserSession, LoginAttempt
        User.__table__.create(s.db_engine, checkfirst=True)
        UserSession.__table__.create(s.db_engine, checkfirst=True)
        LoginAttempt.__table__.create(s.db_engine, checkfirst=True)
        from auth.service import AuthService
        svc = AuthService(session_factory=s.db_session_factory)
        set_auth_service(svc)
        log_activity("Auth Service initialized")
        return svc

    async def _init_risk_manager(s):
        from risk.manager import RiskManager, RiskConfig
        rc = RiskConfig(
            max_position_size_pct=float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.02")),
            max_drawdown_pct=float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
            daily_loss_limit_pct=float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")),
        )
        rm = RiskManager(config=rc)
        log_activity("Risk Manager initialized")
        return rm

    async def _init_broker(s):
        from brokers.paper_trading import PaperTradingBroker
        bal = float(os.getenv("PAPER_TRADING_BALANCE", "10000"))
        b = PaperTradingBroker(initial_balance=bal, session_factory=s.db_session_factory)
        await b.connect()
        log_activity("Paper Trading Broker connected")
        return b

    async def _init_price_engine(s):
        from data.real_time_price_engine import RealTimePriceEngine
        from brokers.paper_trading import PaperTradingBroker as _PTB
        syms = [x.strip().upper() for x in os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD,EURUSD,GBPUSD").split(",") if x.strip()]
        pe = RealTimePriceEngine({"symbols": syms, "websocket_url": os.getenv("WS_PRICE_FEED_URL", ""), "rest_url": os.getenv("REST_PRICE_FEED_URL", "")})
        await pe.start()
        if isinstance(s.broker, _PTB):
            s.broker.set_price_feed(pe)
        return pe

    async def _init_compliance(s):
        from compliance.compliance_manager import ComplianceManager
        return ComplianceManager(session_factory=s.db_session_factory)

    async def _init_aml(s):
        from compliance.aml import init_aml_gate
        init_aml_gate(session_factory=s.db_session_factory)
        return True

    async def _init_strategy_brain(s):
        from strategies.strategy_brain import StrategyBrain
        from strategies.base import StrategyConfig
        from strategies.ma_crossover import MovingAverageCrossover
        from strategies.rsi_strategy import RSIStrategy
        from strategies.macd_strategy import MACDStrategy
        from strategies.bollinger_bands import BollingerBandsStrategy
        def _cfg(name): return StrategyConfig(name=name, symbol="XAUUSD", timeframe="1h")
        brain = StrategyBrain()
        brain.register_strategy(MovingAverageCrossover(_cfg("MA_Crossover")))
        brain.register_strategy(RSIStrategy(_cfg("RSI")))
        brain.register_strategy(MACDStrategy(_cfg("MACD")))
        brain.register_strategy(BollingerBandsStrategy(_cfg("BB")))
        return brain

    async def _init_event_store(s):
        from events.event_store import get_event_store
        es = get_event_store()
        await es.start()
        return es

    async def _init_position_tracker(s):
        from execution.position_tracker import PositionTracker
        return PositionTracker()

    async def _init_trade_executor(s):
        from execution.trade_executor import TradeExecutor
        return TradeExecutor(broker=s.broker, risk_manager=s.risk_manager, position_tracker=s.position_tracker)

    async def _init_hopefx_brain(s):
        from brain.brain import HOPEFXBrain
        b = HOPEFXBrain(config={"max_decision_history": 1000, "regime_check_interval": 60, "circuit_breaker_threshold": 5})
        b.inject_components(
            price_engine=s.price_engine, risk_manager=s.risk_manager, broker=s.broker,
            strategy_manager=s.strategy_brain, notification_manager=s.alert_engine,
            position_tracker=s.position_tracker, trade_executor=s.trade_executor,
        )
        return b

    async def _init_wallet(s):
        from payments.wallet import WalletManager
        return WalletManager(session_factory=s.db_session_factory)

    async def _init_social(s):
        from social import copy_trading_engine, marketplace, leaderboard_manager
        s.copy_trading_engine = copy_trading_engine
        s.marketplace = marketplace
        s.leaderboard_manager = leaderboard_manager
        return True

    async def _init_regime_router(s):
        from strategies.regime_router import RegimeRouter
        from strategies.manager import StrategyManager
        sm = s.strategy_brain or StrategyManager(preload_defaults=True)
        return RegimeRouter(sm)

    async def _init_signal_engine(s):
        from core.signal_engine import run_signal_engine
        t = asyncio.create_task(run_signal_engine(s))
        s.background_tasks.append(t)
        log_activity("Signal engine started")
        return t

    async def _init_reconciler(s):
        from core.position_reconciler import PositionReconciler
        interval = int(os.getenv("RECONCILER_INTERVAL_SECONDS", "30"))
        r = PositionReconciler(
            session_factory=s.db_session_factory,
            broker=getattr(s, "broker", None),
            ws_manager=getattr(s, "ws_manager", None),
            interval_seconds=interval,
        )
        await r.start()
        log_activity("Position reconciler started")
        return r

    async def _init_telegram_bot(s):
        from notifications.telegram_bot import init_telegram_bot
        bot = init_telegram_bot(s)
        if bot:
            t = asyncio.create_task(bot.start())
            s.background_tasks.append(t)
            s.telegram_bot = bot
        return bot

    async def _init_mobile(s):
        from mobile.api import MobileAPIServer
        from mobile.push_notifications import PushNotificationManager
        mob = MobileAPIServer()
        if hasattr(mob, 'router'):
            app.include_router(mob.router, prefix="/api/mobile", tags=["Mobile"])
        elif hasattr(mob, 'app'):
            app.mount("/api/mobile", mob.app)
        s.push_notifications = PushNotificationManager()
        return mob

    async def _init_hyperopt(s):
        from backtesting.hyperopt import create_hyperopt_router
        app.include_router(create_hyperopt_router())
        return True

    # ── Feature-flagged factories ─────────────────────────────────────────────

    async def _init_research(s):
        if not feature_flags.RESEARCH_MODULE:
            return None
        from research import ResearchNotebookEngine, create_research_router
        e = ResearchNotebookEngine()
        app.include_router(create_research_router(e))
        return e

    async def _init_explainability(s):
        if not feature_flags.EXPLAINABILITY:
            return None
        from explainability import AIExplainer, create_explainability_router
        e = AIExplainer()
        app.include_router(create_explainability_router(e))
        return e

    async def _init_transparency(s):
        if not feature_flags.TRANSPARENCY_REPORTS:
            return None
        from transparency import ExecutionTransparencyEngine, create_transparency_router
        e = ExecutionTransparencyEngine()
        app.include_router(create_transparency_router(e))
        return e

    async def _init_teams(s):
        if not feature_flags.TEAMS_MODULE:
            return None
        from teams import TeamManager, create_teams_router
        tm = TeamManager()
        app.include_router(create_teams_router(tm))
        return tm

    async def _init_nocode(s):
        if not feature_flags.NOCODE_BUILDER:
            return None
        from nocode import NoCodeStrategyBuilder, create_nocode_router
        nb = NoCodeStrategyBuilder()
        app.include_router(create_nocode_router(nb))
        return nb

    async def _init_replay(s):
        if not feature_flags.REPLAY_ENGINE:
            return None
        from replay import ChartReplayEngine, create_replay_router
        re = ChartReplayEngine()
        app.include_router(create_replay_router(re))
        return re

    async def _init_ml_predictions(s):
        if not feature_flags.ML_PREDICTIONS:
            return None
        from ml import TechnicalFeatureEngineer, create_ml_router
        fe = TechnicalFeatureEngineer()
        app.include_router(create_ml_router(fe))
        return fe

    # ── Register all components with dependency graph ─────────────────────────
    (
        _registry
        .register("env_check",       _init_env,            required=False)
        .register("config",          _init_config,         required=True,  deps=["env_check"])
        .register("database",        _init_database,       required=True,  deps=["config"])
        .register("cache",           _init_cache,          required=False, deps=["config"])
        .register("data_scheduler",  _init_data_scheduler, required=False, deps=["config"])
        .register("websocket",       _init_websocket,      required=False, deps=["config"])
        .register("alert_engine",    _init_alert_engine,   required=False, deps=["config"])
        .register("order_flow",      _init_order_flow,     required=False, deps=["config"])
        .register("time_and_sales",  _init_time_and_sales, required=False, deps=["config"])
        .register("market_scanner",  _init_market_scanner, required=False, deps=["config"])
        .register("dom",             _init_dom,            required=False, deps=["config"])
        .register("signals_router",  _init_signals_router, required=False, deps=["config"])
        .register("news_router",     _init_news_router,    required=False, deps=["config"])
        .register("auth_service",    _init_auth,           required=False, deps=["database"])
        .register("risk_manager",    _init_risk_manager,   required=False, deps=["config"])
        .register("broker",          _init_broker,         required=False, deps=["database"])
        .register("price_engine",    _init_price_engine,   required=False, deps=["broker"])
        .register("compliance_manager", _init_compliance,  required=False, deps=["database"])
        .register("aml",             _init_aml,            required=False, deps=["database"])
        .register("strategy_brain",  _init_strategy_brain, required=False, deps=["config"])
        .register("event_store",     _init_event_store,    required=False, deps=["config"])
        .register("position_tracker",_init_position_tracker, required=False, deps=["config"])
        .register("trade_executor",  _init_trade_executor, required=False, deps=["broker", "risk_manager", "position_tracker"])
        .register("brain",           _init_hopefx_brain,   required=False, deps=["price_engine", "risk_manager", "broker", "strategy_brain", "alert_engine", "position_tracker", "trade_executor"])
        .register("wallet_manager",  _init_wallet,         required=False, deps=["database"])
        .register("social",          _init_social,         required=False, deps=["config"])
        .register("regime_router",   _init_regime_router,  required=False, deps=["strategy_brain"])
        .register("signal_engine",   _init_signal_engine,  required=False, deps=["risk_manager", "broker"])
        .register("reconciler",      _init_reconciler,     required=False, deps=["database", "broker"])
        .register("telegram_bot",    _init_telegram_bot,   required=False, deps=["alert_engine"])
        .register("mobile",          _init_mobile,         required=False, deps=["config"])
        .register("hyperopt",        _init_hyperopt,       required=False, deps=["config"])
        .register("research_engine", _init_research,       required=False, deps=["config"])
        .register("explainer",       _init_explainability, required=False, deps=["config"])
        .register("transparency_engine", _init_transparency, required=False, deps=["config"])
        .register("teams_manager",   _init_teams,          required=False, deps=["config"])
        .register("nocode_builder",  _init_nocode,         required=False, deps=["config"])
        .register("replay_engine",   _init_replay,         required=False, deps=["config"])
        .register("ml_feature_engineer", _init_ml_predictions, required=False, deps=["config"])
    )

    try:
        # ── Run registry ──────────────────────────────────────────────────────
        await _registry.start_all(app_state)
        _registry.print_table()
        apply_persisted_risk_settings()
        app_state.initialized = True
        log_activity("API server ready")
        logger.info("=" * 70)
        logger.info("API SERVER READY")
        logger.info("=" * 70)

    except Exception as e:
        logger.error("Startup failed: %s", e, exc_info=True)
        raise

    # ── DEAD CODE BELOW — kept for reference, never reached ──────────────────


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
            ok = app_state.cache.health_check() if hasattr(app_state.cache, "health_check") else True
            components["cache"] = "healthy" if ok else "degraded"
        except Exception:
            components["cache"] = "degraded"
    else:
        components["cache"] = "unavailable"

    # Auth service
    components["auth"] = "healthy" if getattr(app_state, "auth_service", None) else "unavailable"

    # Risk manager
    components["risk_manager"] = "healthy" if getattr(app_state, "risk_manager", None) else "unavailable"

    # Compliance manager
    components["compliance"] = "healthy" if getattr(app_state, "compliance_manager", None) else "unavailable"

    # Strategy brain
    components["strategy_brain"] = "healthy" if getattr(app_state, "strategy_brain", None) else "unavailable"

    # WebSocket manager
    components["websocket"] = "healthy" if getattr(app_state, "ws_manager", None) else "unavailable"

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
        components["email"] = "degraded"
    else:
        components["email"] = "unavailable"

    # Overall: degraded if any critical component is not healthy
    critical = ["api", "config", "database"]
    overall_status = "healthy" if all(
        components.get(c) == "healthy" for c in critical
    ) else "degraded"

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


# /metrics is registered by setup_prometheus_monitoring(app) above — no duplicate here.

# ── SendGrid email webhook ────────────────────────────────────────────────────

@app.post("/api/email/webhook", tags=["Email"], include_in_schema=False)
async def sendgrid_webhook(request: Request):
    """
    Receive SendGrid event webhooks (bounce, spam_report, unsubscribe).
    Suppresses future sends to affected addresses by writing to email_suppressions.
    Configure in SendGrid dashboard: Settings → Mail Settings → Event Webhook.
    """
    try:
        events = await request.json()
    except Exception:
        from fastapi import HTTPException
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
            from sqlalchemy import text as _text
            if app_state.db_engine:
                Session = sessionmaker(bind=app_state.db_engine)
                with Session() as session:
                    exists = session.query(EmailSuppression).filter_by(email=email).first()
                    if not exists:
                        session.add(EmailSuppression(email=email, reason=event_type))
                        session.commit()
                        suppressed.append(email)
                        logger.info("Email suppressed: %s (reason: %s)", email, event_type)
        except Exception as exc:
            logger.error("Failed to record email suppression for %s: %s", email, exc)

    return {"suppressed": suppressed, "processed": len(events)}


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
    app.mount("/app", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard")
    logger.info("React dashboard mounted at /app (dashboard/dist/)")
else:
    logger.warning(
        "dashboard/dist/ not found — run 'cd dashboard && npm run build' to build the UI"
    )


def run_server():
    """Run the API server"""
    # Default to localhost for security, use 0.0.0.0 only when explicitly set
    # Set API_HOST=0.0.0.0 in production environment to bind to all interfaces
    host = os.getenv('API_HOST', '127.0.0.1')
    port = int(os.getenv('API_PORT', 8000))
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
