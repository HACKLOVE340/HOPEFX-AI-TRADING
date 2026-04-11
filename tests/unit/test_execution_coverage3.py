# tests/unit/test_execution_coverage3.py
"""Coverage tests for execution/ modules: broker_circuit_breaker, order_algorithms."""
from __future__ import annotations

import asyncio
import pytest


# ── BrokerCircuitBreaker ──────────────────────────────────────────────────────


class TestBrokerCircuitBreakerBasic:
    def setup_method(self):
        from execution.broker_circuit_breaker import BrokerCircuitBreaker, CircuitState

        self.CB = BrokerCircuitBreaker
        self.State = CircuitState

    def test_initial_state_closed(self):
        cb = self.CB("test_broker", max_failures=3, reset_timeout=60)
        assert cb.state == self.State.CLOSED
        assert not cb.is_open
        assert cb.broker_name == "test_broker"

    def test_status_dict_keys(self):
        cb = self.CB("alpaca", max_failures=3, reset_timeout=60)
        s = cb.status()
        assert s["broker"] == "alpaca"
        assert s["state"] == "CLOSED"
        assert "failure_count" in s
        assert "config" in s

    @pytest.mark.asyncio
    async def test_successful_call_stays_closed(self):
        cb = self.CB("b1", max_failures=3, reset_timeout=60)

        async def ok():
            return 42

        result = await cb.call(ok)
        assert result == 42
        assert cb.state == self.State.CLOSED

    @pytest.mark.asyncio
    async def test_sync_callable_works(self):
        cb = self.CB("b1", max_failures=3, reset_timeout=60)

        def sync_fn():
            return "sync"

        result = await cb.call(sync_fn)
        assert result == "sync"

    @pytest.mark.asyncio
    async def test_failures_open_circuit(self):
        from execution.broker_circuit_breaker import CircuitOpenError

        cb = self.CB("b2", max_failures=3, reset_timeout=60)

        async def fail():
            raise ConnectionError("down")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(fail)

        assert cb.state == self.State.OPEN
        assert cb.is_open

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(fail)
        assert exc_info.value.broker_name == "b2"
        assert exc_info.value.failure_count >= 3

    @pytest.mark.asyncio
    async def test_open_circuit_raises_immediately(self):
        from execution.broker_circuit_breaker import CircuitOpenError

        cb = self.CB("b3", max_failures=2, reset_timeout=9999)
        await cb.record_failure("connection")
        await cb.record_failure("connection")
        assert cb.is_open
        with pytest.raises(CircuitOpenError):
            await cb.call(lambda: None)

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        cb = self.CB("b4", max_failures=2, reset_timeout=0.01)
        await cb.record_failure("timeout")
        await cb.record_failure("timeout")
        assert cb.is_open
        await asyncio.sleep(0.05)

        async def ok():
            return "ok"

        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == self.State.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = self.CB("b5", max_failures=2, reset_timeout=0.01, half_open_max=5)
        await cb.record_failure("timeout")
        await cb.record_failure("timeout")
        await asyncio.sleep(0.05)

        async def fail():
            raise RuntimeError("still down")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == self.State.OPEN

    @pytest.mark.asyncio
    async def test_half_open_max_calls_exceeded(self):
        from execution.broker_circuit_breaker import CircuitOpenError

        cb = self.CB("b6", max_failures=2, reset_timeout=0.01, half_open_max=1)
        await cb.record_failure("connection")
        await cb.record_failure("connection")
        await asyncio.sleep(0.05)
        # First call transitions to HALF_OPEN and increments counter
        # Second call should raise CircuitOpenError
        async def ok():
            return 1

        await cb.call(ok)  # uses the 1 allowed half-open call → closes
        # Now closed again; open it again
        await cb.record_failure("connection")
        await cb.record_failure("connection")
        await asyncio.sleep(0.05)
        # Exhaust half_open_max=1 without success
        cb._state = cb._state  # no-op, just ensure state
        # Manually set to HALF_OPEN with calls already at max
        from execution.broker_circuit_breaker import CircuitState

        cb._state = CircuitState.HALF_OPEN
        cb._half_open_calls = 1
        with pytest.raises(CircuitOpenError):
            await cb.call(ok)

    @pytest.mark.asyncio
    async def test_record_success_resets_failure_count(self):
        cb = self.CB("b7", max_failures=5, reset_timeout=60)
        await cb.record_failure("unknown")
        await cb.record_failure("unknown")
        await cb.record_success()
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_failure_type_counts(self):
        cb = self.CB("b8", max_failures=10, reset_timeout=60)
        await cb.record_failure("timeout")
        await cb.record_failure("timeout")
        await cb.record_failure("auth")
        s = cb.status()
        assert s["failure_type_counts"]["timeout"] == 2
        assert s["failure_type_counts"]["auth"] == 1

    @pytest.mark.asyncio
    async def test_unknown_failure_type_normalised(self):
        cb = self.CB("b9", max_failures=10, reset_timeout=60)
        await cb.record_failure("bogus_type")
        s = cb.status()
        assert s["failure_type_counts"]["unknown"] == 1

    @pytest.mark.asyncio
    async def test_status_open_shows_retry_in(self):
        cb = self.CB("b10", max_failures=2, reset_timeout=60)
        await cb.record_failure("connection")
        await cb.record_failure("connection")
        s = cb.status()
        assert s["retry_in_seconds"] is not None
        assert s["retry_in_seconds"] > 0

    @pytest.mark.asyncio
    async def test_total_counters(self):
        cb = self.CB("b11", max_failures=10, reset_timeout=60)

        async def ok():
            return 1

        await cb.call(ok)
        await cb.call(ok)
        s = cb.status()
        assert s["total_calls"] == 2
        assert s["total_successes"] == 2

    @pytest.mark.asyncio
    async def test_value_error_recorded_as_failure(self):
        cb = self.CB("b12", max_failures=10, reset_timeout=60)

        async def bad():
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await cb.call(bad)
        assert cb._total_failures == 1

    @pytest.mark.asyncio
    async def test_os_error_recorded(self):
        cb = self.CB("b13", max_failures=10, reset_timeout=60)

        async def bad():
            raise OSError("socket error")

        with pytest.raises(OSError):
            await cb.call(bad)
        assert cb._total_failures == 1


class TestClassifyError:
    def test_timeout(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(TimeoutError("timed out")) == "timeout"

    def test_connection(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(ConnectionError("network unreachable")) == "connection"

    def test_auth(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(ValueError("unauthorized access")) == "auth"

    def test_rejection(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(RuntimeError("order rejected")) == "rejection"

    def test_unknown(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(RuntimeError("something weird")) == "unknown"

    def test_socket_is_connection(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(OSError("socket unreachable")) == "connection"

    def test_forbidden_is_auth(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(ValueError("forbidden")) == "auth"

    def test_deadline_is_timeout(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(RuntimeError("deadline exceeded")) == "timeout"

    def test_insufficient_is_rejection(self):
        from execution.broker_circuit_breaker import _classify_error

        assert _classify_error(RuntimeError("insufficient funds")) == "rejection"
