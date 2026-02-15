"""
Security Utilities Module

This module provides security-related utilities for the HOPEFX AI Trading platform:
- Security monitoring and audit logging
- Log sanitization to prevent sensitive data leaks
- Credential rotation tracking
- Security configuration validation
- Environment security checks
"""

import os
import re
import logging
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Pattern
from dataclasses import dataclass
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class SecurityLevel(str, Enum):
    """Security levels for audit logging"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ALERT = "alert"


class AuditEventType(str, Enum):
    """Types of security audit events"""
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    CREDENTIAL_ACCESS = "credential_access"
    CREDENTIAL_ROTATION = "credential_rotation"
    CONFIG_CHANGE = "config_change"
    API_ACCESS = "api_access"
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    SECURITY_VIOLATION = "security_violation"
    ENCRYPTION_OPERATION = "encryption_operation"


@dataclass
class AuditEvent:
    """Security audit event record"""
    event_type: AuditEventType
    level: SecurityLevel
    user_id: Optional[str]
    ip_address: Optional[str]
    resource: str
    action: str
    details: Dict[str, Any]
    timestamp: datetime
    success: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage"""
        return {
            'event_type': self.event_type.value,
            'level': self.level.value,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'resource': self.resource,
            'action': self.action,
            'details': self.details,
            'timestamp': self.timestamp.isoformat(),
            'success': self.success
        }


