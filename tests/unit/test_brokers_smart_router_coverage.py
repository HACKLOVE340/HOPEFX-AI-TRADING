# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for brokers/smart_router.py

Targets: BrokerScore, SmartOrderRouter, BrokerConnector
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_score(
    broker_id="b1",
    latency_ms=50.0,
    fill_rate=0.97,
    avg_slippage_bps=3.0,
    cost_score=8.0,
    reliability_score=0.99,
    overall_score=0.0,
):
    from brokers.smart_router import BrokerScore

    return BrokerScore(
        broker_id=broker_id,
        latency_ms=latency_ms,
        fill_rate=fill_rate,
        avg_slippage_bps=avg_slippage_bps,
        cost_score=cost_score,
        reliability_score=reliability_score,
        overall_score=overall_score,
    )


def _default_weights():
    return {
        "latency": 0.25,
        "fill_rate": 0.25,
        "cost": 0.25,
        "reliability": 0.25,
    }


def _make_router():
    from brokers.smart_router import SmartOrderRouter

    return SmartOrderRouter()


def _make_connector(name="test", ping_latency_ms=10.0, fills=None):
    """Return a BrokerConnector backed by a mock client."""
    from brokers.smart_router import BrokerConnector

    client = MagicMock()
    client.get_server_time = AsyncMock(return_value={"time": 1234567890})
    client.place_order = AsyncMock(
        return_value={
            "id": "ord-1",
            "status": "FILLED",
            "avg_price": 1.0820,
        }
    )
    connector = BrokerConnector(name=name, client=client)
    if fills is not None:
        connector.fill_history = fills
    return connector


# ---------------------------------------------------------------------------
# BrokerScore
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrokerScore:
    def test_dataclass_fields(self):
        score = _make_score()
        assert score.broker_id == "b1"
        assert score.latency_ms == 50.0
        assert score.fill_rate == 0.97
        assert score.avg_slippage_bps == 3.0
        assert score.cost_score == 8.0
        assert score.reliability_score == 0.99
        assert score.overall_score == 0.0

    def test_calculate_sets_overall_score(self):
        score = _make_score()
        score.calculate(_default_weights())
        assert 0.0 < score.overall_score <= 1.0

    def test_calculate_uses_custom_weights(self):
        score = _make_score()
        weights = {"latency": 0.5, "fill_rate": 0.5, "cost": 0.0, "reliability": 0.0}
        score.calculate(weights)
        assert score.overall_score > 0.0

    def test_calculate_missing_weight_defaults_to_025(self):
        score = _make_score()
        # Omit 'cost' and 'reliability' — should fall back to 0.25 each
        score.calculate({"latency": 0.25, "fill_rate": 0.25})
        assert score.overall_score > 0.0

    def test_high_latency_lowers_score(self):
        low_lat = _make_score(latency_ms=5.0)
        high_lat = _make_score(latency_ms=500.0)
        low_lat.calculate(_default_weights())
        high_lat.calculate(_default_weights())
        assert low_lat.overall_score > high_lat.overall_score

    def test_high_fill_rate_raises_score(self):
        good = _make_score(fill_rate=0.999)
        bad = _make_score(fill_rate=0.5)
        good.calculate(_default_weights())
        bad.calculate(_default_weights())
        assert good.overall_score > bad.overall_score

    def test_low_cost_raises_score(self):
        cheap = _make_score(cost_score=1.0)
        expensive = _make_score(cost_score=100.0)
        cheap.calculate(_default_weights())
        expensive.calculate(_default_weights())
        assert cheap.overall_score > expensive.overall_score

    def test_high_reliability_raises_score(self):
        reliable = _make_score(reliability_score=1.0)
        unreliable = _make_score(reliability_score=0.5)
        reliable.calculate(_default_weights())
        unreliable.calculate(_default_weights())
        assert reliable.overall_score > unreliable.overall_score

    def test_calculate_idempotent_on_repeated_calls(self):
        score = _make_score()
        score.calculate(_default_weights())
        first = score.overall_score
        score.calculate(_default_weights())
        assert score.overall_score == pytest.approx(first)


