# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
database/async_connection.py
==============================
Full async SQLAlchemy engine with asyncpg, connection pool, and health monitoring.

This module provides the async counterpart to database/connection.py.
It uses SQLAlchemy 2.x async extensions with asyncpg as the driver.

Components
----------
AsyncConnectionPool
    Wraps ``create_async_engine`` with asyncpg, configures pool parameters,
    registers SQLAlchemy event listeners for pool metrics, and exposes a
    health-check coroutine.

AsyncSessionFactory
    Thin wrapper around ``async_sessionmaker`` that provides an
    ``asynccontextmanager`` session factory with automatic rollback on error.

get_async_db()
    FastAPI-compatible async dependency that yields a session and commits
    or rolls back on exit.

AsyncHealthMonitor
    Background task that polls the database every ``interval_seconds`` and
    records pool metrics, query latency, and connection errors.  Exposes
    ``health_snapshot()`` for liveness/readiness probes.

Pool configuration
------------------
  pool_size          — number of persistent connections (default: 10)
  max_overflow       — extra connections above pool_size (default: 20)
  pool_timeout       — seconds to wait for a connection (default: 30)
  pool_recycle       — seconds before a connection is recycled (default: 1800)
  pool_pre_ping      — validate connections before checkout (default: True)

Environment variables
---------------------
  DATABASE_URL       — async DSN, e.g. postgresql+asyncpg://user:pass@host/db
  DB_POOL_SIZE       — pool_size (default: 10)
  DB_MAX_OVERFLOW    — max_overflow (default: 20)
  DB_POOL_TIMEOUT    — pool_timeout seconds (default: 30)
  DB_POOL_RECYCLE    — pool_recycle seconds (default: 1800)
  DB_ECHO            — set to "1" to enable SQLAlchemy query logging
  DB_HEALTH_INTERVAL — health monitor poll interval seconds (default: 30)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# ── Optional dependencies ─────────────────────────────────────────────────────

try:
    from sqlalchemy import event, text
    from sqlalchemy.exc import OperationalError, SQLAlchemyError
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

    _SA_AVAILABLE = True
except ImportError:
    _SA_AVAILABLE = False
    AsyncEngine = None  # type: ignore[assignment,misc]
    AsyncSession = None  # type: ignore[assignment,misc]
    logger.warning(
        "SQLAlchemy async extensions not available. "
        "Install with: pip install 'sqlalchemy[asyncio]>=2.0' asyncpg"
    )

# ── Pool metrics ──────────────────────────────────────────────────────────────


@dataclass
class AsyncPoolMetrics:
    """Rolling metrics for the async connection pool."""

    # Counters
    checkouts: int = 0
    checkins: int = 0
    connect_count: int = 0
    disconnect_count: int = 0
    overflow_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    query_count: int = 0

    # Pool state (snapshot)
    pool_size: int = 0
    checked_out: int = 0
    overflow: int = 0
    invalid: int = 0

    # Latency samples (rolling window)
    _checkout_latency_ms: deque = field(
        default_factory=lambda: deque(maxlen=200), repr=False
    )
    _query_latency_ms: deque = field(
        default_factory=lambda: deque(maxlen=200), repr=False
    )

    def record_checkout_latency(self, ms: float) -> None:
        self._checkout_latency_ms.append(ms)

    def record_query_latency(self, ms: float) -> None:
        self._query_latency_ms.append(ms)
        self.query_count += 1

    def _percentile(self, samples: deque, pct: float) -> float:
        if not samples:
            return 0.0
        s = sorted(samples)
        idx = max(0, min(len(s) - 1, int(len(s) * pct / 100.0)))
        return s[idx]

    @property
    def checkout_p99_ms(self) -> float:
        return self._percentile(self._checkout_latency_ms, 99.0)

    @property
    def query_p50_ms(self) -> float:
        return self._percentile(self._query_latency_ms, 50.0)

    @property
    def query_p99_ms(self) -> float:
        return self._percentile(self._query_latency_ms, 99.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkouts": self.checkouts,
            "checkins": self.checkins,
            "connect_count": self.connect_count,
            "disconnect_count": self.disconnect_count,
            "overflow_count": self.overflow_count,
            "timeout_count": self.timeout_count,
            "error_count": self.error_count,
            "query_count": self.query_count,
            "pool_size": self.pool_size,
            "checked_out": self.checked_out,
            "overflow": self.overflow,
            "invalid": self.invalid,
            "checkout_p99_ms": round(self.checkout_p99_ms, 2),
            "query_p50_ms": round(self.query_p50_ms, 2),
            "query_p99_ms": round(self.query_p99_ms, 2),
        }


