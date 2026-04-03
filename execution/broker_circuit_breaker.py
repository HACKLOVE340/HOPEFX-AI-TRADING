# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/broker_circuit_breaker.py
====================================
Per-broker circuit breaker with typed failure tracking.

State machine
-------------
::

    CLOSED ──[failures >= max]──► OPEN ──[reset_timeout elapsed]──► HALF_OPEN
      ▲                                                                    │
      └──────────────[success]──────────────────────────────────────────┘
                                                        │
                              OPEN ◄──────[failure]──────┘

States
------
CLOSED    Normal operation — all calls are forwarded to the broker.
OPEN      All calls are rejected immediately (fail-fast).
HALF_OPEN A limited number of test calls are allowed through to probe recovery.

Environment variables
---------------------
BROKER_CB_MAX_FAILURES : int
    Consecutive failures before opening the breaker (default: 5).
BROKER_CB_RESET_TIMEOUT : float
    Seconds the breaker stays OPEN before transitioning to HALF_OPEN (default: 60).
BROKER_CB_HALF_OPEN_MAX : int
    Maximum test calls permitted in HALF_OPEN state (default: 2).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Config from environment ────────────────────────────────────────────────────
_MAX_FAILURES: int = int(os.getenv("BROKER_CB_MAX_FAILURES", "5"))
_RESET_TIMEOUT: float = float(os.getenv("BROKER_CB_RESET_TIMEOUT", "60"))
_HALF_OPEN_MAX: int = int(os.getenv("BROKER_CB_HALF_OPEN_MAX", "2"))


class CircuitState(str, Enum):
    """Circuit breaker state."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# ── Typed failure categories ───────────────────────────────────────────────────

FAILURE_TYPES = frozenset({"connection", "timeout", "auth", "rejection", "unknown"})


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN.

    Attributes:
        broker_name: Broker identifier.
        failure_count: Number of recorded failures.
        retry_in_seconds: Approximate seconds until HALF_OPEN transition.
    """

    def __init__(
        self,
        broker_name: str,
        failure_count: int,
        retry_in_seconds: float,
    ) -> None:
        self.broker_name = broker_name
        self.failure_count = failure_count
        self.retry_in_seconds = retry_in_seconds
        super().__init__(
            f"Circuit breaker OPEN for broker '{broker_name}' "
            f"({failure_count} failures). Retry in {retry_in_seconds:.0f}s."
        )