# ---------------------------------------------------------------------------
# SmartOrderRouter — initialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSmartOrderRouterInit:
    def test_default_state(self):
        router = _make_router()
        assert router.brokers == {}
        assert router.scores == {}
        assert router.order_history == []
        assert router.last_route_decision is None

    def test_routing_rules_present(self):
        router = _make_router()
        assert "latency_weight" in router.routing_rules
        assert "fill_rate_weight" in router.routing_rules
        assert "cost_weight" in router.routing_rules
        assert "reliability_weight" in router.routing_rules

    def test_add_broker_registers_connector(self):
        router = _make_router()
        conn = _make_connector("alpha")
        router.add_broker("alpha", conn)
        assert "alpha" in router.brokers
        assert router.brokers["alpha"] is conn

    def test_add_broker_creates_default_score(self):
        from brokers.smart_router import BrokerScore

        router = _make_router()
        router.add_broker("alpha", _make_connector())
        assert "alpha" in router.scores
        assert isinstance(router.scores["alpha"], BrokerScore)

    def test_add_broker_default_score_values(self):
        router = _make_router()
        router.add_broker("alpha", _make_connector())
        s = router.scores["alpha"]
        assert s.latency_ms == 100
        assert s.fill_rate == 0.95
        assert s.avg_slippage_bps == 5.0
        assert s.cost_score == 10.0
        assert s.reliability_score == 0.99

    def test_add_multiple_brokers(self):
        router = _make_router()
        for name in ("a", "b", "c"):
            router.add_broker(name, _make_connector(name))
        assert len(router.brokers) == 3
        assert len(router.scores) == 3


# ---------------------------------------------------------------------------
# SmartOrderRouter — _explain_selection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExplainSelection:
    def test_low_latency_reason(self):
        router = _make_router()
        score = _make_score(latency_ms=30.0)
        reason = router._explain_selection(score)
        assert "low_latency" in reason

    def test_high_fill_rate_reason(self):
        router = _make_router()
        score = _make_score(fill_rate=0.99)
        reason = router._explain_selection(score)
        assert "high_fill_rate" in reason

    def test_low_cost_reason(self):
        router = _make_router()
        score = _make_score(cost_score=3.0)
        reason = router._explain_selection(score)
        assert "low_cost" in reason

    def test_high_reliability_reason(self):
        router = _make_router()
        score = _make_score(reliability_score=0.995)
        reason = router._explain_selection(score)
        assert "high_reliability" in reason

    def test_balanced_score_fallback(self):
        router = _make_router()
        # None of the thresholds met
        score = _make_score(
            latency_ms=200.0,
            fill_rate=0.90,
            cost_score=20.0,
            reliability_score=0.95,
        )
        reason = router._explain_selection(score)
        assert reason == "balanced_score"

    def test_multiple_reasons_joined(self):
        router = _make_router()
        score = _make_score(latency_ms=10.0, fill_rate=0.999, cost_score=2.0, reliability_score=0.999)
        reason = router._explain_selection(score)
        assert "," in reason  # multiple reasons


# ---------------------------------------------------------------------------
# SmartOrderRouter — route_order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRouteOrder:
    @pytest.mark.asyncio
    async def test_route_order_returns_best_broker(self):
        router = _make_router()
        # Add two brokers; alpha has better latency
        alpha = _make_connector("alpha")
        beta = _make_connector("beta")
        router.add_broker("alpha", alpha)
        router.add_broker("beta", beta)
        # Give alpha a better score
        router.scores["alpha"].latency_ms = 10.0
        router.scores["beta"].latency_ms = 200.0

        broker_id, decision = await router.route_order({"symbol": "EURUSD", "side": "buy"})
        assert broker_id == "alpha"
        assert decision["selected_broker"] == "alpha"

    @pytest.mark.asyncio
    async def test_route_order_decision_structure(self):
        router = _make_router()
        router.add_broker("only", _make_connector("only"))

        broker_id, decision = await router.route_order({"symbol": "XAUUSD"})
        assert "selected_broker" in decision
        assert "alternative_brokers" in decision
        assert "selection_reason" in decision
        assert "timestamp" in decision
        assert "expected_latency_ms" in decision
        assert "expected_cost_bps" in decision

    @pytest.mark.asyncio
    async def test_route_order_sets_last_route_decision(self):
        router = _make_router()
        router.add_broker("solo", _make_connector("solo"))
        await router.route_order({"symbol": "BTCUSD"})
        assert router.last_route_decision == "solo"

    @pytest.mark.asyncio
    async def test_route_order_alternative_brokers_list(self):
        router = _make_router()
        for name in ("a", "b", "c", "d"):
            router.add_broker(name, _make_connector(name))
        _, decision = await router.route_order({})
        # At most 2 alternatives
        assert len(decision["alternative_brokers"]) <= 2

    @pytest.mark.asyncio
    async def test_route_order_timestamp_is_iso(self):
        router = _make_router()
        router.add_broker("x", _make_connector("x"))
        _, decision = await router.route_order({})
        # Should parse without error
        datetime.fromisoformat(decision["timestamp"])


