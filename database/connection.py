# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Database Connection Management
SQLAlchemy sync + async engines with connection pooling, retries, and monitoring.

Sync engine  — DatabaseManager / get_db()         — FastAPI sync endpoints
Async engine — AsyncDatabaseManager / get_async_db() — FastAPI async endpoints

Both engines share the same circuit-breaker and metrics infrastructure.
"""

import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import (
        OperationalError,
    )
    from sqlalchemy.exc import (
        TimeoutError as SATimeoutError,
    )
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import QueuePool

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    Session = None  # type: ignore[assignment,misc]
    logger.warning("SQLAlchemy not available, database features disabled")


@dataclass
class DatabaseMetrics:
    """Database connection pool and query metrics."""

    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    checked_out_connections: int = 0
    checkout_time_avg_ms: float = 0.0
    query_count: int = 0
    error_count: int = 0
    slow_query_count: int = 0
    # Extended pool health
    pool_size: int = 0
    pool_overflow: int = 0
    pool_timeout_count: int = 0
    # Latency tracking (rolling 100-sample window)
    _latency_samples: list = field(default_factory=list, repr=False, compare=False)

    def record_latency(self, ms: float) -> None:
        self._latency_samples.append(ms)
        if len(self._latency_samples) > 100:
            self._latency_samples.pop(0)

    @property
    def p50_latency_ms(self) -> float:
        if not self._latency_samples:
            return 0.0
        s = sorted(self._latency_samples)
        return s[len(s) // 2]

    @property
    def p99_latency_ms(self) -> float:
        if not self._latency_samples:
            return 0.0
        s = sorted(self._latency_samples)
        return s[int(len(s) * 0.99)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_connections": self.total_connections,
            "active_connections": self.active_connections,
            "idle_connections": self.idle_connections,
            "checked_out_connections": self.checked_out_connections,
            "checkout_time_avg_ms": round(self.checkout_time_avg_ms, 3),
            "query_count": self.query_count,
            "error_count": self.error_count,
            "slow_query_count": self.slow_query_count,
            "pool_size": self.pool_size,
            "pool_overflow": self.pool_overflow,
            "pool_timeout_count": self.pool_timeout_count,
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "p99_latency_ms": round(self.p99_latency_ms, 3),
        }


class DatabaseManager:
    """
    Production database manager with:
    - Connection pooling with size limits
    - Automatic retry with exponential backoff
    - Query timeout enforcement
    - Connection health checks
    - Metrics collection
    - Circuit breaker for DB failures
    """

    def __init__(
        self,
        connection_string: str,
        pool_size: int = 20,
        max_overflow: int = 40,
        pool_timeout: float = 10.0,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo: bool = False,
        max_retries: int = 3,
        query_timeout: float = 30.0,
    ):
        if not SQLALCHEMY_AVAILABLE:
            raise ImportError("SQLAlchemy required. Install: pip install sqlalchemy")

        self.connection_string = connection_string
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo = echo
        self.max_retries = max_retries
        self.query_timeout = query_timeout

        self._engine: Engine | None = None
        self._session_factory = None
        self._metrics = DatabaseMetrics()
        self._metrics_lock = threading.Lock()
        self._circuit_open = False
        self._circuit_half_open = False  # half-open: allow one probe request
        self._failure_count = 0
        self._circuit_threshold = 5
        self._circuit_recovery_time = 60.0
        self._last_failure_time: float | None = None

        self._initialize()

    @staticmethod
    def _normalise_sync_url(url: str) -> str:
        """Strip async driver prefixes so create_engine (sync) can open the URL."""
        if url.startswith("sqlite+aiosqlite://"):
            return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        return url

    def _initialize(self):
        """Initialize database engine with event listeners"""
        try:
            # Normalise async driver prefixes — QueuePool / create_engine are
            # sync-only and cannot use aiosqlite or asyncpg drivers.
            sync_url = self._normalise_sync_url(self.connection_string)

            is_sqlite = "sqlite" in sync_url
            is_pg = "postgresql" in sync_url

            if is_sqlite:
                # SQLite does not support QueuePool with pool_size/max_overflow.
                # Use NullPool so each call gets a fresh connection; this avoids
                # file-lock deadlocks when alembic or other components also open
                # the same DB file concurrently during startup.
                from sqlalchemy.pool import NullPool as _NullPool
                self._engine = create_engine(
                    sync_url,
                    poolclass=_NullPool,
                    echo=self.echo,
                    connect_args={"check_same_thread": False, "timeout": 30},
                )
            else:
                connect_args: dict = {}
                if is_pg:
                    connect_args = {
                        "connect_timeout": 10,
                        "options": "-c statement_timeout=30000",
                    }
                self._engine = create_engine(
                    sync_url,
                    poolclass=QueuePool,
                    pool_size=self.pool_size,
                    max_overflow=self.max_overflow,
                    pool_timeout=self.pool_timeout,
                    pool_recycle=self.pool_recycle,
                    pool_pre_ping=self.pool_pre_ping,
                    echo=self.echo,
                    connect_args=connect_args,
                )

            # Add event listeners for metrics
            event.listen(self._engine, "checkout", self._on_checkout)
            event.listen(self._engine, "checkin", self._on_checkin)
            event.listen(self._engine, "connect", self._on_connect)

            self._session_factory = sessionmaker(bind=self._engine)

            # Test connection
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            logger.info(
                "Database initialized | Pool: %s/%s | Engine: %s", self.pool_size, self.max_overflow, self._engine.name
            )

        except Exception as e:
            logger.critical("Database initialization failed: %s", e)
            raise

    def _on_checkout(self, dbapi_conn, connection_record, connection_proxy):
        """Called when connection is checked out from pool"""
        with self._metrics_lock:
            self._metrics.checked_out_connections += 1

    def _on_checkin(self, dbapi_conn, connection_record):
        """Called when connection is returned to pool"""
        with self._metrics_lock:
            self._metrics.checked_out_connections -= 1

    def _on_connect(self, dbapi_conn, connection_record):
        """Called when new connection created"""
        with self._metrics_lock:
            self._metrics.total_connections += 1

    def _check_circuit(self) -> bool:
        """
        Check if circuit breaker allows operation.

        States:
          CLOSED      — normal operation (_circuit_open=False)
          OPEN        — all requests rejected (_circuit_open=True, _circuit_half_open=False)
          HALF-OPEN   — one probe request allowed (_circuit_open=True, _circuit_half_open=True)
        """
        if not self._circuit_open:
            return True

        # Transition OPEN → HALF-OPEN after recovery window
        if self._last_failure_time and (
            time.time() - self._last_failure_time > self._circuit_recovery_time
        ):
            if not self._circuit_half_open:
                self._circuit_half_open = True
                logger.info("Database circuit breaker entering HALF-OPEN state — probe allowed")
            return True  # allow the probe request through

        return False

    def _record_success(self):
        """Record successful operation; close circuit if in half-open state."""
        if self._circuit_half_open:
            self._circuit_open = False
            self._circuit_half_open = False
            self._failure_count = 0
            logger.info("Database circuit breaker CLOSED after successful probe")
        else:
            self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self, exc: Exception | None = None):
        """Record failed operation; re-open circuit from half-open if probe fails."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        with self._metrics_lock:
            self._metrics.error_count += 1

        if self._circuit_half_open:
            # Probe failed — stay open, reset half-open flag
            self._circuit_half_open = False
            logger.warning("Database circuit breaker probe FAILED — staying OPEN: %s", exc)
        elif self._failure_count >= self._circuit_threshold:
            self._circuit_open = True
            self._circuit_half_open = False
            logger.critical(
                "Database circuit breaker OPENED after %d failures: %s",
                self._failure_count,
                exc,
            )

    @contextmanager
    def session(self) -> "Generator[Session, None, None]":
        """
        Get database session with automatic cleanup and retry logic

        Usage:
            with db_manager.session() as session:
                result = session.query(Model).all()
        """
        if not self._check_circuit():
            raise ConnectionError("Database circuit breaker is open")

        session: Session | None = None
        last_error = None
        t0 = time.perf_counter()

        for attempt in range(self.max_retries):
            try:
                session = self._session_factory()

                # Set query timeout — value is int-coerced, no user input
                if "postgresql" in self.connection_string:
                    timeout_ms = int(self.query_timeout * 1000)
                    session.execute(text(f"SET statement_timeout = '{timeout_ms}ms'"))  # nosec S608

                yield session

                session.commit()
                self._record_success()

                elapsed_ms = (time.perf_counter() - t0) * 1000
                with self._metrics_lock:
                    self._metrics.query_count += 1
                    self._metrics.record_latency(elapsed_ms)
                    if elapsed_ms > self.query_timeout * 1000 * 0.8:
                        self._metrics.slow_query_count += 1

                return

            except OperationalError as e:
                last_error = e
                self._record_failure(e)

                if session:
                    session.rollback()

                logger.warning("Database operational error (attempt %s): %s", attempt + 1, e)

                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    logger.info("Retrying in %ss...", wait_time)
                    time.sleep(wait_time)

            except SATimeoutError as e:
                last_error = e
                self._record_failure(e)

                if session:
                    session.rollback()

                logger.error("Database query timeout: %s", e)

                with self._metrics_lock:
                    self._metrics.slow_query_count += 1

                raise  # Don't retry timeouts

            except Exception as e:
                last_error = e
                self._record_failure(e)

                if session:
                    session.rollback()

                logger.error("Database error: %s", e)
                raise

            finally:
                if session:
                    session.close()

        # All retries exhausted
        raise last_error or ConnectionError("Max retries exceeded")

    def execute_with_retry(self, operation: Callable, *args, **kwargs):
        """Execute database operation with retry logic."""
        for attempt in range(self.max_retries):
            try:
                with self.session() as session:
                    return operation(session, *args, **kwargs)
            except OperationalError as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt
                    logger.warning("DB retry %s/%s in %ss: %s", attempt + 1, self.max_retries, wait_time, e)
                    time.sleep(wait_time)
                else:
                    raise

    @contextmanager
    def timed_session(self) -> "Generator[Session, None, None]":
        """Alias for session() — latency is already recorded inside session()."""
        with self.session() as s:
            yield s

    def health_check(self) -> bool:
        """Check database connectivity"""
        if self._circuit_open:
            return False

        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Database health check failed: %s", e)
            return False

    def get_metrics(self) -> dict[str, Any]:
        """Get current database metrics including p50/p99 latency."""
        with self._metrics_lock:
            # Refresh live pool stats
            if self._engine and hasattr(self._engine.pool, "size"):
                try:
                    self._metrics.pool_size = self._engine.pool.size()
                    self._metrics.active_connections = self._engine.pool.checkedout()
                    self._metrics.idle_connections = self._engine.pool.checkedin()
                    self._metrics.pool_overflow = self._engine.pool.overflow()
                except Exception:  # nosec B110
                    pass
            return self._metrics.to_dict()

    def close(self):
        """Close all database connections"""
        if self._engine:
            self._engine.dispose()
            logger.info("Database connections closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class DatabaseMigrationManager:
    """
    Database migration management
    Simple version - consider Alembic for complex migrations
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create_tables(self, base):
        """Create all tables"""
        with self.db_manager._engine.begin() as conn:
            base.metadata.create_all(conn)
        logger.info("Database tables created")

    def drop_tables(self, base):
        """Drop all tables"""
        with self.db_manager._engine.begin() as conn:
            base.metadata.drop_all(conn)
        logger.info("Database tables dropped")

    def get_table_stats(self) -> dict[str, int]:
        """Get row counts for all tables"""
        stats = {}

        with self.db_manager.session() as session:
            from sqlalchemy import inspect

            inspector = inspect(self.db_manager._engine)

            for table_name in inspector.get_table_names():
                try:
                    # quoted_name wraps the identifier in dialect-appropriate
                    # quotes, preventing SQL injection via table names.
                    from sqlalchemy.sql import quoted_name

                    safe_name = quoted_name(table_name, quote=True)
                    result = session.execute(
                        text(f"SELECT COUNT(*) FROM {safe_name}")  # nosec B608 - table name wrapped in quoted_name() by SQLAlchemy
                    )
                    count = result.scalar()
                    stats[table_name] = count
                except Exception as e:
                    logger.error("Error getting count for %s: %s", table_name, e)
                    stats[table_name] = -1

        return stats


# ---------------------------------------------------------------------------
# Async database manager (SQLAlchemy 2.x async engine + asyncpg)
# ---------------------------------------------------------------------------

try:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import NullPool, StaticPool

    ASYNC_SQLALCHEMY_AVAILABLE = True
except ImportError:
    ASYNC_SQLALCHEMY_AVAILABLE = False
    AsyncSession = None  # type: ignore[assignment,misc]
    async_sessionmaker = None  # type: ignore[assignment]
    create_async_engine = None  # type: ignore[assignment]
    NullPool = None  # type: ignore[assignment,misc]
    StaticPool = None  # type: ignore[assignment,misc]


class AsyncDatabaseManager:
    """
    Async SQLAlchemy engine backed by asyncpg (PostgreSQL) or aiosqlite (SQLite).

    Provides:
    - Async connection pool with configurable size and overflow
    - Per-query latency tracking
    - Circuit breaker integration
    - Health check coroutine
    - async_session() context manager for use in FastAPI async endpoints

    Usage::

        async with async_db_manager.async_session() as session:
            result = await session.execute(select(Trade))
            trades = result.scalars().all()
    """

    def __init__(
        self,
        connection_string: str,
        pool_size: int = 20,
        max_overflow: int = 40,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo: bool = False,
        max_retries: int = 3,
        query_timeout: float = 30.0,
    ) -> None:
        if not ASYNC_SQLALCHEMY_AVAILABLE:
            raise ImportError(
                "sqlalchemy[asyncio] required. Install: pip install 'sqlalchemy[asyncio]' asyncpg aiosqlite"
            )

        self.connection_string = connection_string
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo = echo
        self.max_retries = max_retries
        self.query_timeout = query_timeout

        self._engine = None
        self._session_factory = None
        self._metrics = DatabaseMetrics()
        self._metrics_lock = threading.Lock()
        self._circuit_open = False
        self._circuit_half_open = False
        self._failure_count = 0
        self._circuit_threshold = 5
        self._circuit_recovery_time = 60.0
        self._last_failure_time: float | None = None

        self._initialize()

    def _async_url(self, url: str) -> str:
        """Convert a sync DB URL to its async driver equivalent."""
        if url.startswith("postgresql://") or url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
                "postgresql+psycopg2://", "postgresql+asyncpg://", 1
            )
        if url.startswith("sqlite://"):
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url

    def _initialize(self) -> None:
        async_url = self._async_url(self.connection_string)
        connect_args: dict = {}
        if "asyncpg" in async_url:
            connect_args = {
                "command_timeout": self.query_timeout,
                "server_settings": {"application_name": "hopefx_async"},
            }
        elif "aiosqlite" in async_url:
            connect_args = {"check_same_thread": False}

        # SQLite (aiosqlite) does not support QueuePool — use NullPool so each
        # call gets a fresh connection.  This avoids file-lock deadlocks when
        # the sync engine (alembic, DatabaseManager) also opens the same DB
        # file concurrently during startup.  pool_size and max_overflow are
        # QueuePool-only kwargs and must be omitted for NullPool.
        if "aiosqlite" in async_url:
            self._engine = create_async_engine(
                async_url,
                poolclass=NullPool,
                echo=self.echo,
                connect_args=connect_args,
            )
        else:
            self._engine = create_async_engine(
                async_url,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_recycle=self.pool_recycle,
                pool_pre_ping=self.pool_pre_ping,
                echo=self.echo,
                connect_args=connect_args,
            )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        logger.info(
            "AsyncDatabaseManager initialized | pool=%s/%s | url=%s",
            self.pool_size,
            self.max_overflow,
            async_url.split("@")[-1] if "@" in async_url else async_url,
        )

    def _check_circuit(self) -> bool:
        """
        CLOSED → normal; OPEN → reject; HALF-OPEN → allow one probe.
        Transitions OPEN → HALF-OPEN after _circuit_recovery_time seconds.
        """
        if not self._circuit_open:
            return True
        if self._last_failure_time and (
            time.time() - self._last_failure_time > self._circuit_recovery_time
        ):
            if not self._circuit_half_open:
                self._circuit_half_open = True
                logger.info("AsyncDatabaseManager circuit breaker entering HALF-OPEN — probe allowed")
            return True
        return False

    def _record_failure(self, exc: Exception) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        with self._metrics_lock:
            self._metrics.error_count += 1
        if self._circuit_half_open:
            self._circuit_half_open = False
            logger.warning("AsyncDatabaseManager probe FAILED — circuit stays OPEN: %s", exc)
        elif self._failure_count >= self._circuit_threshold:
            self._circuit_open = True
            self._circuit_half_open = False
            logger.critical(
                "AsyncDatabaseManager circuit breaker OPENED after %d failures: %s",
                self._failure_count,
                exc,
            )

    def _record_success(self) -> None:
        if self._circuit_half_open:
            self._circuit_open = False
            self._circuit_half_open = False
            self._failure_count = 0
            logger.info("AsyncDatabaseManager circuit breaker CLOSED after successful probe")
        else:
            self._failure_count = max(0, self._failure_count - 1)

    @asynccontextmanager
    async def async_session(self) -> "AsyncGenerator[AsyncSession, None]":
        """
        Async session context manager with automatic commit/rollback.

        Integrates with the resilience circuit breaker.  Retries on
        OperationalError up to max_retries times with exponential back-off.
        """
        if not self._check_circuit():
            raise ConnectionError(
                "AsyncDatabaseManager circuit breaker is OPEN — service temporarily unavailable."
            )

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            session: AsyncSession = self._session_factory()
            t0 = time.perf_counter()
            try:
                yield session
                await session.commit()
                elapsed_ms = (time.perf_counter() - t0) * 1000
                with self._metrics_lock:
                    self._metrics.query_count += 1
                    self._metrics.record_latency(elapsed_ms)
                    if elapsed_ms > self.query_timeout * 1000 * 0.8:
                        self._metrics.slow_query_count += 1
                self._record_success()
                return
            except Exception as exc:
                try:
                    await session.rollback()
                except Exception as rb_exc:
                    logger.debug("AsyncDB rollback failed (connection lost?): %s", rb_exc)
                last_exc = exc
                self._record_failure(exc)
                if attempt < self.max_retries - 1:
                    wait = 2**attempt
                    logger.warning(
                        "AsyncDB retry %d/%d in %.1fs: %s",
                        attempt + 1,
                        self.max_retries,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise
            finally:
                await session.close()

        raise last_exc or ConnectionError("AsyncDatabaseManager: max retries exceeded")

    async def health_check(self) -> bool:
        """Ping the database asynchronously."""
        if self._circuit_open:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.error("AsyncDatabaseManager health check failed: %s", exc)
            return False

    def get_metrics(self) -> dict[str, Any]:
        with self._metrics_lock:
            return self._metrics.to_dict()

    async def dispose(self) -> None:
        """Close all async connections."""
        if self._engine:
            await self._engine.dispose()
            logger.info("AsyncDatabaseManager: connections disposed")


# Global instances
_db_manager: DatabaseManager | None = None
_async_db_manager: AsyncDatabaseManager | None = None


def get_db_manager() -> DatabaseManager | None:
    """Return the global sync database manager, initialising lazily if needed."""
    global _db_manager
    if _db_manager is None:
        try:
            _db_manager = _get_or_init_manager()
        except Exception:  # nosec B110
            return None
    return _db_manager


def init_db_manager(connection_string: str, **kwargs) -> DatabaseManager:
    """Initialize the global sync database manager."""
    global _db_manager
    _db_manager = DatabaseManager(connection_string, **kwargs)
    return _db_manager


def get_async_db_manager() -> AsyncDatabaseManager | None:
    """Return the global async database manager."""
    return _async_db_manager


def init_async_db_manager(connection_string: str, **kwargs) -> AsyncDatabaseManager:
    """Initialize the global async database manager."""
    global _async_db_manager
    _async_db_manager = AsyncDatabaseManager(connection_string, **kwargs)
    return _async_db_manager


# ---------------------------------------------------------------------------
# FastAPI / SQLAlchemy compatibility shims
# ---------------------------------------------------------------------------
# These module-level names are the conventional FastAPI pattern used throughout
# the codebase (get_db, engine, SessionLocal).  They are backed by a lazy
# singleton so the first import does not require DATABASE_URL to be set.

import os as _os
from pathlib import Path as _Path


def _default_db_url() -> str:
    url = _os.getenv("DATABASE_URL", "")
    if not url:
        fallback = f"sqlite:///{_os.path.join(_Path(__file__).parent, '..', 'hopefx.db')}"
        import warnings as _warnings

        _warnings.warn(
            "DATABASE_URL is not set — falling back to SQLite "
            f"({fallback}). SQLite does not support concurrent writes; "
            "set DATABASE_URL=postgresql://... for production use.",
            RuntimeWarning,
            stacklevel=3,
        )
        logger.warning(
            "DATABASE_URL not set — using SQLite fallback (%s). "
            "SQLite does not support concurrent writes. "
            "Set DATABASE_URL=postgresql://user:pass@host:5432/hopefx for production.",  # pragma: allowlist secret
            fallback,
        )
        return fallback
    return url


def _check_sqlite_multiworker(url: str) -> None:
    """Raise RuntimeError when SQLite is configured in a multi-worker deployment.

    SQLite uses file-level locking; concurrent writes from multiple OS processes
    (e.g. ``uvicorn --workers 4``) corrupt the database.  PostgreSQL or another
    server-based engine is required for any multi-worker or multi-node setup.
    """
    if not url.startswith("sqlite"):
        return
    # WEB_CONCURRENCY is set by Gunicorn, uvicorn-gunicorn-fastapi images, and
    # Heroku/Render.  --workers CLI flag sets it automatically.
    concurrency_value = _os.getenv("WEB_CONCURRENCY", "1")
    try:
        concurrency = int(concurrency_value)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid WEB_CONCURRENCY configuration: expected an integer, got {concurrency_value!r}."
        ) from exc
    if concurrency > 1:
        raise RuntimeError(
            f"DATABASE_URL is SQLite but WEB_CONCURRENCY={concurrency}. "
            "SQLite cannot safely handle concurrent writes from multiple OS processes "
            "and will corrupt data. Set DATABASE_URL to a PostgreSQL connection string "
            "(e.g. postgresql+psycopg2://user:pass@host/db) before starting with "  # pragma: allowlist secret
            "multiple workers."
        )
    # Warn even for single-worker so operators know this is dev-only.
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "DATABASE_URL is using SQLite (%s). "
        "This is only suitable for local development. "
        "Use PostgreSQL for any production or multi-worker deployment.",
        url,
    )


def _get_or_init_manager() -> "DatabaseManager":
    """Return the global manager, initialising it with defaults if needed."""
    global _db_manager
    if _db_manager is None:
        url = _default_db_url()
        _check_sqlite_multiworker(url)
        _db_manager = DatabaseManager(url)
    return _db_manager


def _get_or_init_async_manager() -> "AsyncDatabaseManager":
    """Return the global async manager, initialising it with defaults if needed."""
    global _async_db_manager
    if _async_db_manager is None:
        url = _default_db_url()
        _check_sqlite_multiworker(url)
        _async_db_manager = AsyncDatabaseManager(url)
    return _async_db_manager


if SQLALCHEMY_AVAILABLE:

    class _LazyEngine:
        """Proxy that forwards attribute access to the real engine."""

        def __getattr__(self, name: str):
            return getattr(_get_or_init_manager()._engine, name)

        def connect(self):
            return _get_or_init_manager()._engine.connect()

        def begin(self):
            return _get_or_init_manager()._engine.begin()

        def dispose(self):
            return _get_or_init_manager()._engine.dispose()

    engine = _LazyEngine()

    class _LazySessionLocal:
        """Proxy that creates sessions via the global manager."""

        def __call__(self):
            return _get_or_init_manager()._session_factory()

        def __getattr__(self, name: str):
            return getattr(_get_or_init_manager()._session_factory, name)

    SessionLocal = _LazySessionLocal()

    def get_db():
        """
        FastAPI dependency that yields a SQLAlchemy session.

        Uses DatabaseManager.session() so the session is always committed on
        success and rolled back on exception before being closed — preventing
        connections from being returned to the pool in a dirty state.

        The resilience circuit breaker is checked before opening a session.
        When the DB has been failing repeatedly the breaker opens and raises
        immediately rather than blocking on a connection timeout.

        Usage::

            @router.get("/items")
            def list_items(db: Session = Depends(get_db)):
                ...
        """
        # Check resilience circuit breaker before attempting a connection.
        try:
            from resilience.service_circuit_breakers import db_breaker

            if db_breaker.is_open:
                raise RuntimeError(
                    "Database circuit breaker is OPEN — service temporarily unavailable. "
                    f"Retry in {db_breaker._seconds_until_probe():.0f}s."
                )
        except ImportError:  # nosec B110 — circuit breaker is optional; proceed without it
            pass

        # Use the manager's context manager so commit/rollback/close are
        # handled correctly even when the request handler raises.
        try:
            with _get_or_init_manager().session() as db:
                # Record success with the resilience circuit breaker.
                try:
                    from resilience.service_circuit_breakers import db_breaker as _db_cb

                    _db_cb.record_success()
                except Exception:  # nosec B110 — circuit breaker is non-fatal
                    pass
                yield db
        except Exception as _db_exc:
            # Record failure with the resilience circuit breaker.
            try:
                from resilience.service_circuit_breakers import db_breaker as _db_cb

                _db_cb.record_failure(_db_exc)
            except Exception:  # nosec B110 — circuit breaker is non-fatal
                pass
            raise

    async def get_async_db() -> "AsyncGenerator[AsyncSession, None]":
        """
        FastAPI async dependency that yields an AsyncSession.

        Usage::

            @router.get("/items")
            async def list_items(db: AsyncSession = Depends(get_async_db)):
                result = await db.execute(select(Item))
                return result.scalars().all()
        """
        try:
            from resilience.service_circuit_breakers import db_breaker

            if db_breaker.is_open:
                raise RuntimeError(
                    "Database circuit breaker is OPEN — service temporarily unavailable. "
                    f"Retry in {db_breaker._seconds_until_probe():.0f}s."
                )
        except ImportError:  # nosec B110
            pass

        try:
            async with _get_or_init_async_manager().async_session() as session:
                try:
                    from resilience.service_circuit_breakers import db_breaker as _cb

                    _cb.record_success()
                except Exception:  # nosec B110
                    pass
                yield session
        except Exception as _exc:
            try:
                from resilience.service_circuit_breakers import db_breaker as _cb

                _cb.record_failure(_exc)
            except Exception:  # nosec B110
                pass
            raise

else:
    # Stubs when SQLAlchemy is not installed (test / CI environments).
    engine = None  # type: ignore[assignment]
    SessionLocal = None  # type: ignore[assignment]

    def get_db():  # type: ignore[misc]
        raise RuntimeError("SQLAlchemy is not installed — database features unavailable.")

    async def get_async_db():  # type: ignore[misc]
        raise RuntimeError("SQLAlchemy is not installed — async database features unavailable.")
        yield  # make it a generator
