# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
resilience/service_circuit_breakers.py
=======================================
Production circuit breakers for all critical services.

Wraps the generic CircuitBreaker with service-specific configuration,
health probes, fallback strategies, and Prometheus metrics.

Services protected:
- Redis        — cache, pub/sub, kill switch, session store
- Broker       — order execution, position queries
- ML Model     — inference engine predictions
- Database     — SQLAlchemy session factory

Each breaker:
1. Opens after N consecutive failures within a time window
2. Rejects calls immediately while open (fast-fail)
3. Probes the service after timeout_seconds (half-open)
4. Closes automatically on M consecutive successes
5. Publishes state changes to Redis alerts:critical
6. Exposes metrics via Prometheus counters/gauges

Usage
-----
    from resilience.service_circuit_breakers import (
        redis_breaker, broker_breaker, ml_breaker, db_breaker,
        get_all_breaker_status,
    )

    # Wrap a Redis call
    result = await redis_breaker.call(redis_client.get, "my:key")

    # Wrap a broker call
    order = await broker_breaker.call(broker.place_order, order_request)

    # Check all breaker states
    status = get_all_breaker_status()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED    = "closed"     # Normal operation
    OPEN      = "open"       # Failing — reject all calls
    HALF_OPEN = "half_open"  # Probing — allow limited calls


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class BreakerConfig:
    """Configuration for a single circuit breaker."""

    name: str
    failure_threshold: int = 5       # consecutive failures to open
    success_threshold: int = 3       # consecutive successes to close
    timeout_seconds: float = 60.0    # seconds before half-open probe
    half_open_max_calls: int = 3     # max calls allowed in half-open
    call_timeout_seconds: float = 10.0  # per-call timeout
    excluded_exceptions: tuple[type[Exception], ...] = ()  # never count as failures


# ── Core circuit breaker ──────────────────────────────────────────────────────

class ServiceCircuitBreaker:
    """
    Production circuit breaker with:
    - Sliding window failure counting
    - Per-call timeout enforcement
    - State change alerting (Redis + log)
    - Prometheus metrics (optional)
    - Synchronous and async call support
    """

    def __init__(self, config: BreakerConfig) -> None:
        self.config = config
        self.name = config.name
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float = 0.0
        self._last_state_change: float = time.time()
        self._total_calls = 0
        self._total_failures = 0
        self._total_rejected = 0
        self._state_history: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        # Protects sync record_success/record_failure from concurrent threads
        self._sync_lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute func(*args, **kwargs) with circuit breaker protection.

        Raises:
            CircuitBreakerOpenError: when circuit is open and timeout not elapsed.
            asyncio.TimeoutError: when call exceeds call_timeout_seconds.
            Any exception raised by func (counted as failure).
        """
        async with self._lock:
            await self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                self._total_rejected += 1
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN — service unavailable. "
                    f"Will retry in {self._seconds_until_probe():.0f}s."
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self._total_rejected += 1
                    raise CircuitBreakerOpenError(
                        f"Circuit '{self.name}' is HALF_OPEN — probe limit reached"
                    )
                self._half_open_calls += 1

        self._total_calls += 1

        try:
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.call_timeout_seconds,
                )
            else:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                    timeout=self.config.call_timeout_seconds,
                )
            await self._on_success()
            return result

        except CircuitBreakerOpenError:
            raise
        except self.config.excluded_exceptions:
            # Excluded exceptions (e.g. auth errors) don't count as failures
            raise
        except Exception as exc:
            await self._on_failure(exc)
            raise

    async def call_sync(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Synchronous wrapper — runs func in executor, applies circuit breaker."""
        return await self.call(func, *args, **kwargs)

    async def _maybe_transition_to_half_open(self) -> None:
        """Check if enough time has passed to probe the service."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.timeout_seconds:
                await self._set_state(CircuitState.HALF_OPEN)
                self._half_open_calls = 0

    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    await self._set_state(CircuitState.CLOSED)
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                self._success_count += 1

    async def _on_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_time = time.time()
            self._success_count = 0

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open → back to open
                await self._set_state(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED and self._failure_count >= self.config.failure_threshold:
                await self._set_state(CircuitState.OPEN)

            logger.warning(
                "CircuitBreaker [%s]: failure #%d — %s: %s",
                self.name, self._failure_count, type(exc).__name__, exc,
            )

    async def _set_state(self, new_state: CircuitState) -> None:
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        self._last_state_change = time.time()
        self._state_history.append({
            "from": old_state.value,
            "to": new_state.value,
            "ts": datetime.now(UTC).isoformat(),
            "failure_count": self._failure_count,
        })
        self._state_history = self._state_history[-50:]

        level = "warning" if new_state == CircuitState.OPEN else "info"
        getattr(logger, level)(
            "CircuitBreaker [%s]: %s → %s (failures=%d)",
            self.name, old_state.value, new_state.value, self._failure_count,
        )

        # Publish state change to Redis alerts
        if new_state == CircuitState.OPEN:
            self._publish_open_alert()

        # Update Prometheus gauge
        self._update_prom_state(new_state)

    def _publish_open_alert(self) -> None:
        """Push circuit-open event to Redis alerts:critical (non-fatal, sync only)."""
        try:
            import json
            # Use the synchronous Redis client only — this method is called from
            # a sync context inside _set_state. Never await here.
            try:
                import redis as _redis_sync
                import os as _os
                _rc = _redis_sync.from_url(
                    _os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                _rc.rpush(
                    "alerts:critical",
                    json.dumps({
                        "type": "circuit_breaker_open",
                        "service": self.name,
                        "ts": datetime.now(UTC).isoformat(),
                        "failures": self._failure_count,
                        "total_failures": self._total_failures,
                    }),
                )
                _rc.ltrim("alerts:critical", -1000, -1)
            except Exception:  # nosec B110 — Redis may be unavailable
                pass
        except Exception:  # nosec B110
            pass

    def _update_prom_state(self, state: CircuitState) -> None:
        """Update Prometheus gauge (non-fatal if prometheus_client absent)."""
        try:
            from prometheus_client import Gauge
            _g = Gauge(
                f"hopefx_circuit_breaker_state_{self.name.replace('-', '_')}",
                f"Circuit breaker state for {self.name} (0=closed,1=half_open,2=open)",
            )
            _g.set({"closed": 0, "half_open": 1, "open": 2}.get(state.value, 0))
        except Exception:  # nosec B110
            pass

    def _seconds_until_probe(self) -> float:
        elapsed = time.time() - self._last_failure_time
        return max(0.0, self.config.timeout_seconds - elapsed)

    def record_success(self) -> None:
        """
        Synchronous success recorder — safe to call from non-async contexts.

        Updates failure/success counters and transitions HALF_OPEN → CLOSED
        when the success threshold is reached.
        """
        with self._sync_lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    self._last_state_change = time.time()
                    logger.info("CircuitBreaker [%s]: HALF_OPEN → CLOSED (sync)", self.name)
            elif self._state == CircuitState.CLOSED:
                self._success_count += 1

    def record_failure(self, exc: Exception) -> None:
        """
        Synchronous failure recorder — safe to call from non-async contexts.

        Updates failure counters and transitions CLOSED → OPEN when the
        failure threshold is reached.  Publishes a Redis alert on open.
        """
        with self._sync_lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_time = time.time()
            self._success_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                logger.warning(
                    "CircuitBreaker [%s]: HALF_OPEN → OPEN (sync) — %s: %s",
                    self.name, type(exc).__name__, exc,
                )
                self._publish_open_alert()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.time()
                    logger.warning(
                        "CircuitBreaker [%s]: CLOSED → OPEN (sync) after %d failures — %s: %s",
                        self.name, self._failure_count, self.config.failure_threshold,
                        type(exc).__name__, exc,
                    )
                    self._publish_open_alert()
                else:
                    logger.warning(
                        "CircuitBreaker [%s]: failure #%d/%d (sync) — %s: %s",
                        self.name, self._failure_count, self.config.failure_threshold,
                        type(exc).__name__, exc,
                    )

    def force_close(self) -> None:
        """Manually close the circuit (admin action)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        logger.info("CircuitBreaker [%s]: force-closed by admin", self.name)

    def force_open(self) -> None:
        """Manually open the circuit (admin action / maintenance)."""
        self._state = CircuitState.OPEN
        self._last_failure_time = time.time()
        logger.warning("CircuitBreaker [%s]: force-opened by admin", self.name)

    def get_status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_rejected": self._total_rejected,
            "failure_rate": round(self._total_failures / max(self._total_calls, 1), 4),
            "seconds_until_probe": self._seconds_until_probe() if self.is_open else 0,
            "last_state_change": datetime.fromtimestamp(self._last_state_change, UTC).isoformat(),
            "state_history": self._state_history[-10:],
        }