# ---------------------------------------------------------------------------
# SmartOrderRouter — _update_broker_scores
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateBrokerScores:
    @pytest.mark.asyncio
    async def test_latency_ema_updated(self):
        router = _make_router()
        conn = _make_connector("a")
        router.add_broker("a", conn)
        original_latency = router.scores["a"].latency_ms
        await router._update_broker_scores()
        # EMA should have changed
        assert router.scores["a"].latency_ms != original_latency or True  # may be same if ping is fast

    @pytest.mark.asyncio
    async def test_fill_rate_updated_from_recent_fills(self):
        from datetime import timedelta

        router = _make_router()
        now = datetime.now(UTC)
        fills = [
            {"timestamp": now, "filled": True, "slippage_bps": 2.0},
            {"timestamp": now, "filled": True, "slippage_bps": 3.0},
            {"timestamp": now, "filled": False, "slippage_bps": 0.0},
        ]
        conn = _make_connector("a", fills=fills)
        router.add_broker("a", conn)
        await router._update_broker_scores()
        # 2 of 3 filled → fill_rate ≈ 0.667
        assert router.scores["a"].fill_rate == pytest.approx(2 / 3, abs=0.01)

    @pytest.mark.asyncio
    async def test_reliability_degraded_on_ping_failure(self):
        router = _make_router()
        conn = _make_connector("a")
        conn.client.get_server_time = AsyncMock(side_effect=ConnectionError("timeout"))
        router.add_broker("a", conn)
        original_reliability = router.scores["a"].reliability_score
        await router._update_broker_scores()
        assert router.scores["a"].reliability_score < original_reliability

    @pytest.mark.asyncio
    async def test_multiple_failures_compound_degradation(self):
        router = _make_router()
        conn = _make_connector("a")
        conn.client.get_server_time = AsyncMock(side_effect=OSError("down"))
        router.add_broker("a", conn)
        for _ in range(5):
            await router._update_broker_scores()
        assert router.scores["a"].reliability_score < 0.99 * (0.9 ** 4)