# ── Pool configuration ────────────────────────────────────────────────────────


def _resolve_async_db_url() -> str:
    """Return an async-compatible database URL.

    Priority:
    1. ASYNC_DATABASE_URL env var (explicit async DSN)
    2. DATABASE_URL — auto-converted: sqlite:// → sqlite+aiosqlite://
    3. Default PostgreSQL asyncpg DSN
    """
    url = os.environ.get("ASYNC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif url.startswith("postgresql://") and "asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url or "postgresql+asyncpg://hopefx:hopefx@localhost:5432/hopefx"


@dataclass
class AsyncPoolConfig:
    """Configuration for the async connection pool."""

    database_url: str = field(
        default_factory=lambda: _resolve_async_db_url()
    )
    pool_size: int = field(
        default_factory=lambda: int(os.environ.get("DB_POOL_SIZE", "10"))
    )
    max_overflow: int = field(
        default_factory=lambda: int(os.environ.get("DB_MAX_OVERFLOW", "20"))
    )
    pool_timeout: float = field(
        default_factory=lambda: float(os.environ.get("DB_POOL_TIMEOUT", "30"))
    )
    pool_recycle: int = field(
        default_factory=lambda: int(os.environ.get("DB_POOL_RECYCLE", "1800"))
    )
    pool_pre_ping: bool = True
    echo: bool = field(
        default_factory=lambda: os.environ.get("DB_ECHO", "0") == "1"
    )
    # Use NullPool for testing (no persistent connections).
    use_null_pool: bool = False


# ── Async connection pool ─────────────────────────────────────────────────────


class AsyncConnectionPool:
    """
    Async SQLAlchemy engine with asyncpg and pool health monitoring.

    Usage::

        pool = AsyncConnectionPool()
        await pool.connect()

        async with pool.session() as session:
            result = await session.execute(text("SELECT 1"))

        await pool.close()

    Or as an async context manager::

        async with AsyncConnectionPool() as pool:
            async with pool.session() as session:
                ...
    """

    def __init__(self, config: AsyncPoolConfig | None = None) -> None:
        if not _SA_AVAILABLE:
            raise RuntimeError(
                "SQLAlchemy async extensions required: "
                "pip install 'sqlalchemy[asyncio]>=2.0' asyncpg"
            )
        self.config = config or AsyncPoolConfig()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None
        self.metrics = AsyncPoolMetrics()
        self._connected: bool = False

    async def connect(self) -> None:
        """Create the async engine and session factory."""
        pool_class = NullPool if self.config.use_null_pool else AsyncAdaptedQueuePool

        _is_sqlite = self.config.database_url.startswith("sqlite")
        # SQLite does not support connection pool parameters; use StaticPool or
        # NullPool to avoid "pool_size/max_overflow not supported" errors.
        if _is_sqlite:
            from sqlalchemy.pool import StaticPool
            pool_class = StaticPool

        engine_kwargs: dict[str, Any] = {
            "echo": self.config.echo,
            "pool_pre_ping": not _is_sqlite,  # StaticPool has no pre-ping
            "poolclass": pool_class,
        }
        if not self.config.use_null_pool and not _is_sqlite:
            engine_kwargs.update(
                {
                    "pool_size": self.config.pool_size,
                    "max_overflow": self.config.max_overflow,
                    "pool_timeout": self.config.pool_timeout,
                    "pool_recycle": self.config.pool_recycle,
                }
            )
        if _is_sqlite:
            # aiosqlite requires connect_args for thread safety
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        self._engine = create_async_engine(
            self.config.database_url,
            **engine_kwargs,
        )

        # Register pool event listeners for metrics.
        self._register_pool_events()

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        self._connected = True
        logger.info(
            "AsyncConnectionPool connected: url=%s pool_size=%d max_overflow=%d",
            self._redact_url(self.config.database_url),
            self.config.pool_size,
            self.config.max_overflow,
        )

    async def close(self) -> None:
        """Dispose the engine and close all connections."""
        if self._engine:
            await self._engine.dispose()
            self._connected = False
            logger.info("AsyncConnectionPool closed")

    async def __aenter__(self) -> "AsyncConnectionPool":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Yield an ``AsyncSession`` that commits on clean exit and rolls back
        on exception.

        Usage::

            async with pool.session() as session:
                result = await session.execute(text("SELECT 1"))
        """
        if not self._session_factory:
            raise RuntimeError("Pool not connected — call connect() first")

        t0 = time.monotonic()
        async with self._session_factory() as sess:
            self.metrics.checkouts += 1
            self.metrics.record_checkout_latency((time.monotonic() - t0) * 1000)
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                self.metrics.error_count += 1
                raise
            finally:
                self.metrics.checkins += 1

    async def execute(self, query: str, params: dict | None = None) -> Any:
        """
        Execute a raw SQL query and return the result.

        Measures query latency and records it in pool metrics.
        """
        t0 = time.monotonic()
        try:
            async with self.session() as sess:
                result = await sess.execute(text(query), params or {})
                latency_ms = (time.monotonic() - t0) * 1000
                self.metrics.record_query_latency(latency_ms)
                return result
        except Exception as exc:
            self.metrics.error_count += 1
            logger.error("AsyncConnectionPool.execute error: %s", exc)
            raise

    async def health_check(self) -> dict[str, Any]:
        """
        Run a lightweight health check against the database.

        Returns a dict with ``healthy``, ``latency_ms``, and pool metrics.
        """
        t0 = time.monotonic()
        try:
            async with self.session() as sess:
                await sess.execute(text("SELECT 1"))
            latency_ms = (time.monotonic() - t0) * 1000
            self._refresh_pool_stats()
            return {
                "healthy": True,
                "latency_ms": round(latency_ms, 2),
                "pool": self.metrics.to_dict(),
            }
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            self.metrics.error_count += 1
            return {
                "healthy": False,
                "latency_ms": round(latency_ms, 2),
                "error": str(exc),
                "pool": self.metrics.to_dict(),
            }

    def _refresh_pool_stats(self) -> None:
        """Update pool size/overflow snapshot from the engine pool."""
        if not self._engine:
            return
        try:
            pool = self._engine.sync_engine.pool
            self.metrics.pool_size = pool.size()
            self.metrics.checked_out = pool.checkedout()
            self.metrics.overflow = pool.overflow()
            self.metrics.invalid = pool.invalidated()
        except Exception:  # nosec B110
            pass  # Pool stats are best-effort

    def _register_pool_events(self) -> None:
        """Register SQLAlchemy pool event listeners for metrics collection."""
        if not self._engine:
            return
        sync_engine = self._engine.sync_engine

        @event.listens_for(sync_engine, "connect")
        def on_connect(dbapi_conn, connection_record):
            self.metrics.connect_count += 1

        @event.listens_for(sync_engine, "close")
        def on_close(dbapi_conn, connection_record):
            self.metrics.disconnect_count += 1

        # overflow and timeout events only exist on QueuePool, not NullPool.
        if not self.config.use_null_pool:
            @event.listens_for(sync_engine.pool, "overflow")
            def on_overflow(dbapi_conn, connection_record):
                self.metrics.overflow_count += 1

            @event.listens_for(sync_engine.pool, "timeout")
            def on_timeout():
                self.metrics.timeout_count += 1

    @staticmethod
    def _redact_url(url: str) -> str:
        """Redact password from a database URL for safe logging."""
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)
            if parsed.password:
                netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
                return urlunparse(parsed._replace(netloc=netloc))
        except Exception:  # nosec B110
            pass
        return url


# ── Session factory helper ────────────────────────────────────────────────────


class AsyncSessionFactory:
    """
    Convenience wrapper that holds a single ``AsyncConnectionPool`` and
    exposes ``get_session()`` for use as a FastAPI dependency.

    Usage::

        factory = AsyncSessionFactory()
        await factory.connect()

        # FastAPI dependency:
        async def get_db():
            async for session in factory.get_session():
                yield session
    """

    def __init__(self, config: AsyncPoolConfig | None = None) -> None:
        self._pool = AsyncConnectionPool(config)

    async def connect(self) -> None:
        await self._pool.connect()

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._pool.session() as sess:
            yield sess

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """FastAPI-compatible async generator dependency."""
        async with self._pool.session() as sess:
            yield sess

    async def health_check(self) -> dict[str, Any]:
        return await self._pool.health_check()

    @property
    def metrics(self) -> AsyncPoolMetrics:
        return self._pool.metrics


# ── Health monitor ────────────────────────────────────────────────────────────


class AsyncHealthMonitor:
    """
    Background task that periodically polls the database and records metrics.

    Exposes ``health_snapshot()`` for liveness/readiness probes.

    Usage::

        monitor = AsyncHealthMonitor(pool)
        task = asyncio.create_task(monitor.run())
        # Later:
        snapshot = monitor.health_snapshot()
        monitor.stop()
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        interval_seconds: float | None = None,
    ) -> None:
        self._pool = pool
        self._interval = interval_seconds or float(
            os.environ.get("DB_HEALTH_INTERVAL", "30")
        )
        self._running: bool = False
        self._last_snapshot: dict[str, Any] = {}
        self._consecutive_failures: int = 0
        self._check_count: int = 0

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        """Poll the database at ``_interval`` seconds until ``stop()`` is called."""
        self._running = True
        logger.info(
            "AsyncHealthMonitor started: interval=%.0fs", self._interval
        )
        while self._running:
            await self._check()
            await asyncio.sleep(self._interval)
        logger.info("AsyncHealthMonitor stopped")

    async def _check(self) -> None:
        self._check_count += 1
        snapshot = await self._pool.health_check()
        snapshot["check_count"] = self._check_count
        snapshot["checked_at"] = time.time()

        if snapshot["healthy"]:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            logger.warning(
                "DB health check failed (consecutive=%d): %s",
                self._consecutive_failures,
                snapshot.get("error"),
            )

        snapshot["consecutive_failures"] = self._consecutive_failures
        self._last_snapshot = snapshot

    def health_snapshot(self) -> dict[str, Any]:
        """Return the most recent health check result."""
        return dict(self._last_snapshot)

    @property
    def is_healthy(self) -> bool:
        return bool(self._last_snapshot.get("healthy", False))


# ── FastAPI dependency helpers ────────────────────────────────────────────────

# Module-level singleton — initialised by the application lifespan handler.
_default_pool: AsyncConnectionPool | None = None


def set_default_pool(pool: AsyncConnectionPool) -> None:
    """Register the module-level default pool (called from app startup)."""
    global _default_pool
    _default_pool = pool


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI async dependency that yields a database session.

    Requires ``set_default_pool()`` to have been called during app startup.

    Usage::

        @app.get("/trades")
        async def list_trades(db: AsyncSession = Depends(get_async_db)):
            ...
    """
    if _default_pool is None:
        raise RuntimeError(
            "Default async pool not initialised. "
            "Call set_default_pool() during application startup."
        )
    async with _default_pool.session() as sess:
        yield sess
