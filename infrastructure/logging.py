# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Logging Infrastructure
Structured logging with JSON output, log rotation, and remote shipping
"""

import json
import logging
import logging.handlers
import os
import queue
import sys
import threading
import traceback
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, Optional

logger = logging.getLogger(__name__)
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import importlib.util as _importlib_util

JSON_LOGGER_AVAILABLE = _importlib_util.find_spec("pythonjsonlogger") is not None

try:
    import graypy  # For Graylog integration

    GRAYLOG_AVAILABLE = True
except ImportError:
    GRAYLOG_AVAILABLE = False


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogContext:
    """Structured log context"""

    component: str = "unknown"
    request_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    extra: dict[str, Any] = None

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            **(self.extra or {}),
        }


class StructuredLogFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        super().__init__(fmt, datefmt)
        self.hostname = socket.gethostname()
        self.pid = os.getpid()

    def format(self, record: logging.LogRecord) -> str:
        log_dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "source": {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
                "module": record.module,
            },
            "process": {"pid": self.pid, "hostname": self.hostname},
            "thread": {"id": record.thread, "name": record.threadName},
        }

        # Add exception info
        if record.exc_info:
            log_dict["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add extra fields
        if hasattr(record, "context"):
            log_dict["context"] = record.context.to_dict() if isinstance(record.context, LogContext) else record.context

        # Add any custom attributes
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "context",
                "getMessage",
                "message",
            ]:
                log_dict[key] = value

        return json.dumps(log_dict, default=str)


class AsyncLogHandler(logging.Handler):
    """Asynchronous log handler using queue"""

    def __init__(self, target_handler: logging.Handler, max_queue_size: int = 10000):
        super().__init__()
        self.target_handler = target_handler
        self.queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.dropped_count = 0
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        """Start the worker thread"""
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

    def stop(self, timeout: float = 5.0):
        """Stop the worker thread"""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)

    def emit(self, record: logging.LogRecord):
        """Add record to queue"""
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            with self._lock:
                self.dropped_count += 1

    def _process_queue(self):
        """Process log queue"""
        while not self._stop_event.is_set():
            try:
                record = self.queue.get(timeout=0.1)
                self.target_handler.emit(record)
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                # Can't use logger here — we're inside the log handler itself.
                # Write directly to stderr to avoid infinite recursion.
                print(f"AsyncLogHandler: error processing log record: {e}", file=sys.stderr)

    def get_stats(self) -> dict:
        """Get handler statistics"""
        return {
            "queue_size": self.queue.qsize(),
            "dropped_count": self.dropped_count,
            "max_size": self.queue.maxsize,
        }


class HOPEFXLogger:
    """
    Centralized logging manager for HOPEFX

    Features:
    - Structured JSON logging
    - Log rotation by size and time
    - Async processing to prevent blocking
    - Remote shipping (Graylog, ELK)
    - Context propagation
    - Performance metrics
    """

    _instance: Optional["HOPEFXLogger"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:  # pylint: disable=access-member-before-definition
            return

        with self._lock:
            if self._initialized:  # pylint: disable=access-member-before-definition
                return

            self._loggers: dict[str, logging.Logger] = {}
            self._context = threading.local()
            self._async_handlers: list[AsyncLogHandler] = []
            self._metrics = {"logs_emitted": 0, "logs_dropped": 0, "errors": 0}

            self._initialized = True

    def setup(
        self,
        level: str = "INFO",
        log_dir: str = "logs",
        app_name: str = "hopefx",
        json_format: bool = True,
        async_mode: bool = True,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        enable_console: bool = True,
        enable_graylog: bool = False,
        graylog_host: str | None = None,
        graylog_port: int = 12201,
    ):
        """Setup logging infrastructure"""

        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # Root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, level.upper()))

        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Console handler
        # On Windows the default stdout encoding is CP1252 which cannot encode
        # Unicode symbols used in log messages (e.g. checkmarks, box-drawing).
        # Reconfigure stdout to UTF-8 when possible (Python 3.7+).
        if enable_console:
            try:
                if hasattr(sys.stdout, "reconfigure"):
                    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # nosec B110  # noqa: S110
                pass
            console_handler = logging.StreamHandler(sys.stdout)
            if json_format:
                console_handler.setFormatter(StructuredLogFormatter())
            else:
                console_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
                    )
                )

            if async_mode:
                async_console = AsyncLogHandler(console_handler)
                async_console.start()
                self._async_handlers.append(async_console)
                root_logger.addHandler(async_console)
            else:
                root_logger.addHandler(console_handler)

        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            log_path / f"{app_name}.log", maxBytes=max_bytes, backupCount=backup_count
        )

        if json_format:
            file_handler.setFormatter(StructuredLogFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s")
            )

        if async_mode:
            async_file = AsyncLogHandler(file_handler)
            async_file.start()
            self._async_handlers.append(async_file)
            root_logger.addHandler(async_file)
        else:
            root_logger.addHandler(file_handler)

        # Error log (separate file for errors)
        error_handler = logging.handlers.RotatingFileHandler(
            log_path / f"{app_name}_errors.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredLogFormatter())

        if async_mode:
            async_error = AsyncLogHandler(error_handler)
            async_error.start()
            self._async_handlers.append(async_error)
            root_logger.addHandler(async_error)
        else:
            root_logger.addHandler(error_handler)

        # Graylog handler
        if enable_graylog and GRAYLOG_AVAILABLE and graylog_host:
            graylog_handler = graypy.GELFUDPHandler(graylog_host, graylog_port)
            root_logger.addHandler(graylog_handler)
            logger.info("Graylog shipping enabled: %s:%s", graylog_host, graylog_port)

        # Audit log (for security events)
        audit_handler = logging.handlers.RotatingFileHandler(
            log_path / f"{app_name}_audit.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        audit_handler.setFormatter(StructuredLogFormatter())
        self._audit_logger = logging.getLogger("hopefx.audit")
        self._audit_logger.addHandler(audit_handler)
        self._audit_logger.setLevel(logging.INFO)

        logger.info(
            "Logging initialized: level=%s, json=%s, async=%s, dir=%s", level, json_format, async_mode, log_path
        )

    def set_context(self, context: LogContext):
        """Set logging context for current thread"""
        self._context.context = context

    def get_context(self) -> LogContext | None:
        """Get current logging context"""
        return getattr(self._context, "context", None)

    def clear_context(self):
        """Clear logging context"""
        self._context.context = None

    def get_logger(self, name: str) -> logging.Logger:
        """Get logger with context support"""
        logger = logging.getLogger(name)

        # Add context filter
        class ContextFilter(logging.Filter):
            def filter(self, record):
                context = HOPEFXLogger().get_context()
                if context:
                    record.context = context
                return True

        logger.addFilter(ContextFilter())
        return logger

    def audit(self, event: str, details: dict[str, Any]):
        """Log audit event"""
        self._audit_logger.info("AUDIT: %s", event, extra={"audit_details": details})

    def get_metrics(self) -> dict:
        """Get logging metrics"""
        metrics = self._metrics.copy()
        metrics["async_handlers"] = [handler.get_stats() for handler in self._async_handlers]
        return metrics

    def shutdown(self):
        """Shutdown logging gracefully"""
        logger.info("Shutting down logging...")

        for handler in self._async_handlers:
            handler.stop()

        logging.shutdown()


# Convenience functions
def get_logger(name: str) -> logging.Logger:
    """Get logger"""
    return HOPEFXLogger().get_logger(name)


def audit(event: str, details: dict[str, Any]):
    """Log audit event"""
    HOPEFXLogger().audit(event, details)


def set_context(**kwargs):
    """Set context"""
    HOPEFXLogger().set_context(LogContext(**kwargs))


def clear_context():
    """Clear context"""
    HOPEFXLogger().clear_context()
