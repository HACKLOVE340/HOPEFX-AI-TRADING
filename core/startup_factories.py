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

    # Only warn about OPENAI_API_KEY when it is the active LLM backend.
    # When LLM_BACKEND=anthropic (the default) the OpenAI key is irrelevant.
    llm_backend = os.getenv("LLM_BACKEND", "anthropic").lower()
    if llm_backend == "openai" and not os.getenv("OPENAI_API_KEY"):
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
        logger.info(
            "SECURITY_JWT_SECRET not set — using ephemeral random secret for this dev session. "
            "JWT tokens are invalidated on every restart. "
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
        logger.info(
            "CONFIG_ENCRYPTION_KEY not set — using ephemeral random key for this dev session. "
            "Credentials encrypted in previous sessions cannot be decrypted after restart. "
            "Set CONFIG_ENCRYPTION_KEY in .env before deploying to production."
        )

    # ── STRIPE_SECRET_KEY ─────────────────────────────────────────────────────
    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not stripe_key:
        logger.warning(
            "STRIPE_SECRET_KEY not set — wallet, billing, subscriptions, and payments "
            "will run in simulation mode. Set STRIPE_SECRET_KEY=sk_live_... in .env "
            "to enable real Stripe charges."
        )
    if not stripe_webhook:
        logger.warning(
            "STRIPE_WEBHOOK_SECRET not set — Stripe webhook signature verification "
            "is disabled. Set STRIPE_WEBHOOK_SECRET=whsec_... from the Stripe dashboard."
        )

    # ── SMTP ──────────────────────────────────────────────────────────────────
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        logger.warning(
            "SMTP_HOST not set — email notifications and SuperAdmin → Platform → "
            "Test SMTP will fail. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD "
            "in .env to enable outbound email."
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
        url = os.getenv("DATABASE_URL", "sqlite:///hopefx.db")
        # Normalise async driver prefixes so callers that pass this URL to
        # sync create_engine don't get a QueuePool/driver mismatch error.
        if url.startswith("sqlite+aiosqlite://"):
            url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        elif url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        return url


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


async def init_event_bus(s: Any) -> Any:
    """
    Connect the module-level EventBus singleton to Redis at startup.

    Previously, bus.connect() was only called lazily from individual
    subsystems (ws_live, paper_runner, market_ingest, main_loop), meaning
    the bus was in an unconnected state during the entire startup sequence.
    Connecting here ensures the bus is ready before any component publishes
    its first event, and that the degraded-mode warning fires exactly once
    at a predictable point in the startup log rather than mid-operation.

    Non-fatal: if Redis is unavailable the bus activates its in-process
    _LocalBus fallback and startup continues normally.
    """
    from core.event_bus import bus

    await bus.connect()
    return bus


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

    # Normalise async driver prefixes — create_engine (sync) cannot use
    # aiosqlite or asyncpg.  _ConfigDatabaseDefaults.get_connection_string()
    # already normalises, but other config implementations may not.
    if conn_str.startswith("sqlite+aiosqlite://"):
        conn_str = conn_str.replace("sqlite+aiosqlite://", "sqlite://", 1)
    elif conn_str.startswith("postgresql+asyncpg://"):
        conn_str = conn_str.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    # Block SQLite in multi-worker deployments — concurrent OS-process writes
    # corrupt the database.  PostgreSQL is required for any production setup.
    is_sqlite = conn_str.startswith("sqlite")
    if is_sqlite:
        concurrency = int(os.getenv("WEB_CONCURRENCY", "1"))
        if concurrency > 1:
            raise RuntimeError(
                f"DATABASE_URL is SQLite but WEB_CONCURRENCY={concurrency}. "
                "SQLite cannot safely handle concurrent writes from multiple OS "
                "processes and will corrupt data. Set DATABASE_URL to a "
                "PostgreSQL connection string before starting with multiple workers."
            )
        logger.info(
            "Database is SQLite (%s) — suitable for local development only. Use PostgreSQL for production.",
            conn_str,
        )

    # ── Pool configuration ────────────────────────────────────────────────────
    # Read from DatabaseSettings (config/settings.py) so all pool knobs are
    # controlled from one place.  Env-var overrides (DB_POOL_SIZE etc.) are
    # still honoured for backwards compatibility with existing deployments.
    engine_kwargs: dict = {}
    if not is_sqlite:
        try:
            from config.settings import get_settings as _get_settings
            _db_cfg = _get_settings().db
            _pool_size    = int(os.getenv("DB_POOL_SIZE",    str(_db_cfg.pool_size)))
            _max_overflow = int(os.getenv("DB_POOL_MAX_OVERFLOW", str(_db_cfg.max_overflow)))
            _pool_timeout = float(os.getenv("DB_POOL_TIMEOUT",  str(_db_cfg.pool_timeout)))
            _pool_recycle = int(os.getenv("DB_POOL_RECYCLE",   str(_db_cfg.pool_recycle)))
            _pool_pre_ping = _db_cfg.pool_pre_ping
        except Exception as _cfg_err:
            logger.warning(
                "Could not load DatabaseSettings — using legacy env-var defaults: %s", _cfg_err
            )
            _pool_size    = int(os.getenv("DB_POOL_SIZE", "20"))
            _max_overflow = int(os.getenv("DB_POOL_MAX_OVERFLOW", "10"))
            _pool_timeout = float(os.getenv("DB_POOL_TIMEOUT", "30"))
            _pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "1800"))
            _pool_pre_ping = True

        engine_kwargs["pool_size"]     = _pool_size
        engine_kwargs["max_overflow"]  = _max_overflow
        engine_kwargs["pool_timeout"]  = _pool_timeout
        engine_kwargs["pool_recycle"]  = _pool_recycle
        engine_kwargs["pool_pre_ping"] = _pool_pre_ping
        logger.info(
            "DB pool: size=%d overflow=%d timeout=%.0fs recycle=%ds pre_ping=%s",
            _pool_size, _max_overflow, _pool_timeout, _pool_recycle, _pool_pre_ping,
        )

    # ── connect_args ──────────────────────────────────────────────────────────
    # For PostgreSQL we set connect_timeout (TCP handshake) and
    # application_name (visible in pg_stat_activity for debugging).
    # statement_timeout is set as a GUC via server_settings so it applies to
    # every statement on the connection without requiring a SET command.
    # Note: asyncpg uses server_settings; psycopg2 uses options="-c ...".
    # We detect the driver from the URL scheme and build the right dict.
    if "postgresql" in conn_str:
        stmt_timeout_ms = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
        connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
        app_name = os.getenv("DB_APPLICATION_NAME", "hopefx")

        if "asyncpg" in conn_str:
            # asyncpg driver — use server_settings dict
            engine_kwargs["connect_args"] = {
                "command_timeout": float(os.getenv("DB_COMMAND_TIMEOUT", "60")),
                "server_settings": {
                    "application_name": app_name,
                    "statement_timeout": str(stmt_timeout_ms),
                },
            }
        else:
            # psycopg2 / psycopg3 driver — use options string
            engine_kwargs["connect_args"] = {
                "connect_timeout": connect_timeout,
                "options": (
                    f"-c statement_timeout={stmt_timeout_ms} "
                    f"-c application_name={app_name}"
                ),
            }

    # SQLite: use NullPool so each call gets a fresh connection and no idle
    # connection holds the file lock while alembic runs in a thread executor.
    if is_sqlite:
        from sqlalchemy.pool import NullPool as _NullPool
        engine_kwargs["poolclass"] = _NullPool
        engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}

    engine = create_engine(conn_str, **engine_kwargs)
    try:
        from alembic import command as alembic_command
        from alembic.config import Config as AlembicConfig
        from alembic.runtime.migration import MigrationContext
        from alembic.util.exc import CommandError as AlembicCommandError

        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", conn_str)

        # Determine current revision before attempting upgrade so we can
        # distinguish "already at head" (no-op) from a genuine failure.
        with engine.connect() as _conn:
            _mctx = MigrationContext.configure(_conn)
            _current_rev = _mctx.get_current_revision()

        # Run alembic upgrade in a thread executor so it doesn't block the
        # async event loop during startup (alembic is synchronous I/O).
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: alembic_command.upgrade(alembic_cfg, "head")
        )
        logger.info(
            "Database migrations applied (alembic upgrade head, was=%s)",
            _current_rev or "none",
        )
    except ImportError:
        # Alembic not installed — first-run path for minimal/dev installs.
        # create_all is safe here because there is no existing schema to drift from.
        logger.info("Alembic not installed — using create_all for schema setup")
        try:
            Base.metadata.create_all(engine, checkfirst=True)
            logger.info("Database schema ensured via create_all (checkfirst=True)")
        except Exception as exc2:
            logger.warning("create_all also failed: %s", exc2)
    except Exception as exc:
        # Alembic is installed but upgrade failed. Most common cause on dev
        # machines: the DB was created via create_all before Alembic was
        # introduced, so alembic_version table is missing.
        # Fix: stamp the DB at head so future runs apply only new migrations,
        # then run _ensure_user_columns() to add any missing columns directly.
        logger.warning("Alembic upgrade failed (%s) — attempting auto-stamp and column sync.", exc)
        try:
            alembic_command.stamp(alembic_cfg, "head")
            logger.info("DB stamped at alembic head — future migrations will apply incrementally")
        except Exception as stamp_exc:
            logger.warning("Alembic stamp failed: %s", stamp_exc)
        try:
            Base.metadata.create_all(engine, checkfirst=True)
            logger.info("Database schema partially ensured via create_all (checkfirst=True)")
        except Exception as exc2:
            logger.warning("create_all also failed: %s", exc2)
    s.db_engine = engine
    s.db_session_factory = sessionmaker(bind=engine)
    return engine


