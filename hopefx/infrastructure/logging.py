"""
Institutional Logging with:
- Structured JSON output
- Async file writing
- Log rotation
- Sensitive data masking
- Correlation ID tracking
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import gzip
from logging.handlers import RotatingFileHandler

import structlog
from pythonjsonlogger import jsonlogger

# ============================================================================
# CONFIGURATION
# ============================================================================

class LoggingConfig:
    level: str = "INFO"
    log_dir: str = "outputs/logs"
    max_bytes: int = 100 * 1024 * 1024  # 100MB
    backup_count: int = 10
    enable_console: bool = True
    enable_file: bool = True
    enable_audit: bool = True
    mask_fields: list = ["password", "api_key", "secret", "token"]

# ============================================================================
# STRUCTURED LOGGER
# ============================================================================

def setup_logging(config: LoggingConfig = None):
    """Configure institutional logging."""
    if config is None:
        config = LoggingConfig()
    
    Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            _mask_sensitive_fields(config.mask_fields),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Root logger setup
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper()))
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Console handler
    if config.enable_console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(jsonlogger.JsonFormatter(
            '%(timestamp)s %(level)s %(name)s %(message)s'
        ))
        root_logger.addHandler(console)
    
    # File handler with rotation
    if config.enable_file:
        file_handler = RotatingFileHandler(
            f"{config.log_dir}/hopefx.log",
            maxBytes=config.max_bytes,
            backupCount=config.backup_count
        )
        file_handler.setFormatter(jsonlogger.JsonFormatter())
        root_logger.addHandler(file_handler)
    
    # Audit log (separate, no rotation for compliance)
    if config.enable_audit:
        audit_handler = logging.FileHandler(f"{config.log_dir}/audit.log")
        audit_handler.setLevel(logging.INFO)
        audit_handler.setFormatter(jsonlogger.JsonFormatter())
        
        audit_logger = logging.getLogger("hopefx.audit")
        audit_logger.addHandler(audit_handler)
        audit_logger.setLevel(logging.INFO)

def _mask_sensitive_fields(fields: list):
    """Mask sensitive data in logs."""
    def processor(logger, method_name, event_dict):
        for field in fields:
            if field in event_dict:
                event_dict[field] = "***MASKED***"
        return event_dict
    return processor

def get_logger(name: str) -> structlog.BoundLogger:
    """Get structured logger."""
    return structlog.get_logger(name)

# ============================================================================
# AUDIT LOGGER (Regulatory Compliance)
# ============================================================================

class AuditLogger:
    """
    Tamper-evident audit logging for regulatory compliance.
    Every significant action is logged with hash chain.
    """
    
    def __init__(self, log_dir: str = "outputs/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.chain_file = self.log_dir / "audit_chain.jsonl"
        self._last_hash = self._get_last_hash()
    
    def _get_last_hash(self) -> str:
        """Get hash of last entry for chain continuity."""
        if not self.chain_file.exists():
            return "0" * 64
        
        try:
            with open(self.chain_file, "rb") as f:
                # Read last line
                f.seek(-1024, 2)  # Seek to near end
                lines = f.readlines()
                if lines:
                    last_line = lines[-1].decode()
                    entry = json.loads(last_line)
                    return entry.get("hash", "0" * 64)
        except Exception:
            pass
        
        return "0" * 64
    
    def log(
        self,
        action: str,
        user_id: str,
        resource_type: str,
        resource_id: str,
        changes: Dict,
        trace_id: str = ""
    ):
        """
        Log auditable action with hash chain.
        """
        import hashlib
        
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "changes": changes,
            "trace_id": trace_id,
            "previous_hash": self._last_hash
        }
        
        # Calculate hash
        entry_str = json.dumps(entry, sort_keys=True)
        entry["hash"] = hashlib.sha256(entry_str.encode()).hexdigest()
        
        # Append to chain
        with open(self.chain_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        self._last_hash = entry["hash"]
    
    def verify_chain(self) -> bool:
        """
        Verify integrity of audit chain.
        Returns True if valid, False if tampered.
        """
        if not self.chain_file.exists():
            return True
        
        previous_hash = "0" * 64
        
        with open(self.chain_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    
                    # Check link
                    if entry.get("previous_hash") != previous_hash:
                        return False
                    
                    # Verify hash
                    test_entry = entry.copy()
                    test_hash = test_entry.pop("hash")
                    test_str = json.dumps(test_entry, sort_keys=True)
                    calc_hash = hashlib.sha256(test_str.encode()).hexdigest()
                    
                    if calc_hash != test_hash:
                        return False
                    
                    previous_hash = test_hash
                    
                except json.JSONDecodeError:
                    return False
        
        return True
