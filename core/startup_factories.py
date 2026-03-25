"""
core/startup_factories.py
=========================
Component factory functions for the ComponentRegistry startup sequence.

Each factory receives the shared AppState object and returns the initialised
component (or None / True for side-effect-only factories).  They are
registered in app.py's startup_event() and executed in dependency order by
ComponentRegistry.start_all().

Keeping factories here reduces startup_event() from ~428 lines to ~60 lines.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # AppState is duck-typed; no circular import needed

logger = logging.getLogger(__name__)


# ── Environment / config ──────────────────────────────────────────────────────

async def init_env(s: Any) -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set — /api/chat will return 503 until configured")
    if not os.getenv("CONFIG_ENCRYPTION_KEY"):
        logger.warning("CONFIG_ENCRYPTION_KEY not set — using dev default (not for production)")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "dev-key-minimum-32-characters-long-for-testing"
    if not os.getenv("SECURITY_JWT_SECRET"):
        logger.warning("SECURITY_JWT_SECRET not set — using dev default (not for production)")
        os.environ["SECURITY_JWT_SECRET"] = "dev-jwt-secret-minimum-32-characters-long!!"
    try:
        from core.env_validator import validate_and_report
        validate_and_report(strict=False, exit_on_error=False)
    except Exception as exc:
        logger.warning("Env validator unavailable: %s", exc)
    return True


async def init_config(s: Any) -> Any:
    from config import initialize_config
    import os as _os
    _raw = initialize_config()
    if isinstance(_raw, dict):
        class _DB:
            connection_pool_size = 5
            max_overflow = 10
            def get_connection_string(self):
                return _os.getenv("DATABASE_URL", "sqlite:///hopefx.db")
        class _NS:
            def __init__(self, d):
                for k, v in d.items():
                    setattr(self, k, v)
                if not hasattr(self, "environment"):
                    self.environment = _os.getenv("APP_ENV", "development")
                self.database = _DB()
                if not hasattr(self, "api_configs"):
                    self.api_configs = {}
        cfg = _NS(_raw)
    else:
        cfg = _raw
    logger.info("Configuration loaded: %s", cfg.environment)
    return cfg


async def init_database(s: Any) -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base
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
    except Exception as exc:
        logger.warning("Alembic migration failed (%s), falling back to create_all", exc)
        try:
            Base.metadata.create_all(engine)
        except Exception as exc2:
            logger.warning("create_all also failed: %s", exc2)
    s.db_engine = engine
    s.db_session_factory = sessionmaker(bind=engine)
    return engine


async def init_cache(s: Any) -> Any:
    from cache import MarketDataCache
    return MarketDataCache(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        max_retries=1,
        socket_connect_timeout=1,
        enable_fallback=True,
    )


async def init_data_scheduler(s: Any) -> Any:
    from data.scheduler import DataScheduler
    from api.admin import log_activity
    ds = DataScheduler()
    t = asyncio.create_task(ds.start())
    s.background_tasks.append(t)
    s.data_scheduler = ds
    log_activity("Data scheduler started")
    return ds


async def init_websocket(s: Any, app: Any) -> Any:
    from api.websocket_server import WebSocketManager, create_websocket_router
    from api.admin import log_activity
    ws = WebSocketManager()
    app.include_router(create_websocket_router(ws))
    s.ws_manager = ws
    log_activity("WebSocket router registered")
    # Price stream and OANDA poller are started in lifespan, not here
    return ws


async def init_alert_engine(s: Any, app: Any) -> Any:
    from notifications.alert_engine import AlertEngine, create_alert_router
    from api.admin import log_activity
    _smtp_to = [a.strip() for a in os.getenv("SMTP_TO", "").split(",") if a.strip()]
    cfg = {
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_username": os.getenv("SMTP_USERNAME", ""),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_from": os.getenv("SMTP_FROM", ""),
        "smtp_to": _smtp_to,
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL", ""),
    }
    ae = AlertEngine(config=cfg)
    app.include_router(create_alert_router(ae))
    log_activity("Alert router registered")
    return ae


async def init_order_flow(s: Any, app: Any) -> Any:
    from analysis.order_flow import OrderFlowAnalyzer, create_order_flow_router
    ofa = OrderFlowAnalyzer()
    app.include_router(create_order_flow_router(ofa))
    return ofa


async def init_time_and_sales(s: Any, app: Any) -> Any:
    from data.time_and_sales import TimeAndSalesService, create_time_and_sales_router
    svc = TimeAndSalesService()
    app.include_router(create_time_and_sales_router(svc))
    return svc


async def init_market_scanner(s: Any, app: Any) -> Any:
    from analysis.market_scanner import MarketScanner, create_scanner_router
    ms = MarketScanner()
    app.include_router(create_scanner_router(ms))
    return ms


async def init_dom(s: Any, app: Any) -> Any:
    from data.depth_of_market import DepthOfMarketService, create_dom_router
    dom = DepthOfMarketService()
    app.include_router(create_dom_router(dom))
    return dom


async def init_signals_router(s: Any, app: Any) -> Any:
    from api.signals import create_signals_router
    r = create_signals_router()
    if r:
        app.include_router(r)
    return r


async def init_news_router(s: Any, app: Any) -> Any:
    from news import create_news_router
    r = create_news_router()
    if r:
        app.include_router(r)
    return r


async def init_auth(s: Any) -> Any:
    from database.user_models import User, UserSession, LoginAttempt
    from auth.service import AuthService
    from auth.router import set_auth_service
    from api.admin import log_activity
    User.__table__.create(s.db_engine, checkfirst=True)
    UserSession.__table__.create(s.db_engine, checkfirst=True)
    LoginAttempt.__table__.create(s.db_engine, checkfirst=True)
    svc = AuthService(session_factory=s.db_session_factory)
    set_auth_service(svc)
    log_activity("Auth Service initialized")
    return svc


async def init_risk_manager(s: Any) -> Any:
    from risk.manager import RiskManager, RiskConfig
    from api.admin import log_activity
    rc = RiskConfig(
        max_position_size_pct=float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.02")),
        max_drawdown_pct=float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
        daily_loss_limit_pct=float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")),
    )
    rm = RiskManager(config=rc)
    log_activity("Risk Manager initialized")
    return rm


async def init_broker(s: Any) -> Any:
    from brokers.paper_trading import PaperTradingBroker
    from api.admin import log_activity
    bal = float(os.getenv("PAPER_TRADING_BALANCE", "10000"))
    b = PaperTradingBroker(initial_balance=bal, session_factory=s.db_session_factory)
    await b.connect()
    log_activity("Paper Trading Broker connected")
    return b


async def init_price_engine(s: Any) -> Any:
    from data.real_time_price_engine import RealTimePriceEngine
    from brokers.paper_trading import PaperTradingBroker as _PTB
    syms = [
        x.strip().upper()
        for x in os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD,EURUSD,GBPUSD").split(",")
        if x.strip()
    ]
    pe = RealTimePriceEngine({
        "symbols": syms,
        "websocket_url": os.getenv("WS_PRICE_FEED_URL", ""),
        "rest_url": os.getenv("REST_PRICE_FEED_URL", ""),
    })
    await pe.start()
    if isinstance(s.broker, _PTB):
        s.broker.set_price_feed(pe)
    return pe


async def init_compliance(s: Any) -> Any:
    from compliance.compliance_manager import ComplianceManager
    return ComplianceManager(session_factory=s.db_session_factory)


async def init_aml(s: Any) -> bool:
    from compliance.aml import init_aml_gate
    init_aml_gate(session_factory=s.db_session_factory)
    return True


async def init_strategy_brain(s: Any) -> Any:
    from strategies.strategy_brain import StrategyBrain
    from strategies.base import StrategyConfig
    from strategies.ma_crossover import MovingAverageCrossover
    from strategies.rsi_strategy import RSIStrategy
    from strategies.macd_strategy import MACDStrategy
    from strategies.bollinger_bands import BollingerBandsStrategy

    def _cfg(name: str) -> StrategyConfig:
        return StrategyConfig(name=name, symbol="XAUUSD", timeframe="1h")

    brain = StrategyBrain()
    brain.register_strategy(MovingAverageCrossover(_cfg("MA_Crossover")))
    brain.register_strategy(RSIStrategy(_cfg("RSI")))
    brain.register_strategy(MACDStrategy(_cfg("MACD")))
    brain.register_strategy(BollingerBandsStrategy(_cfg("BB")))
    return brain


async def init_event_store(s: Any) -> Any:
    from events.event_store import get_event_store
    es = get_event_store()
    await es.start()
    return es


async def init_position_tracker(s: Any) -> Any:
    from execution.position_tracker import PositionTracker
    return PositionTracker()


async def init_trade_executor(s: Any) -> Any:
    from execution.trade_executor import TradeExecutor
    return TradeExecutor(
        broker=s.broker,
        risk_manager=s.risk_manager,
        position_tracker=s.position_tracker,
    )


async def init_hopefx_brain(s: Any) -> Any:
    from brain.brain import HOPEFXBrain
    b = HOPEFXBrain(config={
        "max_decision_history": 1000,
        "regime_check_interval": 60,
        "circuit_breaker_threshold": 5,
    })
    b.inject_components(
        price_engine=s.price_engine,
        risk_manager=s.risk_manager,
        broker=s.broker,
        strategy_manager=s.strategy_brain,
        notification_manager=s.alert_engine,
        position_tracker=s.position_tracker,
        trade_executor=s.trade_executor,
    )
    return b


async def init_wallet(s: Any) -> Any:
    from payments.wallet import WalletManager
    return WalletManager(session_factory=s.db_session_factory)


async def init_social(s: Any) -> bool:
    from social import copy_trading_engine, marketplace, leaderboard_manager
    s.copy_trading_engine = copy_trading_engine
    s.marketplace = marketplace
    s.leaderboard_manager = leaderboard_manager
    return True


async def init_regime_router(s: Any) -> Any:
    from strategies.regime_router import RegimeRouter
    from strategies.manager import StrategyManager
    sm = s.strategy_brain or StrategyManager(preload_defaults=True)
    return RegimeRouter(sm)


async def init_signal_engine(s: Any) -> Any:
    from core.signal_engine import run_signal_engine
    from api.admin import log_activity
    t = asyncio.create_task(run_signal_engine(s))
    s.background_tasks.append(t)
    log_activity("Signal engine started")
    return t


async def init_reconciler(s: Any) -> Any:
    from core.position_reconciler import PositionReconciler
    from api.admin import log_activity
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


async def init_telegram_bot(s: Any) -> Any:
    from notifications.telegram_bot import init_telegram_bot
    bot = init_telegram_bot(s)
    if bot:
        t = asyncio.create_task(bot.start())
        s.background_tasks.append(t)
        s.telegram_bot = bot
    return bot


async def init_mobile(s: Any, app: Any) -> Any:
    from mobile.api import MobileAPIServer
    from mobile.push_notifications import PushNotificationManager
    mob = MobileAPIServer()
    if hasattr(mob, "router"):
        app.include_router(mob.router, prefix="/api/mobile", tags=["Mobile"])
    elif hasattr(mob, "app"):
        app.mount("/api/mobile", mob.app)
    s.push_notifications = PushNotificationManager()
    return mob


async def init_hyperopt(s: Any, app: Any) -> bool:
    from backtesting.hyperopt import create_hyperopt_router
    app.include_router(create_hyperopt_router())
    return True


# ── Feature-flagged factories ─────────────────────────────────────────────────

async def init_research(s: Any, app: Any, flags: Any) -> Any:
    if not flags.RESEARCH_MODULE:
        return None
    from research import ResearchNotebookEngine, create_research_router
    e = ResearchNotebookEngine()
    app.include_router(create_research_router(e))
    return e


async def init_explainability(s: Any, app: Any, flags: Any) -> Any:
    if not flags.EXPLAINABILITY:
        return None
    from explainability import AIExplainer, create_explainability_router
    e = AIExplainer()
    app.include_router(create_explainability_router(e))
    return e


async def init_transparency(s: Any, app: Any, flags: Any) -> Any:
    if not flags.TRANSPARENCY_REPORTS:
        return None
    from transparency import ExecutionTransparencyEngine, create_transparency_router
    e = ExecutionTransparencyEngine()
    app.include_router(create_transparency_router(e))
    return e


async def init_teams(s: Any, app: Any, flags: Any) -> Any:
    if not flags.TEAMS_MODULE:
        return None
    from teams import TeamManager, create_teams_router
    tm = TeamManager()
    app.include_router(create_teams_router(tm))
    return tm


async def init_nocode(s: Any, app: Any, flags: Any) -> Any:
    if not flags.NOCODE_BUILDER:
        return None
    from nocode import NoCodeStrategyBuilder, create_nocode_router
    nb = NoCodeStrategyBuilder()
    app.include_router(create_nocode_router(nb))
    return nb


async def init_replay(s: Any, app: Any, flags: Any) -> Any:
    if not flags.REPLAY_ENGINE:
        return None
    from replay import ChartReplayEngine, create_replay_router
    re = ChartReplayEngine()
    app.include_router(create_replay_router(re))
    return re


async def init_ml_predictions(s: Any, app: Any, flags: Any) -> Any:
    if not flags.ML_PREDICTIONS:
        return None
    from ml import TechnicalFeatureEngineer, create_ml_router
    fe = TechnicalFeatureEngineer()
    app.include_router(create_ml_router(fe))
    return fe
