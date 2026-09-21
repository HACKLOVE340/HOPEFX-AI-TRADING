# tests/unit/test_execution_coverage4.py
"""Coverage tests for order_algorithms (TWAP, VWAP, PartialFillAggregator)."""

from __future__ import annotations

import pytest


class TestPartialFillAggregator:
    def setup_method(self):
        from execution.order_algorithms import PartialFillAggregator

        self.agg = PartialFillAggregator()

    def test_register_and_pending_count(self):
        self.agg.register("ord1", "XAUUSD", "long", 0.1)
        assert self.agg.pending_count() == 1

    def test_record_fill_partial(self):
        self.agg.register("ord2", "XAUUSD", "long", 0.1)
        state = self.agg.record_fill("ord2", 0.05, 2350.0)
        assert state is not None
        assert state.filled_lots == pytest.approx(0.05)
        assert self.agg.pending_count() == 1  # still open

    def test_record_fill_completes(self):
        completed = []
        self.agg.on_complete(lambda s: completed.append(s))
        self.agg.register("ord3", "XAUUSD", "long", 0.1)
        self.agg.record_fill("ord3", 0.05, 2350.0)
        self.agg.record_fill("ord3", 0.05, 2351.0)
        assert len(completed) == 1
        assert self.agg.pending_count() == 0

    def test_record_fill_unknown_parent(self):
        result = self.agg.record_fill("nonexistent", 0.01, 2350.0)
        assert result is None

    def test_avg_price_weighted(self):
        self.agg.register("ord4", "XAUUSD", "long", 0.2)
        self.agg.record_fill("ord4", 0.1, 2350.0)
        state = self.agg.record_fill("ord4", 0.1, 2360.0)
        assert state.avg_price == pytest.approx(2355.0)

    def test_fill_pct(self):
        self.agg.register("ord5", "XAUUSD", "long", 0.1)
        state = self.agg.record_fill("ord5", 0.05, 2350.0)
        assert state.fill_pct == pytest.approx(0.5)

    def test_remaining_lots(self):
        self.agg.register("ord6", "XAUUSD", "long", 0.1)
        state = self.agg.record_fill("ord6", 0.03, 2350.0)
        assert state.remaining_lots == pytest.approx(0.07)

    def test_callback_error_does_not_propagate(self):
        def bad_cb(s):
            raise RuntimeError("callback error")

        self.agg.on_complete(bad_cb)
        self.agg.register("ord7", "XAUUSD", "long", 0.01)
        # Should not raise even though callback raises
        self.agg.record_fill("ord7", 0.01, 2350.0)

    def test_timeout_triggers_complete(self):
        from unittest.mock import patch

        completed = []
        self.agg.on_complete(lambda s: completed.append(s))
        self.agg.register("ord8", "XAUUSD", "long", 1.0)
        # Patch is_timed_out to return True
        with patch(
            "execution.order_algorithms.PartialFillState.is_timed_out",
            new_callable=lambda: property(lambda self: True),
        ):
            self.agg.record_fill("ord8", 0.1, 2350.0)
        assert len(completed) == 1


class TestPartialFillState:
    def test_is_complete_tolerance(self):
        from execution.order_algorithms import PartialFillState

        s = PartialFillState("p1", "XAUUSD", "long", 0.1)
        s.add_fill(0.0999, 2350.0)  # 99.9% — within 0.1% tolerance
        assert s.is_complete

    def test_not_complete_below_tolerance(self):
        from execution.order_algorithms import PartialFillState

        s = PartialFillState("p2", "XAUUSD", "long", 0.1)
        s.add_fill(0.09, 2350.0)  # 90% — not complete
        assert not s.is_complete

    def test_is_not_timed_out_immediately(self):
        from execution.order_algorithms import PartialFillState

        s = PartialFillState("p3", "XAUUSD", "long", 0.1)
        assert not s.is_timed_out


