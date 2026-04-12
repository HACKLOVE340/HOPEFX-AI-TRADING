# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comprehensive tests for execution/smart_router.py."""
from __future__ import annotations
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from execution.smart_router import BrokerState, RoutingDecision, SmartRouter

def _router():
    return SmartRouter()

def _broker_inst(status="filled", order_id="ord_1"):
    b = MagicMock()
    result = {"order_id": order_id, "status": status, "fill_price": 2000.0,
              "filled_quantity": 1.0, "avg_price": 2000.0, "commission": 0.5,
              "latency_ms": 10.0, "slippage_bps": 2.0}
    b.place_order = AsyncMock(return_value=result)
    return b

def _order(direction="long", qty=1.0, mid=2000.0, bid=1999.0, ask=2001.0):
    return {
        "order_id": "o1", "symbol": "XAUUSD", "direction": direction,
        "quantity": qty, "order_type": "MARKET",
        "mid_price": mid, "bid": bid, "ask": ask,
        "ofi": 0.0, "sentiment_score": 0.0, "impact_score": 0.0,
    }

# ── BrokerState ────────────────────────────────────────────────────────────────

class TestBrokerState:
    def test_initial_state(self):
        s = BrokerState(broker_id="test")
        assert s.circuit_open is False
        assert s.fill_rate == pytest.approx(0.95)
        assert s.ema_latency_ms == pytest.approx(100.0)

    def test_record_fill_updates_ema_latency(self):
        s = BrokerState(broker_id="test")
        s.record_fill(latency_ms=10.0, slippage_bps=1.0)
        assert s.ema_latency_ms < 100.0

    def test_record_fill_updates_slippage(self):
        s = BrokerState(broker_id="test")
        s.record_fill(latency_ms=10.0, slippage_bps=1.0)
        assert s.avg_slippage_bps < 5.0

    def test_record_fill_increments_counters(self):
        s = BrokerState(broker_id="test")
        s.record_fill(latency_ms=10.0, slippage_bps=1.0)
        assert s.total_fills == 1 and s.total_orders == 1

    def test_record_fill_updates_fill_rate(self):
        s = BrokerState(broker_id="test")
        s.record_fill(latency_ms=10.0, slippage_bps=1.0)
        assert s.fill_rate == pytest.approx(1.0)

    def test_record_error_increments_counters(self):
        s = BrokerState(broker_id="test")
        s.record_error()
        assert s.total_errors == 1 and s.total_orders == 1

    def test_record_error_degrades_reliability(self):
        s = BrokerState(broker_id="test")
        initial = s.reliability
        s.record_error()
        assert s.reliability < initial

    def test_record_error_opens_circuit_at_threshold(self):
        from execution.smart_router import _CB_ERROR_THRESHOLD
        s = BrokerState(broker_id="test")
        for _ in range(_CB_ERROR_THRESHOLD):
            s.record_error()
        assert s.circuit_open is True

    def test_record_error_below_threshold_circuit_closed(self):
        from execution.smart_router import _CB_ERROR_THRESHOLD
        s = BrokerState(broker_id="test")
        for _ in range(_CB_ERROR_THRESHOLD - 1):
            s.record_error()
        assert s.circuit_open is False

    def test_check_circuit_reset_after_timeout(self):
        from execution.smart_router import _CB_RESET_S
        s = BrokerState(broker_id="test")
        s.circuit_open = True
        s.circuit_open_at = time.monotonic() - _CB_RESET_S - 1
        s.check_circuit_reset()
        assert s.circuit_open is False and s.error_times == []

    def test_check_circuit_reset_before_timeout_stays_open(self):
        s = BrokerState(broker_id="test")
        s.circuit_open = True
        s.circuit_open_at = time.monotonic()
        s.check_circuit_reset()
        assert s.circuit_open is True

    def test_check_circuit_reset_not_open_noop(self):
        BrokerState(broker_id="test").check_circuit_reset()  # must not raise

    def test_routing_score_returns_float(self):
        assert isinstance(BrokerState(broker_id="t").routing_score("long", 0.0, 0.0), float)

    def test_routing_score_between_zero_and_one(self):
        score = BrokerState(broker_id="t").routing_score("long", 0.5, 0.3)
        assert 0.0 <= score <= 1.0

    def test_routing_score_circuit_open_excluded_from_ranking(self):
        from execution.smart_router import _CB_RESET_S
        r = _router(); r.add_broker("open", _broker_inst()); r.add_broker("closed", _broker_inst())
        r._states["open"].circuit_open = True
        # Set circuit_open_at to now so reset timeout hasn't expired
        r._states["open"].circuit_open_at = time.monotonic()
        ranked = r._rank_brokers("long", 0.0, 0.0)
        ids = [bid for bid, _ in ranked]
        assert "open" not in ids and "closed" in ids

    def test_routing_score_lower_latency_higher_score(self):
        fast = BrokerState(broker_id="f"); fast.ema_latency_ms = 5.0
        slow = BrokerState(broker_id="s"); slow.ema_latency_ms = 500.0
        assert fast.routing_score("long", 0.0, 0.0) > slow.routing_score("long", 0.0, 0.0)

    def test_routing_score_lower_slippage_higher_score(self):
        good = BrokerState(broker_id="g"); good.avg_slippage_bps = 0.5
        bad = BrokerState(broker_id="b"); bad.avg_slippage_bps = 50.0
        assert good.routing_score("long", 0.0, 0.0) > bad.routing_score("long", 0.0, 0.0)