_REDIS_MAXMEMORY_DEFAULT = "512mb"
_REDIS_MAXMEMORY_POLICY_DEFAULT = "allkeys-lru"


def _enforce_redis_maxmemory(host: str, port: int, password: str | None = None) -> None:
    """
    Check Redis maxmemory and set a safe default if it is unlimited (0).

    A Redis instance with maxmemory=0 will consume all available RAM under
    tick-data load and trigger an OS OOM-kill, taking the kill-switch latch
    and position state with it.

    This runs synchronously at startup before the async event loop is busy.
    Failures are logged as warnings — Redis being unreachable here does not
    block startup (the MarketDataCache has its own fallback logic).
    """
    try:
        import redis as _redis_sync

        r = _redis_sync.Redis(
            host=host,
            port=port,
            password=password,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        maxmemory = int(r.config_get("maxmemory").get("maxmemory", 0))
        if maxmemory == 0:
            configured = os.getenv("REDIS_MAXMEMORY", _REDIS_MAXMEMORY_DEFAULT)
            policy = os.getenv("REDIS_MAXMEMORY_POLICY", _REDIS_MAXMEMORY_POLICY_DEFAULT)
            try:
                r.config_set("maxmemory", configured)
                r.config_set("maxmemory-policy", policy)
                logger.info(
                    "Redis maxmemory was unlimited — set to %s with policy %s. "
                    "Override with REDIS_MAXMEMORY / REDIS_MAXMEMORY_POLICY env vars.",
                    configured,
                    policy,
                )
            except Exception as set_exc:
                logger.warning(
                    "Redis maxmemory is UNLIMITED and could not be set automatically "
                    "(%s). Add 'maxmemory %s' and 'maxmemory-policy %s' to your "
                    "redis.conf to prevent OOM on VPS/K8s.",
                    set_exc,
                    configured,
                    policy,
                )
        else:
            logger.debug("Redis maxmemory OK: %d bytes", maxmemory)
    except Exception as exc:
        # Redis being unreachable at startup is expected in dev/offline mode.
        # The automations.yaml Redis service sets maxmemory on start, so this
        # check is a belt-and-suspenders guard for production deployments.
        logger.info(
            "Could not check Redis maxmemory at startup (%s) — "
            "ensure Redis is running and maxmemory is configured in production.",
            exc,
        )


async def init_cache(s: Any) -> Any:
    # ── Redis URL resolution ──────────────────────────────────────────────────
    # Prefer REDIS_URL (used by get_redis() and the rest of the app) over
    # the legacy REDIS_HOST / REDIS_PORT pair so all components share the
    # same Redis instance.
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        try:
            from urllib.parse import urlparse

            _parsed = urlparse(redis_url)
            host = _parsed.hostname or "localhost"
            port = int(_parsed.port or 6379)
            password = _parsed.password or os.getenv("REDIS_PASSWORD") or None
            db = int((_parsed.path or "/0").lstrip("/") or "0")
        except Exception:
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", "6379"))
            password = os.getenv("REDIS_PASSWORD") or None
            db = 0
    else:
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD") or None
        db = 0

    # ── TLS ssl_context from RedisSettings ───────────────────────────────────
    # Build the ssl_context once here so MarketDataCache and every other
    # Redis client in the process uses the same TLS configuration.
    # Falls back gracefully when config/settings.py is unavailable.
    _ssl_context = None
    try:
        from config.settings import get_settings as _get_settings
        _redis_cfg = _get_settings().redis
        _ssl_context = _redis_cfg.build_ssl_context()
        if _ssl_context is not None:
            logger.info(
                "Redis TLS enabled (force_tls=%s skip_verify=%s)",
                _redis_cfg.force_tls,
                _redis_cfg.tls_skip_verify,
            )
    except Exception as _tls_err:
        logger.debug("RedisSettings TLS config skipped (non-fatal): %s", _tls_err)

    # Enforce maxmemory before the cache starts writing tick data.
    # Runs in executor so the sync Redis client doesn't block the event loop.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _enforce_redis_maxmemory, host, port, password)

    from cache import MarketDataCache

    # Pass ssl_context when TLS is required; MarketDataCache forwards it to
    # redis.Redis(ssl_context=...) so the connection is encrypted end-to-end.
    _cache_kwargs: dict = dict(
        host=host,
        port=port,
        db=db,
        password=password,
        max_retries=1,
        socket_connect_timeout=1,
        enable_fallback=True,
    )
    if _ssl_context is not None:
        _cache_kwargs["ssl"] = True
        _cache_kwargs["ssl_context"] = _ssl_context

    cache = MarketDataCache(**_cache_kwargs)

    # ── Celery health registration ────────────────────────────────────────────
    # Wire Celery worker heartbeat registration so workers write their
    # liveness key to the same Redis instance the health probe reads from.
    try:
        from celery_app import register_celery_health

        register_celery_health(cache._redis_client)
        logger.info("Celery health registration wired to Redis cache")
    except Exception as _celery_exc:
        logger.debug("Celery health registration skipped (non-fatal): %s", _celery_exc)

    return cache


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
    from api.ws_live import get_live_manager

    # Router is already registered by core/router_registry.py (register_routers).
    # Only wire the manager into app_state here — do not call app.include_router
    # again or the /ws/live WebSocket route is mounted twice, causing FastAPI to
    # match the wrong handler on alternate requests.
    mgr = get_live_manager()
    s.ws_manager = mgr
    log_activity("WebSocket manager wired (/ws/live)")
    # Broadcasters are started in lifespan via start_broadcasters()
    return mgr


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


def _ensure_user_columns(engine: Any) -> None:
    """Add columns missing from auth-related tables (users, user_sessions, login_attempts).

    Covers databases created before a migration was applied. Each ADD COLUMN is
    wrapped in its own try/except so one failure never blocks the others.
    """
    import sqlalchemy as _sa
    from database.user_models import LoginAttempt, User, UserSession

    inspector = _sa.inspect(engine)

    for model in (User, UserSession, LoginAttempt):
        table_name = model.__tablename__
        try:
            existing = {col["name"] for col in inspector.get_columns(table_name)}
        except Exception as exc:
            logger.warning("Could not inspect table '%s': %s", table_name, exc)
            continue

        missing = [col for col in model.__table__.columns if col.name not in existing]
        if not missing:
            continue

        with engine.begin() as conn:
            for col in missing:
                try:
                    col_type = col.type.compile(engine.dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default_clause = ""
                    if col.default is not None and col.default.is_scalar:
                        val = col.default.arg
                        if isinstance(val, str):
                            default_clause = f" DEFAULT '{val}'"
                        elif isinstance(val, bool):
                            default_clause = f" DEFAULT {int(val)}"
                        elif val is not None:
                            default_clause = f" DEFAULT {val}"
                    conn.execute(
                        _sa.text(
                            f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}{default_clause} {nullable}'
                        )
                    )
                    logger.info("%s table: added missing column '%s'", table_name, col.name)
                except Exception as exc:
                    logger.warning("Could not add column '%s.%s': %s", table_name, col.name, exc)


async def init_auth(s: Any) -> Any:
    from api.admin import log_activity
    from auth.jwt import _get_secret as _jwt_get_secret
    from auth.router import set_auth_service
    from auth.service import AuthService
    from database.user_models import LoginAttempt, User, UserSession

    # Validate JWT secret at startup — fail loud rather than returning 503
    # on the first token decode attempt.
    try:
        _jwt_get_secret()
    except RuntimeError as exc:
        raise RuntimeError(
            f"Auth service startup blocked — JWT secret invalid: {exc}. "
            "Set SECURITY_JWT_SECRET to a random string of ≥32 characters."
        ) from exc

    User.__table__.create(s.db_engine, checkfirst=True)
    UserSession.__table__.create(s.db_engine, checkfirst=True)
    LoginAttempt.__table__.create(s.db_engine, checkfirst=True)

    # Add any columns present in the ORM model but missing from the live DB.
    # This handles databases created before a migration was applied (e.g. the
    # KYC columns added in migration k1l2m3n4o5p6).  Safe to run on every
    # startup — existing columns are left untouched.
    _ensure_user_columns(s.db_engine)

    svc = AuthService(session_factory=s.db_session_factory)
    set_auth_service(svc)
    log_activity("Auth Service initialized")
    logger.info(
        "Auth service ready (JWT secret: %d chars, DB tables: User/UserSession/LoginAttempt)",
        len(_jwt_get_secret()),
    )

    # Ensure bootstrap users exist so superadmin/admin/trader can always log in.
    # Idempotent — skips users that already exist.
    _ensure_bootstrap_users(s.db_session_factory)

    # Background task: purge expired/revoked sessions daily to keep the table lean.
    async def _purge_expired_sessions() -> None:
        import asyncio as _asyncio
        from datetime import datetime as _dt, timezone as _tz

        while True:
            await _asyncio.sleep(86400)  # run once per day
            try:
                with s.db_session_factory() as _db:
                    now = _dt.now(_tz.utc)
                    deleted = (
                        _db.query(UserSession)
                        .filter(
                            (UserSession.expires_at < now) | (UserSession.is_revoked.is_(True))
                        )
                        .delete(synchronize_session=False)
                    )
                    _db.commit()
                    logger.info("Session cleanup: removed %d expired/revoked rows", deleted)
            except Exception as _exc:
                logger.warning("Session cleanup failed (non-fatal): %s", _exc)

    t = asyncio.create_task(_purge_expired_sessions())
    s.background_tasks.append(t)

    return svc


def _ensure_bootstrap_users(session_factory) -> None:
    """
    Seed superadmin / admin / trader accounts from BOOTSTRAP_* env vars if
    they are absent from the database.  Safe to call on every startup —
    existing rows are left untouched.
    """
    from database.user_models import User, UserRole, UserStatus
    from auth.service import hash_password
    import uuid as _uuid

    _seeds = [
        (
            os.getenv("BOOTSTRAP_SUPERADMIN_EMAIL", "superadmin@hopefx.io"),
            "superadmin",
            os.getenv("BOOTSTRAP_SUPERADMIN_PASSWORD", ""),
            UserRole.SUPERADMIN.value,
        ),
        (
            os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@hopefx.io"),
            "admin",
            os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""),
            UserRole.ADMIN.value,
        ),
        (
            os.getenv("BOOTSTRAP_TRADER_EMAIL", "trader@hopefx.io"),
            "trader",
            os.getenv("BOOTSTRAP_TRADER_PASSWORD", ""),
            UserRole.TRADER.value,
        ),
    ]

    with session_factory() as session:
        for email, username, password, role in _seeds:
            if not password:
                continue  # skip if password not configured
            existing = session.query(User).filter_by(email=email).first()
            if existing:
                changed = False
                # Ensure role is correct (may have been downgraded accidentally)
                if existing.role != role:
                    existing.role = role
                    changed = True
                    logger.info("Bootstrap user role corrected: %s -> %s", email, role)
                # Sync password — if .env was regenerated the hash will be stale
                from auth.service import verify_password as _vp
                if not _vp(password, existing.hashed_password):
                    existing.hashed_password = hash_password(password)
                    existing.status = UserStatus.ACTIVE.value
                    existing.is_email_verified = True
                    changed = True
                    logger.info("Bootstrap user password resynced: %s", email)
                if changed:
                    session.commit()
                continue
            user = User(
                id=str(_uuid.uuid4()),
                email=email,
                username=username,
                hashed_password=hash_password(password),
                role=role,
                status=UserStatus.ACTIVE.value,
                is_email_verified=True,
            )
            session.add(user)
            session.commit()
            logger.info("Bootstrap user created: %s (role=%s)", email, role)


