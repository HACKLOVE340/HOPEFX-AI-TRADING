"""
HOPEFX Logging Infrastructure
Structured logging with JSON output, log rotation, and remote shipping
"""

import logging
import logging.handlers
import json
import sys
import os
import queue
import threading
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
import socket
import platform

try:
    from pythonjsonlogger import jsonlogger
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False

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
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra: Dict[str, Any] = None
    
    def to_dict(self) -> Dict:
        return {
            'component': self.component,
            'request_id': self.request_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'trace_id': self.trace_id,
            **(self.extra or {})
        }


class StructuredLogFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt, datefmt)
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
    
    def format(self, record: logging.LogRecord) -> str:
        log_dict = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'source': {
                'file': record.filename,
                'line': record.lineno,
                'function': record.funcName,
                'module': record.module
            },
            'process': {
                'pid': self.pid,
                'hostname': self.hostname
            },
            'thread': {
                'id': record.thread,
                'name': record.threadName
            }
        }
        
        # Add exception info
        if record.exc_info:
            log_dict['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields
        if hasattr(record, 'context'):
            log_dict['context'] = record.context.to_dict() if isinstance(record.context, LogContext) else record.context
        
        # Add any custom attributes
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                          'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                          'thread', 'threadName', 'processName', 'process', 'context',
                          'getMessage', 'message']:
                log_dict[key] = value
        
        return json.dumps(log_dict, default=str)


class AsyncLogHandler(logging.Handler):
    """Asynchronous log handler using queue"""
    
    def __init__(self, target_handler: logging.Handler, max_queue_size: int = 10000):
        super().__init__()
        self.target_handler = target_handler
        self.queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.dropped_count = 0
        self._worker_thread: Optional[threading.Thread] = None
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
                print(f"Error processing log: {e}", file=sys.stderr)
    
    def get_stats(self) -> Dict:
        """Get handler statistics"""
        return {
            'queue_size': self.queue.qsize(),
            'dropped_count': self.dropped_count,
            'max_size': self.queue.maxsize
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
    
    _instance: Optional['HOPEFXLogger'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._loggers: Dict[str, logging.Logger] = {}
            self._context = threading.local()
            self._async_handlers: List[AsyncLogHandler] = []
            self._metrics = {
                'logs_emitted': 0,
                'logs_dropped': 0,
                'errors': 0
            }
            
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
        graylog_host: Optional[str] = None,
        graylog_port: int = 12201
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
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            if json_format and JSON_LOGGER_AVAILABLE:
                console_handler.setFormatter(StructuredLogFormatter())
            else:
                console_handler.setFormatter(
                    logging.Formatter(
                        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
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
            log_path / f"{app_name}.log",
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        
        if json_format:
            file_handler.setFormatter(StructuredLogFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
                )
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
            backupCount=backup_count
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
            logger.info(f"Graylog shipping enabled: {graylog_host}:{graylog_port}")
        
        # Audit log (for security events)
        audit_handler = logging.handlers.RotatingFileHandler(
            log_path / f"{app_name}_audit.log",
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        audit_handler.setFormatter(StructuredLogFormatter())
        self._audit_logger = logging.getLogger("hopefx.audit")
        self._audit_logger.addHandler(audit_handler)
        self._audit_logger.setLevel(logging.INFO)
        
        logger.info(
            f"Logging initialized: level={level}, json={json_format}, "
            f"async={async_mode}, dir={log_path}"
        )
    
    def set_context(self, context: LogContext):
        """Set logging context for current thread"""
        self._context.context = context
    
    def get_context(self) -> Optional[LogContext]:
        """Get current logging context"""
        return getattr(self._context, 'context', None)
    
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
    
    def audit(self, event: str, details: Dict[str, Any]):
        """Log audit event"""
        self._audit_logger.info(
            f"AUDIT: {event}",
            extra={'audit_details': details}
        )
    
    def get_metrics(self) -> Dict:
        """Get logging metrics"""
        metrics = self._metrics.copy()
        metrics['async_handlers'] = [
            handler.get_stats() for handler in self._async_handlers
        ]
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


def audit(event: str, details: Dict[str, Any]):
    """Log audit event"""
    HOPEFXLogger().audit(event, details)


def set_context(**kwargs):
    """Set context"""
    HOPEFXLogger().set_context(LogContext(**kwargs))


def clear_context():
    """Clear context"""
    HOPEFXLogger().clear_context()
