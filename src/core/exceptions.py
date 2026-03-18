"""
Hierarchical exception system for granular error handling.
"""

from typing import Any


class HopeFXError(Exception):
    """Base exception."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Configuration errors
class ConfigurationError(HopeFXError):
    """Invalid configuration."""
    pass


class ValidationError(HopeFXError):
    """Data validation failed."""
    pass


# Infrastructure errors
class InfrastructureError(HopeFXError):
    """Infrastructure failure."""
    pass


class DatabaseError(InfrastructureError):
    """Database operation failed."""
    pass


class CacheError(InfrastructureError):
    """Cache operation failed."""
    pass


class MessagingError(InfrastructureError):
    """Message broker error."""
    pass


# Trading errors
class TradingError(HopeFXError):
    """Trading operation failed."""
    pass


class OrderError(TradingError):
    """Order submission failed."""
    pass


class ExecutionError(TradingError):
    """Order execution failed."""
    pass


class RiskViolation(TradingError):
    """Risk limit violated."""
    def __init__(
        self,
        message: str,
        rule: str,
        limit: float,
        actual: float,
        details: dict[str, Any] | None = None
    ):
        super().__init__(message, details)
        self.rule = rule
        self.limit = limit
        self.actual = actual


class InsufficientFunds(TradingError):
    """Account lacks funds."""
    pass


class MarketClosed(TradingError):
    """Market not open."""
    pass


# Broker errors
class BrokerError(TradingError):
    """Broker API error."""
    pass


class BrokerConnectionError(BrokerError):
    """Cannot connect to broker."""
    pass


class BrokerAuthenticationError(BrokerError):
    """Broker auth failed."""
    pass


class BrokerRateLimit(BrokerError):
    """Rate limited by broker."""
    pass


# ML errors
class MLError(HopeFXError):
    """Machine learning error."""
    pass


class ModelNotFound(MLError):
    """Model not in registry."""
    pass


class PredictionError(MLError):
    """Inference failed."""
    pass


class DriftDetected(MLError):
    """Model drift detected."""
    pass


# Data errors
class DataError(HopeFXError):
    """Data operation failed."""
    pass


class FeedError(DataError):
    """Data feed error."""
    pass


class ValidationFailed(DataError):
    """Data validation failed."""
    pass


# Security errors
class SecurityError(HopeFXError):
    """Security violation."""
    pass


class AuthenticationError(SecurityError):
    """Auth failed."""
    pass


class AuthorizationError(SecurityError):
    """Permission denied."""
    pass


class EncryptionError(SecurityError):
    """Encryption/decryption failed."""
    pass