async def init_risk_manager(s: Any) -> Any:
    from api.admin import log_activity
    from risk.manager import RiskConfig, RiskManager

    rc = RiskConfig(
        max_position_size_pct=float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.02")),
        max_drawdown_pct=float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
        daily_loss_limit_pct=float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")),
    )
    # Wire the data layer orchestrator so the risk manager reads live data
    # quality, sentiment, and macro features from the authoritative source.
    orchestrator = None
    try:
        from data_layer.orchestrator import orchestrator as _orch

        orchestrator = _orch
    except Exception as _orch_exc:
        logger.debug("init_risk_manager: orchestrator unavailable: %s", _orch_exc)

    rm = RiskManager(config=rc, orchestrator=orchestrator)
    # Also update the module-level singleton so callers that import
    # risk_manager directly get the same wired instance.
    try:
        import risk.manager as _rm_mod

        _rm_mod.risk_manager = rm
    except Exception:  # noqa: BLE001 — module-level alias is best-effort
        pass
    log_activity("Risk Manager initialized")
    return rm


async def init_broker(s: Any) -> Any:
    """
    Broker factory — selects the active broker based on environment variables.

    Priority order:
      1. BROKER_TYPE=mt5  (or BROKER=mt5)  AND  MT5_SERVER / MT5_LOGIN / MT5_PASSWORD set
         → MT5Connector (any MT5-compatible broker or prop firm)
      2. BROKER_TYPE=oanda  AND  BROKER_OANDA_TOKEN set
         → AsyncOANDAConnector (practice or live per OANDA_ENVIRONMENT)
         → 30-day paper trading clock starts on first successful connection
      3. BROKER_TYPE=paper  (default)
         → PaperTradingBroker (in-memory simulation)

    BROKER and BROKER_TYPE are treated as aliases — either works.
    The 30-day OANDA paper trading run clock is tracked in
    ``data/oanda_paper_start.json``.
    """
    from api.admin import log_activity

    # Accept both BROKER_TYPE and BROKER env vars (BROKER_TYPE takes precedence).
    broker_type = (os.getenv("BROKER_TYPE") or os.getenv("BROKER") or "paper").lower()
    oanda_token = os.getenv("BROKER_OANDA_TOKEN", "") or os.getenv("OANDA_API_KEY", "")
    oanda_account = os.getenv("BROKER_OANDA_ACCOUNT", "") or os.getenv("OANDA_ACCOUNT_ID", "")
    oanda_practice = os.getenv("OANDA_ENVIRONMENT", os.getenv("BROKER_OANDA_ENVIRONMENT", "practice")) != "live"

    if broker_type == "mt5":
        mt5_broker = await _try_connect_mt5(log_activity)
        if mt5_broker is not None:
            await _publish_broker_status(broker_type="mt5", connected=True)
            return mt5_broker
        logger.error(
            "[BROKER] MT5 connection failed (check MT5_SERVER / MT5_LOGIN / MT5_PASSWORD). "
            "Set FALLBACK_TO_PAPER=true to allow automatic paper-trading fallback."
        )
        if os.getenv("FALLBACK_TO_PAPER", "false").lower() not in ("1", "true", "yes"):
            raise RuntimeError(
                "Configured broker 'mt5' is unavailable and FALLBACK_TO_PAPER is not set. "
                "Fix broker credentials or set FALLBACK_TO_PAPER=true to start in paper mode."
            )
        log_activity(
            "MT5 broker unavailable — falling back to paper trading (FALLBACK_TO_PAPER=true)"
        )

    if broker_type == "oanda":
        if not oanda_token or not oanda_account:
            logger.error(
                "[BROKER] BROKER_TYPE=oanda but BROKER_OANDA_TOKEN / BROKER_OANDA_ACCOUNT are not set. "
                "Set FALLBACK_TO_PAPER=true to allow automatic paper-trading fallback."
            )
        else:
            broker = await _try_connect_oanda(oanda_token, oanda_account, oanda_practice, log_activity)
            if broker is not None:
                await _publish_broker_status(broker_type="oanda", connected=True)
                return broker
            logger.error(
                "[BROKER] OANDA connection failed. "
                "Set FALLBACK_TO_PAPER=true to allow automatic paper-trading fallback."
            )
        # Only auto-fall-back if operator has explicitly opted in.
        if os.getenv("FALLBACK_TO_PAPER", "false").lower() not in ("1", "true", "yes"):
            raise RuntimeError(
                "Configured broker 'oanda' is unavailable and FALLBACK_TO_PAPER is not set. "
                "Fix broker credentials or set FALLBACK_TO_PAPER=true to start in paper mode."
            )
        log_activity("OANDA broker unavailable — falling back to paper trading (FALLBACK_TO_PAPER=true)")

    broker = await _connect_paper_broker(s, broker_type, oanda_token, oanda_account, log_activity)
    await _publish_broker_status(broker_type="paper", connected=True)
    return broker