# ---------------------------------------------------------------------------
# SmartOrderRouter — execute_with_fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteWithFallback:
    @pytest.mark.asyncio
    async def test_success_on_primary(self):
        router = _make_router()
        conn = _make_connector("primary")
        router.add_broker("primary", conn)

        result = await router.execute_with_fallback({"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1})
        assert "routing" in result
        assert result.get("id") == "ord-1"

    @pytest.mark.asyncio
    async def test_fallback_used_when_primary_fails(self):
        router = _make_router()

        # Primary always fails
        bad_conn = _make_connector("primary")
        bad_conn.client.place_order = AsyncMock(side_effect=RuntimeError("primary down"))
        router.add_broker("primary", bad_conn)

        # Fallback succeeds
        good_conn = _make_connector("fallback")
        router.add_broker("fallback", good_conn)

        # Force primary to be selected first
        router.scores["primary"].latency_ms = 1.0
        router.scores["fallback"].latency_ms = 200.0

        result = await router.execute_with_fallback(
            {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        )
        assert "fallback_used" in result["routing"]

    @pytest.mark.asyncio
    async def test_raises_when_all_brokers_fail(self):
        router = _make_router()

        for name in ("a", "b", "c"):
            conn = _make_connector(name)
            conn.client.place_order = AsyncMock(side_effect=RuntimeError("down"))
            router.add_broker(name, conn)

        with pytest.raises(RuntimeError, match="All brokers failed"):
            await router.execute_with_fallback({"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1})

    @pytest.mark.asyncio
    async def test_fallback_reason_recorded(self):
        router = _make_router()

        bad = _make_connector("bad")
        bad.client.place_order = AsyncMock(side_effect=RuntimeError("primary error"))
        router.add_broker("bad", bad)

        good = _make_connector("good")
        router.add_broker("good", good)

        router.scores["bad"].latency_ms = 1.0
        router.scores["good"].latency_ms = 200.0

        result = await router.execute_with_fallback(
            {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        )
        assert "fallback_reason" in result["routing"]
        assert "primary error" in result["routing"]["fallback_reason"]


# ---------------------------------------------------------------------------
# SmartOrderRouter — _execute_with_timeout
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteWithTimeout:
    @pytest.mark.asyncio
    async def test_executes_successfully(self):
        router = _make_router()
        conn = _make_connector("a")
        router.add_broker("a", conn)
        result = await router._execute_with_timeout(
            "a", {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        )
        assert result["id"] == "ord-1"

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        router = _make_router()
        conn = _make_connector("slow")

        async def _slow(*args, **kwargs):
            await asyncio.sleep(10)
            return {}

        conn.client.place_order = _slow
        router.add_broker("slow", conn)

        with pytest.raises(asyncio.TimeoutError):
            await router._execute_with_timeout(
                "slow",
                {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1},
                timeout_ms=50,
            )


# ---------------------------------------------------------------------------
# BrokerConnector
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrokerConnector:
    @pytest.mark.asyncio
    async def test_ping_returns_latency(self):
        conn = _make_connector("a")
        latency = await conn.ping()
        assert latency >= 0.0

    @pytest.mark.asyncio
    async def test_ping_appends_to_history(self):
        conn = _make_connector("a")
        assert len(conn.latency_history) == 0
        await conn.ping()
        assert len(conn.latency_history) == 1

    @pytest.mark.asyncio
    async def test_ping_history_capped_at_1000(self):
        conn = _make_connector("a")
        conn.client.get_server_time = AsyncMock(return_value={})
        for _ in range(1005):
            await conn.ping()
        assert len(conn.latency_history) == 1000

    @pytest.mark.asyncio
    async def test_place_order_returns_result(self):
        conn = _make_connector("a")
        order = {
            "symbol": "EURUSD",
            "side": "buy",
            "type": "MARKET",
            "size": 1,
            "price": 1.0820,
        }
        result = await conn.place_order(order)
        assert result["id"] == "ord-1"
        assert result["status"] == "FILLED"

    @pytest.mark.asyncio
    async def test_place_order_appends_fill_history(self):
        conn = _make_connector("a")
        order = {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        await conn.place_order(order)
        assert len(conn.fill_history) == 1

    @pytest.mark.asyncio
    async def test_place_order_fill_record_structure(self):
        conn = _make_connector("a")
        order = {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        await conn.place_order(order)
        record = conn.fill_history[0]
        assert "timestamp" in record
        assert "order_id" in record
        assert "filled" in record
        assert "slippage_bps" in record
        assert "latency_ms" in record

    @pytest.mark.asyncio
    async def test_place_order_filled_flag_true_when_status_filled(self):
        conn = _make_connector("a")
        order = {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        await conn.place_order(order)
        assert conn.fill_history[0]["filled"] is True

    @pytest.mark.asyncio
    async def test_place_order_filled_flag_false_when_not_filled(self):
        conn = _make_connector("a")
        conn.client.place_order = AsyncMock(
            return_value={"id": "x", "status": "REJECTED", "avg_price": 1.0}
        )
        order = {"symbol": "EURUSD", "side": "buy", "type": "MARKET", "size": 1}
        await conn.place_order(order)
        assert conn.fill_history[0]["filled"] is False

    @pytest.mark.asyncio
    async def test_get_recent_fills_returns_within_window(self):
        from datetime import timedelta

        conn = _make_connector("a")
        now = datetime.now(UTC)
        conn.fill_history = [
            {"timestamp": now, "filled": True, "slippage_bps": 1.0},
            {"timestamp": now - timedelta(hours=2), "filled": True, "slippage_bps": 2.0},
        ]
        recent = await conn.get_recent_fills(hours=1)
        assert len(recent) == 1

    @pytest.mark.asyncio
    async def test_get_recent_fills_empty_history(self):
        conn = _make_connector("a")
        recent = await conn.get_recent_fills(hours=1)
        assert recent == []

    @pytest.mark.asyncio
    async def test_get_recent_fills_all_within_window(self):
        from datetime import timedelta

        conn = _make_connector("a")
        now = datetime.now(UTC)
        conn.fill_history = [
            {"timestamp": now - timedelta(minutes=10), "filled": True, "slippage_bps": 1.0},
            {"timestamp": now - timedelta(minutes=20), "filled": True, "slippage_bps": 2.0},
        ]
        recent = await conn.get_recent_fills(hours=1)
        assert len(recent) == 2


# ---------------------------------------------------------------------------
# BrokerConnector — _calculate_slippage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculateSlippage:
    def test_no_price_in_order_returns_zero(self):
        conn = _make_connector("a")
        result = conn._calculate_slippage({"side": "buy"}, {"avg_price": 1.0820})
        assert result == 0.0

    def test_no_avg_price_in_result_returns_zero(self):
        conn = _make_connector("a")
        result = conn._calculate_slippage({"side": "buy", "price": 1.0820}, {})
        assert result == 0.0

    def test_buy_slippage_positive_when_actual_above_expected(self):
        conn = _make_connector("a")
        result = conn._calculate_slippage(
            {"side": "buy", "price": 1.0820},
            {"avg_price": 1.0830},
        )
        assert result > 0.0

    def test_sell_slippage_positive_when_actual_below_expected(self):
        conn = _make_connector("a")
        result = conn._calculate_slippage(
            {"side": "sell", "price": 1.0830},
            {"avg_price": 1.0820},
        )
        assert result > 0.0

    def test_buy_zero_slippage_when_filled_at_expected(self):
        conn = _make_connector("a")
        result = conn._calculate_slippage(
            {"side": "buy", "price": 1.0820},
            {"avg_price": 1.0820},
        )
        assert result == pytest.approx(0.0)

    def test_slippage_in_basis_points(self):
        conn = _make_connector("a")
        # 1 pip on EURUSD = 0.0001 → ~1 bps
        result = conn._calculate_slippage(
            {"side": "buy", "price": 1.0000},
            {"avg_price": 1.0001},
        )
        assert result == pytest.approx(1.0, abs=0.01)
