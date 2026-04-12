# tests/unit/test_execution_coverage12.py
"""Targeted coverage for smart_router: _execute_with_fallback, _pre_route_gate,
_route_via_algo, _submit_child_order, _explain_selection, metrics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _router_with_broker(fill_status="filled", fill_price=2350.0, raise_exc=None):
    from execution.smart_router import BrokerState, SmartRouter

    r = SmartRouter()
    broker = MagicMock()
    if raise_exc:
        broker.place_order = AsyncMock(side_effect=raise_exc)
    else:
        broker.place_order = AsyncMock(return_value={"status": fill_status, "fill_price": fill_price, "quantity": 0.01})
    r.add_broker("b1", broker)
    # Inject a state so ranking works
    r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=10.0, fill_rate=0.99)
    return r


def _order(qty=0.01, direction="long", symbol="XAUUSD", **kwargs):
    base = {
        "symbol": symbol,
        "direction": direction,
        "quantity": qty,
        "order_type": "MARKET",
        "mid_price": 2350.0,
        "bid": 2349.0,
        "ask": 2351.0,
        "spread": 2.0,
        "confidence": 0.8,
        "sentiment": 0.0,
        "impact": 0.0,
        "features": {},
    }
    base.update(kwargs)
    return base


class TestExecuteWithFallback:
    @pytest.mark.asyncio
    async def test_filled_returns_fill_dict(self):
        r = _router_with_broker(fill_status="filled", fill_price=2350.0)
        result = await r.route_and_execute(_order())
        assert result["status"] == "filled"
        assert result["broker"] == "b1"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_broker_non_fill_returns_rejected(self):
        r = _router_with_broker(fill_status="rejected")
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_broker_timeout_returns_rejected(self):
        r = _router_with_broker(raise_exc=TimeoutError("timed out"))
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"
        assert "all_brokers_failed" in result["reason"]

    @pytest.mark.asyncio
    async def test_broker_connection_error_returns_rejected(self):
        r = _router_with_broker(raise_exc=ConnectionError("down"))
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_broker_runtime_error_returns_rejected(self):
        r = _router_with_broker(raise_exc=RuntimeError("internal"))
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_fallback_to_second_broker(self):
        from execution.smart_router import BrokerState, SmartRouter

        r = SmartRouter()
        # b1 fails, b2 fills
        b1 = MagicMock()
        b1.place_order = AsyncMock(return_value={"status": "rejected", "reason": "b1_fail"})
        b2 = MagicMock()
        b2.place_order = AsyncMock(return_value={"status": "filled", "fill_price": 2351.0, "quantity": 0.01})
        r.add_broker("b1", b1)
        r.add_broker("b2", b2)
        r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=200.0, fill_rate=0.5)
        r._states["b2"] = BrokerState(broker_id="b2", ema_latency_ms=10.0, fill_rate=0.99)
        result = await r.route_and_execute(_order())
        # b2 should fill
        assert result["status"] == "filled"
        assert result["broker"] == "b2"

    @pytest.mark.asyncio
    async def test_fill_records_state(self):
        r = _router_with_broker(fill_status="filled", fill_price=2350.0)
        await r.route_and_execute(_order())
        assert r._states["b1"].total_fills == 1

    @pytest.mark.asyncio
    async def test_error_records_state(self):
        r = _router_with_broker(raise_exc=RuntimeError("err"))
        await r.route_and_execute(_order())
        assert r._states["b1"].total_errors == 1


class TestPreRouteGate:
    def _router(self):
        from execution.smart_router import SmartRouter

        return SmartRouter()

    def test_high_spread_rejected(self):
        r = self._router()
        result = r._pre_route_gate(
            spread_bps=60.0,  # above MAX_SPREAD_BPS
            sentiment_score=0.0,
            impact_score=0.0,
            direction="long",
            ofi=0.0,
        )
        assert result is not None
        assert "spread" in result

    def test_high_impact_rejected(self):
        r = self._router()
        result = r._pre_route_gate(
            spread_bps=2.0,
            sentiment_score=0.0,
            impact_score=0.95,  # above MAX_IMPACT_SCORE
            direction="long",
            ofi=0.0,
        )
        assert result is not None
        assert "impact" in result

    def test_adverse_sentiment_rejected(self):
        r = self._router()
        # Long with very negative sentiment
        result = r._pre_route_gate(
            spread_bps=2.0,
            sentiment_score=-0.9,
            impact_score=0.0,
            direction="long",
            ofi=0.0,
        )
        assert result is not None

    def test_normal_conditions_pass(self):
        r = self._router()
        result = r._pre_route_gate(
            spread_bps=2.0,
            sentiment_score=0.1,
            impact_score=0.1,
            direction="long",
            ofi=0.5,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unwind_bypasses_gate(self):
        r = _router_with_broker(fill_status="filled")
        # High spread + high impact but is_unwind=True → should not be rejected by gate
        result = await r.route_and_execute(
            _order(
                spread=100.0,
                impact=0.99,
                is_unwind=True,
            )
        )
        assert result["status"] == "filled"


class TestRouteViaAlgo:
    @pytest.mark.asyncio
    async def test_large_order_delegates_to_algo(self):
        from execution.smart_router import SmartRouter, _ALGO_LARGE_THRESHOLD

        r = SmartRouter()
        # Mock the algo manager
        r._algo.submit_auto = AsyncMock(return_value="algo_123")
        result = await r.route_and_execute(_order(qty=_ALGO_LARGE_THRESHOLD + 1.0))
        assert result["status"] == "algo_submitted"
        assert result["algo_id"] == "algo_123"

    @pytest.mark.asyncio
    async def test_algo_returns_none_falls_through(self):
        from execution.smart_router import BrokerState, SmartRouter, _ALGO_LARGE_THRESHOLD

        r = SmartRouter()
        r._algo.submit_auto = AsyncMock(return_value=None)
        # Add a broker so fallback can fill
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value={"status": "filled", "fill_price": 2350.0, "quantity": 0.01})
        r.add_broker("b1", broker)
        r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=10.0, fill_rate=0.99)
        result = await r.route_and_execute(_order(qty=_ALGO_LARGE_THRESHOLD + 1.0))
        assert result["status"] == "filled"

    @pytest.mark.asyncio
    async def test_algo_none_no_brokers_rejected(self):
        from execution.smart_router import SmartRouter, _ALGO_LARGE_THRESHOLD

        r = SmartRouter()
        r._algo.submit_auto = AsyncMock(return_value=None)
        result = await r.route_and_execute(_order(qty=_ALGO_LARGE_THRESHOLD + 1.0))
        assert result["status"] == "rejected"


class TestSubmitChildOrder:
    @pytest.mark.asyncio
    async def test_child_order_filled(self):
        r = _router_with_broker(fill_status="filled", fill_price=2350.0)
        result = await r._submit_child_order(
            {
                "child_id": "c1",
                "algo_id": "algo1",
                "symbol": "XAUUSD",
                "side": "BUY",
                "quantity": 0.01,
                "mid_price": 2350.0,
                "bid": 2349.0,
                "ask": 2351.0,
                "spread": 2.0,
            }
        )
        assert result["status"] == "filled"

    @pytest.mark.asyncio
    async def test_child_order_no_brokers_rejected(self):
        from execution.smart_router import SmartRouter

        r = SmartRouter()
        result = await r._submit_child_order(
            {
                "child_id": "c2",
                "algo_id": "algo1",
                "symbol": "XAUUSD",
                "side": "BUY",
                "quantity": 0.01,
                "mid_price": 2350.0,
            }
        )
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_child_order_sell_direction(self):
        r = _router_with_broker(fill_status="filled", fill_price=2349.0)
        result = await r._submit_child_order(
            {
                "child_id": "c3",
                "algo_id": "algo1",
                "symbol": "XAUUSD",
                "side": "SELL",
                "quantity": 0.01,
                "mid_price": 2350.0,
                "bid": 2349.0,
                "ask": 2351.0,
            }
        )
        assert result["status"] == "filled"


class TestExplainSelection:
    def test_no_state_returns_only_available(self):
        from execution.smart_router import SmartRouter

        r = SmartRouter()
        reason = r._explain_selection("unknown_broker", ofi=0.0, sentiment=0.0)
        assert reason == "only_available"

    def test_low_latency_reason(self):
        from execution.smart_router import BrokerState, SmartRouter

        r = SmartRouter()
        r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=10.0, fill_rate=0.99, avg_slippage_bps=1.0)
        reason = r._explain_selection("b1", ofi=0.5, sentiment=0.1)
        assert "low_latency" in reason

    def test_ofi_aligned_reason(self):
        from execution.smart_router import BrokerState, SmartRouter

        r = SmartRouter()
        r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=200.0, fill_rate=0.90, avg_slippage_bps=10.0)
        reason = r._explain_selection("b1", ofi=0.5, sentiment=0.5)
        assert "ofi_aligned" in reason

    def test_best_composite_score_fallback(self):
        from execution.smart_router import BrokerState, SmartRouter

        r = SmartRouter()
        r._states["b1"] = BrokerState(broker_id="b1", ema_latency_ms=200.0, fill_rate=0.90, avg_slippage_bps=10.0)
        reason = r._explain_selection("b1", ofi=0.1, sentiment=0.5)
        assert reason  # non-empty


class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_after_fill(self):
        r = _router_with_broker(fill_status="filled")
        await r.route_and_execute(_order())
        m = r.metrics()
        assert m["total_routed"] >= 1
        assert m["total_filled"] >= 1

    @pytest.mark.asyncio
    async def test_metrics_fill_rate(self):
        r = _router_with_broker(fill_status="filled")
        await r.route_and_execute(_order())
        m = r.metrics()
        assert m["fill_rate"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_metrics_throttled(self):
        from execution.smart_router import SmartRouter

        r = SmartRouter()
        # Force throttle by exhausting the budget
        for _ in range(200):
            r._throttler.record_message("order")
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"
        m = r.metrics()
        assert m["total_throttled"] >= 1