# ── SmartRouter — broker management ───────────────────────────────────────────

class TestSmartRouterBrokerManagement:
    def test_add_broker_registers(self):
        r = _router(); r.add_broker("b1", _broker_inst())
        assert "b1" in r._brokers and "b1" in r._states

    def test_add_broker_creates_state(self):
        r = _router(); r.add_broker("b1", _broker_inst())
        assert isinstance(r._states["b1"], BrokerState)

    def test_remove_broker_unregisters(self):
        r = _router(); r.add_broker("b1", _broker_inst()); r.remove_broker("b1")
        assert "b1" not in r._brokers and "b1" not in r._states

    def test_remove_nonexistent_broker_noop(self):
        _router().remove_broker("ghost")  # must not raise

    def test_multiple_brokers_registered(self):
        r = _router(); r.add_broker("b1", _broker_inst()); r.add_broker("b2", _broker_inst())
        assert len(r._brokers) == 2

# ── SmartRouter — _rank_brokers ────────────────────────────────────────────────

class TestSmartRouterRankBrokers:
    def test_rank_returns_list(self):
        r = _router(); r.add_broker("b1", _broker_inst()); r.add_broker("b2", _broker_inst())
        assert isinstance(r._rank_brokers("long", 0.0, 0.0), list)

    def test_rank_excludes_open_circuit(self):
        r = _router(); r.add_broker("b1", _broker_inst()); r.add_broker("b2", _broker_inst())
        r._states["b1"].circuit_open = True
        # Force reset window to be past so check_circuit_reset doesn't clear it
        r._states["b1"].circuit_open_at = time.monotonic()
        ids = [bid for bid, _ in r._rank_brokers("long", 0.0, 0.0)]
        assert "b1" not in ids

    def test_rank_empty_brokers_returns_empty(self):
        assert _router()._rank_brokers("long", 0.0, 0.0) == []

    def test_rank_sorted_by_score_descending(self):
        r = _router(); r.add_broker("fast", _broker_inst()); r.add_broker("slow", _broker_inst())
        r._states["fast"].ema_latency_ms = 5.0; r._states["slow"].ema_latency_ms = 500.0
        assert r._rank_brokers("long", 0.0, 0.0)[0][0] == "fast"

# ── SmartRouter — _pre_route_gate ──────────────────────────────────────────────

class TestSmartRouterPreRouteGate:
    def test_normal_order_returns_none(self):
        r = _router()
        result = r._pre_route_gate(spread_bps=2.0, sentiment_score=0.0, impact_score=0.0,
                                   direction="long", ofi=0.0)
        assert result is None

    def test_spread_too_wide_returns_reason(self):
        from execution.smart_router import _MAX_SPREAD_BPS
        r = _router()
        result = r._pre_route_gate(spread_bps=_MAX_SPREAD_BPS + 1, sentiment_score=0.0,
                                   impact_score=0.0, direction="long", ofi=0.0)
        assert result is not None and "spread" in result

    def test_extreme_sentiment_returns_reason(self):
        from execution.smart_router import _SENT_BLACKOUT_THRESH
        r = _router()
        result = r._pre_route_gate(spread_bps=1.0, sentiment_score=_SENT_BLACKOUT_THRESH + 0.1,
                                   impact_score=0.0, direction="long", ofi=0.0)
        assert result is not None and "sentiment" in result

    def test_high_impact_returns_reason(self):
        from execution.smart_router import _IMPACT_BLACKOUT
        r = _router()
        result = r._pre_route_gate(spread_bps=1.0, sentiment_score=0.0,
                                   impact_score=_IMPACT_BLACKOUT + 0.1, direction="long", ofi=0.0)
        assert result is not None and "impact" in result

    def test_adverse_ofi_long_returns_reason(self):
        r = _router()
        result = r._pre_route_gate(spread_bps=1.0, sentiment_score=0.0, impact_score=0.0,
                                   direction="long", ofi=-0.9)
        assert result is not None and "ofi" in result

    def test_adverse_ofi_short_returns_reason(self):
        r = _router()
        result = r._pre_route_gate(spread_bps=1.0, sentiment_score=0.0, impact_score=0.0,
                                   direction="short", ofi=0.9)
        assert result is not None and "ofi" in result

    def test_ofi_aligned_long_returns_none(self):
        r = _router()
        result = r._pre_route_gate(spread_bps=1.0, sentiment_score=0.0, impact_score=0.0,
                                   direction="long", ofi=0.5)
        assert result is None

