# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Database Connection Management
SQLAlchemy with connection pooling, retries, and monitoring
"""

import logging
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass

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
    """Database connection metrics"""

    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    checked_out_connections: int = 0
    checkout_time_avg_ms: float = 0.0
    query_count: int = 0
    error_count: int = 0
    slow_query_count: int = 0


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
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: float = 30.0,
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
        self._failure_count = 0
        self._circuit_threshold = 5
        self._circuit_recovery_time = 60.0
        self._last_failure_time: float | None = None

        self._initialize()

    def _initialize(self):
        """Initialize database engine with event listeners"""
        try:
            self._engine = create_engine(
                self.connection_string,
                poolclass=QueuePool,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
                pool_pre_ping=self.pool_pre_ping,
                echo=self.echo,
                connect_args={
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=30000",  # 30s PostgreSQL
                }
                if "postgresql" in self.connection_string
                else {},
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
        """Check if circuit breaker allows operation"""
        if not self._circuit_open:
            return True

        # Try recovery
        if self._last_failure_time and (time.time() - self._last_failure_time > self._circuit_recovery_time):
            self._circuit_open = False
            self._failure_count = 0
            logger.info("Database circuit breaker recovered")
            return True

        return False

    def _record_success(self):
        """Record successful operation"""
        self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self):
        """Record failed operation"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self._circuit_threshold:
            self._circuit_open = True
            logger.critical("Database circuit breaker OPENED after %s failures", self._failure_count)

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

                with self._metrics_lock:
                    self._metrics.query_count += 1

                return

            except OperationalError as e:
                last_error = e
                self._record_failure()

                if session:
                    session.rollback()

                logger.warning("Database operational error (attempt %s): %s", attempt + 1, e)

                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    logger.info("Retrying in %ss...", wait_time)
                    time.sleep(wait_time)

            except SATimeoutError as e:
                last_error = e
                self._record_failure()

                if session:
                    session.rollback()

                logger.error("Database query timeout: %s", e)

                with self._metrics_lock:
                    self._metrics.slow_query_count += 1

                raise  # Don't retry timeouts

            except Exception as e:
                last_error = e
                self._record_failure()

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
        """Execute database operation with retry logic"""
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

    def get_metrics(self) -> DatabaseMetrics:
        """Get current database metrics"""
        with self._metrics_lock:
            # Update pool stats
            if self._engine and hasattr(self._engine.pool, "size"):
                self._metrics.active_connections = self._engine.pool.checkedout()
                self._metrics.idle_connections = self._engine.pool.checkedin()

            return DatabaseMetrics(
                total_connections=self._metrics.total_connections,
                active_connections=self._metrics.active_connections,
                idle_connections=self._metrics.idle_connections,
                checked_out_connections=self._metrics.checked_out_connections,
                checkout_time_avg_ms=self._metrics.checkout_time_avg_ms,
                query_count=self._metrics.query_count,
                error_count=self._metrics.error_count,
                slow_query_count=self._metrics.slow_query_count,
            )

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


# Global instance
_db_manager: DatabaseManager | None = None


def get_db_manager() -> DatabaseManager | None:
    """Get global database manager"""
    return _db_manager


def init_db_manager(connection_string: str, **kwargs) -> DatabaseManager:
    """Initialize global database manager"""
    global _db_manager
    _db_manager = DatabaseManager(connection_string, **kwargs)
    return _db_manager


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
            "Set DATABASE_URL=postgresql://user:pass@host:5432/hopefx for production.",
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
            "(e.g. postgresql+psycopg2://user:pass@host/db) before starting with "
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

        Usage::

            @router.get("/items")
            def list_items(db: Session = Depends(get_db)):
                ...
        """
        db = _get_or_init_manager()._session_factory()
        try:
            yield db
        finally:
            db.close()

else:
    # Stubs when SQLAlchemy is not installed (test / CI environments).
    engine = None  # type: ignore[assignment]
    SessionLocal = None  # type: ignore[assignment]

    def get_db():  # type: ignore[misc]
        raise RuntimeError("SQLAlchemy is not installed — database features unavailable.")
