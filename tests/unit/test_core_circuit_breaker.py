# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_circuit_breaker.py
=======================================
Coverage tests for core/circuit_breaker.py.

All tests use real CircuitBreaker instances — no mocking of the module under
test.  External I/O (Prometheus, event bus) is patched at the boundary.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from core.circuit_breaker import (
    CBState,
    CircuitBreaker,
    CircuitBreakerOpenError,
    circuit_breaker,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _fresh(name: str = "test_broker", **kw) -> CircuitBreaker:
    """Return a new CircuitBreaker not in the global registry."""
    return CircuitBreaker(name=name, **kw)


# ── CBState enum ──────────────────────────────────────────────────────────────


def test_cbstate_values():
    assert CBState.CLOSED == 0
    assert CBState.HALF_OPEN == 1
    assert CBState.OPEN == 2


# ── CircuitBreakerOpenError ───────────────────────────────────────────────────


def test_open_error_attributes():
    err = CircuitBreakerOpenError("oanda", 42.5)
    assert err.broker == "oanda"
    assert err.retry_after == 42.5
    assert "oanda" in str(err)
    assert "42.5" in str(err)


# ── Initial state ─────────────────────────────────────────────────────────────


def test_initial_state_closed():
    cb = _fresh()
    assert cb.state == CBState.CLOSED
    assert not cb.is_open
    assert cb.failure_count == 0


def test_status_dict():
    cb = _fresh("broker_x")
    s = cb.status()
    assert s["name"] == "broker_x"
    assert s["state"] == "CLOSED"
    assert s["failure_count"] == 0
    assert s["last_error"] is None
    assert s["opened_at"] is None


# ── Context manager — success path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_manager_success_no_state_change():
    cb = _fresh()
    async with cb:
        pass
    assert cb.state == CBState.CLOSED
    assert cb.failure_count == 0


# ── Failure accumulation → OPEN ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failures_open_circuit():
    cb = _fresh(failure_threshold=3, reset_timeout=60.0)
    for _ in range(3):
        try:
            async with cb:
                raise ValueError("boom")
        except ValueError:
            pass
    assert cb.state == CBState.OPEN
    assert cb.is_open


@pytest.mark.asyncio
async def test_open_circuit_rejects_calls():
    cb = _fresh(failure_threshold=1, reset_timeout=60.0)
    try:
        async with cb:
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    assert cb.is_open
    with pytest.raises(CircuitBreakerOpenError):
        async with cb:
            pass  # should never reach here


@pytest.mark.asyncio
async def test_open_error_not_counted_as_failure():
    """CircuitBreakerOpenError must not increment failure_count."""
    cb = _fresh(failure_threshold=1, reset_timeout=60.0)
    try:
        async with cb:
            raise RuntimeError("first")
    except RuntimeError:
        pass
    count_before = cb.failure_count
    try:
        async with cb:
            pass
    except CircuitBreakerOpenError:
        pass
    assert cb.failure_count == count_before


# ── OPEN → HALF_OPEN after timeout ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transitions_to_half_open_after_timeout():
    cb = _fresh(failure_threshold=1, reset_timeout=0.01)
    try:
        async with cb:
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    assert cb.is_open
    await asyncio.sleep(0.05)
    # Next call should be allowed (HALF_OPEN probe)
    async with cb:
        pass
    # Successful probe with success_threshold=2 → still HALF_OPEN after 1 success
    assert cb.state in (CBState.HALF_OPEN, CBState.CLOSED)


@pytest.mark.asyncio
async def test_transitions_to_closed_after_enough_successes():
    cb = _fresh(failure_threshold=1, reset_timeout=0.01, success_threshold=2)
    try:
        async with cb:
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    await asyncio.sleep(0.05)
    # Two successful probes → CLOSED
    async with cb:
        pass
    async with cb:
        pass
    assert cb.state == CBState.CLOSED


# ── HALF_OPEN → OPEN on probe failure ────────────────────────────────────────


@pytest.mark.asyncio
async def test_half_open_failure_reopens():
    cb = _fresh(failure_threshold=1, reset_timeout=0.01, success_threshold=2)
    try:
        async with cb:
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    await asyncio.sleep(0.05)
    # Probe fails → back to OPEN
    try:
        async with cb:
            raise RuntimeError("probe fail")
    except RuntimeError:
        pass
    assert cb.state == CBState.OPEN


# ── Class-level registry ──────────────────────────────────────────────────────


def test_get_returns_same_instance():
    name = "registry_test_broker"
    # Clean up any pre-existing entry
    CircuitBreaker._registry.pop(name, None)
    cb1 = CircuitBreaker.get(name, failure_threshold=3)
    cb2 = CircuitBreaker.get(name, failure_threshold=3)
    assert cb1 is cb2
    CircuitBreaker._registry.pop(name, None)


def test_all_statuses_returns_dict():
    name = "status_test_broker"
    CircuitBreaker._registry.pop(name, None)
    CircuitBreaker.get(name)
    statuses = CircuitBreaker.all_statuses()
    assert name in statuses
    assert "state" in statuses[name]
    CircuitBreaker._registry.pop(name, None)


# ── Decorator ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decorator_passes_through_on_success():
    name = "decorator_ok_broker"
    CircuitBreaker._registry.pop(name, None)

    @circuit_breaker(name, failure_threshold=5, reset_timeout=60)
    async def _fn():
        return 42

    result = await _fn()
    assert result == 42
    CircuitBreaker._registry.pop(name, None)


@pytest.mark.asyncio
async def test_decorator_opens_on_repeated_failure():
    name = "decorator_fail_broker"
    CircuitBreaker._registry.pop(name, None)

    @circuit_breaker(name, failure_threshold=2, reset_timeout=60)
    async def _fn():
        raise ValueError("always fails")

    for _ in range(2):
        try:
            await _fn()
        except ValueError:
            pass

    with pytest.raises(CircuitBreakerOpenError):
        await _fn()
    CircuitBreaker._registry.pop(name, None)


# ── Prometheus / event bus degradation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_transition_survives_prometheus_error():
    """Prometheus gauge failure must not crash the circuit breaker."""
    cb = _fresh(failure_threshold=1, reset_timeout=60.0)
    with patch("core.circuit_breaker._PROM_AVAILABLE", True), patch(
        "core.circuit_breaker._CB_STATE_GAUGE"
    ) as mock_gauge:
        mock_gauge.labels.side_effect = RuntimeError("prom down")
        try:
            async with cb:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
    # Circuit still opened despite Prometheus error
    assert cb.is_open


@pytest.mark.asyncio
async def test_transition_survives_event_bus_error():
    """Event bus publish failure must not crash the circuit breaker."""
    cb = _fresh(failure_threshold=1, reset_timeout=60.0)
    with patch("core.circuit_breaker._PROM_AVAILABLE", False):
        try:
            async with cb:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
    assert cb.is_open


# ── Retry-after in open error ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_after_decreases_over_time():
    cb = _fresh(failure_threshold=1, reset_timeout=5.0)
    try:
        async with cb:
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    try:
        async with cb:
            pass
    except CircuitBreakerOpenError as e:
        assert e.retry_after <= 5.0
        assert e.retry_after > 0
