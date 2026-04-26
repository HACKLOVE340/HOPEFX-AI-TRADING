# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for resilience/retry.py.

Covers:
- RetryPolicy.execute() — async path
- RetryPolicy.execute_sync() — sync path
- Exponential back-off delay computation
- Full jitter (delay in [0, computed])
- Exception filter (only retry on specified types)
- on_retry / on_success / on_failure callbacks
- @retry decorator (async and sync)
- Pre-built policies: redis_retry, broker_retry, http_retry, db_retry
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# RetryPolicy.execute — async
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetryPolicyAsync:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """No retry when the first call succeeds."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3, base_delay=0.0)
        func = AsyncMock(return_value=42)
        result = await policy.execute(func)
        assert result == 42
        func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        """Retries until success within max_attempts."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=False)
        func = AsyncMock(side_effect=[ValueError("fail"), ValueError("fail"), 99])
        result = await policy.execute(func)
        assert result == 99
        assert func.await_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        """Raises the last exception when all attempts are exhausted."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=2, base_delay=0.0, jitter=False)
        func = AsyncMock(side_effect=RuntimeError("always fails"))
        with pytest.raises(RuntimeError, match="always fails"):
            await policy.execute(func)
        assert func.await_count == 2

    @pytest.mark.asyncio
    async def test_exception_filter_no_retry_on_excluded(self):
        """Does not retry when exception type is not in the filter."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3, base_delay=0.0, exceptions=(ValueError,))
        func = AsyncMock(side_effect=TypeError("wrong type"))
        with pytest.raises(TypeError):
            await policy.execute(func)
        func.assert_awaited_once()  # no retry

    @pytest.mark.asyncio
    async def test_exception_filter_retries_on_matching(self):
        """Retries when exception type matches the filter."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=False, exceptions=(ValueError,))
        func = AsyncMock(side_effect=[ValueError("v"), ValueError("v"), "ok"])
        result = await policy.execute(func)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_on_retry_callback_called(self):
        """on_retry callback is called for each retry."""
        from resilience.retry import RetryPolicy

        on_retry = MagicMock()
        policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=False, on_retry=on_retry)
        func = AsyncMock(side_effect=[OSError("e"), OSError("e"), "done"])
        await policy.execute(func)
        assert on_retry.call_count == 2

    @pytest.mark.asyncio
    async def test_on_success_callback_called(self):
        """on_success callback is called on success."""
        from resilience.retry import RetryPolicy

        on_success = MagicMock()
        policy = RetryPolicy(max_attempts=3, base_delay=0.0, on_success=on_success)
        func = AsyncMock(return_value="result")
        await policy.execute(func)
        on_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_failure_callback_called(self):
        """on_failure callback is called when all attempts are exhausted."""
        from resilience.retry import RetryPolicy

        on_failure = MagicMock()
        policy = RetryPolicy(max_attempts=2, base_delay=0.0, jitter=False, on_failure=on_failure)
        func = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await policy.execute(func)
        on_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_func_executed_in_executor(self):
        """Synchronous callables are run in an executor."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=1, base_delay=0.0)
        calls = []

        def sync_func():
            calls.append(1)
            return "sync_result"

        result = await policy.execute(sync_func)
        assert result == "sync_result"
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# RetryPolicy.execute_sync — sync path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetryPolicySync:
    def test_success_on_first_attempt(self):
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3, base_delay=0.0)
        func = MagicMock(return_value="ok")
        result = policy.execute_sync(func)
        assert result == "ok"
        func.assert_called_once()

    def test_retries_then_succeeds(self):
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=False)
        func = MagicMock(side_effect=[OSError("e"), OSError("e"), "done"])
        result = policy.execute_sync(func)
        assert result == "done"
        assert func.call_count == 3

    def test_raises_after_max_attempts(self):
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=2, base_delay=0.0, jitter=False)
        func = MagicMock(side_effect=ValueError("always"))
        with pytest.raises(ValueError, match="always"):
            policy.execute_sync(func)
        assert func.call_count == 2


# ---------------------------------------------------------------------------
# Delay computation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDelayComputation:
    def test_no_jitter_exponential(self):
        """Without jitter, delay grows exponentially up to max_delay."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(base_delay=1.0, max_delay=10.0, backoff_factor=2.0, jitter=False)
        assert policy._compute_delay(1) == 1.0
        assert policy._compute_delay(2) == 2.0
        assert policy._compute_delay(3) == 4.0
        assert policy._compute_delay(4) == 8.0
        assert policy._compute_delay(5) == 10.0  # capped at max_delay

    def test_jitter_within_bounds(self):
        """With jitter, delay is in [0, computed_delay]."""
        from resilience.retry import RetryPolicy

        policy = RetryPolicy(base_delay=1.0, max_delay=10.0, backoff_factor=2.0, jitter=True)
        for attempt in range(1, 6):
            raw = min(1.0 * (2.0 ** (attempt - 1)), 10.0)
            delay = policy._compute_delay(attempt)
            assert 0.0 <= delay <= raw + 1e-9


# ---------------------------------------------------------------------------
# @retry decorator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetryDecorator:
    @pytest.mark.asyncio
    async def test_async_decorator(self):
        """@retry wraps async functions correctly."""
        from resilience.retry import retry

        call_count = 0

        @retry(max_attempts=3, base_delay=0.0, jitter=False)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("not yet")
            return "done"

        result = await flaky()
        assert result == "done"
        assert call_count == 3

    def test_sync_decorator(self):
        """@retry wraps sync functions correctly."""
        from resilience.retry import retry

        call_count = 0

        @retry(max_attempts=3, base_delay=0.0, jitter=False)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("not yet")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 2

    def test_decorator_preserves_function_name(self):
        """@retry preserves __name__ via functools.wraps."""
        from resilience.retry import retry

        @retry(max_attempts=1)
        async def my_function():
            pass

        assert my_function.__name__ == "my_function"


# ---------------------------------------------------------------------------
# Pre-built policies
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrebuiltPolicies:
    def test_redis_retry_config(self):
        from resilience.retry import redis_retry

        assert redis_retry.max_attempts == 3
        assert redis_retry.base_delay == 0.1
        assert redis_retry.max_delay == 2.0

    def test_broker_retry_config(self):
        from resilience.retry import broker_retry

        assert broker_retry.max_attempts == 5
        assert broker_retry.base_delay == 1.0
        assert broker_retry.max_delay == 30.0

    def test_http_retry_config(self):
        from resilience.retry import http_retry

        assert http_retry.max_attempts == 3
        assert http_retry.base_delay == 0.5

    def test_db_retry_config(self):
        from resilience.retry import db_retry

        assert db_retry.max_attempts == 3
        assert db_retry.base_delay == 0.2