class LogSanitizer:
    """
    Sanitizes log messages to prevent sensitive data leaks.
    
    Automatically redacts:
    - API keys and tokens
    - Passwords
    - Credit card numbers
    - Email addresses (optionally)
    - Custom patterns
    """

    # Default patterns to redact
    DEFAULT_PATTERNS: Dict[str, Pattern] = {
        'api_key': re.compile(r'(?i)(api[_-]?key|apikey)["\s:=]+["\']?([a-zA-Z0-9_\-]{20,})["\']?'),
        'password': re.compile(r'(?i)(password|passwd|pwd|secret)["\s:=]+["\']?([^\s"\',}]+)["\']?'),
        'bearer_token': re.compile(r'(?i)(bearer\s+|authorization:\s*bearer\s+)([a-zA-Z0-9_\-\.]+)'),
        'authorization_header': re.compile(r'(?i)(authorization:\s*)([^\s,]+)'),
        'credit_card': re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
        'aws_key': re.compile(r'(?i)(aws[_-]?(?:access[_-]?key|secret)[_-]?(?:id)?)["\s:=]+["\']?([A-Z0-9]{16,})["\']?'),
        'private_key': re.compile(r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----'),
        'encryption_key': re.compile(r'(?i)(encryption[_-]?key|config[_-]?encryption[_-]?key)["\s:=]+["\']?([a-fA-F0-9]{32,})["\']?'),
    }

    def __init__(
        self,
        enabled: bool = True,
        redact_emails: bool = False,
        custom_patterns: Optional[Dict[str, Pattern]] = None,
        redaction_text: str = "[REDACTED]"
    ):
        """
        Initialize log sanitizer.
        
        Args:
            enabled: Whether sanitization is enabled
            redact_emails: Whether to redact email addresses
            custom_patterns: Additional regex patterns to redact
            redaction_text: Text to replace sensitive data with
        """
        self.enabled = enabled
        self.redaction_text = redaction_text
        self.patterns = dict(self.DEFAULT_PATTERNS)
        
        if redact_emails:
            self.patterns['email'] = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        
        if custom_patterns:
            self.patterns.update(custom_patterns)

    def sanitize(self, message: str) -> str:
        """
        Sanitize a log message by redacting sensitive data.
        
        Args:
            message: The log message to sanitize
            
        Returns:
            Sanitized log message
        """
        if not self.enabled or not message:
            return message

        sanitized = message
        for pattern_name, pattern in self.patterns.items():
            # For patterns with groups, replace the captured group
            if pattern.groups:
                sanitized = pattern.sub(
                    lambda m: m.group(0).replace(m.group(m.lastindex), self.redaction_text),
                    sanitized
                )
            else:
                sanitized = pattern.sub(self.redaction_text, sanitized)

        return sanitized

    def sanitize_dict(self, data: Dict[str, Any], sensitive_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Sanitize a dictionary by redacting sensitive keys.
        
        Args:
            data: Dictionary to sanitize
            sensitive_keys: List of keys to always redact
            
        Returns:
            Sanitized dictionary
        """
        default_sensitive = [
            'password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apikey',
            'api_secret', 'apisecret', 'access_key', 'secret_key', 'private_key',
            'encryption_key', 'auth_token', 'authorization', 'bearer'
        ]
        
        sensitive = set(key.lower() for key in (sensitive_keys or default_sensitive))
        
        def redact_value(key: str, value: Any) -> Any:
            key_lower = key.lower()
            for s in sensitive:
                if s in key_lower:
                    if isinstance(value, str) and len(value) > 4:
                        return f"{value[:2]}...{self.redaction_text}"
                    return self.redaction_text
            
            if isinstance(value, str):
                return self.sanitize(value)
            elif isinstance(value, dict):
                return self.sanitize_dict(value, sensitive_keys)
            elif isinstance(value, list):
                return [redact_value(key, v) for v in value]
            return value

        return {k: redact_value(k, v) for k, v in data.items()}


class SecurityAuditor:
    """
    Handles security audit logging and monitoring.
    
    Records security-relevant events for compliance and monitoring.
    """

    def __init__(
        self,
        enabled: bool = True,
        log_to_file: bool = True,
        audit_log_path: str = "./logs/security_audit.log"
    ):
        """
        Initialize security auditor.
        
        Args:
            enabled: Whether auditing is enabled
            log_to_file: Whether to log to a separate audit file
            audit_log_path: Path to the audit log file
        """
        self.enabled = enabled
        self._events: List[AuditEvent] = []
        self._log_sanitizer = LogSanitizer()
        
        if log_to_file:
            self._setup_audit_logger(audit_log_path)

    def _setup_audit_logger(self, log_path: str) -> None:
        """Setup dedicated audit logger"""
        os.makedirs(os.path.dirname(log_path) or '.', exist_ok=True)
        
        self.audit_logger = logging.getLogger('security_audit')
        self.audit_logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - AUDIT - %(levelname)s - %(message)s'
        ))
        self.audit_logger.addHandler(handler)

    def log_event(
        self,
        event_type: AuditEventType,
        resource: str,
        action: str,
        success: bool = True,
        level: SecurityLevel = SecurityLevel.INFO,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditEvent:
        """
        Log a security audit event.
        
        Args:
            event_type: Type of security event
            resource: Resource being accessed
            action: Action being performed
            success: Whether the action was successful
            level: Security level of the event
            user_id: User performing the action
            ip_address: IP address of the request
            details: Additional details
            
        Returns:
            The created audit event
        """
        if not self.enabled:
            return None

        # Sanitize details
        safe_details = self._log_sanitizer.sanitize_dict(details or {})

        event = AuditEvent(
            event_type=event_type,
            level=level,
            user_id=user_id,
            ip_address=ip_address,
            resource=resource,
            action=action,
            details=safe_details,
            timestamp=datetime.now(timezone.utc),
            success=success
        )

        self._events.append(event)
        
        # Log to audit file
        if hasattr(self, 'audit_logger'):
            log_level = {
                SecurityLevel.INFO: logging.INFO,
                SecurityLevel.WARNING: logging.WARNING,
                SecurityLevel.CRITICAL: logging.CRITICAL,
                SecurityLevel.ALERT: logging.ERROR,
            }.get(level, logging.INFO)
            
            self.audit_logger.log(
                log_level,
                f"[{event_type.value}] {action} on {resource} - "
                f"Success: {success} - User: {user_id or 'N/A'}"
            )

        return event

    def get_events(
        self,
        event_type: Optional[AuditEventType] = None,
        level: Optional[SecurityLevel] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """Get filtered audit events"""
        events = self._events
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if level:
            events = [e for e in events if e.level == level]
        if since:
            events = [e for e in events if e.timestamp >= since]
        
        return events[-limit:]


class CredentialRotationTracker:
    """
    Tracks credential rotation schedules and sends alerts.
    
    Helps maintain security compliance by monitoring credential age.
    """

    def __init__(self, rotation_days: int = 90):
        """
        Initialize credential rotation tracker.
        
        Args:
            rotation_days: Days until credentials should be rotated
        """
        self.rotation_days = rotation_days
        self._credentials: Dict[str, datetime] = {}

    def register_credential(
        self,
        credential_name: str,
        created_at: Optional[datetime] = None
    ) -> None:
        """Register a credential for rotation tracking"""
        self._credentials[credential_name] = created_at or datetime.now(timezone.utc)
        logger.info(f"Registered credential for rotation tracking: {credential_name}")

    def get_credential_age(self, credential_name: str) -> Optional[timedelta]:
        """Get the age of a credential"""
        if credential_name not in self._credentials:
            return None
        return datetime.now(timezone.utc) - self._credentials[credential_name]

    def needs_rotation(self, credential_name: str) -> bool:
        """Check if a credential needs rotation"""
        age = self.get_credential_age(credential_name)
        if age is None:
            return False
        return age.days >= self.rotation_days

    def get_rotation_status(self) -> Dict[str, Dict[str, Any]]:
        """Get rotation status for all tracked credentials"""
        status = {}
        for name, created_at in self._credentials.items():
            age = datetime.now(timezone.utc) - created_at
            days_until_rotation = max(0, self.rotation_days - age.days)
            
            status[name] = {
                'created_at': created_at.isoformat(),
                'age_days': age.days,
                'needs_rotation': age.days >= self.rotation_days,
                'days_until_rotation': days_until_rotation,
                'status': 'expired' if days_until_rotation == 0 else 
                         'warning' if days_until_rotation <= 14 else 'ok'
            }
        
        return status

    def get_credentials_needing_rotation(self) -> List[str]:
        """Get list of credentials that need rotation"""
        return [name for name in self._credentials if self.needs_rotation(name)]


class SecurityConfigValidator:
    """
    Validates security configuration settings.
    
    Checks that required security settings are properly configured.
    """

    REQUIRED_ENV_VARS = [
        'CONFIG_ENCRYPTION_KEY',
    ]

    RECOMMENDED_ENV_VARS = [
        'CONFIG_SALT',
        'APP_ENV',
    ]

    PRODUCTION_REQUIRED = [
        'DB_SSL_ENABLED',
    ]

    def __init__(self):
        """Initialize security config validator"""
        self.issues: List[Dict[str, str]] = []

    def validate(self) -> bool:
        """
        Validate security configuration.
        
        Returns:
            True if all required settings are valid
        """
        self.issues = []
        is_valid = True

        # Check required environment variables
        for var in self.REQUIRED_ENV_VARS:
            value = os.getenv(var)
            if not value:
                self.issues.append({
                    'level': 'error',
                    'variable': var,
                    'message': f'Required security variable {var} is not set'
                })
                is_valid = False
            elif var == 'CONFIG_ENCRYPTION_KEY' and len(value) < 32:
                self.issues.append({
                    'level': 'error',
                    'variable': var,
                    'message': f'{var} must be at least 32 characters'
                })
                is_valid = False

        # Check recommended variables
        for var in self.RECOMMENDED_ENV_VARS:
            if not os.getenv(var):
                self.issues.append({
                    'level': 'warning',
                    'variable': var,
                    'message': f'Recommended security variable {var} is not set'
                })

        # Check production-specific requirements
        app_env = os.getenv('APP_ENV', 'development')
        if app_env == 'production':
            for var in self.PRODUCTION_REQUIRED:
                value = os.getenv(var, '').lower()
                if value not in ['true', '1', 'yes']:
                    self.issues.append({
                        'level': 'error',
                        'variable': var,
                        'message': f'{var} must be enabled in production'
                    })
                    is_valid = False

            # Check debug mode
            if os.getenv('DEBUG', '').lower() in ['true', '1', 'yes']:
                self.issues.append({
                    'level': 'error',
                    'variable': 'DEBUG',
                    'message': 'DEBUG must be disabled in production'
                })
                is_valid = False

        return is_valid

    def get_security_report(self) -> Dict[str, Any]:
        """Generate a security configuration report"""
        is_valid = self.validate()
        app_env = os.getenv('APP_ENV', 'development')
        
        return {
            'valid': is_valid,
            'environment': app_env,
            'issues': self.issues,
            'checklist': {
                'CONFIG_ENCRYPTION_KEY': bool(os.getenv('CONFIG_ENCRYPTION_KEY')),
                'CONFIG_SALT': bool(os.getenv('CONFIG_SALT')),
                'APP_ENV': bool(os.getenv('APP_ENV')),
                'DB_SSL_ENABLED': os.getenv('DB_SSL_ENABLED', '').lower() in ['true', '1', 'yes'],
                'DEBUG_DISABLED': os.getenv('DEBUG', '').lower() not in ['true', '1', 'yes'],
                'API_KEY_ENCRYPTION': os.getenv('API_KEY_ENCRYPTION', '').lower() in ['true', '1', 'yes'],
                'LOG_SANITIZATION': os.getenv('LOG_SANITIZATION_ENABLED', '').lower() in ['true', '1', 'yes'],
            },
            'recommendations': [
                issue for issue in self.issues 
                if issue['level'] == 'warning'
            ]
        }


def audit_function(
    event_type: AuditEventType,
    resource: str,
    action: str
):
    """
    Decorator to automatically audit function calls.
    
    Args:
        event_type: Type of audit event
        resource: Resource being accessed
        action: Action description
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            auditor = SecurityAuditor(enabled=os.getenv('ENABLE_SECURITY_MONITORING', 'true').lower() == 'true')
            
            try:
                result = func(*args, **kwargs)
                auditor.log_event(
                    event_type=event_type,
                    resource=resource,
                    action=action,
                    success=True
                )
                return result
            except Exception as e:
                auditor.log_event(
                    event_type=event_type,
                    resource=resource,
                    action=action,
                    success=False,
                    level=SecurityLevel.WARNING,
                    details={'error': str(e)}
                )
                raise
        
        return wrapper
    return decorator


def generate_secure_key(length: int = 32) -> str:
    """Generate a cryptographically secure key"""
    return secrets.token_hex(length)


def generate_secure_salt(length: int = 16) -> str:
    """Generate a cryptographically secure salt"""
    return secrets.token_hex(length)


def check_security_setup() -> Dict[str, Any]:
    """
    Perform a comprehensive security setup check.
    
    Returns a report of security status and recommendations.
    """
    validator = SecurityConfigValidator()
    report = validator.get_security_report()
    
    # Add key generation helpers if needed
    if not report['checklist']['CONFIG_ENCRYPTION_KEY']:
        report['setup_commands'] = {
            'CONFIG_ENCRYPTION_KEY': f"export CONFIG_ENCRYPTION_KEY={generate_secure_key(32)}",
            'CONFIG_SALT': f"export CONFIG_SALT={generate_secure_salt(16)}"
        }
    
    return report


# Global instances
log_sanitizer = LogSanitizer(
    enabled=os.getenv('LOG_SANITIZATION_ENABLED', 'true').lower() == 'true'
)

security_auditor = SecurityAuditor(
    enabled=os.getenv('ENABLE_SECURITY_MONITORING', 'true').lower() == 'true'
)

credential_tracker = CredentialRotationTracker(
    rotation_days=int(os.getenv('CREDENTIAL_ROTATION_DAYS', '90'))
)
