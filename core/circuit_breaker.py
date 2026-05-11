# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/circuit_breaker.py
========================
Circuit breaker for external broker API calls.

States
------
CLOSED   — normal operation; calls pass through
OPEN     — too many failures; calls are rejected immediately without hitting
           the remote API; transitions to HALF_OPEN after reset_timeout
HALF_OPEN — one probe call is allowed; success → CLOSED, failure → OPEN

Usage — decorator
-----------------
    from core.circuit_breaker import circuit_breaker

    @circuit_breaker("oanda", failure_threshold=5, reset_timeout=60)
    async def my_api_call():
        ...

Usage — instance
----------------
    from core.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("oanda", failure_threshold=5, reset_timeout=60)
    async with cb:
        result = await oanda.get_live_prices(symbols)

Prometheus
----------
The gauge ``hopefx_broker_circuit_state`` is updated on every state change.
Values: 0=CLOSED, 1=HALF_OPEN, 2=OPEN.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from enum import IntEnum
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

# ── Prometheus gauge (optional — degrades gracefully if prometheus_client absent)
try:
    from prometheus_client import Gauge as _Gauge

    _CB_STATE_GAUGE = _Gauge(
        "hopefx_broker_circuit_state",
        "Circuit breaker state per broker (0=closed, 1=half_open, 2=open)",
        ["broker"],
    )
    _PROM_AVAILABLE = True
except Exception as _prom_exc:
    _CB_STATE_GAUGE = None
    _PROM_AVAILABLE = False
    # prometheus_client is optional — circuit breaker works without it
    logger.debug("prometheus_client unavailable — CB metrics disabled: %s", _prom_exc)


class CBState(IntEnum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""

    def __init__(self, broker: str, retry_after: float):
        self.broker = broker
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker OPEN for '{broker}' — retry after {retry_after:.1f}s",
        )


class CircuitBreaker:
    """
    Per-broker circuit breaker.

    Parameters
    ----------
    name              : Broker / service name (used in logs + Prometheus label)
    failure_threshold : Consecutive failures before opening the circuit
    reset_timeout     : Seconds to wait in OPEN state before probing (HALF_OPEN)
    success_threshold : Consecutive successes in HALF_OPEN before closing
    """

    # Global registry so the same breaker is reused across call sites
    _registry: ClassVar[dict[str, CircuitBreaker]] = {}

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold

        self._state = CBState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> CircuitBreaker:
        await self._check()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            await self._on_success()
        elif exc_type is not CircuitBreakerOpenError:
            await self._on_failure(str(exc_val))
        return False  # never suppress exceptions

    # ── State machine ─────────────────────────────────────────────────────────

    async def _check(self) -> None:
        async with self._lock:
            if self._state == CBState.CLOSED:
                return

            if self._state == CBState.OPEN:
                elapsed = time.monotonic() - (self._opened_at or 0)
                if elapsed >= self.reset_timeout:
                    self._transition(CBState.HALF_OPEN)
                    logger.info("Circuit breaker '%s' → HALF_OPEN (probing)", self.name)
                    return
                raise CircuitBreakerOpenError(self.name, self.reset_timeout - elapsed)

            # HALF_OPEN: allow one probe through (no action needed here)

    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            if self._state == CBState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition(CBState.CLOSED)
                    logger.info("Circuit breaker '%s' → CLOSED (recovered)", self.name)

    async def _on_failure(self, error: str) -> None:
        async with self._lock:
            self._last_error = error
            self._failure_count += 1
            self._success_count = 0

            if self._state == CBState.HALF_OPEN:
                # Probe failed — reopen immediately
                self._transition(CBState.OPEN)
                logger.warning(
                    "Circuit breaker '%s' → OPEN (probe failed: %s)",
                    self.name,
                    error,
                )
            elif self._state == CBState.CLOSED and self._failure_count >= self.failure_threshold:
                self._transition(CBState.OPEN)
                logger.error(
                    "Circuit breaker '%s' → OPEN after %d failures. Last: %s",
                    self.name,
                    self._failure_count,
                    error,
                )

    def _transition(self, new_state: CBState) -> None:
        old = self._state
        self._state = new_state
        if new_state == CBState.OPEN:
            self._opened_at = time.monotonic()
            self._success_count = 0
        elif new_state == CBState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None

        # Publish typed event
        try:
            from events.typed_events import (
                CircuitBreakerEvent,
                EventEnvelope,
                publish_sync,
            )

            publish_sync(
                EventEnvelope.wrap(
                    source="circuit_breaker",
                    payload=CircuitBreakerEvent(
                        broker=self.name,
                        state=new_state.name,
                        failure_count=self._failure_count,
                        last_error=self._last_error,
                    ),
                ),
            )
        except Exception as _bus_exc:
            logger.debug("CB event bus publish failed (non-fatal): %s", _bus_exc)

        # Update Prometheus gauge
        if _PROM_AVAILABLE and _CB_STATE_GAUGE is not None:
            try:
                _CB_STATE_GAUGE.labels(broker=self.name).set(int(new_state))
            except Exception as _gauge_exc:
                logger.debug("CB Prometheus gauge update failed (non-fatal): %s", _gauge_exc)

        logger.debug("CB '%s': %s → %s", self.name, old.name, new_state.name)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def state(self) -> CBState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CBState.OPEN

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.name,
            "failure_count": self._failure_count,
            "last_error": self._last_error,
            "opened_at": self._opened_at,
        }

    # ── Class-level registry ──────────────────────────────────────────────────

    @classmethod
    def get(
        cls,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
    ) -> "CircuitBreaker":
        """Return (or create) the named circuit breaker from the global registry.

        Uses setdefault() for atomic check-and-insert under the GIL so two
        concurrent callers always get the same CircuitBreaker instance.
        The previous check-then-set pattern was not atomic: two coroutines
        could both pass the 'not in' check and create two different instances,
        causing each to track failures independently and never opening.
        """
        return cls._registry.setdefault(
            name,
            cls(
                name=name,
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
            ),
        )

    @classmethod
    def all_statuses(cls) -> dict[str, dict]:
        return {name: cb.status() for name, cb in cls._registry.items()}


# ── Decorator ─────────────────────────────────────────────────────────────────


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    reset_timeout: float = 60.0,
) -> Callable:
    """
    Decorator that wraps an async function with a named circuit breaker.

    Example
    -------
        @circuit_breaker("oanda", failure_threshold=5, reset_timeout=60)
        async def fetch_prices(symbols):
            return await session.get(...)
    """
    cb = CircuitBreaker.get(
        name,
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
    )

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            async with cb:
                return await fn(*args, **kwargs)

        return wrapper

    return decorator
