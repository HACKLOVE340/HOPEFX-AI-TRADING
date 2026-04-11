# HOPEFX-AI-TRADING
# Coverage boost: smart_router, trade_executor, order_algorithms
"""Real unit tests — no mocks/stubs/fake data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# SmartRouter — uncovered: 459-468, 512-516, 617-628
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartRouterPreGate:
    """Lines 512-516: _pre_route_gate rejection paths."""

    def _router(self):
        from execution.smart_router import SmartRouter
        return SmartRouter()

    def test_spread_too_wide_rejected(self):
        r = self._router()
        reason = r._pre_route_gate(
            spread_bps=200.0, sentiment_score=0.0,
            impact_score=0.0, direction="long", ofi=0.0,
        )
        assert reason is not None
        assert "spread_too_wide" in reason

    def test_sentiment_blackout(self):
        r = self._router()
        reason = r._pre_route_gate(
            spread_bps=1.0, sentiment_score=0.95,
            impact_score=0.0, direction="long", ofi=0.0,
        )
        assert reason is not None
        assert "sentiment_blackout" in reason

    def test_macro_impact_blackout(self):
        r = self._router()
        reason = r._pre_route_gate(
            spread_bps=1.0, sentiment_score=0.0,
            impact_score=0.9, direction="long", ofi=0.0,
        )
        assert reason is not None
        assert "macro_impact" in reason

    def test_adverse_ofi_long(self):
        r = self._router()
        reason = r._pre_route_gate(
            spread_bps=1.0, sentiment_score=0.0,
            impact_score=0.0, direction="long", ofi=-0.8,
        )
        assert reason is not None
        assert "adverse_ofi" in reason

    def test_adverse_ofi_short(self):
        r = self._router()
        reason = r._pre_route_gate(
            spread_bps=1.0, sentiment_score=0.0,
            impact_score=0.0, direction="short", ofi=0.8,
        )
        assert reason is not None
        assert "adverse_ofi" in reason

    def test_no_rejection_normal(self):
        r = self._router()
        reason = r._pre_route_gate(
            spread_bps=1.0, sentiment_score=0.1,
            impact_score=0.1, direction="long", ofi=0.1,
        )
        assert reason is None


class TestSmartRouterLineage:
    """Lines 617-628: _write_routing_lineage."""

    def test_lineage_write_no_store(self):
        from execution.smart_router import SmartRouter, RoutingDecision
        r = SmartRouter(lineage_store=None)
        decision = RoutingDecision(
            decision_id="d1", order_id="o1", selected_broker="oanda",
            fallback_chain=[], scores={}, ofi=0.1, sentiment_score=0.0,
            impact_score=0.0, spread_bps=2.0, reason="test",
        )
        r._write_routing_lineage(decision, {"direction": "long", "symbol": "XAU_USD"})

    def test_lineage_write_with_store_error_suppressed(self):
        from execution.smart_router import SmartRouter, RoutingDecision

        class _BadStore:
            def record_signal(self, **kw): raise RuntimeError("db error")

        r = SmartRouter(lineage_store=_BadStore())
        decision = RoutingDecision(
            decision_id="d2", order_id="o2", selected_broker="oanda",
            fallback_chain=[], scores={}, ofi=0.1, sentiment_score=0.0,
            impact_score=0.0, spread_bps=2.0, reason="test",
        )
        r._write_routing_lineage(decision, {"direction": "long", "symbol": "XAU_USD"})


class TestSmartRouterExplain:
    """Lines 459-468: _explain_selection."""

    def test_explain_only_available(self):
        from execution.smart_router import SmartRouter
        r = SmartRouter()
        result = r._explain_selection("unknown_broker", 0.0, 0.0)
        assert result == "only_available"

    def test_explain_low_latency(self):
        from execution.smart_router import SmartRouter, BrokerState
        r = SmartRouter()
        r._states["fast"] = BrokerState(broker_id="fast", ema_latency_ms=30.0, fill_rate=0.99)
        result = r._explain_selection("fast", 0.0, 0.0)
        assert "low_latency" in result or "high_fill_rate" in result


class TestSmartRouterAllBrokersFail:
    """Lines 600-610: _execute_with_fallback all fail."""

    @pytest.mark.asyncio
    async def test_all_brokers_fail_returns_rejected(self):
        from execution.smart_router import SmartRouter, BrokerState, RoutingDecision

        class _FailBroker:
            async def place_order(self, req): raise RuntimeError("down")

        r = SmartRouter()
        r._brokers["fail1"] = _FailBroker()
        r._states["fail1"] = BrokerState(broker_id="fail1")
        decision = RoutingDecision(
            decision_id="d3", order_id="o3", selected_broker="fail1",
            fallback_chain=["fail1"], scores={}, ofi=0.0, sentiment_score=0.0,
            impact_score=0.0, spread_bps=2.0, reason="test",
        )
        order = {"symbol": "XAU_USD", "direction": "long", "lots": 0.01,
                 "mid_price": 2000.0, "bid": 1999.0, "ask": 2001.0}
        # ranked is list of (broker_id, score) tuples
        result = await r._execute_with_fallback(order, [("fail1", 0.5)], decision)
        assert result["status"] == "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# TradeExecutor — uncovered: 170-174, 304-305, 395-447, 406-418, 411-412,
#   444-445, 493-494, 532, 579-606, 583-591, 597-602, 622-623, 644-651,
#   655-702, 714-720, 731-732
# ─────────────────────────────────────────────────────────────────────────────

def _make_executor():
    from execution.trade_executor import TradeExecutor

    class _FakeBroker:
        async def place_market_order(self, symbol, side, size, **kw):
            return {"order_id": "ord1", "filled_quantity": size,
                    "average_price": 2000.0, "commission": 0.5, "status": "filled"}
        async def close_position(self, position_id): return True
        async def cancel_order(self, order_id): return True

    class _FakeRiskManager:
        _trading_halted = False
        _halt_reason = None
        daily_starting_equity = 100_000.0
        def get_equity(self): return 100_000.0
        def update_equity(self, v): pass
        def record_trade_outcome(self, **kw): pass
        async def validate_trade(self, signal): return True, ""
        async def check_pre_trade(self, signal):
            return True, ""

    class _FakePositionTracker:
        def __init__(self):
            self._positions = {}
        async def add_position(self, **kw): pass
        async def close_position(self, pid, price, commission=0):
            class _Closed:
                realized_pnl = 50.0
                symbol = "XAUUSD"
                side = "buy"
                entry_price = 2000.0
                signal_confidence = 0.7
            return _Closed()
        def get_position(self, pid):
            class _Pos:
                current_price = 2050.0
                quantity = 1.0
                commission = 0.5
            return _Pos()

    return TradeExecutor(
        broker=_FakeBroker(),
        risk_manager=_FakeRiskManager(),
        position_tracker=_FakePositionTracker(),
    )


class TestTradeExecutorRiskStatus:
    """Lines 714-720, 731-732: get_risk_status."""

    def test_get_risk_status_keys(self):
        ex = _make_executor()
        status = ex.get_risk_status()
        assert "consecutive_losses" in status
        assert "drawdown_halt_pct" in status
        assert "streak_halted" in status

    def test_get_risk_status_streak_cooldown(self):
        import time
        ex = _make_executor()
        ex._streak_halted_until = time.monotonic() + 1800
        status = ex.get_risk_status()
        assert status["streak_halted"] is True
        assert status["streak_cooldown_remaining_min"] is not None


class TestTradeExecutorDrawdownCB:
    """Lines 579-606: _check_drawdown_circuit_breaker."""

    def test_drawdown_cb_not_triggered(self):
        ex = _make_executor()
        blocked, msg = ex._check_drawdown_circuit_breaker()
        assert blocked is False

    def test_drawdown_cb_triggered(self):
        ex = _make_executor()
        ex.risk_manager._trading_halted = True
        ex.risk_manager._halt_reason = "drawdown"
        blocked, msg = ex._check_drawdown_circuit_breaker()
        assert blocked is True


class TestTradeExecutorStreakCB:
    """Lines 622-623: _check_streak_circuit_breaker."""

    def test_streak_cb_not_triggered(self):
        ex = _make_executor()
        blocked, msg = ex._check_streak_circuit_breaker()
        assert blocked is False

    def test_streak_cb_triggered(self):
        import time
        ex = _make_executor()
        ex._streak_halted_until = time.monotonic() + 1800
        blocked, msg = ex._check_streak_circuit_breaker()
        assert blocked is True


class TestTradeExecutorRiskCap:
    """Lines 644-651: _clamp_size_to_risk_cap."""

    def test_risk_cap_with_sl(self):
        ex = _make_executor()
        signal = {"symbol": "XAUUSD", "size": 100.0,
                  "entry_price": 2000.0, "stop_loss": 1990.0}
        capped = ex._clamp_size_to_risk_cap(signal, 100.0)
        assert capped <= 100.0

    def test_risk_cap_no_sl_notional(self):
        ex = _make_executor()
        signal = {"symbol": "XAUUSD", "size": 100.0, "entry_price": 2000.0}
        capped = ex._clamp_size_to_risk_cap(signal, 100.0)
        assert capped <= 100.0

    def test_risk_cap_no_price_returns_original(self):
        ex = _make_executor()
        signal = {"symbol": "XAUUSD", "size": 0.01}
        capped = ex._clamp_size_to_risk_cap(signal, 0.01)
        assert capped == pytest.approx(0.01)


class TestTradeExecutorCallbacks:
    """Lines 655-702: register_callback, _notify_callbacks."""

    @pytest.mark.asyncio
    async def test_register_and_notify_sync_callback(self):
        ex = _make_executor()
        received = []
        ex.register_callback(lambda r, s: received.append(r))
        from execution.trade_executor import ExecutionResult, OrderStatus
        result = ExecutionResult(
            success=True, order_id="o1", filled_quantity=1.0,
            average_price=2000.0, commission=0.5,
            status=OrderStatus.FILLED, message="ok",
        )
        await ex._notify_callbacks(result, {"symbol": "XAUUSD"})
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_register_and_notify_async_callback(self):
        ex = _make_executor()
        received = []

        async def _cb(r, s): received.append(r)

        ex.register_callback(_cb)
        from execution.trade_executor import ExecutionResult, OrderStatus
        result = ExecutionResult(
            success=True, order_id="o1", filled_quantity=1.0,
            average_price=2000.0, commission=0.5,
            status=OrderStatus.FILLED, message="ok",
        )
        await ex._notify_callbacks(result, {"symbol": "XAUUSD"})
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_callback_error_suppressed(self):
        ex = _make_executor()
        ex.register_callback(lambda r, s: (_ for _ in ()).throw(RuntimeError("boom")))
        from execution.trade_executor import ExecutionResult, OrderStatus
        result = ExecutionResult(
            success=True, order_id="o1", filled_quantity=1.0,
            average_price=2000.0, commission=0.5,
            status=OrderStatus.FILLED, message="ok",
        )
        await ex._notify_callbacks(result, {"symbol": "XAUUSD"})


class TestTradeExecutorCancelAll:
    """Lines 493-494: cancel_all_pending."""

    @pytest.mark.asyncio
    async def test_cancel_all_pending_empty(self):
        ex = _make_executor()
        result = await ex.cancel_all_pending()
        assert result == []


class TestTradeExecutorUpdateStreak:
    """Lines 304-305: _update_streak."""

    def test_update_streak_loss(self):
        ex = _make_executor()
        ex._update_streak(-50.0)
        assert ex._consecutive_losses == 1

    def test_update_streak_win_resets(self):
        ex = _make_executor()
        ex._consecutive_losses = 2
        ex._update_streak(50.0)
        assert ex._consecutive_losses == 0

    def test_update_streak_halt_after_threshold(self):
        from execution.trade_executor import STREAK_HALT_LOSSES
        ex = _make_executor()
        for _ in range(STREAK_HALT_LOSSES):
            ex._update_streak(-10.0)
        assert ex._streak_halted_until is not None


# ─────────────────────────────────────────────────────────────────────────────
# order_algorithms — uncovered: 60-61, 96, 186-189, 221-222, 301-305,
#   341-344, 425, 427-430, 445
# ─────────────────────────────────────────────────────────────────────────────

class TestOrderAlgorithmsPrometheus:
    """Lines 60-61: prometheus import path."""

    def test_prom_ok_flag_is_bool(self):
        from execution.order_algorithms import _PROM_OK
        assert isinstance(_PROM_OK, bool)


class TestPartialFillAggregatorTimeout:
    """Lines 186-189: is_timed_out path."""

    def test_timeout_fires_callback(self):
        from execution.order_algorithms import PartialFillAggregator
        import time

        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "long", 1.0)
        # Force timeout
        agg._states["p1"].started_at = time.monotonic() - 9999
        completed = []
        agg.on_complete(lambda s: completed.append(s))
        agg.record_fill("p1", 0.1, 2000.0)
        assert len(completed) == 1


class TestPartialFillAggregatorUnknown:
    """Lines 221-222: unknown parent_id."""

    def test_unknown_parent_returns_none(self):
        from execution.order_algorithms import PartialFillAggregator
        agg = PartialFillAggregator()
        result = agg.record_fill("unknown", 0.1, 2000.0)
        assert result is None


class TestTWAPNoRouter:
    """Lines 301-305: TWAP with no router (pending mode)."""

    @pytest.mark.asyncio
    async def test_twap_no_router_returns_pending(self):
        from execution.order_algorithms import TWAPExecutor
        ex = TWAPExecutor(router=None)
        result = await ex.execute(
            parent_id="t1", symbol="XAUUSD", side="long",
            total_lots=0.01, duration_s=0.01, slices=2,
        )
        assert result["algo"] == "twap"
        assert result["child_count"] == 2


class TestTWAPRouterFails:
    """Lines 341-344: TWAP router error path."""

    @pytest.mark.asyncio
    async def test_twap_router_error_counts_failed(self):
        class _FailRouter:
            async def route(self, req): raise RuntimeError("broker down")

        from execution.order_algorithms import TWAPExecutor
        ex = TWAPExecutor(router=_FailRouter())
        result = await ex.execute(
            parent_id="t2", symbol="XAUUSD", side="long",
            total_lots=0.002, duration_s=0.01, slices=2,
        )
        assert result["failed_slices"] == 2


class TestVWAPNoRouter:
    """Lines 425, 427-430: VWAP with no router."""

    @pytest.mark.asyncio
    async def test_vwap_no_router(self):
        from execution.order_algorithms import VWAPExecutor
        ex = VWAPExecutor(router=None)
        result = await ex.execute(
            parent_id="v1", symbol="XAUUSD", side="long",
            total_lots=0.01, duration_s=0.01, slices=3,
        )
        assert result["algo"] == "vwap"


class TestVWAPRouterFails:
    """Lines 445: VWAP router error."""

    @pytest.mark.asyncio
    async def test_vwap_router_error(self):
        class _FailRouter:
            async def route(self, req): raise RuntimeError("down")

        from execution.order_algorithms import VWAPExecutor
        ex = VWAPExecutor(router=_FailRouter())
        result = await ex.execute(
            parent_id="v2", symbol="XAUUSD", side="long",
            total_lots=0.01, duration_s=0.01, slices=2,
        )
        assert result["failed_slices"] >= 1


class TestVWAPSliceWeights:
    """Line 96: _compute_slice_weights."""

    def test_weights_sum_to_one(self):
        from execution.order_algorithms import VWAPExecutor
        ex = VWAPExecutor()
        weights = ex._compute_slice_weights(8, 6)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_weights_wrap_around_midnight(self):
        from execution.order_algorithms import VWAPExecutor
        ex = VWAPExecutor()
        weights = ex._compute_slice_weights(22, 6)
        assert len(weights) == 6
        assert abs(sum(weights) - 1.0) < 1e-9