class BrokerCircuitBreaker:
    """Per-broker circuit breaker with typed failure tracking.

    Each broker should have its own :class:`BrokerCircuitBreaker` instance.
    This class is **not** a singleton.

    Args:
        broker_name: Human-readable broker identifier (used in logs/metrics).
        max_failures: Consecutive failures before opening (env: BROKER_CB_MAX_FAILURES).
        reset_timeout: Seconds OPEN before transitioning to HALF_OPEN
            (env: BROKER_CB_RESET_TIMEOUT).
        half_open_max: Max test calls in HALF_OPEN (env: BROKER_CB_HALF_OPEN_MAX).

    Example:
        ::

            cb = BrokerCircuitBreaker("alpaca")
            try:
                result = await cb.call(broker.submit_order, order)
            except CircuitOpenError:
                # shed the load
            except Exception:
                # real broker error (already recorded by cb)
    """

    def __init__(
        self,
        broker_name: str,
        *,
        max_failures: int = _MAX_FAILURES,
        reset_timeout: float = _RESET_TIMEOUT,
        half_open_max: int = _HALF_OPEN_MAX,
    ) -> None:
        self._broker_name = broker_name
        self._max_failures = max_failures
        self._reset_timeout = reset_timeout
        self._half_open_max = half_open_max

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._half_open_calls: int = 0
        self._opened_at: float | None = None
        self._last_failure_type: str | None = None
        self._last_failure_at: datetime | None = None
        self._total_calls: int = 0
        self._total_successes: int = 0
        self._total_failures: int = 0

        # Typed failure counters
        self._failure_type_counts: dict[str, int] = {ft: 0 for ft in FAILURE_TYPES}

        self._lock = asyncio.Lock()

        logger.info(
            "BrokerCircuitBreaker[%s] created | max_failures=%d reset_timeout=%.0fs half_open_max=%d",
            broker_name,
            max_failures,
            reset_timeout,
            half_open_max,
        )

    # ------------------------------------------------------------------
    # Core call wrapper
    # ------------------------------------------------------------------

    async def call(self, broker_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute *broker_fn* through the circuit breaker.

        Args:
            broker_fn: Async or sync callable representing the broker operation.
            *args: Positional arguments forwarded to *broker_fn*.
            **kwargs: Keyword arguments forwarded to *broker_fn*.

        Returns:
            Whatever *broker_fn* returns on success.

        Raises:
            CircuitOpenError: When the breaker is OPEN and the reset timeout
                has not elapsed.
            Exception: Any exception raised by *broker_fn* (also recorded as
                a failure).
        """
        await self._check_state()

        self._total_calls += 1
        try:
            if asyncio.iscoroutinefunction(broker_fn):
                result = await broker_fn(*args, **kwargs)
            else:
                result = broker_fn(*args, **kwargs)
            await self.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            error_type = _classify_error(exc)
            await self.record_failure(error_type)
            raise

    # ------------------------------------------------------------------
    # State inspection / transition helpers
    # ------------------------------------------------------------------

    async def _check_state(self) -> None:
        """Assert that a call is permissible in the current state.

        Raises:
            CircuitOpenError: When OPEN and reset timeout has not elapsed.
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return

            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - (self._opened_at or 0)
                if elapsed >= self._reset_timeout:
                    self._transition_to_half_open()
                else:
                    retry_in = self._reset_timeout - elapsed
                    raise CircuitOpenError(
                        self._broker_name,
                        self._failure_count,
                        retry_in,
                    )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._half_open_max:
                    raise CircuitOpenError(
                        self._broker_name,
                        self._failure_count,
                        0.0,
                    )
                self._half_open_calls += 1

    async def record_failure(self, error_type: str = "unknown") -> None:
        """Record a typed broker failure and transition state if needed.

        Args:
            error_type: Failure category — one of ``connection``, ``timeout``,
                ``auth``, ``rejection``, ``unknown``.
        """
        if error_type not in FAILURE_TYPES:
            error_type = "unknown"

        async with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_type = error_type
            self._last_failure_at = datetime.now(UTC)
            self._failure_type_counts[error_type] = self._failure_type_counts.get(error_type, 0) + 1

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    "BrokerCircuitBreaker[%s]: failure in HALF_OPEN — returning to OPEN",
                    self._broker_name,
                )
                self._transition_to_open()
            elif self._state == CircuitState.CLOSED and self._failure_count >= self._max_failures:
                logger.critical(
                    "BrokerCircuitBreaker[%s]: %d consecutive failures (%s) — circuit OPEN",
                    self._broker_name,
                    self._failure_count,
                    error_type,
                )
                self._transition_to_open()

    async def record_success(self) -> None:
        """Record a successful broker call and reset the breaker if in HALF_OPEN.

        In HALF_OPEN state a success causes the breaker to fully CLOSE.
        In CLOSED state it simply resets the consecutive failure counter.
        """
        async with self._lock:
            self._total_successes += 1
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "BrokerCircuitBreaker[%s]: success in HALF_OPEN — circuit CLOSED",
                    self._broker_name,
                )
                self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition_to_open(self) -> None:
        """Move to OPEN state (must be called under ``_lock``)."""
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        """Move to HALF_OPEN state (must be called under ``_lock``)."""
        logger.info(
            "BrokerCircuitBreaker[%s]: reset timeout elapsed — transitioning to HALF_OPEN",
            self._broker_name,
        )
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0

    def _transition_to_closed(self) -> None:
        """Move to CLOSED state and reset counters (must be called under ``_lock``)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None
        self._half_open_calls = 0

    # ------------------------------------------------------------------
    # Status / inspection
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a JSON-serialisable status dictionary.

        Returns:
            Dictionary containing state, counters, and configuration.
        """
        now = time.monotonic()
        open_since: float | None = None
        retry_in: float | None = None
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            open_since = round(now - self._opened_at, 1)
            retry_in = max(0.0, round(self._reset_timeout - open_since, 1))

        return {
            "broker": self._broker_name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "failure_type_counts": dict(self._failure_type_counts),
            "last_failure_type": self._last_failure_type,
            "last_failure_at": self._last_failure_at.isoformat() if self._last_failure_at else None,
            "open_since_seconds": open_since,
            "retry_in_seconds": retry_in,
            "half_open_calls": self._half_open_calls,
            "config": {
                "max_failures": self._max_failures,
                "reset_timeout_seconds": self._reset_timeout,
                "half_open_max": self._half_open_max,
            },
        }

    @property
    def state(self) -> CircuitState:
        """Current circuit breaker state."""
        return self._state

    @property
    def is_open(self) -> bool:
        """``True`` when the breaker is OPEN (blocking all calls)."""
        return self._state == CircuitState.OPEN

    @property
    def broker_name(self) -> str:
        """Name of the broker this breaker guards."""
        return self._broker_name


# ── Error classifier ───────────────────────────────────────────────────────────


def _classify_error(exc: Exception) -> str:
    """Classify a broker exception into a typed failure category.

    Args:
        exc: The exception raised by the broker call.

    Returns:
        One of ``connection``, ``timeout``, ``auth``, ``rejection``, ``unknown``.
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if any(k in msg or k in name for k in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(k in msg or k in name for k in ("auth", "unauthorized", "forbidden", "credential")):
        return "auth"
    if any(k in msg or k in name for k in ("reject", "refused", "denied", "insufficient")):
        return "rejection"
    if any(k in msg or k in name for k in ("connect", "connection", "network", "socket", "unreachable")):
        return "connection"
    return "unknown"