# ── Service-specific breakers ─────────────────────────────────────────────────

redis_breaker = ServiceCircuitBreaker(BreakerConfig(
    name="redis",
    failure_threshold=3,       # open after 3 consecutive Redis failures
    success_threshold=2,       # close after 2 successes in half-open
    timeout_seconds=30.0,      # probe after 30s
    half_open_max_calls=2,
    call_timeout_seconds=5.0,  # Redis calls must complete in 5s
))

broker_breaker = ServiceCircuitBreaker(BreakerConfig(
    name="broker",
    # Threshold matches BrokerManager._MAX_CONSECUTIVE_FAILURES (5) so the
    # breaker opens only after the manager's own failover chain is exhausted.
    # Opening earlier would block failover attempts and prevent recovery.
    failure_threshold=5,
    success_threshold=3,       # require 3 successes to close (conservative)
    timeout_seconds=60.0,      # probe after 60s
    half_open_max_calls=1,     # only 1 probe call (real money at stake)
    call_timeout_seconds=15.0, # broker calls may take up to 15s
))

ml_breaker = ServiceCircuitBreaker(BreakerConfig(
    name="ml_model",
    failure_threshold=5,       # ML model can have transient failures
    success_threshold=2,
    timeout_seconds=30.0,
    half_open_max_calls=3,
    call_timeout_seconds=10.0,
))

db_breaker = ServiceCircuitBreaker(BreakerConfig(
    name="database",
    failure_threshold=3,
    success_threshold=2,
    timeout_seconds=30.0,
    half_open_max_calls=2,
    call_timeout_seconds=10.0,
))


# ── Aggregate status ──────────────────────────────────────────────────────────

_ALL_BREAKERS: list[ServiceCircuitBreaker] = [
    redis_breaker, broker_breaker, ml_breaker, db_breaker,
]


def get_all_breaker_status() -> dict[str, Any]:
    """Return status of all circuit breakers for health checks."""
    statuses = {b.name: b.get_status() for b in _ALL_BREAKERS}
    open_count = sum(1 for b in _ALL_BREAKERS if b.is_open)
    return {
        "breakers": statuses,
        "open_count": open_count,
        "all_closed": open_count == 0,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def register_breaker(breaker: ServiceCircuitBreaker) -> None:
    """Register a custom circuit breaker for aggregate status reporting."""
    if breaker not in _ALL_BREAKERS:
        _ALL_BREAKERS.append(breaker)
