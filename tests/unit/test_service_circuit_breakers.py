# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for resilience/service_circuit_breakers.py.

Covers:
- CLOSED → OPEN transition after failure_threshold failures
- OPEN → HALF_OPEN transition after timeout_seconds
- HALF_OPEN → CLOSED transition after success_threshold successes
- HALF_OPEN → OPEN on failure
- CircuitBreakerOpenError raised when circuit is OPEN
- record_success() / record_failure() sync methods
- force_close() / force_open() admin methods
- get_status() returns correct state dict
- get_all_breaker_status() aggregates all breakers
- Pre-built breakers: redis_breaker, broker_breaker, ml_breaker, db_breaker
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_breaker(
    failure_threshold: int = 3, success_threshold: int = 2, timeout_seconds: float = 60.0, call_timeout: float = 5.0
):
    from resilience.service_circuit_breakers import BreakerConfig, ServiceCircuitBreaker

    cfg = BreakerConfig(
        name="test",
        failure_threshold=failure_threshold,
        success_threshold=success_threshold,
        timeout_seconds=timeout_seconds,
        half_open_max_calls=3,
        call_timeout_seconds=call_timeout,
    )
    return ServiceCircuitBreaker(cfg)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed

    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=3)

        async def fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(fail)

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        from resilience.service_circuit_breakers import CircuitBreakerOpenError

        breaker = _make_breaker(failure_threshold=1)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        assert breaker.is_open
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(AsyncMock(return_value="ok"))

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        breaker = _make_breaker(failure_threshold=1, timeout_seconds=0.01)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        assert breaker.is_open
        await asyncio.sleep(0.05)  # wait for timeout

        # Next call should probe (half-open)
        async def succeed():
            return "ok"

        result = await breaker.call(succeed)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_half_open_closes_after_success_threshold(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=1, success_threshold=2, timeout_seconds=0.01)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        await asyncio.sleep(0.05)

        async def succeed():
            return "ok"

        await breaker.call(succeed)  # first success in half-open
        await breaker.call(succeed)  # second success → should close

        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_reopens_on_failure(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=1, timeout_seconds=0.01)

        async def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        await asyncio.sleep(0.05)

        with pytest.raises(RuntimeError):
            await breaker.call(fail)

        assert breaker.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# Sync record methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncRecordMethods:
    def test_record_failure_opens_after_threshold(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=3)
        exc = RuntimeError("err")
        breaker.record_failure(exc)
        breaker.record_failure(exc)
        assert breaker.state == CircuitState.CLOSED  # not yet
        breaker.record_failure(exc)
        assert breaker.state == CircuitState.OPEN

    def test_record_success_resets_failure_count(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=3)
        exc = RuntimeError("err")
        breaker.record_failure(exc)
        breaker.record_failure(exc)
        breaker.record_success()
        assert breaker._failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    def test_record_success_closes_half_open(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=1, success_threshold=2)
        breaker.record_failure(RuntimeError("e"))
        assert breaker.state == CircuitState.OPEN
        # Manually set to half-open to test sync path
        breaker._state = CircuitState.HALF_OPEN
        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Admin methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdminMethods:
    def test_force_open(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker()
        breaker.force_open()
        assert breaker.state == CircuitState.OPEN

    def test_force_close(self):
        from resilience.service_circuit_breakers import CircuitState

        breaker = _make_breaker(failure_threshold=1)
        breaker.record_failure(RuntimeError("e"))
        assert breaker.is_open
        breaker.force_close()
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStatus:
    def test_status_keys(self):
        breaker = _make_breaker()
        status = breaker.get_status()
        required_keys = {
            "name",
            "state",
            "failure_count",
            "success_count",
            "total_calls",
            "total_failures",
            "total_rejected",
            "failure_rate",
            "seconds_until_probe",
            "last_state_change",
        }
        assert required_keys.issubset(status.keys())

    def test_status_state_value(self):
        breaker = _make_breaker()
        status = breaker.get_status()
        assert status["state"] == "closed"


# ---------------------------------------------------------------------------
# get_all_breaker_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllBreakerStatus:
    def test_returns_all_breakers(self):
        from resilience.service_circuit_breakers import get_all_breaker_status

        result = get_all_breaker_status()
        assert "breakers" in result
        assert "open_count" in result
        assert "all_closed" in result
        assert "redis" in result["breakers"]
        assert "broker" in result["breakers"]
        assert "ml_model" in result["breakers"]
        assert "database" in result["breakers"]


# ---------------------------------------------------------------------------
# Pre-built breakers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrebuiltBreakers:
    def test_redis_breaker_config(self):
        from resilience.service_circuit_breakers import redis_breaker

        assert redis_breaker.name == "redis"
        assert redis_breaker.config.failure_threshold == 3
        assert redis_breaker.config.timeout_seconds == 30.0

    def test_broker_breaker_config(self):
        from resilience.service_circuit_breakers import broker_breaker

        assert broker_breaker.name == "broker"
        assert broker_breaker.config.failure_threshold == 5

    def test_ml_breaker_config(self):
        from resilience.service_circuit_breakers import ml_breaker

        assert ml_breaker.name == "ml_model"

    def test_db_breaker_config(self):
        from resilience.service_circuit_breakers import db_breaker

        assert db_breaker.name == "database"


# ---------------------------------------------------------------------------
# resilience/__init__.py exports
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResilienceInit:
    def test_imports_from_init(self):
        """All public symbols are importable from the resilience package."""
        from resilience import (
            ServiceCircuitBreaker,
            ServiceCircuitBreakers,
            RetryPolicy,
            retry,
        )

        assert ServiceCircuitBreaker is not None
        assert ServiceCircuitBreakers is ServiceCircuitBreaker
        assert RetryPolicy is not None
        assert callable(retry)