# ── SmartRouter — route_and_execute ───────────────────────────────────────────

class TestSmartRouterRouteAndExecute:
    @pytest.mark.asyncio
    async def test_route_success(self):
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        result = await r.route_and_execute(_order())
        assert result["status"] == "filled"

    @pytest.mark.asyncio
    async def test_route_records_fill_state(self):
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        await r.route_and_execute(_order())
        assert r._states["b1"].total_fills == 1

    @pytest.mark.asyncio
    async def test_route_increments_total_routed(self):
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        await r.route_and_execute(_order())
        assert r._total_routed == 1

    @pytest.mark.asyncio
    async def test_route_no_brokers_returns_rejected(self):
        r = _router()
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_route_broker_exception_records_error(self):
        r = _router()
        b = MagicMock(); b.place_order = AsyncMock(side_effect=ConnectionError("timeout"))
        r.add_broker("b1", b)
        await r.route_and_execute(_order())
        assert r._states["b1"].total_errors >= 1

    @pytest.mark.asyncio
    async def test_route_fallback_to_second_broker(self):
        r = _router()
        bad = MagicMock(); bad.place_order = AsyncMock(side_effect=ConnectionError("timeout"))
        r.add_broker("bad", bad)
        r.add_broker("good", _broker_inst(status="filled"))
        r._states["bad"].ema_latency_ms = 9999.0
        r._states["good"].ema_latency_ms = 5.0
        result = await r.route_and_execute(_order())
        assert result["status"] == "filled"

    @pytest.mark.asyncio
    async def test_route_stores_decision(self):
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        await r.route_and_execute(_order())
        assert len(r._decisions) == 1

    @pytest.mark.asyncio
    async def test_route_decision_has_correct_broker(self):
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        await r.route_and_execute(_order())
        assert r._decisions[0].selected_broker == "b1"

    @pytest.mark.asyncio
    async def test_route_all_brokers_fail_returns_rejected(self):
        r = _router()
        b = MagicMock(); b.place_order = AsyncMock(return_value={"status": "rejected", "reason": "margin"})
        r.add_broker("b1", b)
        result = await r.route_and_execute(_order())
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_route_pre_gate_rejection_returns_rejected(self):
        from execution.smart_router import _SENT_BLACKOUT_THRESH
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        # Use the key the router actually reads: "sentiment"
        order = _order(); order["sentiment"] = _SENT_BLACKOUT_THRESH + 0.5
        result = await r.route_and_execute(order)
        assert result["status"] == "rejected"

# ── SmartRouter — metrics ──────────────────────────────────────────────────────

class TestSmartRouterMetrics:
    def test_metrics_empty(self):
        m = _router().metrics()
        assert isinstance(m, dict) and m["total_routed"] == 0

    @pytest.mark.asyncio
    async def test_metrics_after_route(self):
        r = _router(); r.add_broker("b1", _broker_inst(status="filled"))
        await r.route_and_execute(_order())
        assert r.metrics()["total_routed"] == 1

    def test_metrics_has_broker_states(self):
        r = _router(); r.add_broker("b1", _broker_inst())
        assert "b1" in r.metrics()["brokers"]

    def test_metrics_broker_state_keys(self):
        r = _router(); r.add_broker("b1", _broker_inst())
        b_state = r.metrics()["brokers"]["b1"]
        for k in ("ema_latency_ms","fill_rate","avg_slippage_bps","circuit_open","total_orders"):
            assert k in b_state

# ── SmartRouter — _explain_selection ──────────────────────────────────────────

class TestSmartRouterExplainSelection:
    def test_explain_returns_string(self):
        r = _router(); r.add_broker("b1", _broker_inst())
        assert isinstance(r._explain_selection("b1", 0.5, 0.3), str)

    def test_explain_unknown_broker_returns_string(self):
        assert isinstance(_router()._explain_selection("ghost", 0.0, 0.0), str)
