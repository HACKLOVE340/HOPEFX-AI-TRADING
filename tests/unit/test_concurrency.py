# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Concurrency and thread-safety tests.

Verifies that shared singletons used on every tick — RiskManager,
InferenceEngine, and CircuitBreaker — produce consistent, non-corrupted
results under concurrent access from multiple threads and async tasks.

Test strategy:
  - ThreadPoolExecutor: simulates multiple broker threads calling assess_risk()
    and calculate_position_size() simultaneously (as happens when multiple
    symbols are processed in parallel).
  - asyncio.gather: simulates multiple async tasks hitting the circuit breaker
    concurrently (as happens when the execution engine processes a burst of
    signals).
  - Invariants checked after every concurrent run:
      * No exception escapes from any worker
      * Numeric results are finite and within valid ranges
      * Internal counters are consistent (no lost updates)
"""

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

# ---------------------------------------------------------------------------
# RiskManager thread-safety
# ---------------------------------------------------------------------------


class TestRiskManagerConcurrency:
    """
    RiskManager.assess_risk() and calculate_position_size() must be safe to
    call from multiple threads simultaneously.

    In production, the signal engine processes XAUUSD ticks while the
    execution engine may be processing a fill callback on a different thread.
    Both paths call into RiskManager.
    """

    _WORKERS = 20
    _CALLS_PER_WORKER = 50

    @pytest.fixture()
    def risk_manager(self):
        from risk.manager import RiskConfig, RiskManager

        rc = RiskConfig(
            max_position_size_pct=0.02,
            max_drawdown_pct=0.10,
            daily_loss_limit_pct=0.05,
        )
        return RiskManager(config=rc)

    def _assess_worker(self, rm, worker_id: int) -> list[dict]:
        """Call assess_risk() _CALLS_PER_WORKER times and collect results."""
        results = []
        account_info = {"equity": 100_000.0 + worker_id * 1000, "balance": 100_000.0}
        positions = [{"symbol": "XAUUSD", "quantity": 0.1 * worker_id, "current_price": 2000.0}]
        for _ in range(self._CALLS_PER_WORKER):
            assessment = rm.assess_risk(account_info, positions)
            results.append({"can_trade": assessment.can_trade, "messages": assessment.messages})
        return results

    def _size_worker(self, rm, worker_id: int) -> list[dict]:
        """Call calculate_position_size() _CALLS_PER_WORKER times."""
        results = []
        equity = 100_000.0 + worker_id * 500
        for i in range(self._CALLS_PER_WORKER):
            entry = 2000.0 + i * 0.1
            sizing = rm.calculate_position_size(
                symbol="XAUUSD",
                signal_strength=0.6,
                entry_price=entry,
                stop_loss_price=entry - 10.0,
                take_profit_price=entry + 20.0,
                account_equity=equity,
                volatility=0.15,
                existing_positions=[],
            )
            results.append({"approved": sizing.approved, "size": sizing.recommended_size})
        return results

    def test_assess_risk_concurrent_no_exceptions(self, risk_manager) -> None:
        """No exception must escape from concurrent assess_risk() calls."""
        errors: list[Exception] = []

        def worker(wid):
            try:
                return self._assess_worker(risk_manager, wid)
            except Exception as exc:
                errors.append(exc)
                return []

        with ThreadPoolExecutor(max_workers=self._WORKERS) as pool:
            futures = [pool.submit(worker, i) for i in range(self._WORKERS)]
            all_results = [f.result() for f in as_completed(futures)]

        assert not errors, f"Exceptions in concurrent assess_risk: {errors}"
        total = sum(len(r) for r in all_results)
        assert total == self._WORKERS * self._CALLS_PER_WORKER

    def test_calculate_position_size_concurrent_results_valid(self, risk_manager) -> None:
        """All concurrent sizing results must have non-negative recommended_size."""
        errors: list[Exception] = []
        all_results: list[list[dict]] = []
        lock = threading.Lock()

        def worker(wid):
            try:
                res = self._size_worker(risk_manager, wid)
                with lock:
                    all_results.extend(res)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(self._WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Exceptions in concurrent calculate_position_size: {errors}"
        for r in all_results:
            if r["approved"]:
                assert r["size"] >= 0.0, f"Negative size returned: {r['size']}"

    def test_concurrent_assess_and_size_interleaved(self, risk_manager) -> None:
        """
        Interleave assess_risk() and calculate_position_size() calls across
        threads — simulates the real production pattern where the signal engine
        and execution engine share the same RiskManager instance.
        """
        errors: list[Exception] = []

        def assess_worker():
            try:
                self._assess_worker(risk_manager, 0)
            except Exception as exc:
                errors.append(exc)

        def size_worker():
            try:
                self._size_worker(risk_manager, 1)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=assess_worker) for _ in range(10)] + [
            threading.Thread(target=size_worker) for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Interleaved concurrency errors: {errors}"


# ---------------------------------------------------------------------------
# CircuitBreaker async concurrency
# ---------------------------------------------------------------------------


class TestCircuitBreakerConcurrency:
    """
    CircuitBreaker.record_failure() and record_success() must be safe to
    call from multiple concurrent async tasks.

    In production, the execution engine processes fills concurrently via
    asyncio.gather() — all paths call into the same CircuitBreaker instance.
    """

    @pytest.fixture()
    def circuit_breaker(self):
        from execution.engine import EngineCircuitBreaker

        # max_failures=5, window_sec=60, reset_sec=3600 (won't auto-reset during test)
        return EngineCircuitBreaker(max_failures=5, window_sec=60.0, reset_sec=3600.0)

    @pytest.mark.asyncio
    async def test_concurrent_failures_open_breaker(self, circuit_breaker) -> None:
        """
        Concurrent record_failure() calls must open the breaker once
        max_failures is reached — no failure must be silently dropped.
        """
        n = 20  # well above max_failures=5
        await asyncio.gather(*[circuit_breaker.record_failure() for _ in range(n)])
        # Breaker must be open — failures were not lost
        assert circuit_breaker._open is True

    @pytest.mark.asyncio
    async def test_concurrent_successes_close_breaker(self, circuit_breaker) -> None:
        """record_success() must close the breaker and clear the failure list."""
        # Prime with enough failures to open
        for _ in range(circuit_breaker._max_failures):
            await circuit_breaker.record_failure()
        assert circuit_breaker._open is True

        # Concurrent successes — any one of them must close it
        await asyncio.gather(*[circuit_breaker.record_success() for _ in range(10)])
        assert circuit_breaker._open is False
        assert circuit_breaker._failures == []

    @pytest.mark.asyncio
    async def test_check_raises_when_open_under_concurrency(self, circuit_breaker) -> None:
        """
        Once the breaker opens, concurrent check() calls must all raise
        RuntimeError — no call must silently pass through.
        """
        # Open the breaker
        for _ in range(circuit_breaker._max_failures):
            await circuit_breaker.record_failure()
        assert circuit_breaker._open is True

        errors: list[bool] = []
        passes: list[bool] = []

        async def check_task():
            try:
                await circuit_breaker.check()
                passes.append(True)
            except RuntimeError:
                errors.append(True)

        await asyncio.gather(*[check_task() for _ in range(30)])
        assert not passes, "No check() call must pass through an open circuit breaker"
        assert len(errors) == 30

    @pytest.mark.asyncio
    async def test_mixed_failure_success_no_exceptions(self, circuit_breaker) -> None:
        """
        Interleaved failures and successes must not raise unexpected exceptions
        and must leave the breaker in a consistent boolean state.
        """

        async def fail_task():
            await circuit_breaker.record_failure()

        async def success_task():
            await circuit_breaker.record_success()

        tasks = [fail_task() for _ in range(5)] + [success_task() for _ in range(5)]
        await asyncio.gather(*tasks)
        # State must be a valid boolean — no corruption
        assert isinstance(circuit_breaker._open, bool)
        assert isinstance(circuit_breaker._failures, list)


# ---------------------------------------------------------------------------
# InferenceEngine singleton thread-safety
# ---------------------------------------------------------------------------


class TestInferenceEngineSingletonConcurrency:
    """
    The InferenceEngine module-level singleton must be safe to access from
    multiple threads simultaneously.

    In production, the signal engine calls get_inference_engine() on every
    tick while the hourly trainer may be updating the model concurrently.
    """

    _WORKERS = 10
    _CALLS_PER_WORKER = 20

    def test_get_inference_engine_returns_same_instance(self) -> None:
        """get_inference_engine() must always return the same object."""
        from ml.inference_engine import get_inference_engine

        instances = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            try:
                eng = get_inference_engine()
                with lock:
                    instances.append(id(eng))
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(self._WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"get_inference_engine() raised: {errors}"
        # All threads must get the same singleton instance
        assert len(set(instances)) == 1, f"get_inference_engine() returned {len(set(instances))} different instances"

    def test_health_concurrent_no_exceptions(self) -> None:
        """engine.health() must be safe to call from multiple threads."""
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            for _ in range(self._CALLS_PER_WORKER):
                try:
                    health = engine.health()
                    assert isinstance(health, dict)
                    assert "model_available" in health
                except Exception as exc:
                    with lock:
                        errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(self._WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent engine.health() raised: {errors}"


# ---------------------------------------------------------------------------
# Signal engine _build_ohlcv_proxy thread-safety
# ---------------------------------------------------------------------------


class TestSignalEngineHelpersConcurrency:
    """
    Pure helper functions extracted from signal_engine must be safe to call
    from multiple threads — they are called on every tick.
    """

    _WORKERS = 20
    _CALLS_PER_WORKER = 100

    def test_build_ohlcv_proxy_concurrent(self) -> None:
        """_build_ohlcv_proxy() must return consistent results under concurrency."""
        from core.signal_engine import _build_ohlcv_proxy

        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            data = {
                "prices": [2000.0 + i for i in range(50)],
                "highs": [2010.0 + i for i in range(50)],
                "lows": [1990.0 + i for i in range(50)],
            }
            for _ in range(self._CALLS_PER_WORKER):
                try:
                    result = _build_ohlcv_proxy(data)
                    assert result is not None
                    assert len(result) == 50
                    assert list(result.columns) == ["close", "high", "low"]
                except Exception as exc:
                    with lock:
                        errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(self._WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent _build_ohlcv_proxy() raised: {errors}"

    def test_estimate_vol_concurrent(self) -> None:
        """_estimate_annualised_volatility() must be safe under concurrency."""
        from core.signal_engine import _estimate_annualised_volatility

        import math

        errors: list[Exception] = []
        lock = threading.Lock()

        def worker():
            data = {"prices": [2000.0 * (1 + 0.001 * i) for i in range(30)]}
            for _ in range(self._CALLS_PER_WORKER):
                try:
                    vol = _estimate_annualised_volatility(data, entry=2000.0)
                    assert vol >= 0.0
                    assert math.isfinite(vol)
                except Exception as exc:
                    with lock:
                        errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(self._WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent _estimate_annualised_volatility() raised: {errors}"