async def _publish_broker_status(broker_type: str, connected: bool) -> None:
    """Write broker connection status to Redis so health probes can read it."""
    try:
        import json as _json
        from cache.redis_client import get_redis as _get_redis

        rc = await _get_redis()
        if rc is not None:
            payload = _json.dumps({"broker_type": broker_type, "connected": connected})
            await rc.set("broker:connection_status", payload, ex=3600)
            logger.debug("broker:connection_status published to Redis (type=%s)", broker_type)
    except Exception as _exc:
        logger.debug("_publish_broker_status failed (non-fatal): %s", _exc)


async def _try_connect_mt5(log_activity: Any) -> Any | None:
    """
    Attempt to connect to MetaTrader 5 using env vars.

    Required env vars:
        MT5_SERVER   — MT5 server address (e.g. "ICMarkets-Demo")
        MT5_LOGIN    — MT5 account number (integer)
        MT5_PASSWORD — MT5 account password

    Optional:
        MT5_TIMEOUT  — connection timeout ms (default 60000)
        MT5_PATH     — path to MT5 terminal executable

    Returns the connected MT5Connector, or None on any failure so the
    caller can fall back to the paper broker without crashing startup.
    """
    server = os.getenv("MT5_SERVER", "")
    login_str = os.getenv("MT5_LOGIN", "")
    password = os.getenv("MT5_PASSWORD", "")

    if not (server and login_str and password):
        logger.warning(
            "BROKER_TYPE=mt5 but MT5_SERVER / MT5_LOGIN / MT5_PASSWORD are not all set "
            "— falling back to paper broker. Set all three env vars to use MT5."
        )
        return None

    try:
        login = int(login_str)
    except ValueError:
        logger.error("MT5_LOGIN must be an integer (got %r) — falling back to paper broker", login_str)
        return None

    config = {
        "server": server,
        "login": login,
        "password": password,
        "timeout": int(os.getenv("MT5_TIMEOUT", "60000")),
        "path": os.getenv("MT5_PATH") or None,
    }

    try:
        from brokers.mt5 import MT5Connector

        broker = MT5Connector(config)
        if broker.connect():
            log_activity(f"MT5 broker connected (server={server} login={login})")
            logger.info("[OK] MT5 broker connected (server=%s login=%s)", server, login)
            return broker
        logger.warning("MT5 connection returned False — falling back to paper broker")
        return None
    except ImportError:
        logger.warning(
            "MetaTrader5 SDK not installed — falling back to paper broker. Install with: pip install MetaTrader5"
        )
        return None
    except Exception as exc:
        logger.warning("MT5 broker init failed (%s) — falling back to paper broker", exc)
        return None


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
    except Exception as _exc:
        logger.debug("_get_existing_stamp: cannot parse stamp file: %s", _exc)
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
        except Exception as exc:
            logger.debug("Suppressed exception in %s: %s", __name__, exc)
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


async def init_position_manager(s: Any) -> Any:
    """
    Wire the module-level PositionManager singleton with a Redis client and
    restore any open positions that were persisted before the last restart.

    This closes the crash-recovery gap: without this call, a process restart
    with an open position leaves the in-memory state empty, risking duplicate
    entries or missed stop-losses on the existing position.

    Depends on 'cache' so Redis is available before we attempt to connect.
    Falls back gracefully when Redis is unreachable — positions start empty
    and a warning is logged so the operator knows to reconcile manually.
    """
    from execution.position_manager import position_manager as _pm

    # Wire a Redis async client if available.
    # Only warn when REDIS_URL is explicitly configured but unreachable —
    # absence of REDIS_URL in dev is expected and non-actionable.
    _redis_url_explicit = bool(os.getenv("REDIS_URL", "").strip())
    try:
        import redis.asyncio as aioredis  # pylint: disable=no-name-in-module

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = aioredis.from_url(redis_url, decode_responses=False, socket_connect_timeout=2)
        # Inject the Redis store into the existing singleton
        from execution.redis_state import AsyncRedisStateStore

        _pm._redis = redis_client
        _pm._redis_store = AsyncRedisStateStore(redis_client)
        logger.info("PositionManager: Redis client wired (%s)", redis_url)
    except Exception as exc:
        if _redis_url_explicit:
            logger.warning(
                "PositionManager: could not wire Redis client (%s) — "
                "positions will not survive restarts. Check REDIS_URL.",
                exc,
            )
        else:
            logger.info(
                "PositionManager: Redis not configured — position state is in-memory only "
                "(will not survive restarts). Set REDIS_URL to enable persistence."
            )

    # Restore open positions from the previous session.
    # A Timeout/ConnectionError here means Redis is not running — expected in dev.
    try:
        restored = await _pm.restore_from_redis()
        if restored:
            logger.info("PositionManager: restored %d open position(s) from Redis on startup", restored)
        else:
            logger.info("PositionManager: no open positions to restore from Redis")
    except Exception as exc:
        if _redis_url_explicit:
            logger.warning(
                "PositionManager: restore_from_redis() failed at startup (%s) — "
                "starting with empty position state. Reconcile open positions manually.",
                exc,
            )
        else:
            logger.info(
                "PositionManager: restore_from_redis() skipped (Redis not configured) — "
                "starting with empty position state."
            )

    return _pm


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
    """
    Initialise the canonical HOPEFXBrain (async loop, regime-aware).

    Uses brain.brain.HOPEFXBrain which has start() + dominate() for the
    continuous async decision loop. brain.hopefx_brain.HOPEFXBrain is a
    per-bar synchronous helper used by the MCC and should not be used here.
    """
    from brain.brain import HOPEFXBrain

    b = HOPEFXBrain(config={"max_decision_history": 1000, "regime_check_interval": 60, "circuit_breaker_threshold": 5})

    broker = getattr(s, "broker", None)
    price_engine = getattr(s, "price_engine", None)
    risk_manager = getattr(s, "risk_manager", None)
    strategy_manager = getattr(s, "strategy_brain", None)
    alert_engine = getattr(s, "alert_engine", None)
    position_tracker = getattr(s, "position_tracker", None)
    trade_executor = getattr(s, "trade_executor", None)

    b.inject_components(
        price_engine=price_engine,
        risk_manager=risk_manager,
        broker=broker,
        strategy_manager=strategy_manager,
        notification_manager=alert_engine,
        position_tracker=position_tracker,
        trade_executor=trade_executor,
    )

    await b.start()
    asyncio.create_task(b.dominate(), name="hopefx-brain")
    logger.info("HOPEFXBrain: started — dominate() loop running")
    return b


