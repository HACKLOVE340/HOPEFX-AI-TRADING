"""Custom exceptions with context."""
from __future__ import annotations


class HopeFXError(Exception):
    """Base exception."""
    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class VaultError(HopeFXError):
    """Cryptographic vault error."""
    pass


class AuthenticationError(HopeFXError):
    """Auth failure."""
    pass


class EventBusError(HopeFXError):
    """Event bus failure."""
    pass


class DataValidationError(HopeFXError):
    """Tick/data validation failed."""
    pass


class CircuitBreakerError(HopeFXError):
    """Circuit breaker open."""
    pass


class RiskLimitError(HopeFXError):
    """Risk limit exceeded."""
    pass


class ExecutionError(HopeFXError):
    """Order execution failed."""
    pass


class ModelError(HopeFXError):
    """ML model error."""
    pass


class DriftDetectedError(HopeFXError):
    """Model drift threshold exceeded."""
    pass


# ── Aliases expected by tests ─────────────────────────────────────────────────
RiskViolation = RiskLimitError
BrokerError = ExecutionError
BrokerConnectionError = BrokerError
TradingError = ExecutionError
ConfigurationError = HopeFXError
NetworkError = HopeFXError
TimeoutError = HopeFXError
FeedError = HopeFXError
DataError = DataValidationError
DatabaseError = HopeFXError
CacheError = HopeFXError
InfrastructureError = HopeFXError
EncryptionError = HopeFXError
ValidationFailed = DataValidationError
