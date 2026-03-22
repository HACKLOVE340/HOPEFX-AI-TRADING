"""
Structured Logging System
- Rotating file handlers
- Console output
- JSON formatting
"""

import logging
import logging.handlers
import json
from datetime import datetime
from typing import Optional
import os

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)

class Logger:
    """Structured logger factory"""
    
    _loggers = {}
    _configured = False
    
    @classmethod
    def configure(cls, 
                 log_dir: str = 'logs',
                 log_level: str = 'INFO',
                 json_output: bool = True):
        """
        Configure logging system
        
        Args:
            log_dir: Directory for log files
            log_level: Logging level
            json_output: Use JSON formatting
        """
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        cls._json_output = json_output
        cls._log_level = getattr(logging, log_level)
        cls._log_dir = log_dir
        cls._configured = True
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Get logger instance
        
        Args:
            name: Logger name (usually __name__)
            
        Returns:
            Configured logger instance
        """
        if name in cls._loggers:
            return cls._loggers[name]
        
        if not cls._configured:
            cls.configure()
        
        logger = logging.getLogger(name)
        logger.setLevel(cls._log_level)
        
        # Remove existing handlers
        logger.handlers = []
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(cls._log_level)
        
        if cls._json_output:
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler with rotation
        log_file = os.path.join(cls._log_dir, f"{name}.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(cls._log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        cls._loggers[name] = logger
        return logger

# Convenience functions
def get_logger(name: str) -> logging.Logger:
    """Get logger for module"""
    return Logger.get_logger(name)

def configure_logging(log_dir: str = 'logs', 
                     log_level: str = 'INFO',
                     json_output: bool = True):
    """Configure logging system"""
    Logger.configure(log_dir, log_level, json_output)