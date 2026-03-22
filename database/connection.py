"""
HOPEFX Database Connection Management
SQLAlchemy with connection pooling, retries, and monitoring
"""

import logging
import time
import threading
from typing import Optional, Dict, Any, List, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

try:
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import QueuePool
    from sqlalchemy.exc import SQLAlchemyError, OperationalError, TimeoutError as SATimeoutError
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    logging.warning("SQLAlchemy not available, database features disabled")

logger = logging.getLogger(__name__)


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
        query_timeout: float = 30.0
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
        
        self._engine: Optional[Engine] = None
        self._session_factory = None
        self._metrics = DatabaseMetrics()
        self._metrics_lock = threading.Lock()
        self._circuit_open = False
        self._failure_count = 0
        self._circuit_threshold = 5
        self._circuit_recovery_time = 60.0
        self._last_failure_time: Optional[float] = None
        
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
                    'connect_timeout': 10,
                    'options': '-c statement_timeout=30000'  # 30s PostgreSQL
                } if 'postgresql' in self.connection_string else {}
            )
            
            # Add event listeners for metrics
            event.listen(self._engine, 'checkout', self._on_checkout)
            event.listen(self._engine, 'checkin', self._on_checkin)
            event.listen(self._engine, 'connect', self._on_connect)
            
            self._session_factory = sessionmaker(bind=self._engine)
            
            # Test connection
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            logger.info(
                f"Database initialized | Pool: {self.pool_size}/{self.max_overflow} | "
                f"Engine: {self._engine.name}"
            )
            
        except Exception as e:
            logger.critical(f"Database initialization failed: {e}")
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
            logger.critical(f"Database circuit breaker OPENED after {self._failure_count} failures")
    
    @contextmanager
    def session(self):
        """
        Get database session with automatic cleanup and retry logic
        
        Usage:
            with db_manager.session() as session:
                result = session.query(Model).all()
        """
        if not self._check_circuit():
            raise ConnectionError("Database circuit breaker is open")
        
        session: Optional[Session] = None
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                session = self._session_factory()
                
                # Set query timeout
                if 'postgresql' in self.connection_string:
                    session.execute(text(f"SET statement_timeout = '{int(self.query_timeout * 1000)}ms'"))
                
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
                
                logger.warning(f"Database operational error (attempt {attempt + 1}): {e}")
                
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    
            except SATimeoutError as e:
                last_error = e
                self._record_failure()
                
                if session:
                    session.rollback()
                
                logger.error(f"Database query timeout: {e}")
                
                with self._metrics_lock:
                    self._metrics.slow_query_count += 1
                
                raise  # Don't retry timeouts
                
            except Exception as e:
                last_error = e
                self._record_failure()
                
                if session:
                    session.rollback()
                
                logger.error(f"Database error: {e}")
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
                    wait_time = 2 ** attempt
                    logger.warning(f"DB retry {attempt + 1}/{self.max_retries} in {wait_time}s: {e}")
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
            logger.error(f"Database health check failed: {e}")
            return False
    
    def get_metrics(self) -> DatabaseMetrics:
        """Get current database metrics"""
        with self._metrics_lock:
            # Update pool stats
            if self._engine and hasattr(self._engine.pool, 'size'):
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
                slow_query_count=self._metrics.slow_query_count
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
    
    def get_table_stats(self) -> Dict[str, int]:
        """Get row counts for all tables"""
        stats = {}
        
        with self.db_manager.session() as session:
            from sqlalchemy import inspect
            inspector = inspect(self.db_manager._engine)
            
            for table_name in inspector.get_table_names():
                try:
                    result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    count = result.scalar()
                    stats[table_name] = count
                except Exception as e:
                    logger.error(f"Error getting count for {table_name}: {e}")
                    stats[table_name] = -1
        
        return stats


# Global instance
_db_manager: Optional[DatabaseManager] = None

def get_db_manager() -> Optional[DatabaseManager]:
    """Get global database manager"""
    global _db_manager
    return _db_manager

def init_db_manager(connection_string: str, **kwargs) -> DatabaseManager:
    """Initialize global database manager"""
    global _db_manager
    _db_manager = DatabaseManager(connection_string, **kwargs)
    return _db_manager
