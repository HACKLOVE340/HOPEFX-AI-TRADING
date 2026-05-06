# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_ultimate_helpers.py
=====================================
Unit tests for utils/ultimate_helpers.py.

Covers:
- async_retry() — retries on failure, raises after max_attempts, succeeds on first try
- measure_latency() — wraps async and sync functions, returns (result, latency_ms)
- PerformanceProfiler.log() / get_stats() — records metrics and computes statistics
- PerformanceProfiler.snapshot() — returns system metrics dict
"""

from __future__ import annotations

import asyncio
import pytest


# ---------------------------------------------------------------------------
# async_retry
# ---------------------------------------------------------------------------


class TestAsyncRetry:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        from utils.ultimate_helpers import async_retry

        call_count = [0]

        @async_retry(max_attempts=3, delay=0.0)
        async def always_succeeds():
            call_count[0] += 1
            return "ok"

        result = await always_succeeds()
        assert result == "ok"
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        from utils.ultimate_helpers import async_retry

        call_count = [0]

        @async_retry(max_attempts=3, delay=0.0)
        async def fails_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient")
            return "recovered"

        result = await fails_twice()
        assert result == "recovered"
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        from utils.ultimate_helpers import async_retry

        call_count = [0]

        @async_retry(max_attempts=3, delay=0.0)
        async def always_fails():
            call_count[0] += 1
            raise ConnectionError("always down")

        with pytest.raises(ConnectionError, match="always down"):
            await always_fails()
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        from utils.ultimate_helpers import async_retry

        @async_retry(max_attempts=2, delay=0.0)
        async def my_func():
            return 1

        assert my_func.__name__ == "my_func"

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        from utils.ultimate_helpers import async_retry

        @async_retry(max_attempts=2, delay=0.0)
        async def add(a, b, *, multiplier=1):
            return (a + b) * multiplier

        result = await add(3, 4, multiplier=2)
        assert result == 14


# ---------------------------------------------------------------------------
# measure_latency
# ---------------------------------------------------------------------------


class TestMeasureLatency:
    @pytest.mark.asyncio
    async def test_async_function_returns_result_and_latency(self):
        from utils.ultimate_helpers import measure_latency

        @measure_latency
        async def fetch():
            return "data"

        result, latency_ms = await fetch()
        assert result == "data"
        assert latency_ms >= 0.0

    @pytest.mark.asyncio
    async def test_async_latency_is_positive(self):
        from utils.ultimate_helpers import measure_latency

        @measure_latency
        async def slow():
            await asyncio.sleep(0.01)
            return "done"

        _, latency_ms = await slow()
        assert latency_ms >= 5.0  # at least 5ms for a 10ms sleep

    def test_sync_function_returns_result_and_latency(self):
        from utils.ultimate_helpers import measure_latency

        @measure_latency
        def compute():
            return 42

        result, latency_ms = compute()
        assert result == 42
        assert latency_ms >= 0.0

    def test_sync_latency_is_float(self):
        from utils.ultimate_helpers import measure_latency

        @measure_latency
        def noop():
            return None

        _, latency_ms = noop()
        assert isinstance(latency_ms, float)

    def test_sync_preserves_function_name(self):
        from utils.ultimate_helpers import measure_latency

        @measure_latency
        def my_sync_func():
            return 1

        assert my_sync_func.__name__ == "my_sync_func"

    @pytest.mark.asyncio
    async def test_async_preserves_function_name(self):
        from utils.ultimate_helpers import measure_latency

        @measure_latency
        async def my_async_func():
            return 1

        assert my_async_func.__name__ == "my_async_func"


# ---------------------------------------------------------------------------
# PerformanceProfiler
# ---------------------------------------------------------------------------


class TestPerformanceProfiler:
    def test_log_stores_metric(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        p.log("api", "latency_ms", 12.5)
        assert "api" in p.metrics
        assert "latency_ms" in p.metrics["api"]
        assert len(p.metrics["api"]["latency_ms"]) == 1

    def test_log_multiple_values(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        for v in [10.0, 20.0, 30.0]:
            p.log("api", "latency_ms", v)
        assert len(p.metrics["api"]["latency_ms"]) == 3

    def test_get_stats_empty_returns_empty_dict(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        assert p.get_stats("nonexistent", "metric") == {}

    def test_get_stats_returns_statistics(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            p.log("api", "latency_ms", v)
        stats = p.get_stats("api", "latency_ms")
        assert "mean" in stats
        assert "std" in stats
        assert "min" in stats
        assert "max" in stats
        assert "p50" in stats
        assert "p99" in stats

    def test_get_stats_mean_correct(self):
        from utils.ultimate_helpers import PerformanceProfiler
        import pytest
        p = PerformanceProfiler()
        for v in [10.0, 20.0, 30.0]:
            p.log("api", "latency_ms", v)
        stats = p.get_stats("api", "latency_ms")
        assert stats["mean"] == pytest.approx(20.0)

    def test_get_stats_min_max_correct(self):
        from utils.ultimate_helpers import PerformanceProfiler
        import pytest
        p = PerformanceProfiler()
        for v in [5.0, 15.0, 25.0]:
            p.log("api", "latency_ms", v)
        stats = p.get_stats("api", "latency_ms")
        assert stats["min"] == pytest.approx(5.0)
        assert stats["max"] == pytest.approx(25.0)

    def test_snapshot_returns_dict(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        snap = p.snapshot()
        assert isinstance(snap, dict)
        assert "cpu_percent" in snap
        assert "memory_percent" in snap

    def test_snapshot_cpu_in_valid_range(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        snap = p.snapshot()
        assert 0.0 <= snap["cpu_percent"] <= 100.0

    def test_snapshot_memory_in_valid_range(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        snap = p.snapshot()
        assert 0.0 <= snap["memory_percent"] <= 100.0

    def test_multiple_components_tracked_independently(self):
        from utils.ultimate_helpers import PerformanceProfiler
        p = PerformanceProfiler()
        p.log("api", "latency_ms", 10.0)
        p.log("db", "query_ms", 50.0)
        assert "api" in p.metrics
        assert "db" in p.metrics
        assert "latency_ms" in p.metrics["api"]
        assert "query_ms" in p.metrics["db"]
