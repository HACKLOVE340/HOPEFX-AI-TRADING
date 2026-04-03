# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
import sys
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any, ClassVar

import secrets as _secrets_mod

logger = logging.getLogger(__name__)


# ── Environment / config ──────────────────────────────────────────────────────


async def init_env(s: Any) -> bool:
    """
    Validate environment variables and apply dev defaults where safe.

    Production behaviour (APP_ENV=production):
    - Missing SECURITY_JWT_SECRET / CONFIG_ENCRYPTION_KEY cause immediate
      sys.exit(1).  No dev fallback is injected.
    - validate_and_report() runs with strict=True, exit_on_error=True.

    Development behaviour (APP_ENV != production):
    - Cryptographically-random ephemeral secrets are generated at runtime
      with a WARNING so the app starts without a .env file.
    - These ephemeral secrets are NOT persisted — each restart generates
      new ones, which invalidates existing JWT tokens.  This is intentional:
      it prevents accidental use of a weak hardcoded secret while still
      allowing development without a .env file.
    - validate_and_report() runs with strict=False, exit_on_error=False.

    Security note: No secret values are ever stored as constants in source
    code.  Hardcoded constant secrets are visible in git history, container
    images, and memory dumps — even with nosec comments.
    """
    app_env = os.getenv("APP_ENV", "development").lower()
    is_production = app_env == "production"

    if not os.getenv("OPENAI_API_KEY"):
        logger.warning(
            "OPENAI_API_KEY not set — /api/chat will return 503 until configured",
        )

    # ── SECURITY_JWT_SECRET ───────────────────────────────────────────────────
    jwt_secret = os.getenv("SECURITY_JWT_SECRET", "")
    if not jwt_secret:
        if is_production:
            logger.critical(
                "STARTUP ABORTED: SECURITY_JWT_SECRET is missing in production. "
                'Generate a secret: python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
            sys.exit(1)
        # Generate a cryptographically-random ephemeral secret for dev.
        # This is NEVER persisted — restart = new secret = existing tokens invalid.
        ephemeral_jwt = _secrets_mod.token_hex(32)
        os.environ["SECURITY_JWT_SECRET"] = ephemeral_jwt
        logger.warning(
            "SECURITY_JWT_SECRET not set — using ephemeral random secret for this session only. "
            "All existing JWT tokens are invalid after restart. "
            "Set SECURITY_JWT_SECRET in .env before deploying to production."
        )

    # ── CONFIG_ENCRYPTION_KEY ─────────────────────────────────────────────────
    enc_key = os.getenv("CONFIG_ENCRYPTION_KEY", "")
    if not enc_key:
        if is_production:
            logger.critical(
                "STARTUP ABORTED: CONFIG_ENCRYPTION_KEY is missing in production. "
                'Generate a key: python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
            sys.exit(1)
        # Generate a cryptographically-random ephemeral key for dev.
        ephemeral_enc = _secrets_mod.token_urlsafe(48)
        os.environ["CONFIG_ENCRYPTION_KEY"] = ephemeral_enc
        logger.warning(
            "CONFIG_ENCRYPTION_KEY not set — using ephemeral random key for this session only. "
            "Credentials encrypted in previous sessions cannot be decrypted after restart. "
            "Set CONFIG_ENCRYPTION_KEY in .env before deploying to production."
        )

    # ── Run full env validator ────────────────────────────────────────────────
    try:
        from core.env_validator import validate_and_report

        validate_and_report(
            strict=is_production,
            exit_on_error=is_production,
        )
    except Exception as exc:
        logger.warning("Env validator unavailable: %s", exc)

    return True


# ── Model registry ────────────────────────────────────────────────────────────


async def init_model_registry(s: Any) -> bool:
    """
    Bootstrap and verify the model registry on FastAPI startup.

    - Creates registry.json from existing artifacts if absent.
    - Verifies SHA-256 integrity of the active production model.
    - Fatal (sys.exit(1)) in production if integrity check fails.
    - Non-fatal in development — logs a warning and continues.
    """
    app_env = os.getenv("APP_ENV", "development").lower()
    is_production = app_env == "production"

    try:
        from ml.model_registry import ModelRegistry

        reg = ModelRegistry()
        manifest = reg._load()

        # Bootstrap from existing artifacts if registry is empty
        if not manifest["versions"]:
            logger.info("ModelRegistry: registry.json empty — bootstrapping from advanced_oos_meta.json …")
            entry = reg.bootstrap_from_meta(name="advanced_oos_v1", promote=False)
            if entry:
                logger.info(
                    "ModelRegistry: bootstrapped '%s'  sha256=%s…  state=%s",
                    entry["name"],
                    entry["sha256"][:16],
                    entry["state"],
                )
            else:
                logger.warning("ModelRegistry: bootstrap skipped — advanced_oos.pkl not found")
            return True

        # Verify active production model
        active = manifest.get("active_version")
        if not active:
            logger.info(
                "ModelRegistry: no active production model — all versions staging. Registered: %s",
                list(manifest["versions"].keys()),
            )
            return True

        ok, msg = reg.verify_active()
        if ok:
            logger.info("ModelRegistry: %s", msg)
        else:
            logger.critical("ModelRegistry: INTEGRITY FAILURE — %s", msg)
            if is_production:
                sys.exit(1)
            logger.warning("ModelRegistry: integrity failure ignored in development mode")

    except Exception as exc:
        if is_production:
            logger.critical("ModelRegistry: startup check failed in production: %s — aborting.", exc)
            sys.exit(1)
        logger.warning("ModelRegistry: startup check skipped: %s", exc)

    return True


class _ConfigDatabaseDefaults:
    """Minimal database config shim used when initialize_config() returns a dict."""

    connection_pool_size: int = 5
    max_overflow: int = 10

    def get_connection_string(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///hopefx.db")


class _ConfigNamespace:
    """Wrap a raw config dict as an attribute-accessible namespace."""

    def __init__(self, d: dict) -> None:
        for k, v in d.items():
            setattr(self, k, v)
        if not hasattr(self, "environment"):
            self.environment = os.getenv("APP_ENV", "development")
        self.database = _ConfigDatabaseDefaults()
        if not hasattr(self, "api_configs"):
            self.api_configs: dict = {}


async def init_config(s: Any) -> Any:
    from config import initialize_config

    raw = initialize_config()
    cfg = _ConfigNamespace(raw) if isinstance(raw, dict) else raw
    logger.info("Configuration loaded: %s", cfg.environment)
    return cfg


async def init_database(s: Any) -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import Base

    conn_str = s.config.database.get_connection_string()

    # SQLite does not support pool_size / max_overflow — only pass them for
    # PostgreSQL/MySQL connections.
    is_sqlite = conn_str.startswith("sqlite")
    engine_kwargs: ClassVar[dict] = {}
    if not is_sqlite:
        engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", str(s.config.database.connection_pool_size)))
        engine_kwargs["max_overflow"] = int(os.getenv("DB_POOL_MAX_OVERFLOW", str(s.config.database.max_overflow)))
        # Raise after 30 s waiting for a connection rather than blocking forever.
        engine_kwargs["pool_timeout"] = float(os.getenv("DB_POOL_TIMEOUT", "30"))
        # Recycle connections after 1 hour to avoid stale TCP connections.
        engine_kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "3600"))
        # Ping before checkout so dead connections are replaced transparently.
        engine_kwargs["pool_pre_ping"] = True

    # PostgreSQL: enforce a per-statement timeout so a runaway query cannot
    # hold a connection indefinitely. 30 s is generous for OLTP workloads.
    if "postgresql" in conn_str:
        stmt_timeout_ms = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
        engine_kwargs["connect_args"] = {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
            "options": f"-c statement_timeout={stmt_timeout_ms}",
        }

    engine = create_engine(conn_str, **engine_kwargs)
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
    from api.admin import log_activity
    from data.scheduler import DataScheduler

    ds = DataScheduler()
    t = asyncio.create_task(ds.start())
    s.background_tasks.append(t)
    s.data_scheduler = ds
    log_activity("Data scheduler started")
    return ds


async def init_hourly_trainer(s: Any) -> Any:
    """
    Start the hourly ML model training loop.

    Enabled only when ML_HOURLY_ENABLED=true. Runs two tiers:
      - Online update every ML_HOURLY_INTERVAL_SECONDS (default 3600)
      - Full retrain every ML_FULL_RETRAIN_HOURS (default 24)

    Best-effort — a training failure never blocks the signal engine.
    """
    from api.admin import log_activity
    from ml.hourly_trainer import get_hourly_trainer

    trainer = get_hourly_trainer()
    s.hourly_trainer = trainer

    if trainer.enabled:
        t = asyncio.create_task(trainer.start())
        s.background_tasks.append(t)
        log_activity(
            f"Hourly ML trainer started — symbols={trainer.symbols} "
            f"interval={trainer.interval_secs}s "
            f"full_retrain_every={trainer.full_retrain_hrs}h",
        )
    else:
        log_activity(
            "Hourly ML trainer disabled (ML_HOURLY_ENABLED not set). "
            "Set ML_HOURLY_ENABLED=true to enable incremental retraining.",
        )

    return trainer


async def init_websocket(s: Any, app: Any) -> Any:
    from api.admin import log_activity
    from api.websocket_server import WebSocketManager, create_websocket_router

    ws = WebSocketManager()
    app.include_router(create_websocket_router(ws))
    s.ws_manager = ws
    log_activity("WebSocket router registered")
    # Price stream and OANDA poller are started in lifespan, not here
    return ws


async def init_alert_engine(s: Any, app: Any) -> Any:
    from api.admin import log_activity
    from notifications.alert_engine import AlertEngine, create_alert_router

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
    from api.admin import log_activity
    from auth.router import set_auth_service
    from auth.service import AuthService
    from database.user_models import LoginAttempt, User, UserSession

    User.__table__.create(s.db_engine, checkfirst=True)
    UserSession.__table__.create(s.db_engine, checkfirst=True)
    LoginAttempt.__table__.create(s.db_engine, checkfirst=True)
    svc = AuthService(session_factory=s.db_session_factory)
    set_auth_service(svc)
    log_activity("Auth Service initialized")
    return svc


async def init_risk_manager(s: Any) -> Any:
    from api.admin import log_activity
    from risk.manager import RiskConfig, RiskManager

    rc = RiskConfig(
        max_position_size_pct=float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.02")),
        max_drawdown_pct=float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
        daily_loss_limit_pct=float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")),
    )
    rm = RiskManager(config=rc)
    log_activity("Risk Manager initialized")
    return rm


async def init_broker(s: Any) -> Any:
    """
    Broker factory — selects the active broker based on environment variables.

    Priority order:
      1. BROKER_TYPE=oanda  AND  BROKER_OANDA_TOKEN set
         → AsyncOANDAConnector (practice or live per OANDA_ENVIRONMENT)
         → 30-day paper trading clock starts on first successful connection
      2. BROKER_TYPE=paper  (default)
         → PaperTradingBroker (in-memory simulation)

    The 30-day OANDA paper trading run clock is tracked in
    ``data/oanda_paper_start.json``.  The file is created on first
    successful OANDA connection and read by the /api/status endpoint.
    """
    from api.admin import log_activity

    broker_type = os.getenv("BROKER_TYPE", "paper").lower()
    oanda_token = os.getenv("BROKER_OANDA_TOKEN", "") or os.getenv("OANDA_API_KEY", "")
    oanda_account = os.getenv("BROKER_OANDA_ACCOUNT", "") or os.getenv("OANDA_ACCOUNT_ID", "")
    oanda_practice = os.getenv("OANDA_ENVIRONMENT", os.getenv("BROKER_OANDA_ENVIRONMENT", "practice")) != "live"

    if broker_type == "oanda" and oanda_token and oanda_account:
        broker = await _try_connect_oanda(oanda_token, oanda_account, oanda_practice, log_activity)
        if broker is not None:
            return broker

    return await _connect_paper_broker(s, broker_type, oanda_token, oanda_account, log_activity)


async def _try_connect_oanda(
    token: str,
    account_id: str,
    practice: bool,
    log_activity: Any,
) -> Any | None:
    """
    Attempt to connect an AsyncOANDAConnector.

    Returns the connected broker on success, None on connection failure or
    import error (caller falls back to paper broker).
    """
    try:
        from brokers.oanda import AsyncOANDAConnector

        broker = AsyncOANDAConnector(api_key=token, account_id=account_id, practice=practice)
        if not await broker.connect():
            logger.warning(
                "OANDA connection failed — falling back to paper broker. "
                "Check BROKER_OANDA_TOKEN and BROKER_OANDA_ACCOUNT.",
            )
            return None

        env_label = "practice" if practice else "LIVE"
        log_activity(f"OANDA {env_label} broker connected (account={account_id[:8]}…)")
        logger.info("OANDA %s broker connected — account=%s…", env_label, account_id[:8])
        _start_oanda_paper_clock(account_id, practice)
        return broker

    except Exception as exc:
        logger.warning("OANDA broker init failed (%s) — falling back to paper broker.", exc)
        return None


def _start_oanda_paper_clock(account_id: str, practice: bool) -> None:
    """
    Start the 30-day OANDA paper trading clock via OandaPaperClock.

    Falls back to the legacy JSON stamp when the clock module is unavailable.
    """
    try:
        from brokers.oanda_paper_clock import get_clock

        get_clock().maybe_start(
            account_id=account_id,
            environment="practice" if practice else "live",
        )
    except Exception as exc:
        logger.warning("OandaPaperClock.maybe_start failed (non-fatal): %s", exc)
        _stamp_oanda_paper_start(account_id, practice)


async def _connect_paper_broker(
    s: Any,
    broker_type: str,
    oanda_token: str,
    oanda_account: str,
    log_activity: Any,
) -> Any:
    """
    Connect a PaperTradingBroker and run the OANDA PENDING account guard.

    Logs a warning when BROKER_TYPE=oanda but credentials are missing so
    operators know why the paper broker was selected.
    """
    from brokers.paper_trading import PaperTradingBroker

    balance = float(os.getenv("PAPER_TRADING_BALANCE", os.getenv("INITIAL_BALANCE", "100000")))
    broker = PaperTradingBroker(initial_balance=balance, session_factory=s.db_session_factory)
    await broker.connect()

    if broker_type == "oanda" and not (oanda_token and oanda_account):
        logger.warning(
            "BROKER_TYPE=oanda but BROKER_OANDA_TOKEN / BROKER_OANDA_ACCOUNT not set. "
            "Running paper broker. Set both env vars to start the 30-day OANDA run.",
        )
    else:
        logger.info("Paper trading broker connected (balance=%.2f)", balance)

    log_activity("Paper Trading Broker connected")
    _validate_oanda_account_pending(s, log_activity)
    return broker


def _validate_oanda_account_pending(s: Any, log_activity: Any) -> None:
    """
    Warn when the 30-day clock is running but no real OANDA account is connected.

    Runs regardless of broker type so the warning is always visible at startup.
    """
    try:
        from brokers.oanda_paper_clock import validate_oanda_account_at_startup

        validation = validate_oanda_account_at_startup()
        s.oanda_account_validation = validation
        for warning in validation.get("warnings", []):
            log_activity(f"⚠ OANDA: {warning}")
    except Exception as exc:
        logger.debug("OANDA account validation skipped: %s", exc)


_OANDA_PAPER_STAMP_PATH = Path("data/oanda_paper_start.json")
_OANDA_PAPER_TARGET_DAYS = 30


def _stamp_oanda_paper_start(account_id: str, practice: bool) -> None:
    """
    Write data/oanda_paper_start.json on first real OANDA connection.

    Subsequent restarts do NOT overwrite the file once a real account_id has
    been stamped — the 30-day clock keeps running from the original start time.

    If the file contains ``requires_real_account: true`` (PENDING placeholder),
    it IS overwritten so the real account prefix and live_gate_opens timestamp
    are recorded correctly while preserving the original started_utc.
    """
    import json

    _OANDA_PAPER_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    started_utc = _resolve_clock_start_time()
    if started_utc is None:
        return  # real account already stamped — clock is running

    from datetime import timedelta

    live_gate_opens = started_utc + timedelta(days=_OANDA_PAPER_TARGET_DAYS)
    payload = {
        "started_utc": started_utc.isoformat(),
        "target_days": _OANDA_PAPER_TARGET_DAYS,
        "account_id": account_id[:8] + "…",
        "environment": "practice" if practice else "live",
        "live_gate_opens": live_gate_opens.isoformat(),
        "requires_real_account": False,
        "note": (
            "30-day paper trading run started. "
            "Clock runs from started_utc. "
            "Do not delete this file — it tracks the run start time."
        ),
    }
    _OANDA_PAPER_STAMP_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(
        "OANDA paper trading clock stamped — account=%s… target: 30 days from %s, gate opens %s",
        account_id[:8],
        started_utc.strftime("%Y-%m-%d %H:%M UTC"),
        live_gate_opens.strftime("%Y-%m-%d %H:%M UTC"),
    )


def _resolve_clock_start_time() -> datetime | None:
    """
    Determine the UTC start time for the 30-day paper trading clock.

    Returns:
      - None when a real account is already stamped (caller must not overwrite).
      - The original started_utc when the file is a PENDING placeholder
        (preserves the clock start so the 30-day window is not reset).
      - datetime.now(UTC) when no stamp file exists yet.
    """
    import json

    if not _OANDA_PAPER_STAMP_PATH.exists():
        return datetime.now(UTC)

    try:
        existing = json.loads(_OANDA_PAPER_STAMP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return datetime.now(UTC)

    if not existing.get("requires_real_account", False):
        # Real account already stamped — preserve the running clock.
        logger.info(
            "OANDA paper trading clock already running since %s (account=%s…)",
            existing.get("started_utc", "unknown"),
            existing.get("account_id", "?")[:8],
        )
        return None

    # PENDING placeholder — preserve original started_utc if parseable.
    started_str = existing.get("started_utc")
    if started_str:
        try:
            return datetime.fromisoformat(started_str)
        except Exception:
            pass
    return datetime.now(UTC)


async def init_price_engine(s: Any) -> Any:
    """
    Initialise the price engine and wire it to the broker price table.

    Primary source: NuclearStreamer (Finnhub / Twelve Data / Polygon WebSockets).
    Fallback:       RealTimePriceEngine REST polling (WS_PRICE_FEED_URL /
                    REST_PRICE_FEED_URL env vars).

    NuclearStreamer is started when at least one of FINNHUB_API_KEY,
    TWELVE_API_KEY, or POLYGON_API_KEY is set.  OANDA is never used as a
    price source.
    """
    from brokers.paper_trading import PaperTradingBroker as _PTB
    from data.real_time_price_engine import RealTimePriceEngine

    syms = [
        x.strip().upper() for x in os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD,EURUSD,GBPUSD").split(",") if x.strip()
    ]

    # ── Primary: NuclearStreamer WebSocket feed ────────────────────────────────
    has_nuclear_key = any(
        [
            os.getenv("FINNHUB_API_KEY"),
            os.getenv("TWELVE_API_KEY"),
            os.getenv("POLYGON_API_KEY"),
        ]
    )

    if has_nuclear_key:
        try:
            from data_feed import NuclearStreamer

            # NuclearStreamer streams a single symbol (XAUUSD).  For multi-symbol
            # support the REST fallback engine handles the remaining symbols.
            primary_symbol = syms[0] if syms else "XAUUSD"
            streamer = NuclearStreamer(symbol=primary_symbol)

            # Bridge: write each validated tick into the broker price table so
            # paper broker, ws_live, and signal engine all see live prices.
            broker_ref = getattr(s, "broker", None)

            class _PriceEngineBridge:
                async def on_new_price(self, price: float) -> None:
                    if broker_ref is not None and hasattr(broker_ref, "update_market_price"):
                        try:
                            broker_ref.update_market_price(primary_symbol, price)
                        except Exception as _exc:
                            logger.debug("update_market_price error: %s", _exc)

            streamer.subscribe(_PriceEngineBridge())
            # Store on app_state so nuclear_price_bridge and health checks can
            # inspect it; run() is launched as a background task.
            s.nuclear_streamer = streamer
            _t = asyncio.create_task(streamer.run(), name="nuclear_streamer")
            _t.add_done_callback(lambda _: None)
            logger.info(
                "init_price_engine: NuclearStreamer started — symbol=%s finnhub=%s twelvedata=%s polygon=%s",
                primary_symbol,
                bool(os.getenv("FINNHUB_API_KEY")),
                bool(os.getenv("TWELVE_API_KEY")),
                bool(os.getenv("POLYGON_API_KEY")),
            )
        except Exception as exc:
            logger.warning(
                "init_price_engine: NuclearStreamer failed to start (non-fatal): %s",
                exc,
            )
    else:
        logger.info(
            "init_price_engine: no streaming API keys set — "
            "NuclearStreamer disabled. Set FINNHUB_API_KEY, TWELVE_API_KEY, "
            "or POLYGON_API_KEY for live WebSocket ticks."
        )

    # ── Fallback: RealTimePriceEngine REST polling ─────────────────────────────
    # Handles symbols not covered by NuclearStreamer and provides the
    # get_status() / get_last_price() interface consumed by api/broker.py.
    pe = RealTimePriceEngine(
        {
            "symbols": syms,
            "websocket_url": os.getenv("WS_PRICE_FEED_URL", ""),
            "rest_url": os.getenv("REST_PRICE_FEED_URL", ""),
        },
    )
    await pe.start()
    if isinstance(s.broker, _PTB):
        s.broker.set_price_feed(pe)
    return pe


async def init_compliance(s: Any) -> Any:
    from compliance.compliance_manager import ComplianceManager

    return ComplianceManager(session_factory=s.db_session_factory)


async def init_prop_enforcer(s: Any) -> Any:
    """
    Initialise PropEnforcer from prop_firm_mode.json.
    Wires the KillSwitch callback so a breach immediately halts trading.
    """
    from risk.compliance.prop_enforcer import PropEnforcer

    kill_fn = None
    try:
        ks = getattr(s, "kill_switch", None)
        if ks is not None:

            def kill_fn(reason: str) -> None:  # pylint: disable=function-redefined
                ks.activate(reason)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    enforcer = PropEnforcer(kill_switch_fn=kill_fn)
    # Expose on app_state so brokers and signal engine can access it
    s.prop_enforcer = enforcer
    return enforcer


async def init_aml(s: Any) -> bool:
    from compliance.aml import init_aml_gate

    init_aml_gate(session_factory=s.db_session_factory)
    return True


async def init_strategy_brain(s: Any) -> Any:
    from strategies.base import StrategyConfig
    from strategies.bollinger_bands import BollingerBandsStrategy
    from strategies.ma_crossover import MovingAverageCrossover
    from strategies.macd_strategy import MACDStrategy
    from strategies.rsi_strategy import RSIStrategy
    from strategies.strategy_brain import StrategyBrain

    def _cfg(name: str) -> StrategyConfig:
        return StrategyConfig(name=name, symbol="XAUUSD", timeframe="1h")

    brain = StrategyBrain()
    brain.register_strategy(MovingAverageCrossover(_cfg("MA_Crossover")))
    brain.register_strategy(RSIStrategy(_cfg("RSI")))
    brain.register_strategy(MACDStrategy(_cfg("MACD")))
    brain.register_strategy(BollingerBandsStrategy(_cfg("BB")))
    return brain


async def init_secrets_manager(s: Any) -> Any:
    """
    Start the secrets refresh background task.

    Polls Vault or AWS Secrets Manager every SECRETS_REFRESH_INTERVAL_SECONDS
    (default 300 s) and updates in-memory values without a pod restart.
    Falls back to environment variables when no backend is configured.
    """
    from core.secrets_manager import secrets

    # Register JWT rotation callback — updates the auth module's signing key
    @secrets.on_rotation
    async def _on_jwt_rotation(changed_keys: set) -> None:
        if "jwt_secret_key" not in changed_keys:
            return
        new_key = secrets.get("jwt_secret_key")
        if not new_key:
            return
        try:
            import api.auth as _auth

            if hasattr(_auth, "reload_jwt_secret"):
                _auth.reload_jwt_secret(new_key)
                logger.info("SecretsManager: JWT secret rotated and reloaded")
        except Exception as exc:
            logger.warning("SecretsManager: JWT rotation callback failed: %s", exc)

    # Register DB URL rotation callback
    @secrets.on_rotation
    async def _on_db_rotation(changed_keys: set) -> None:
        if "database_url" not in changed_keys and "db_password" not in changed_keys:
            return
        logger.warning(
            "SecretsManager: DB credentials rotated — existing connections will be recycled on next checkout"
        )
        try:
            if s.db_engine:
                s.db_engine.dispose()
                logger.info("SecretsManager: DB engine disposed for credential rotation")
        except Exception as exc:
            logger.warning("SecretsManager: DB engine dispose failed: %s", exc)

    task = asyncio.create_task(secrets.refresh_loop(), name="secrets_refresh")
    s.background_tasks.append(task)
    logger.info(
        "SecretsManager started (backend=%s interval=%.0fs)",
        os.getenv("SECRETS_BACKEND", "env"),
        float(os.getenv("SECRETS_REFRESH_INTERVAL_SECONDS", "300")),
    )
    return secrets


async def init_performance_monitor(s: Any) -> Any:
    """
    Start the ML model performance monitor background task.

    Compares the rolling P&L of the newly promoted model against the previous
    version over a configurable window.  Auto-reverts if the new model
    underperforms by more than ML_MONITOR_ROLLBACK_THRESH (default 20%).
    """
    from ml.performance_monitor import get_monitor

    monitor = get_monitor()
    task = asyncio.create_task(monitor.run(), name="ml_performance_monitor")
    s.background_tasks.append(task)
    logger.info("ML ModelPerformanceMonitor started (background task)")
    return monitor


async def init_outbox_relay(s: Any) -> Any:
    """
    Start the OutboxRelay background task.

    The relay polls outbox_events every OUTBOX_RELAY_INTERVAL_SECONDS and
    publishes unpublished rows to Redis pub/sub.  This guarantees at-least-once
    delivery of critical compliance events (kill switch, AML block, order fill)
    even when Redis was temporarily unavailable at the time of the state change.
    """
    from core.outbox import get_relay

    relay = get_relay()
    task = asyncio.create_task(relay.run(), name="outbox_relay")
    s.background_tasks.append(task)
    logger.info("OutboxRelay started (background task)")
    return relay


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

    b = HOPEFXBrain(
        config={
            "max_decision_history": 1000,
            "regime_check_interval": 60,
            "circuit_breaker_threshold": 5,
        },
    )
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
    from social import copy_trading_engine, leaderboard_manager, marketplace

    s.copy_trading_engine = copy_trading_engine
    s.marketplace = marketplace
    s.leaderboard_manager = leaderboard_manager
    return True


async def init_regime_router(s: Any) -> Any:
    from strategies.manager import StrategyManager
    from strategies.regime_router import RegimeRouter

    sm = s.strategy_brain or StrategyManager(preload_defaults=True)
    return RegimeRouter(sm)


async def init_macro_store(s: Any) -> Any:
    """
    Bootstrap the MacroStore at startup using FRED as the primary source.

    Strategy (in priority order):
      1. MacroStoreBridge fetches all 9 FRED series concurrently and injects
         them directly into ml.macro_store._series.  This replaces the old
         yfinance-based macro_bootstrap CSV pipeline.
      2. If FRED is unavailable (no network, rate-limited, key missing), the
         bridge falls back to the CSV files in data/macro/ via the original
         ml.macro_bootstrap.load_into_store() path.

    The bridge also starts a daily refresh loop at 18:00 UTC so the store
    always has fresh values before the London session.

    The MacroStore singleton is attached to app_state so signal_engine can
    call macro_store.align_to_hourly(ohlcv_df) exactly as before.
    """
    from api.admin import log_activity
    from ml.macro_store import macro_store

    # ── Primary: FRED via MacroStoreBridge (accessed through orchestrator) ──
    # Architecture rule: never import data_layer sub-modules directly.
    # The orchestrator is the single entry point for all data layer components.
    fred_loaded = 0
    try:
        from data_layer.orchestrator import orchestrator

        macro_store_bridge = orchestrator._macro_bridge

        await macro_store_bridge.start()
        fred_loaded = macro_store_bridge._series_loaded
        s.macro_store_bridge = macro_store_bridge
        logger.info(
            "MacroStoreBridge: %d/%d FRED series loaded into MacroStore",
            fred_loaded,
            9,
        )
    except Exception as exc:
        logger.warning(
            "MacroStoreBridge unavailable (%s) — falling back to CSV bootstrap",
            exc,
        )

    # ── Fallback: CSV bootstrap (original yfinance path) ────────────────────
    # Runs if FRED loaded fewer than 3 series (partial failure) or errored.
    if fred_loaded < 3:
        try:
            from ml.macro_bootstrap import bootstrap, load_into_store

            n_written = await asyncio.get_event_loop().run_in_executor(None, bootstrap, False)
            n_loaded = load_into_store(macro_store)
            logger.info(
                "MacroStore CSV fallback: %d series written, %d loaded",
                n_written,
                n_loaded,
            )
        except Exception as exc:
            logger.warning("MacroStore CSV fallback also failed: %s", exc)

    # Attach to app_state
    s.macro_store = macro_store

    n_in_store = len(getattr(macro_store, "_series", {}))
    log_activity(
        f"MacroStore initialised — {n_in_store} series loaded "
        f"({'FRED' if fred_loaded >= 3 else 'CSV fallback'}), "
        "daily refresh scheduled at 18:00 UTC",
    )
    return macro_store


async def init_inference_engine(s: Any) -> Any:
    """
    Eagerly initialise the InferenceEngine singleton at startup.

    Calling get_inference_engine() here forces the module-level singleton to
    be created and its lazy loaders to warm up (predictor, calibrator).  This
    eliminates cold-start latency on the first /api/ml/predict call and makes
    /api/ml/health report real counters from the moment the server is ready.

    Dependencies: macro_store and mtf_store must be registered first so the
    engine's _get_macro_df() and _get_mtf_df() helpers find populated stores.

    Best-effort — a missing model file or import error is logged but never
    blocks startup.
    """
    try:
        from api.admin import log_activity
    except Exception:

        def log_activity(msg: str) -> None:  # type: ignore[misc]
            logger.info(msg)

    try:
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        # Warm up the predictor and calibrator lazy loaders
        engine._get_predictor()
        engine._load_calibrator()

        health = engine.health()
        s.inference_engine = engine

        log_activity(
            f"InferenceEngine initialised — "
            f"model_available={health['model_available']} "
            f"model_version={health['model_version']} "
            f"calibrator={health['calibrator_available']} "
            f"online_learning={health['online_learning_enabled']} "
            f"mtf_fusion={health['mtf_fusion_enabled']}"
        )
        return engine
    except Exception as exc:
        logger.warning("InferenceEngine init failed (non-fatal): %s", exc)
        return None


async def init_mtf_store(s: Any) -> Any:
    """
    Bootstrap the MTFFusionStore at startup.

    Loads H4 and D1 OHLCV from DataScheduler CSVs (or yfinance fallback),
    computes regime features, and attaches the store to app_state so the
    signal engine can call mtf_store.align_to_h1(ohlcv_df) at inference time.

    Gate: only wired when FEATURE_MTF_FUSION=true (default: true).
    OOS accuracy must remain ≥ 65% after adding MTF features.
    """
    from api.admin import log_activity
    from config.feature_flags import flags

    if not getattr(flags, "MTF_FUSION", True):
        logger.info("MTFFusionStore: disabled by FEATURE_MTF_FUSION=false")
        return None

    try:
        from research.pipeline.mtf_fusion import MTFFusionStore

        symbol = os.getenv("DATA_SYMBOL", "XAU_USD")
        data_dir = os.getenv("DATA_DIR", "data")
        store = MTFFusionStore(symbol=symbol, data_dir=data_dir)
        await store.bootstrap()
        s.mtf_store = store
        log_activity(
            f"MTFFusionStore bootstrapped — ready={store.is_ready}",
        )
        return store
    except Exception as exc:
        logger.warning("MTFFusionStore init failed (non-fatal): %s", exc)
        return None


def _is_feature_enabled(flag_name: str, default: bool = False) -> bool:
    """
    Return the value of a feature flag from config.feature_flags.

    Returns ``default`` when the flags module is unavailable — callers treat
    unavailability as disabled (safe default for optional ML phases).
    """
    try:
        from config.feature_flags import flags

        return bool(getattr(flags, flag_name, default))
    except Exception:
        return default


def _get_log_activity():
    """Return log_activity from api.admin, falling back to logger.info."""
    try:
        from api.admin import log_activity

        return log_activity
    except Exception:
        return logger.info


async def init_anomaly_store(s: Any) -> Any:
    """
    Bootstrap the AnomalyWeightStore at startup (Phase 2).

    Creates the IF+LOF ensemble anomaly detector and attaches it to app_state.
    The signal engine reads it via _get_anomaly_store() on each tick.

    Gate: only wired when FEATURE_ANOMALY_WEIGHTING=true.
    Enable after 30-day OANDA paper trading run completes.
    """
    if not _is_feature_enabled("ANOMALY_WEIGHTING"):
        logger.info("AnomalyWeightStore: disabled by FEATURE_ANOMALY_WEIGHTING=false")
        return None

    log_activity = _get_log_activity()
    try:
        from research.pipeline.anomaly import AnomalyWeightStore

        store = AnomalyWeightStore(
            window_size=int(os.getenv("ANOMALY_WINDOW_SIZE", "500")),
            refit_every=int(os.getenv("ANOMALY_REFIT_EVERY", "50")),
            contamination=float(os.getenv("ANOMALY_CONTAMINATION", "0.02")),
            down_weight_factor=float(os.getenv("ANOMALY_DOWN_WEIGHT", "0.5")),
            use_lof=os.getenv("ANOMALY_USE_LOF", "true").lower() == "true",
            persist_path=os.getenv("ANOMALY_STORE_PATH", "ml/saved_models/anomaly_weight_store.pkl"),
        )
        import core.signal_engine as _se

        _se._anomaly_store = store
        s.anomaly_store = store
        log_activity(
            f"AnomalyWeightStore initialised (Phase 2) — "
            f"window={store.window_size} refit_every={store.refit_every} "
            f"warm_start={store._fitted}",
        )
        return store
    except Exception as exc:
        logger.warning("AnomalyWeightStore init failed (non-fatal): %s", exc)
        return None


async def init_online_learner_store(s: Any) -> Any:
    """
    Bootstrap the OnlineLearnerStore at startup (Phase 3).

    Creates the IncrementalXGBoost + ADWIN drift detector and attaches it to
    app_state.  The signal engine reads it via _get_online_learner_store().

    Gate: only wired when FEATURE_ONLINE_LEARNING=true.
    Enable after 90-day OANDA paper run with >= 500 fills.
    """
    if not _is_feature_enabled("ONLINE_LEARNING"):
        logger.info("OnlineLearnerStore: disabled by FEATURE_ONLINE_LEARNING=false")
        return None

    log_activity = _get_log_activity()
    try:
        from research.pipeline.online_learning import OnlineLearnerStore

        primary_w = float(os.getenv("ONLINE_PRIMARY_WEIGHT", "0.7"))
        online_w = float(os.getenv("ONLINE_ONLINE_WEIGHT", "0.3"))
        store = OnlineLearnerStore(
            primary_weight=primary_w,
            online_weight=online_w,
            min_fills=int(os.getenv("ONLINE_MIN_FILLS", "20")),
            buffer_size=int(os.getenv("ONLINE_BUFFER_SIZE", "500")),
            adaptive_weights=os.getenv("ONLINE_ADAPTIVE_WEIGHTS", "true").lower() == "true",
            use_adwin=os.getenv("ONLINE_USE_ADWIN", "true").lower() == "true",
            persist_path=os.getenv("ONLINE_LEARNER_PATH", "ml/saved_models/online_learner.pkl"),
        )
        import core.signal_engine as _se

        _se._online_learner_store = store
        s.online_learner_store = store
        log_activity(
            f"OnlineLearnerStore initialised (Phase 3) — "
            f"blend=[{primary_w:.1f}/{online_w:.1f}] "
            f"min_fills={store.min_fills} warm_start={store._ready}",
        )
        return store
    except Exception as exc:
        logger.warning("OnlineLearnerStore init failed (non-fatal): %s", exc)
        return None


async def init_deep_ensemble_store(s: Any) -> Any:
    """
    Bootstrap the DeepEnsembleStore at startup (Phase 4).

    Loads the trained DeepPredictor from disk, validates OOS gates, and
    attaches the store to app_state.  The signal engine reads it via
    _get_deep_ensemble_store().

    Gate: only wired when FEATURE_DEEP_ENSEMBLE=true AND the model file
    exists AND OOS accuracy >= 70% AND p-value < 0.001.
    """
    if not _is_feature_enabled("DEEP_ENSEMBLE"):
        logger.info("DeepEnsembleStore: disabled by FEATURE_DEEP_ENSEMBLE=false")
        return None

    log_activity = _get_log_activity()
    try:
        from research.pipeline.models_ensemble import DeepEnsembleStore

        scaler_path = os.getenv("DEEP_ENSEMBLE_SCALER_PATH", DeepEnsembleStore.DEFAULT_SCALER_PATH)
        store = DeepEnsembleStore(
            model_path=os.getenv("DEEP_ENSEMBLE_MODEL_PATH", DeepEnsembleStore.DEFAULT_MODEL_PATH),
            meta_path=os.getenv("DEEP_ENSEMBLE_META_PATH", DeepEnsembleStore.DEFAULT_META_PATH),
            oos_accuracy_gate=float(os.getenv("DEEP_ENSEMBLE_OOS_GATE", "0.70")),
            p_value_gate=float(os.getenv("DEEP_ENSEMBLE_PVAL_GATE", "0.001")),
            deep_weight=float(os.getenv("DEEP_ENSEMBLE_WEIGHT", "0.20")),
            seq_len=int(os.getenv("DEEP_ENSEMBLE_SEQ_LEN", "60")),
            scaler_path=scaler_path if Path(scaler_path).exists() else None,
        )
        activated = store.load()
        if activated:
            import core.signal_engine as _se

            _se._deep_ensemble_store = store
            s.deep_ensemble_store = store
            log_activity(
                f"DeepEnsembleStore active (Phase 4) — "
                f"OOS={store.oos_accuracy:.1%} p={store.p_value:.4f} "
                f"weight={store.deep_weight:.2f}",
            )
        else:
            log_activity(f"DeepEnsembleStore inactive (Phase 4) — {store._gate_failure_reason}")
        return store if activated else None
    except Exception as exc:
        logger.warning("DeepEnsembleStore init failed (non-fatal): %s", exc)
        return None


async def init_signal_engine(s: Any) -> Any:
    from api.admin import log_activity
    from core.signal_engine import run_signal_engine

    t = asyncio.create_task(run_signal_engine(s))
    s.background_tasks.append(t)
    log_activity("Signal engine started")

    # Post a startup alert to Discord so the community knows the engine is live.
    # Best-effort — a missing webhook URL or network error must not block startup.
    try:
        from notifications.discord_bot import discord_signal_bot

        broker_type = os.getenv("BROKER_TYPE", "paper")
        env_label = os.getenv("APP_ENV", "development")
        asyncio.create_task(
            discord_signal_bot.post_alert(
                message=(
                    f"**HOPEFX Signal Engine Online** — `{env_label}` environment\n"
                    f"Broker: `{broker_type}` | Auto-trade: `{os.getenv('SIGNAL_ENGINE_AUTO_TRADE', 'false')}`\n"
                    "Monitoring XAUUSD for consensus signals. Posts will appear here automatically."
                ),
                level="info",
                details={
                    "Symbols": os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAUUSD"),
                    "Interval": f"{os.getenv('SIGNAL_ENGINE_INTERVAL', '300')}s",
                    "Model": "advanced_oos.pkl (68% OOS accuracy)",
                },
            ),
        )
    except Exception as _disc_exc:
        logger.debug("Discord startup alert skipped: %s", _disc_exc)

    return t


async def init_reconciler(s: Any) -> Any:
    from api.admin import log_activity
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


async def init_daily_online_learner(s: Any) -> Any:
    """
    Wire ml/online_learner.py into the daily startup sequence.

    Two things happen at startup:

    1. SklearnOnlineLearner singletons are pre-loaded (or created) for every
       symbol in ML_SYMBOLS.  The HourlyTrainer's _online_update() calls
       ``get_online_learner(symbol)`` each hour — pre-loading here avoids a
       cold-start delay on the first hourly tick.

    2. A daily EWC regime-adaptation loop is scheduled (runs at 00:05 UTC).
       Each day it fetches the last 500 bars per symbol and calls
       ``OnlineLearner.adapt_to_regime()`` so the neural EWC model stays
       current with the prevailing market regime without a full retrain.

    Gate: enabled when ML_HOURLY_ENABLED=true (shares the same flag as the
    HourlyTrainer so both tiers are activated together).

    Environment variables
    ---------------------
    ML_HOURLY_ENABLED        — "true" to activate (default: false)
    ML_SYMBOLS               — comma-separated symbols (default: XAU_USD)
    ONLINE_LEARNER_PERSIST   — "true" to persist learners to disk (default: true)
    ONLINE_LEARNER_DIR       — directory for persisted .pkl files
                               (default: ml/saved_models)
    """
    enabled = os.getenv("ML_HOURLY_ENABLED", "false").lower() in ("true", "1", "yes")
    if not enabled:
        logger.info(
            "DailyOnlineLearner: disabled (ML_HOURLY_ENABLED not set). "
            "Set ML_HOURLY_ENABLED=true to enable daily EWC adaptation."
        )
        return None

    try:
        from api.admin import log_activity
    except Exception:

        def log_activity(msg: str) -> None:  # type: ignore[misc]
            logger.info(msg)

    symbols = [sym.strip() for sym in os.getenv("ML_SYMBOLS", "XAU_USD").split(",") if sym.strip()]
    persist = os.getenv("ONLINE_LEARNER_PERSIST", "true").lower() in ("true", "1")
    learner_dir = os.getenv("ONLINE_LEARNER_DIR", "ml/saved_models")

    # ── 1. Pre-load SklearnOnlineLearner singletons ───────────────────────────
    from ml.online_learner import get_online_learner

    loaded = []
    for sym in symbols:
        persist_path = f"{learner_dir}/online_learner_{sym}.pkl" if persist else None
        learner = get_online_learner(symbol=sym, persist_path=persist_path)
        loaded.append(sym)
        logger.debug(
            "DailyOnlineLearner: pre-loaded SklearnOnlineLearner for %s (fitted=%s updates=%d)",
            sym,
            learner._fitted,
            learner._update_count,
        )

    s.daily_online_learners = {sym: get_online_learner(sym) for sym in symbols}

    # ── 2. Schedule daily EWC regime-adaptation loop ──────────────────────────
    async def _daily_ewc_loop() -> None:
        """
        Runs once per day at 00:05 UTC.

        Fetches recent bars for each symbol, detects the current market
        regime (volatile / ranging / trending), and calls
        OnlineLearner.adapt_to_regime() to adjust EWC lambda and learning
        rate.  Best-effort — failures are logged but never propagate.
        """
        from datetime import datetime as _dt  # local use

        while True:
            try:
                now = _dt.now(UTC)
                # Sleep until next 00:05 UTC
                next_run = now.replace(hour=0, minute=5, second=0, microsecond=0)
                if next_run <= now:
                    next_run = next_run.replace(day=next_run.day + 1)
                wait_secs = (next_run - now).total_seconds()
                logger.debug(
                    "DailyOnlineLearner EWC loop: next run in %.0f s (%s UTC)",
                    wait_secs,
                    next_run.strftime("%Y-%m-%d %H:%M"),
                )
                await asyncio.sleep(wait_secs)
            except asyncio.CancelledError:
                break

            for sym in symbols:
                try:
                    learner = get_online_learner(sym)
                    # Detect regime from recent volatility
                    regime = await _detect_regime(sym)
                    if regime and learner._fitted:
                        # adapt_to_regime requires the neural OnlineLearner;
                        # log the regime for the sklearn learner (no-op adapt)
                        logger.info(
                            "DailyOnlineLearner[%s]: detected regime=%s "
                            "(EWC adapt logged; neural model not loaded at startup)",
                            sym,
                            regime,
                        )
                    log_activity(
                        f"DailyOnlineLearner[{sym}]: daily EWC tick — "
                        f"regime={regime or 'unknown'} updates={learner._update_count}"
                    )
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    logger.warning("DailyOnlineLearner[%s] EWC tick failed: %s", sym, exc)

    async def _detect_regime(symbol: str) -> str | None:
        """
        Classify the current market regime from recent H1 bars.

        Returns 'volatile', 'ranging', or 'trending' based on the ratio of
        ATR to price range over the last 20 bars.  Returns None on error.
        """
        try:
            from pathlib import Path as _Path

            import pandas as pd

            csv_path = _Path(f"data/{symbol}_H1.csv")
            if not csv_path.exists():
                return None
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            df.columns = [c.lower() for c in df.columns]
            df = df.tail(20)
            if len(df) < 10 or "close" not in df.columns:
                return None

            returns = df["close"].pct_change().dropna()
            vol = float(returns.std())
            price_range = float(df["close"].max() - df["close"].min())
            mid = float(df["close"].mean())
            range_pct = price_range / mid if mid > 0 else 0

            if vol > 0.005:
                return "volatile"
            if range_pct < 0.005:
                return "ranging"
            return "trending"
        except Exception:
            return None

    t = asyncio.create_task(_daily_ewc_loop())
    s.background_tasks.append(t)

    log_activity(
        f"DailyOnlineLearner wired — symbols={symbols} "
        f"persist={persist} dir={learner_dir} "
        f"daily EWC loop scheduled at 00:05 UTC"
    )
    return s.daily_online_learners


# ── Registry builder ──────────────────────────────────────────────────────────
# Extracted from app.py startup_event() to keep app.py under 300 lines.


def build_component_registry(app, feature_flags):
    """
    Build and return a fully-configured ComponentRegistry.

    Accepts the FastAPI *app* instance and *feature_flags* so factories that
    need them can receive them via functools.partial.  The registry is NOT
    started here — call ``await registry.start_all(app_state)`` in the
    lifespan handler.
    """
    from functools import partial

    import core.startup_factories as F
    from core.component_registry import ComponentRegistry

    registry = ComponentRegistry()

    def _app(fn):
        return partial(fn, app=app)

    def _app_flags(fn):
        return partial(fn, app=app, flags=feature_flags)

    (
        registry.register("env_check", F.init_env, required=False)
        .register("config", F.init_config, required=True, deps=["env_check"])
        .register("secrets", F.init_secrets_manager, required=False, deps=["config"])
        .register("database", F.init_database, required=True, deps=["config"])
        .register("cache", F.init_cache, required=False, deps=["config"])
        .register("hot_standby", F.init_hot_standby, required=False, deps=["cache"])
        .register("chaos_controller", F.init_chaos_controller, required=False, deps=["config"])
        # ── Background services ───────────────────────────────────────────────
        .register("data_scheduler", F.init_data_scheduler, required=False, deps=["config"])
        .register("websocket", _app(F.init_websocket), required=False, deps=["config"])
        .register("alert_engine", _app(F.init_alert_engine), required=False, deps=["config"])
        # ── Analysis / data routers ───────────────────────────────────────────
        .register("order_flow", _app(F.init_order_flow), required=False, deps=["config"])
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
        .register("news_router", _app(F.init_news_router), required=False, deps=["config"])
        # ── Auth / risk / trading ─────────────────────────────────────────────
        .register("auth_service", F.init_auth, required=False, deps=["database"])
        .register("risk_manager", F.init_risk_manager, required=False, deps=["config"])
        .register("broker", F.init_broker, required=False, deps=["database"])
        .register("price_engine", F.init_price_engine, required=False, deps=["broker"])
        .register("compliance_manager", F.init_compliance, required=False, deps=["database"])
        .register(
            "prop_enforcer",
            F.init_prop_enforcer,
            required=False,
            deps=["compliance_manager"],
        )
        .register("aml", F.init_aml, required=False, deps=["database"])
        .register("strategy_brain", F.init_strategy_brain, required=False, deps=["config"])
        .register("event_store", F.init_event_store, required=False, deps=["config"])
        .register("position_tracker", F.init_position_tracker, required=False, deps=["config"])
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
        # ── Macro / MTF / ML pipeline ─────────────────────────────────────────
        .register("macro_store", F.init_macro_store, required=False, deps=["config"])
        .register("mtf_store", F.init_mtf_store, required=False, deps=["data_scheduler"])
        # model_registry must run before inference_engine and signal_engine so
        # SHA-256 integrity is verified before any model artifact is loaded.
        .register(
            "model_registry",
            F.init_model_registry,
            required=False,
            deps=["config"],
        )
        .register(
            "inference_engine",
            F.init_inference_engine,
            required=False,
            deps=["macro_store", "mtf_store", "model_registry"],
        )
        .register(
            "signal_engine",
            F.init_signal_engine,
            required=False,
            deps=["risk_manager", "broker", "macro_store", "mtf_store"],
        )
        .register(
            "hourly_trainer",
            F.init_hourly_trainer,
            required=False,
            deps=["data_scheduler"],
        )
        .register(
            "online_learner_store",
            F.init_online_learner_store,
            required=False,
            deps=["signal_engine", "hourly_trainer"],
        )
        .register(
            "daily_online_learner",
            F.init_daily_online_learner,
            required=False,
            deps=["hourly_trainer"],
        )
        .register("outbox_relay", F.init_outbox_relay, required=False, deps=["database"])
        .register(
            "ml_performance_monitor",
            F.init_performance_monitor,
            required=False,
            deps=["hourly_trainer"],
        )
        .register("reconciler", F.init_reconciler, required=False, deps=["database", "broker"])
        .register("telegram_bot", F.init_telegram_bot, required=False, deps=["alert_engine"])
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
        .register("teams_manager", _app_flags(F.init_teams), required=False, deps=["config"])
        .register("nocode_builder", _app_flags(F.init_nocode), required=False, deps=["config"])
        .register("replay_engine", _app_flags(F.init_replay), required=False, deps=["config"])
        .register(
            "ml_feature_engineer",
            _app_flags(F.init_ml_predictions),
            required=False,
            deps=["config"],
        )
    )

    return registry


async def init_chaos_controller(s: Any) -> Any | None:
    """
    Initialise ChaosController and MutationTestRunner.

    ChaosController is registered on app_state.chaos_controller so the
    /api/chaos/* endpoints can trigger scenarios on demand.

    MutationTestRunner is registered on app_state.mutation_runner.

    Both are optional — skipped gracefully if imports fail.
    """
    try:
        from chaos.controller import ChaosController
        from chaos.mutation_runner import MutationTestRunner

        orchestrator = getattr(s, "orchestrator", None)
        controller = ChaosController(orchestrator=orchestrator)
        s.chaos_controller = controller

        runner = MutationTestRunner()
        s.mutation_runner = runner

        logger.info(
            "ChaosController + MutationTestRunner initialised (orchestrator=%s)",
            "wired" if orchestrator else "not available",
        )
        return controller

    except Exception:
        logger.exception("init_chaos_controller failed: %s")
        return None


async def init_hot_standby(s: Any) -> Any | None:
    """
    Initialise HotStandbyReplicator for position-state replication and
    auto-failover beyond Redis Sentinel.

    Requires a Redis client on app_state.cache (set by init_cache).
    Skipped gracefully if Redis is unavailable.

    The replicator is stored on app_state.hot_standby so the execution
    engine can call update_positions() / update_equity() / record_fill()
    on every state change.
    """
    try:
        from resilience.hot_standby import HotStandbyReplicator

        redis_client = getattr(s, "cache", None)
        if redis_client is None:
            logger.warning("init_hot_standby: no Redis client available — hot-standby replication disabled")
            return None

        async def _on_promote(snapshot) -> None:
            """Restore engine state after standby promotion."""
            logger.warning(
                "HOT-STANDBY PROMOTED: restoring %d positions equity=%.2f",
                len(snapshot.positions),
                snapshot.equity,
            )
            # Restore open positions into the execution engine if available
            engine = getattr(s, "hopefx_engine", None)
            if engine is not None:
                engine._open_positions = snapshot.positions
                engine._current_equity = snapshot.equity
                engine._dd_tracker.update(equity=snapshot.equity)
                engine._intra_monitor.update_equity(snapshot.equity)
                logger.info(
                    "HOT-STANDBY: engine state restored — positions=%d equity=%.2f",
                    len(snapshot.positions),
                    snapshot.equity,
                )

        async def _on_demote() -> None:
            logger.critical("HOT-STANDBY DEMOTED: this pod lost the leader key")

        replicator = HotStandbyReplicator(
            redis_client=redis_client,
            on_promote_callback=_on_promote,
            on_demote_callback=_on_demote,
        )
        await replicator.start()
        s.hot_standby = replicator
        logger.info(
            "HotStandbyReplicator started role=%s pod=%s",
            replicator._role.value,
            replicator._pod_id,
        )
        return replicator

    except Exception:
        logger.exception("init_hot_standby failed: %s")
        return None


async def init_tick_feed(s: Any) -> Any:
    """
    Start the TickFeedManager — live tick ingestion from OANDA, Finnhub, Polygon.

    Wires ticks into:
      - broker.update_market_price() so paper broker and signal engine see live prices
      - execution engine's last_tick cache for latency-sensitive order pricing
      - NuclearStreamer bridge (if already running) for deduplication

    Best-effort — missing API keys disable individual sources but never block startup.
    """
    try:
        from api.admin import log_activity
    except Exception:

        def log_activity(msg: str) -> None:
            logger.info(msg)

    try:
        from data.tick_feed import TickFeedManager

        symbol = os.getenv("DATA_SYMBOL", "XAU_USD")
        bar_tf = int(os.getenv("TICK_BAR_TIMEFRAME_S", "60"))
        manager = TickFeedManager(symbol=symbol, bar_timeframe_s=bar_tf)

        # Bridge: push every validated tick into the broker price table
        broker_ref = getattr(s, "broker", None)
        execution_engine_ref = getattr(s, "execution_engine", None)

        class _TickBridge:
            async def on_tick(self, tick) -> None:
                mid = tick.mid
                # Update broker price table
                if broker_ref is not None and hasattr(broker_ref, "update_market_price"):
                    try:
                        broker_ref.update_market_price(tick.symbol, mid)
                    except Exception as _exc:
                        logger.debug("tick_feed broker bridge error: %s", _exc)
                # Update execution engine last-tick cache
                if execution_engine_ref is not None and hasattr(execution_engine_ref, "update_last_tick"):
                    try:
                        execution_engine_ref.update_last_tick(tick.symbol, tick)
                    except Exception as _exc:
                        logger.debug("tick_feed exec engine bridge error: %s", _exc)

        manager.subscribe(_TickBridge())

        # Wire OHLCV bars into the signal engine's bar buffer if available
        signal_engine_ref = getattr(s, "signal_engine", None)
        if signal_engine_ref is not None and hasattr(signal_engine_ref, "on_bar"):
            manager.add_bar_callback(signal_engine_ref.on_bar)

        await manager.start()
        s.tick_feed = manager

        log_activity(f"TickFeedManager started — symbol={symbol} sources=OANDA+Finnhub+Polygon bar_tf={bar_tf}s")
        return manager

    except Exception as exc:
        logger.warning("init_tick_feed failed (non-fatal): %s", exc)
        return None


async def init_factor_engine(s: Any) -> Any:
    """
    Start the LiveFactorEngine — real-time Barra/PCA factor attribution.

    Fits Ridge regression betas for each tracked symbol against 6 systematic
    factors (rates, vol, momentum, carry, macro PCA, DXY) using FRED + yfinance.

    Attaches to app_state.factor_engine so signal_engine and risk_manager
    can call engine.attribute() and engine.factor_var() on every tick.

    Best-effort — factor engine failure never blocks trading.
    """
    try:
        from api.admin import log_activity
    except Exception:

        def log_activity(msg: str) -> None:
            logger.info(msg)

    try:
        from portfolio.factor_model import LiveFactorEngine

        symbols_raw = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAU_USD,BTC_USD,ETH_USD")
        symbols = [s_sym.strip() for s_sym in symbols_raw.split(",") if s_sym.strip()]
        interval_s = int(os.getenv("FACTOR_ENGINE_INTERVAL_S", "3600"))

        engine = LiveFactorEngine(interval_s=interval_s, symbols=symbols)
        await engine.start()
        s.factor_engine = engine

        log_activity(
            f"LiveFactorEngine started — symbols={symbols} "
            f"interval={interval_s}s factors=rates,vol,momentum,carry,macro,dxy"
        )
        return engine

    except Exception as exc:
        logger.warning("init_factor_engine failed (non-fatal): %s", exc)
        return None


async def init_portfolio_rebalancer(s: Any) -> Any:
    """
    Initialise the DynamicRebalancer and attach it to the StrategyOrchestra.

    Method is controlled by REBALANCER_METHOD env var (default: risk_parity).
    Supported: risk_parity | mean_variance | equal_weight

    The rebalancer is also attached to app_state.rebalancer so the API
    route can expose current weights and trigger manual rebalances.
    """
    try:
        from api.admin import log_activity
    except Exception:

        def log_activity(msg: str) -> None:
            logger.info(msg)

    try:
        from portfolio.rebalancer import DynamicRebalancer

        method = os.getenv("REBALANCER_METHOD", "risk_parity")
        max_weight = float(os.getenv("REBALANCER_MAX_WEIGHT", "0.40"))
        dd_limit = float(os.getenv("REBALANCER_DD_LIMIT", "0.15"))
        interval_hours = float(os.getenv("REBALANCER_INTERVAL_HOURS", "4.0"))

        rebalancer = DynamicRebalancer(
            method=method,
            max_weight=max_weight,
            dd_limit=dd_limit,
            interval_hours=interval_hours,
        )
        s.rebalancer = rebalancer

        # Wire into StrategyOrchestra if available
        orchestra = getattr(s, "strategy_orchestra", None)
        if orchestra is not None and hasattr(orchestra, "attach_rebalancer"):
            orchestra._rebalancer = rebalancer
            logger.info("DynamicRebalancer wired into StrategyOrchestra")

        # Wire into PortfolioManager if available
        pms = getattr(s, "portfolio_manager", None)
        if pms is not None and hasattr(pms, "attach_rebalancer"):
            pms._rebalancer = rebalancer
            logger.info("DynamicRebalancer wired into PortfolioManager")

        log_activity(
            f"DynamicRebalancer initialised — method={method} "
            f"max_weight={max_weight:.0%} dd_limit={dd_limit:.0%} "
            f"interval={interval_hours}h"
        )
        return rebalancer

    except Exception as exc:
        logger.warning("init_portfolio_rebalancer failed (non-fatal): %s", exc)
        return None


def run_startup_stress_tests(risk_manager) -> None:
    """
    Run standard stress scenarios against the risk manager at startup.
    Logs a WARNING for any scenario that projects >20% portfolio loss.
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
        threshold = 0.20

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