class TestTWAPExecutor:
    @pytest.mark.asyncio
    async def test_no_router_returns_pending(self):
        from execution.order_algorithms import TWAPExecutor

        ex = TWAPExecutor(router=None)
        result = await ex.execute(
            parent_id="twap1",
            symbol="XAUUSD",
            side="long",
            total_lots=0.05,
            duration_s=0.01,
            slices=2,
        )
        assert result["algo"] == "twap"
        assert result["parent_id"] == "twap1"
        assert result["child_count"] == 2

    @pytest.mark.asyncio
    async def test_with_router_filled(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import TWAPExecutor

        router = AsyncMock()
        router.route.return_value = {"status": "filled", "fill_price": 2350.0}
        ex = TWAPExecutor(router=router)
        result = await ex.execute(
            parent_id="twap2",
            symbol="XAUUSD",
            side="long",
            total_lots=0.02,
            duration_s=0.01,
            slices=2,
        )
        assert result["status"] == "filled"
        assert result["filled_lots"] == pytest.approx(0.02, abs=0.001)

    @pytest.mark.asyncio
    async def test_with_router_partial_fill(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import TWAPExecutor

        router = AsyncMock()
        router.route.side_effect = [
            {"status": "filled", "fill_price": 2350.0},
            {"status": "failed"},
        ]
        ex = TWAPExecutor(router=router)
        result = await ex.execute(
            parent_id="twap3",
            symbol="XAUUSD",
            side="long",
            total_lots=0.02,
            duration_s=0.01,
            slices=2,
        )
        assert result["status"] == "partial"
        assert result["failed_slices"] == 1

    @pytest.mark.asyncio
    async def test_router_exception_counted(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import TWAPExecutor

        router = AsyncMock()
        router.route.side_effect = ConnectionError("broker down")
        ex = TWAPExecutor(router=router)
        result = await ex.execute(
            parent_id="twap4",
            symbol="XAUUSD",
            side="long",
            total_lots=0.01,
            duration_s=0.01,
            slices=1,
        )
        assert result["failed_slices"] == 1

    @pytest.mark.asyncio
    async def test_small_lots_reduces_slices(self):
        from execution.order_algorithms import TWAPExecutor

        ex = TWAPExecutor(router=None)
        # total_lots=0.001 with slices=10 → each slice=0.0001 < MIN_SLICE_LOTS=0.001
        result = await ex.execute(
            parent_id="twap5",
            symbol="XAUUSD",
            side="short",
            total_lots=0.001,
            duration_s=0.01,
            slices=10,
        )
        assert result["child_count"] >= 1

    @pytest.mark.asyncio
    async def test_short_side(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import TWAPExecutor

        router = AsyncMock()
        router.route.return_value = {"status": "filled", "fill_price": 2350.0}
        ex = TWAPExecutor(router=router)
        await ex.execute(
            parent_id="twap6",
            symbol="XAUUSD",
            side="short",
            total_lots=0.01,
            duration_s=0.01,
            slices=1,
        )
        call_args = router.route.call_args[0][0]
        assert call_args["direction"] == "short"


class TestVWAPExecutor:
    @pytest.mark.asyncio
    async def test_no_router_returns_result(self):
        from execution.order_algorithms import VWAPExecutor

        ex = VWAPExecutor(router=None)
        result = await ex.execute(
            parent_id="vwap1",
            symbol="XAUUSD",
            side="long",
            total_lots=0.06,
            duration_s=0.01,
            slices=6,
        )
        assert result["algo"] == "vwap"
        assert result["parent_id"] == "vwap1"

    @pytest.mark.asyncio
    async def test_with_router_filled(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import VWAPExecutor

        router = AsyncMock()
        router.route.return_value = {"status": "filled", "fill_price": 2355.0}
        ex = VWAPExecutor(router=router)
        result = await ex.execute(
            parent_id="vwap2",
            symbol="XAUUSD",
            side="long",
            total_lots=0.06,
            duration_s=0.01,
            slices=6,
        )
        assert result["filled_lots"] > 0

    @pytest.mark.asyncio
    async def test_router_exception_counted(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import VWAPExecutor

        router = AsyncMock()
        router.route.side_effect = TimeoutError("timeout")
        ex = VWAPExecutor(router=router)
        result = await ex.execute(
            parent_id="vwap3",
            symbol="XAUUSD",
            side="long",
            total_lots=0.06,
            duration_s=0.01,
            slices=3,
        )
        assert result["failed_slices"] > 0

    def test_compute_slice_weights_sum_to_one(self):
        from execution.order_algorithms import VWAPExecutor

        ex = VWAPExecutor()
        weights = ex._compute_slice_weights(start_hour_utc=8, n_slices=6)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_compute_slice_weights_wraps_midnight(self):
        from execution.order_algorithms import VWAPExecutor

        ex = VWAPExecutor()
        weights = ex._compute_slice_weights(start_hour_utc=22, n_slices=6)
        assert len(weights) == 6
        assert all(w > 0 for w in weights)

    @pytest.mark.asyncio
    async def test_short_side_direction(self):
        from unittest.mock import AsyncMock

        from execution.order_algorithms import VWAPExecutor

        router = AsyncMock()
        router.route.return_value = {"status": "filled", "fill_price": 2350.0}
        ex = VWAPExecutor(router=router)
        await ex.execute(
            parent_id="vwap4",
            symbol="XAUUSD",
            side="short",
            total_lots=0.06,
            duration_s=0.01,
            slices=2,
        )
        call_args = router.route.call_args[0][0]
        assert call_args["direction"] == "short"
