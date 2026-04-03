# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_circuit_breaker_deep.py
========================================
Deep unit tests for core/circuit_breaker.py covering the full state-machine,
registry, decorator, and error types.

Coverage targets:
- ``CBState`` enum values
- ``CircuitBreakerOpenError`` attributes
- Full state transitions: CLOSED → OPEN → HALF_OPEN → CLOSED
- Probe failure in HALF_OPEN reopens circuit immediately
- Reset timeout window (OPEN→HALF_OPEN)
- ``status()`` dict shape and content
- ``is_open`` / ``state`` / ``failure_count`` properties
- ``CircuitBreaker.get()`` registry deduplication
- ``CircuitBreaker.all_statuses()`` aggregation
- ``circuit_breaker`` decorator — passes on success, opens on failures
- Context-manager ``__aexit__`` does not suppress exceptions
"""

from __future__ import annotations

import asyncio

import pytest

from core.circuit_breaker import (
    CBState,
    CircuitBreaker,
    CircuitBreakerOpenError,
    circuit_breaker,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _cb(
    name: str = "test",
    failure_threshold: int = 3,
    reset_timeout: float = 60.0,
    success_threshold: int = 2,
) -> CircuitBreaker:
    """Return a fresh (unregistered) CircuitBreaker for isolation."""
    return CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
        success_threshold=success_threshold,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CBState enum
# ─────────────────────────────────────────────────────────────────────────────


class TestCBState:
    def test_three_states_exist(self):
        assert CBState.CLOSED is not None
        assert CBState.OPEN is not None
        assert CBState.HALF_OPEN is not None

    def test_closed_is_not_open(self):
        assert CBState.CLOSED != CBState.OPEN


# ─────────────────────────────────────────────────────────────────────────────
# CircuitBreakerOpenError
# ─────────────────────────────────────────────────────────────────────────────


class TestCircuitBreakerOpenError:
    def test_has_broker_and_retry_after(self):
        err = CircuitBreakerOpenError("oanda", 45.0)
        assert err.broker == "oanda"
        assert err.retry_after == 45.0

    def test_is_exception(self):
        err = CircuitBreakerOpenError("test", 10.0)
        assert isinstance(err, Exception)


# ─────────────────────────────────────────────────────────────────────────────
# Initial state
# ─────────────────────────────────────────────────────────────────────────────


class TestInitialState:
    def test_starts_closed(self):
        cb = _cb()
        assert cb.state == CBState.CLOSED
        assert cb.is_open is False

    def test_initial_failure_count_is_zero(self):
        cb = _cb()
        assert cb.failure_count == 0

    def test_status_dict_shape(self):
        cb = _cb()
        s = cb.status()
        assert s["name"] == "test"
        assert s["state"] == "CLOSED"
        assert s["failure_count"] == 0
        assert s["last_error"] is None


# ─────────────────────────────────────────────────────────────────────────────
# CLOSED → OPEN state transition
# ─────────────────────────────────────────────────────────────────────────────


class TestClosedToOpen:
    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = _cb(failure_threshold=3)
        for _ in range(3):
            await cb._on_failure("err")
        assert cb.state == CBState.OPEN
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_stays_closed_below_threshold(self):
        cb = _cb(failure_threshold=3)
        for _ in range(2):
            await cb._on_failure("err")
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_check_raises_when_open(self):
        cb = _cb(failure_threshold=1)
        await cb._on_failure("err")
        with pytest.raises(CircuitBreakerOpenError):
            await cb._check()

    @pytest.mark.asyncio
    async def test_context_manager_opens_on_exceptions(self):
        cb = _cb(failure_threshold=2)
        for _ in range(2):
            try:
                async with cb:
                    raise ValueError("simulated error")
            except ValueError:
                pass
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_context_manager_blocked_when_open(self):
        cb = _cb(failure_threshold=1)
        await cb._on_failure("err")
        with pytest.raises(CircuitBreakerOpenError):
            async with cb:
                pass  # pragma: no cover


# ─────────────────────────────────────────────────────────────────────────────
# OPEN → HALF_OPEN state transition (reset timeout)
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenToHalfOpen:
    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        cb = _cb(failure_threshold=1, reset_timeout=0.05)  # 50ms timeout
        await cb._on_failure("err")
        assert cb.state == CBState.OPEN

        await asyncio.sleep(0.1)  # wait for reset timeout

        # _check() should transition to HALF_OPEN (not raise)
        await cb._check()
        assert cb.state == CBState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_does_not_transition_before_timeout(self):
        cb = _cb(failure_threshold=1, reset_timeout=9999.0)
        await cb._on_failure("err")
        with pytest.raises(CircuitBreakerOpenError):
            await cb._check()
        assert cb.state == CBState.OPEN


# ─────────────────────────────────────────────────────────────────────────────
# HALF_OPEN → CLOSED (recovery)
# ─────────────────────────────────────────────────────────────────────────────


class TestHalfOpenToClosed:
    @pytest.mark.asyncio
    async def test_closes_after_success_threshold_in_half_open(self):
        cb = _cb(failure_threshold=1, reset_timeout=0.01, success_threshold=2)
        await cb._on_failure("err")
        await asyncio.sleep(0.05)
        await cb._check()  # → HALF_OPEN

        await cb._on_success()  # 1st success
        assert cb.state == CBState.HALF_OPEN
        await cb._on_success()  # 2nd success → CLOSED
        assert cb.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_count_reset_on_close(self):
        cb = _cb(failure_threshold=1, reset_timeout=0.01, success_threshold=1)
        await cb._on_failure("err")
        await asyncio.sleep(0.05)
        await cb._check()  # → HALF_OPEN
        await cb._on_success()  # → CLOSED
        assert cb.failure_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# HALF_OPEN → OPEN (probe failure)
# ─────────────────────────────────────────────────────────────────────────────


class TestHalfOpenProbeFailure:
    @pytest.mark.asyncio
    async def test_probe_failure_reopens_circuit(self):
        cb = _cb(failure_threshold=1, reset_timeout=0.01)
        await cb._on_failure("first err")
        await asyncio.sleep(0.05)
        await cb._check()  # → HALF_OPEN

        await cb._on_failure("probe failed")
        assert cb.state == CBState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count_in_half_open(self):
        cb = _cb(failure_threshold=1, reset_timeout=0.01, success_threshold=3)
        await cb._on_failure("err")
        await asyncio.sleep(0.05)
        await cb._check()  # → HALF_OPEN

        await cb._on_success()
        assert cb.failure_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Context manager — does not suppress exceptions
# ─────────────────────────────────────────────────────────────────────────────


class TestContextManager:
    @pytest.mark.asyncio
    async def test_reraises_value_error(self):
        cb = _cb(failure_threshold=100)
        with pytest.raises(ValueError, match="boom"):
            async with cb:
                raise ValueError("boom")

    @pytest.mark.asyncio
    async def test_does_not_suppress_circuit_breaker_open_error(self):
        cb = _cb(failure_threshold=1)
        await cb._on_failure("err")
        with pytest.raises(CircuitBreakerOpenError):
            async with cb:
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_success_path_calls_on_success(self):
        cb = _cb()
        # Prime with one failure so we can observe success reset
        await cb._on_failure("err")
        assert cb.failure_count == 1
        async with cb:
            pass  # success
        assert cb.failure_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Registry: get() and all_statuses()
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistry:
    def setup_method(self):
        """Clear registry before each test to avoid cross-test contamination."""
        CircuitBreaker._registry.clear()

    def test_get_creates_new_instance(self):
        cb = CircuitBreaker.get("broker_a")
        assert isinstance(cb, CircuitBreaker)
        assert cb.name == "broker_a"

    def test_get_returns_same_instance(self):
        cb1 = CircuitBreaker.get("broker_b")
        cb2 = CircuitBreaker.get("broker_b")
        assert cb1 is cb2

    def test_all_statuses_returns_all(self):
        CircuitBreaker.get("svc_x")
        CircuitBreaker.get("svc_y")
        statuses = CircuitBreaker.all_statuses()
        assert "svc_x" in statuses
        assert "svc_y" in statuses

    def test_all_statuses_empty_when_no_registrations(self):
        assert CircuitBreaker.all_statuses() == {}


# ─────────────────────────────────────────────────────────────────────────────
# @circuit_breaker decorator
# ─────────────────────────────────────────────────────────────────────────────


class TestCircuitBreakerDecorator:
    def setup_method(self):
        CircuitBreaker._registry.clear()

    @pytest.mark.asyncio
    async def test_passes_through_on_success(self):
        results = []

        @circuit_breaker("deco_test", failure_threshold=5)
        async def my_fn():
            results.append(1)
            return 42

        val = await my_fn()
        assert val == 42
        assert results == [1]

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        call_count = [0]

        @circuit_breaker("deco_fail", failure_threshold=2, reset_timeout=9999.0)
        async def my_fn():
            call_count[0] += 1
            raise ValueError("service down")

        # Two failures should open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await my_fn()

        # Third call blocked by open circuit
        with pytest.raises(CircuitBreakerOpenError):
            await my_fn()
        assert call_count[0] == 2  # third call was blocked before entering fn

    @pytest.mark.asyncio
    async def test_decorator_wraps_preserves_function_name(self):
        @circuit_breaker("deco_meta")
        async def my_special_function():
            pass  # pragma: no cover

        assert my_special_function.__name__ == "my_special_function"
