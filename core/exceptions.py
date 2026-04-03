# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Custom exceptions with context."""

from __future__ import annotations


class HopeFXError(Exception):
    """Base exception."""

    def __init__(
        self,
        message: str = "",
        context: dict | None = None,
        **kwargs,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class VaultError(HopeFXError):
    """Cryptographic vault error."""


class AuthenticationError(HopeFXError):
    """Auth failure."""


class EventBusError(HopeFXError):
    """Event bus failure."""


class DataValidationError(HopeFXError):
    """Tick/data validation failed."""


class CircuitBreakerError(HopeFXError):
    """Circuit breaker open."""


class RiskLimitError(HopeFXError):
    """Risk limit exceeded."""

    def __init__(
        self,
        message="Risk limit exceeded",
        rule=None,
        limit=None,
        actual=None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.rule = rule
        self.limit = limit
        self.actual = actual


class ExecutionError(HopeFXError):
    """Order execution failed."""


class ModelError(HopeFXError):
    """ML model error."""


class DriftDetectedError(HopeFXError):
    """Model drift threshold exceeded."""


# ── Aliases expected by tests ─────────────────────────────────────────────────
RiskViolation = RiskLimitError
BrokerError = ExecutionError
BrokerConnectionError = BrokerError
TradingError = ExecutionError
ConfigurationError = HopeFXError
NetworkError = HopeFXError
HopeFXTimeoutError = HopeFXError  # use HopeFXTimeoutError to avoid shadowing builtin TimeoutError
FeedError = HopeFXError
DataError = DataValidationError
DatabaseError = HopeFXError
CacheError = HopeFXError
InfrastructureError = HopeFXError
EncryptionError = HopeFXError
ValidationFailed = DataValidationError