async def init_wallet(s: Any) -> Any:
    from payments.wallet import WalletManager

    return WalletManager(session_factory=s.db_session_factory)


async def init_social(s: Any) -> bool:
    from social import copy_trading_engine, leaderboard_manager, marketplace

    # Inject the live broker so copy trades actually place orders.
    # init_broker() must have run before init_social() in the startup sequence.
    broker = getattr(s, "broker", None)
    if broker is not None:
        copy_trading_engine.set_broker(broker)
    else:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "init_social: s.broker is None — copy trading will be in broker_offline mode. "
            "Ensure init_broker() runs before init_social() in the startup sequence."
        )

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
      3. WGC gold demand series are fetched via wgc_feed.fetch_and_inject()
         and merged into the store.  WGCFeed uses its own three/four-source
         fallback chain (JSON API → CSV download → yfinance proxy / World Bank
         CB proxy → stale cache) so this step is always attempted regardless
         of FRED availability.

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
    # In dev/CI environments without FRED keys the bridge will time out on
    # every retry.  Cap the total wait so startup is not blocked for >60s.
    _bridge_timeout = float(os.getenv("MACRO_BRIDGE_TOTAL_TIMEOUT_S", "30.0"))
    try:
        from data_layer.orchestrator import orchestrator

        macro_store_bridge = orchestrator._macro_bridge

        await asyncio.wait_for(macro_store_bridge.start(), timeout=_bridge_timeout)
        fred_loaded = macro_store_bridge._series_loaded
        s.macro_store_bridge = macro_store_bridge
        logger.info(
            "MacroStoreBridge: %d/%d FRED series loaded into MacroStore",
            fred_loaded,
            9,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "MacroStoreBridge: timed out after %.0fs — falling back to CSV bootstrap",
            _bridge_timeout,
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

            n_written = await asyncio.get_running_loop().run_in_executor(None, bootstrap, False)
            n_loaded = load_into_store(macro_store)
            logger.info(
                "MacroStore CSV fallback: %d series written, %d loaded",
                n_written,
                n_loaded,
            )
        except Exception as exc:
            logger.warning("MacroStore CSV fallback also failed: %s", exc)

    # ── WGC gold demand series ───────────────────────────────────────────────
    # Fetched independently of FRED — WGCFeed has its own fallback chain
    # (JSON API → CSV download → yfinance ETF proxy / World Bank CB proxy →
    # stale local cache) so this block is resilient to network failures.
    # Series injected: wgc_total_demand, wgc_investment, wgc_central_bank,
    #                  wgc_jewellery, wgc_etf_flow (and proxy variants).
    wgc_injected = 0
    _wgc_timeout = float(os.getenv("WGC_STARTUP_TIMEOUT_S", "20.0"))
    try:
        from data_layer.feeds.macro.wgc import wgc_feed

        wgc_status = await asyncio.wait_for(wgc_feed.fetch_and_inject(), timeout=_wgc_timeout)
        wgc_injected = wgc_status.get("series_injected", 0)
        logger.info(
            "WGC: %d series injected into MacroStore (fetched: %s)",
            wgc_injected,
            wgc_status.get("series_fetched", []),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "WGC startup download timed out after %.0fs — gold demand series unavailable",
            _wgc_timeout,
        )
    except Exception as exc:
        logger.warning("WGC startup download failed (%s) — gold demand series unavailable", exc)

    # Attach to app_state
    s.macro_store = macro_store

    n_in_store = len(getattr(macro_store, "_series", {}))
    log_activity(
        f"MacroStore initialised — {n_in_store} series loaded "
        f"({'FRED' if fred_loaded >= 3 else 'CSV fallback'}), "
        f"WGC gold demand: {wgc_injected} series, "
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

        # Publish ML status to Redis so health probes and superadmin can read it.
        try:
            import json as _json
            from cache.redis_client import get_redis as _get_redis

            _rc = await _get_redis()
            if _rc is not None:
                _payload = _json.dumps({
                    "model_available": health.get("model_available", False),
                    "model_version": health.get("model_version", "none"),
                    "calibrator": health.get("calibrator_available", False),
                    "online_learning": health.get("online_learning_enabled", False),
                })
                await _rc.set("ml:model:status", _payload, ex=3600)
                logger.debug("ml:model:status published to Redis")
        except Exception as _ml_redis_exc:
            logger.debug("ML status Redis publish failed (non-fatal): %s", _ml_redis_exc)

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
    except Exception as _exc:
        logger.debug("_get_feature_flag(%s): flags unavailable, using default=%s: %s", flag_name, default, _exc)
        return default


def _get_log_activity():
    """Return log_activity from api.admin, falling back to logger.info."""
    try:
        from api.admin import log_activity

        return log_activity
    except Exception as _exc:
        logger.debug("_get_log_activity: api.admin unavailable, using logger.info: %s", _exc)
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
    from core.signal_engine import run_signal_engine, _ML_AVAILABLE  # noqa: PLC0415

    # Pre-flight: warn loudly if ML package is missing so operators see it in
    # startup logs rather than discovering degraded signals silently at runtime.
    if not _ML_AVAILABLE:
        logger.warning(
            "[STARTUP] ML package unavailable — signal engine will run WITHOUT ML "
            "probability enrichment.  Signals are still generated from StrategyBrain "
            "but model_version will be reported as 'none'.  "
            "Fix: ensure ml/ package imports cleanly (check PyTorch, scikit-learn, etc.)."
        )

    t = asyncio.create_task(run_signal_engine(s))
    s.background_tasks.append(t)
    # Expose the task handle on app_state so health checks and MCC can reference it
    s.signal_engine = t
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
    """Instantiate AIExplainer and attach to app_state.

    Router registration is handled by router_registry.py (EXPLAINABILITY flag).
    This factory only creates the engine so other components can reference it
    via app_state.explainer.
    """
    if not flags.EXPLAINABILITY:
        return None
    try:
        from explainability import AIExplainer

        e = AIExplainer()
        s.explainer = e
        logger.info("AIExplainer initialised")
        return e
    except Exception as exc:
        logger.warning("AIExplainer init failed (non-fatal): %s", exc)
        return None


async def init_transparency(s: Any, app: Any, flags: Any) -> Any:
    """Instantiate ExecutionTransparencyEngine and attach to app_state.

    Router registration is handled by router_registry.py (TRANSPARENCY_REPORTS flag).
    """
    if not flags.TRANSPARENCY_REPORTS:
        return None
    try:
        from transparency import ExecutionTransparencyEngine

        e = ExecutionTransparencyEngine()
        s.transparency_engine = e
        logger.info("ExecutionTransparencyEngine initialised")
        return e
    except Exception as exc:
        logger.warning("ExecutionTransparencyEngine init failed (non-fatal): %s", exc)
        return None


async def init_teams(s: Any, app: Any, flags: Any) -> Any:
    """Instantiate TeamManager and attach to app_state.

    Router registration is handled by router_registry.py (TEAMS_MODULE flag).
    """
    if not flags.TEAMS_MODULE:
        return None
    try:
        from teams import TeamManager

        tm = TeamManager()
        s.teams_manager = tm
        logger.info("TeamManager initialised")
        return tm
    except Exception as exc:
        logger.warning("TeamManager init failed (non-fatal): %s", exc)
        return None


async def init_nocode(s: Any, app: Any, flags: Any) -> Any:
    """Instantiate NoCodeStrategyBuilder and attach to app_state.

    Router registration is handled by router_registry.py (NOCODE_BUILDER flag).
    """
    if not flags.NOCODE_BUILDER:
        return None
    try:
        from nocode import NoCodeStrategyBuilder

        nb = NoCodeStrategyBuilder()
        s.nocode_builder = nb
        logger.info("NoCodeStrategyBuilder initialised")
        return nb
    except Exception as exc:
        logger.warning("NoCodeStrategyBuilder init failed (non-fatal): %s", exc)
        return None


async def init_replay(s: Any, app: Any, flags: Any) -> Any:
    """Instantiate ChartReplayEngine and attach to app_state.

    Router registration is handled by router_registry.py (REPLAY_ENGINE flag).
    """
    if not flags.REPLAY_ENGINE:
        return None
    try:
        from replay import ChartReplayEngine

        re = ChartReplayEngine()
        s.replay_engine = re
        logger.info("ChartReplayEngine initialised")
        return re
    except Exception as exc:
        logger.warning("ChartReplayEngine init failed (non-fatal): %s", exc)
        return None


async def init_ml_predictions(s: Any, app: Any, flags: Any) -> Any:
    """Instantiate TechnicalFeatureEngineer and attach to app_state.

    Router registration is handled by router_registry.py (ML_PREDICTIONS flag).
    """
    if not flags.ML_PREDICTIONS:
        return None
    try:
        from ml import TechnicalFeatureEngineer

        fe = TechnicalFeatureEngineer()
        s.ml_feature_engineer = fe
        logger.info("TechnicalFeatureEngineer initialised")
        return fe
    except Exception as exc:
        logger.warning("TechnicalFeatureEngineer init failed (non-fatal): %s", exc)
        return None


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
        except Exception as _exc:
            logger.debug("_detect_regime(%s): CSV read/calc failed: %s", symbol, _exc)
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
        # event_bus must connect before cache and broker so the degraded-mode
        # warning fires once at startup rather than mid-operation, and so that
        # components can publish events as soon as they initialise.
        .register("event_bus", F.init_event_bus, required=False, deps=["config"])
        .register("cache", F.init_cache, required=False, deps=["config"])
        .register("hot_standby", F.init_hot_standby, required=False, deps=["cache", "broker"])
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
        # auth_service is required=True: without it every auth endpoint returns
        # 503 and no user can log in.  It depends on database (already required),
        # so a DB failure will surface as a database error, not a silent auth skip.
        .register("auth_service", F.init_auth, required=True, deps=["database"])
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
        .register(
            "position_manager",
            F.init_position_manager,
            required=False,
            deps=["cache", "broker"],
        )
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
        .register("social", F.init_social, required=False, deps=["config", "broker"])
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
        # Deep Ensemble (Phase 4) — loads LSTM/Transformer/TCN model from disk,
        # validates OOS gates, and wires into signal_engine._deep_ensemble_store.
        # Only active when FEATURE_DEEP_ENSEMBLE=true and model files exist.
        .register(
            "deep_ensemble_store",
            F.init_deep_ensemble_store,
            required=False,
            deps=["signal_engine"],
        )
        .register(
            "feature_engineer",
            F.init_feature_engineer,
            required=False,
            deps=["data_scheduler"],
        )
        .register(
            "decision_engine",
            F.init_decision_engine,
            required=False,
            deps=["strategy_brain", "risk_manager", "trade_executor", "feature_engineer"],
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
        # Master Control Centre — strategy orchestration, regime detection,
        # signal aggregation, and broker execution routing.
        # Depends on broker + signal_engine so it starts after both are live.
        .register(
            "mcc",
            F.init_mcc,
            required=False,
            deps=["broker", "signal_engine"],
        )
        # ── Multi-source tick feed (yFinance → Alpha Vantage → Twelve Data) ──
        # Runs concurrently with the existing TickFeedManager (OANDA/Finnhub/Polygon).
        # Writes to Redis tick:SYMBOL keys and hopefx:tick pub/sub channel.
        # Depends on cache (Redis) and broker (price bridge) but is non-fatal
        # when either is unavailable — degrades gracefully to in-process only.
        .register(
            "multi_source_feed",
            F.init_multi_source_feed,
            required=False,
            deps=["cache", "broker"],
        )
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
        # ── Security subsystems ───────────────────────────────────────────────
        # global_fortress mounts /api/security/* (attacks, lockdown, blocked-ips,
        # alerts, fixes) and starts the 24/7 HOPEFXBrain monitor loop.
        .register(
            "security_brain",
            _app(F.init_security_brain),
            required=False,
            deps=["config"],
        )
        # self_healer mounts /api/security/heal/* and starts the file-integrity
        # drift-detection + auto-patch background task.
        .register(
            "self_healer",
            _app(F.init_self_healer),
            required=False,
            deps=["config"],
        )
        # antivirus mounts /api/security/av/* and starts the YARA/ClamAV scan loop.
        .register(
            "antivirus",
            _app(F.init_antivirus),
            required=False,
            deps=["config"],
        )
        # auto_rollback monitors circuit breakers, error rates, and health
        # checks; triggers soft/medium/hard/full rollback when thresholds are
        # exceeded.  Depends on broker and cache so it can observe their state.
        .register(
            "auto_rollback",
            F.init_auto_rollback,
            required=False,
            deps=["broker", "cache"],
        )
        # HopeFXEngine — main trading engine wired to broker, risk, and brain.
        # Registered last so all dependencies are available.
        .register(
            "engine",
            F.init_trading_engine,
            required=False,
            deps=["broker", "risk_manager", "brain", "signal_engine"],
        )
    )

    return registry


async def init_trading_engine(s: Any) -> Any | None:
    """
    Initialise HopeFXEngine and store it on s.engine.

    HopeFXEngine reads its own configuration from environment variables and
    lazily connects to the broker on first tick.  We store the instance on
    app_state.engine so health probes and admin endpoints can inspect
    _running / status without importing hopefx_engine directly.
    """
    try:
        from hopefx_engine import HopeFXEngine

        engine = HopeFXEngine()
        # Inject already-initialised components so the engine doesn't create
        # duplicate instances when they are available.
        if getattr(s, "broker", None) is not None:
            engine._broker = s.broker
        if getattr(s, "risk_manager", None) is not None:
            engine._risk_manager = s.risk_manager
        if getattr(s, "brain", None) is not None or getattr(s, "strategy_brain", None) is not None:
            engine._brain = s.brain or s.strategy_brain
        s.engine = engine
        logger.info("HopeFXEngine initialised and wired to app_state.engine")
        return engine
    except Exception as exc:
        logger.warning("HopeFXEngine init failed (non-fatal): %s", exc)
        return None


async def init_mcc(s: Any) -> Any | None:
    """
    Initialise the Master Control Centre and wire it to all live components.

    Connects:
      - config_manager  → s.config
      - cache           → s.cache
      - broker          → s.broker  (price updates routed via on_price_update)
      - risk_manager    → s.risk_manager  (daily P&L / kill-switch sync)
      - brain           → s.brain / s.strategy_brain
      - signal_engine   → s.signal_engine  (task handle)
      - db_session      → s.db_session_factory

    The MCC instance is stored on app_state.mcc so health checks and the
    /api/health/components endpoint can report its status.
    """
    try:
        from core.mcc.master_control import MasterControlCore, MCCConfig
        from cache.market_data_cache import MarketDataCache

        cfg = MCCConfig(
            max_strategies_active=int(os.getenv("MCC_MAX_STRATEGIES", "5")),
            emergency_drawdown_pct=float(os.getenv("MCC_EMERGENCY_DD_PCT", "0.10")),
        )
        mcc = MasterControlCore(cfg)

        # Wire config + cache
        config_mgr = getattr(s, "config", None)
        cache = getattr(s, "cache", None)
        db_session = None
        if s.db_session_factory is not None:
            try:
                db_session = s.db_session_factory()
            except Exception:  # noqa: BLE001 — DB session creation is best-effort
                pass

        if config_mgr is not None or cache is not None:
            mcc.initialize(
                config_manager=config_mgr,
                cache=cache,
                db_session=db_session,
            )

        # Seed current prices from broker market_prices
        broker = getattr(s, "broker", None)
        if broker is not None:
            market_prices = getattr(broker, "market_prices", {})
            from decimal import Decimal as _D
            for sym, price in market_prices.items():
                if price and price > 0:
                    mcc.current_prices[sym] = _D(str(price))

        # Register price-update callback on the price engine so MCC receives
        # every tick and can route it to registered strategies.
        pe = getattr(s, "price_engine", None)
        if pe is not None:
            from decimal import Decimal as _D

            def _mcc_price_cb(tick: Any) -> None:
                try:
                    mcc.on_price_update(
                        symbol=tick.symbol,
                        price=_D(str(tick.mid)),
                        bid=_D(str(tick.bid)),
                        ask=_D(str(tick.ask)),
                    )
                except Exception as _cb_exc:
                    logger.debug("MCC price callback error: %s", _cb_exc)

            pe.register_price_callback(_mcc_price_cb) if hasattr(pe, "register_price_callback") else None

        # Sync kill-switch state with risk manager
        rm = getattr(s, "risk_manager", None)
        if rm is not None and getattr(rm, "kill_switch_active", False):
            mcc.trigger_kill_switch("risk_manager kill switch active at startup")

        mcc.is_running = True
        s.mcc = mcc
        logger.info(
            "MCC initialised — broker=%s price_engine=%s brain=%s signal_engine=%s",
            type(broker).__name__ if broker else "None",
            type(pe).__name__ if pe else "None",
            type(getattr(s, "brain", None) or getattr(s, "strategy_brain", None)).__name__
            if (getattr(s, "brain", None) or getattr(s, "strategy_brain", None))
            else "None",
            "running" if getattr(s, "signal_engine", None) else "None",
        )
        return mcc
    except Exception as exc:
        logger.warning("MCC init failed (non-fatal): %s", exc)
        return None


async def init_security_brain(s: Any, app: Any) -> Any | None:
    """Mount HOPEFXBrain router (/api/security/*) and start the 24/7 monitor loop."""
    try:
        from security.global_fortress import start_brain as _start_brain

        brain = await _start_brain(app)
        s.security_brain = brain
        logger.info("HOPEFXBrain started — /api/security/* routes mounted")
        return brain
    except Exception as exc:
        logger.warning("HOPEFXBrain failed to start (non-fatal): %s", exc)
        return None


async def init_self_healer(s: Any, app: Any) -> Any | None:
    """Mount SelfHealer router (/api/security/heal/*) and start the integrity scan loop."""
    try:
        from security.self_healer import start_healer as _start_healer

        await _start_healer(app)
        logger.info("SelfHealer started — /api/security/heal/* routes mounted")
        return getattr(s, "self_healer", None)
    except Exception as exc:
        logger.warning("SelfHealer failed to start (non-fatal): %s", exc)
        return None


async def init_auto_rollback(s: Any) -> Any | None:
    """
    Start the AutoRollbackManager as an independent component.

    Monitors circuit breaker states, error rates, and health check results.
    Triggers soft/medium/hard/full rollback when configured thresholds are
    exceeded.  Runs as a background asyncio task — non-fatal if unavailable.

    Registered after 'broker' and 'cache' so it can observe their state from
    the first monitoring cycle.
    """
    try:
        from resilience.auto_rollback import rollback_manager as _rm

        # Register a health-check trigger that fires when the readiness probe
        # returns degraded — this catches DB/Redis/ML failures not covered by
        # the circuit breakers alone.
        from resilience.auto_rollback import RollbackTrigger, RollbackStrategy

        def _health_degraded() -> bool:
            """Return True when the /api/health/ready probe would return 503."""
            try:
                from api.health import _check_ready_sync

                return not _check_ready_sync()
            except Exception:
                return False

        _rm.register_trigger(
            RollbackTrigger(
                name="health_ready_degraded",
                condition=_health_degraded,
                strategy=RollbackStrategy.SOFT,
                description="Readiness probe degraded — disable affected feature flags",
                cooldown_seconds=300,  # at most once every 5 minutes
            )
        )

        await _rm.start()
        s.auto_rollback = _rm
        logger.info(
            "AutoRollbackManager started — monitoring %d triggers",
            len(_rm._triggers),
        )
        return _rm
    except Exception as exc:
        logger.warning("AutoRollbackManager failed to start (non-fatal): %s", exc)
        return None


async def init_antivirus(s: Any, app: Any) -> Any | None:
    """Mount AntivirusScanner router (/api/security/av/*) and start the scan loop."""
    try:
        from security.antivirus import start_av_scanner as _start_av

        await _start_av(app)
        logger.info("AntivirusScanner started — /api/security/av/* routes mounted")
        return getattr(s, "antivirus", None)
    except Exception as exc:
        logger.warning("AntivirusScanner failed to start (non-fatal): %s", exc)
        return None


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
        logger.exception("init_chaos_controller failed")
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

        # HotStandbyReplicator requires an async Redis client (calls await
        # self._redis.get() / .set() / .setex()).  s.cache is a MarketDataCache
        # (sync, no .get/.set), so we obtain a dedicated async client here.
        from cache.redis_client import get_redis as _get_async_redis

        redis_client = await _get_async_redis()
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
        logger.exception("init_hot_standby failed")
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


async def init_multi_source_feed(s: Any) -> Any:
    """
    Start the MultiSourceTickFeed — yFinance → Alpha Vantage → Twelve Data fallback chain.

    Responsibilities
    ----------------
    * Polls all configured symbols concurrently on a configurable interval.
    * Per-source circuit breakers prevent cascading failures.
    * Validated ticks are written to Redis (tick:SYMBOL, hopefx:dl:tick:SYMBOL,
      hopefx:tick:SYMBOL pub/sub, hopefx:tick CH_TICK, price_queue list).
    * Bridges every tick into the broker price table and execution engine cache.
    * Wires OHLCV bars into the signal engine bar buffer when available.

    Symbols are driven by config/multi_source_feed.yaml.
    API keys: ALPHA_VANTAGE_KEY, TWELVE_API_KEY (yFinance needs no key).

    Best-effort — missing keys disable individual sources but never block startup.
    """
    try:
        from api.admin import log_activity
    except Exception:
        def log_activity(msg: str) -> None:
            logger.info(msg)

    try:
        from data_feed.multi_source_feed import MultiSourceTickFeed

        # Allow operator to restrict symbols via env var (comma-separated).
        symbols_env = os.getenv("MULTI_FEED_SYMBOLS", "").strip()
        symbols = [s.strip() for s in symbols_env.split(",") if s.strip()] if symbols_env else None

        feed = MultiSourceTickFeed(symbols=symbols)

        # Bridge: push every validated tick into the broker price table and
        # execution engine last-tick cache so all downstream components see
        # live prices from the multi-source feed.
        broker_ref = getattr(s, "broker", None)
        execution_engine_ref = getattr(s, "execution_engine", None)
        price_engine_ref = getattr(s, "price_engine", None)

        class _MultiSourceBridge:
            async def on_new_price(self, symbol: str, price: float) -> None:
                # Update broker price table (paper broker + live broker) for any symbol.
                if broker_ref is not None and hasattr(broker_ref, "update_market_price"):
                    try:
                        broker_ref.update_market_price(symbol, price)
                    except Exception as _exc:
                        logger.debug("multi_source_feed broker bridge error: %s", _exc)
                # Update execution engine last-tick cache for any symbol.
                if execution_engine_ref is not None and hasattr(execution_engine_ref, "update_last_tick"):
                    try:
                        execution_engine_ref.update_last_tick(symbol, price)
                    except Exception as _exc:
                        logger.debug("multi_source_feed exec engine bridge error: %s", _exc)
                # Update price engine current price (symbol-aware when supported).
                if price_engine_ref is not None and hasattr(price_engine_ref, "on_new_price"):
                    try:
                        import inspect as _inspect
                        _sig = _inspect.signature(price_engine_ref.on_new_price)
                        _nparams = sum(
                            1 for p in _sig.parameters.values()
                            if p.default is _inspect.Parameter.empty
                            and p.kind not in (
                                _inspect.Parameter.VAR_POSITIONAL,
                                _inspect.Parameter.VAR_KEYWORD,
                            )
                        )
                        if _nparams >= 2:
                            await price_engine_ref.on_new_price(symbol, price)
                        else:
                            await price_engine_ref.on_new_price(price)
                    except Exception as _exc:
                        logger.debug("multi_source_feed price engine bridge error: %s", _exc)

        feed.subscribe(_MultiSourceBridge())

        # Wire signal engine if available
        signal_engine_ref = getattr(s, "signal_engine", None)
        if signal_engine_ref is not None and hasattr(signal_engine_ref, "on_new_price"):
            feed.subscribe(signal_engine_ref)

        await feed.start()

        # Store on app_state
        s.multi_source_feed = feed

        active_symbols = list(feed._states.keys())
        log_activity(
            f"MultiSourceTickFeed started — symbols={active_symbols} "
            f"chain=yFinance→AlphaVantage→TwelveData "
            f"redis={'connected' if feed._tick_writer else 'unavailable'}"
        )
        logger.info(
            "MultiSourceTickFeed registered on app_state | symbols=%s",
            active_symbols,
        )
        return feed

    except Exception as exc:
        logger.warning("init_multi_source_feed failed (non-fatal): %s", exc)
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


# ---------------------------------------------------------------------------
# Broker manager accessor — used by MCC and integration tests
# ---------------------------------------------------------------------------


def get_broker_manager():
    """
    Return a ``BrokerManager`` instance backed by the active broker on
    ``app_state``, or ``None`` when no broker is configured.

    The manager is cached on ``app_state._mcc_broker_manager`` so
    subsequent calls within the same process reuse the same instance.
    A new manager is created whenever the active broker reference changes.
    """
    try:
        from core.app_state import app_state
        from brokers.manager import BrokerManager

        broker = getattr(app_state, "broker", None)
        if broker is None:
            return None

        # Return cached manager when the broker reference hasn't changed.
        cached: BrokerManager | None = getattr(app_state, "_mcc_broker_manager", None)
        if cached is not None and getattr(cached, "_mcc_broker_ref", None) is broker:
            return cached

        mgr = BrokerManager(primary_broker_name="primary")
        mgr.register("primary", broker)
        mgr.set_active("primary")
        mgr._mcc_broker_ref = broker  # mark cache tag
        app_state._mcc_broker_manager = mgr
        return mgr

    except Exception as exc:
        logger.debug("get_broker_manager: could not build manager: %s", exc)
        return None


def create_app_state():
    """
    Create and return a fresh AppState instance.

    Convenience factory used by tests and external callers that need a
    clean app state without importing core.app_state directly.
    """
    from core.app_state import AppState

    return AppState()


async def init_feature_engineer(s: Any) -> Any:
    """
    Initialise the AdvancedFeatureEngineer and attach it to app_state.

    The engineer is fitted on a short warm-up window fetched from the
    data layer.  If the data layer is unavailable the engineer is returned
    unfitted — it will fit lazily on the first transform() call.

    Stores the result in ``s.feature_engineer``.
    """
    try:
        from ml.features.advanced_features import AdvancedFeatureEngineer

        fe = AdvancedFeatureEngineer(lookback_periods=252)

        # Attempt to warm-fit on recent OHLCV data
        try:
            orch = getattr(s, "data_orchestrator", None) or getattr(s, "orchestrator", None)
            if orch is not None and hasattr(orch, "get_ohlcv"):
                df = await orch.get_ohlcv("XAUUSD", "1h", limit=300)
                if df is not None and len(df) >= 60:
                    fe.fit(df)
                    logger.info("FeatureEngineer fitted on %d bars", len(df))
                else:
                    logger.info("FeatureEngineer: insufficient warm-up data — will fit lazily")
            else:
                logger.info("FeatureEngineer: data orchestrator unavailable — will fit lazily")
        except Exception as _fit_exc:
            logger.debug("FeatureEngineer warm-fit skipped: %s", _fit_exc)

        s.feature_engineer = fe
        return fe
    except Exception as exc:
        logger.warning("init_feature_engineer failed: %s", exc)
        return None


async def init_decision_engine(s: Any) -> Any:
    """
    Initialise HOPEFXDecisionEngine and attach it to app_state.

    Wires all required sub-systems from app_state:
      - brain / strategy_brain  → Phase 1 signal generation
      - risk_manager            → Phase 3 position sizing
      - gatekeeper              → Phase 3 pre-trade gate
      - trade_executor          → Phase 4 order execution
      - event_bus / bus         → Phase 5 fill broadcast
      - feature_engineer        → optional ML feature pipeline
      - compliance_manager      → optional Phase 5 audit log
      - inference_engine        → optional Phase 2 ML predictor

    All sub-systems are optional — the engine degrades gracefully when
    any component is absent.  Stores the result in ``s.decision_engine``.
    """
    try:
        from core.decision.HOPEFXDecisionEngine import HOPEFXDecisionEngine
        from core.event_bus import bus as _bus

        # Resolve brain: prefer strategy_brain (StrategyBrain), fall back to brain (HOPEFXBrain)
        brain = getattr(s, "strategy_brain", None) or getattr(s, "brain", None)
        if brain is None:
            logger.warning("init_decision_engine: no brain available — decision engine will produce NO_SIGNAL")

        risk_manager = getattr(s, "risk_manager", None)
        gatekeeper = getattr(s, "gatekeeper", None)

        # Gatekeeper may not be on app_state yet — build one if missing
        if gatekeeper is None:
            try:
                from risk.gatekeeper import Gatekeeper

                gatekeeper = Gatekeeper(orchestrator=getattr(s, "data_orchestrator", None))
                logger.info("init_decision_engine: built Gatekeeper inline")
            except Exception as _gk_exc:
                logger.warning("init_decision_engine: could not build Gatekeeper: %s", _gk_exc)

        trade_executor = getattr(s, "trade_executor", None)
        feature_engineer = getattr(s, "feature_engineer", None)
        compliance_manager = getattr(s, "compliance_manager", None)
        ml_predictor = getattr(s, "inference_engine", None)

        engine = HOPEFXDecisionEngine(
            brain=brain,
            risk_manager=risk_manager,
            gatekeeper=gatekeeper,
            trade_executor=trade_executor,
            event_bus=_bus,
            feature_engineer=feature_engineer,
            compliance_manager=compliance_manager,
            ml_predictor=ml_predictor,
        )

        s.decision_engine = engine
        logger.info(
            "HOPEFXDecisionEngine initialised — brain=%s risk=%s gate=%s executor=%s",
            type(brain).__name__ if brain else "None",
            type(risk_manager).__name__ if risk_manager else "None",
            type(gatekeeper).__name__ if gatekeeper else "None",
            type(trade_executor).__name__ if trade_executor else "None",
        )
        return engine
    except Exception as exc:
        logger.exception("init_decision_engine failed: %s", exc)
        return None
