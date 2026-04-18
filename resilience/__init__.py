# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
resilience — Fault tolerance, auto-rollback, and hot standby systems.

Public API
----------
    AutoRollbackManager     Monitors service health and triggers automatic
                            rollback on degradation. Integrates with Sentry.
    HotStandbyReplicator    Replicates state to a hot standby instance for
                            zero-downtime failover.
    ServiceCircuitBreakers  Per-service circuit breakers with configurable
                            thresholds and reset timeouts.
    CircuitBreaker          Generic circuit breaker (CLOSED/OPEN/HALF_OPEN).
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from resilience.auto_rollback import AutoRollbackManager, rollback_manager  # noqa: F401
except Exception as _exc:
    logger.debug("resilience.auto_rollback unavailable: %s", _exc)
    AutoRollbackManager = None  # type: ignore[assignment,misc]
    rollback_manager = None  # type: ignore[assignment]

try:
    from resilience.hot_standby import HotStandbyReplicator  # noqa: F401
except Exception as _exc:
    logger.debug("resilience.hot_standby unavailable: %s", _exc)
    HotStandbyReplicator = None  # type: ignore[assignment,misc]

try:
    from resilience.service_circuit_breakers import (  # noqa: F401
        ServiceCircuitBreaker,
        get_all_breaker_status,
        redis_breaker,
        broker_breaker,
        ml_breaker,
        db_breaker,
    )
    # Alias for backwards-compat with any code that imported ServiceCircuitBreakers
    ServiceCircuitBreakers = ServiceCircuitBreaker  # type: ignore[assignment]
except Exception as _exc:
    logger.debug("resilience.service_circuit_breakers unavailable: %s", _exc)
    ServiceCircuitBreaker = None  # type: ignore[assignment,misc]
    ServiceCircuitBreakers = None  # type: ignore[assignment,misc]

try:
    from resilience.circuit_breaker import CircuitBreaker  # noqa: F401
except Exception as _exc:
    logger.debug("resilience.circuit_breaker unavailable: %s", _exc)
    CircuitBreaker = None  # type: ignore[assignment,misc]

try:
    from resilience.retry import (  # noqa: F401
        RetryPolicy,
        retry,
        redis_retry,
        broker_retry,
        http_retry,
        db_retry,
    )
except Exception as _exc:
    logger.debug("resilience.retry unavailable: %s", _exc)
    RetryPolicy = None  # type: ignore[assignment,misc]
    retry = None  # type: ignore[assignment]

__all__ = [
    "AutoRollbackManager",
    "CircuitBreaker",
    "HotStandbyReplicator",
    "RetryPolicy",
    "ServiceCircuitBreaker",
    "ServiceCircuitBreakers",
    "broker_retry",
    "broker_breaker",
    "db_breaker",
    "db_retry",
    "get_all_breaker_status",
    "http_retry",
    "ml_breaker",
    "redis_breaker",
    "redis_retry",
    "retry",
    "rollback_manager",
]
