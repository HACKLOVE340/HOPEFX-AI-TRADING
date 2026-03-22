"""
Production-grade logging with rotation, JSON formatting, and correlation IDs
"""

import logging
import json
import sys
import uuid
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime
from typing import Optional, Dict, Any
import threading

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread_id': threading.get_ident(),
        }
        
        # Add correlation ID if present
        if hasattr(record, 'correlation_id'):
            log_obj['correlation_id'] = record.correlation_id
            
        # Add extra fields
        if hasattr(record, 'extra'):
            log_obj.update(record.extra)
            
        # Add exception info
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
            
        return json.dumps(log_obj)

class CorrelationIdFilter(logging.Filter):
    """Inject correlation ID into log records."""
    
    _local = threading.local()
    
    @classmethod
    def set_correlation_id(cls, cid: str):
        cls._local.correlation_id = cid
        
    @classmethod
    def get_correlation_id(cls) -> str:
        return getattr(cls._local, 'correlation_id', str(uuid.uuid4())[:8])
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = self.get_correlation_id()
        return True

def setup_logging(
    app_name: str = 'hopefx',
    log_dir: str = 'logs',
    level: str = 'INFO',
    json_format: bool = True,
    rotation: str = 'midnight'
) -> logging.Logger:
    """
    Setup production-grade logging.
    
    Args:
        app_name: Application name for log files
        log_dir: Directory for log files
        level: Logging level
        json_format: Use JSON formatting for production
        rotation: 'midnight', 'size', or None
    """
    
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    logger.handlers = []
    
    # Add correlation ID filter
    logger.addFilter(CorrelationIdFilter())
    
    # Console handler
    console = logging.StreamHandler(sys.stdout)
    if json_format:
        console.setFormatter(JSONFormatter())
    else:
        console.setFormatter(logging.Formatter(
            '%(asctime)s [%(correlation_id)s] %(levelname)s: %(message)s'
        ))
    logger.addHandler(console)
    
    # File handlers with rotation
    if rotation == 'midnight':
        file_handler = TimedRotatingFileHandler(
            f'{log_dir}/{app_name}.log',
            when='midnight',
            interval=1,
            backupCount=30  # Keep 30 days
        )
        error_handler = TimedRotatingFileHandler(
            f'{log_dir}/{app_name}_error.log',
            when='midnight',
            interval=1,
            backupCount=30
        )
    elif rotation == 'size':
        file_handler = RotatingFileHandler(
            f'{log_dir}/{app_name}.log',
            maxBytes=100*1024*1024,  # 100MB
            backupCount=10
        )
        error_handler = RotatingFileHandler(
            f'{log_dir}/{app_name}_error.log',
            maxBytes=100*1024*1024,
            backupCount=10
        )
    
    if json_format:
        file_handler.setFormatter(JSONFormatter())
        error_handler.setFormatter(JSONFormatter())
    
    error_handler.setLevel(logging.ERROR)
    
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    
    # Separate audit log for trading actions
    audit_handler = TimedRotatingFileHandler(
        f'{log_dir}/{app_name}_audit.log',
        when='midnight',
        backupCount=90  # Keep 90 days for compliance
    )
    audit_handler.setFormatter(JSONFormatter())
    audit_logger = logging.getLogger('hopefx.audit')
    audit_logger.addHandler(audit_handler)
    audit_logger.setLevel(logging.INFO)
    
    return logger

class TradeLogger:
    """Specialized logger for trading actions with audit compliance."""
    
    def __init__(self):
        self.logger = logging.getLogger('hopefx.audit')
        
    def log_order(self, order: Dict[str, Any], result: Dict[str, Any]):
        """Log order execution for audit trail."""
        self.logger.info('ORDER_EXECUTED', extra={
            'event_type': 'order',
            'order_id': order.get('id'),
            'symbol': order.get('symbol'),
            'side': order.get('side'),
            'quantity': order.get('quantity'),
            'price': order.get('price'),
            'broker': order.get('broker'),
            'status': result.get('status'),
            'commission': result.get('commission'),
            'timestamp': datetime.utcnow().isoformat()
        })
    
    def log_position_change(self, position: Dict[str, Any]):
        """Log position updates."""
        self.logger.info('POSITION_UPDATE', extra={
            'event_type': 'position',
            'position_id': position.get('id'),
            'symbol': position.get('symbol'),
            'direction': position.get('direction'),
            'size': position.get('size'),
            'entry_price': position.get('entry_price'),
            'unrealized_pnl': position.get('unrealized_pnl'),
            'timestamp': datetime.utcnow().isoformat()
        })
    
    def log_risk_event(self, event_type: str, details: Dict[str, Any]):
        """Log risk management events."""
        self.logger.warning('RISK_EVENT', extra={
            'event_type': 'risk',
            'risk_type': event_type,
            'details': details,
            'timestamp': datetime.utcnow().isoformat()
        })
