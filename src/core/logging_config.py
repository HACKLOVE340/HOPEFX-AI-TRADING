"""
Structured logging with JSON output, rotation, and correlation IDs.
"""

import logging
import sys
from pathlib import Path

import structlog
from structlog.processors import (
    CallsiteParameter,
    CallsiteParameterAdder,
    EventRenamer,
    JSONRenderer,
    TimeStamper,
    add_log_level,
    dict_tracebacks,
)
from structlog.stdlib import (
    BoundLogger,
    LoggerFactory,
    add_log_level,
    filter_by_level,
)


def configure_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    log_file: Path | None = None
) -> None:
    """Configure structured logging."""
    
    shared_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        CallsiteParameterAdder(
            parameters={
                CallsiteParameter.FILENAME,
                CallsiteParameter.FUNC_NAME,
                CallsiteParameter.LINENO,
            }
        ),
    ]
    
    if json_output:
        # Production JSON logging
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        # Development console logging
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level),
    )
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10_000_000,  # 10MB
            backupCount=5,
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)
    
    # Silence noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> BoundLogger:
    """Get structured logger."""
    return structlog.get_logger(name)
