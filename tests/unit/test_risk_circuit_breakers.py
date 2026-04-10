# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/circuit_breakers.py — CircuitBreaker, RiskLimits, CircuitState."""

from __future__ import annotations

from datetime import timezone
from unittest.mock import MagicMock

import pytest

from risk.circuit_breakers import (
    CircuitBreaker,
    CircuitState,
    RiskLimits,
    get_circuit_breakers,
    register_circuit_breaker,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_broker(balance: float = 100_000.0) -> MagicMock:
    broker = MagicMock()
    broker.get_balance.return_value = balance
    broker.get_positions.return_value = []
    broker.cancel_all_orders.return_value = None
    broker.close_position.return_value = None
    return broker


def _make_cb(balance: float = 100_000.0) -> CircuitBreaker:
    broker = _make_broker(balance)
    return CircuitBreaker(broker=broker, redis_client=None)


# ---------------------------------------------------------------------------
# RiskLimits
# ---------------------------------------------------------------------------


class TestRiskLimits:
    def test_defaults(self):
        rl = RiskLimits()
        assert rl.max_daily_drawdown_pct == pytest.approx(0.03)
        assert rl.max_total_drawdown_pct == pytest.approx(0.10)
        assert rl.max_orders_per_minute == 10
        assert rl.max_leverage_ratio == pytest.approx(10.0)

    def test_custom_values(self):
        rl = RiskLimits(max_daily_drawdown_pct=0.05, max_orders_per_minute=20)
        assert rl.max_daily_drawdown_pct == pytest.approx(0.05)
        assert rl.max_orders_per_minute == 20


# ---------------------------------------------------------------------------
# CircuitState
# ---------------------------------------------------------------------------


class TestCircuitState:
    def test_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


# ---------------------------------------------------------------------------
# CircuitBreaker construction
# ---------------------------------------------------------------------------


class TestCircuitBreakerInit:
    def test_initial_state_closed(self):
        cb = _make_cb()
        assert cb.state == CircuitState.CLOSED

    def test_initial_pnl_zero(self):
        cb = _make_cb()
        assert cb.daily_pnl == 0.0
        assert cb.total_pnl == 0.0

    def test_peak_balance_set_from_broker(self):
        cb = _make_cb(balance=50_000.0)
        assert cb.peak_balance == pytest.approx(50_000.0)

    def test_no_redis_no_crash(self):
        cb = _make_cb()
        assert cb.redis is None


# ---------------------------------------------------------------------------
# pre_trade_check
# ---------------------------------------------------------------------------


class TestPreTradeCheck:
    def test_allows_normal_order(self):
        cb = _make_cb()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1900.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is True
        assert reason is None

    def test_blocks_when_open(self):
        cb = _make_cb()
        cb.state = CircuitState.OPEN
        cb.breach_history.append({"reason": "TEST", "message": "test"})
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1900.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert reason is not None

    def test_blocks_oversized_order(self):
        cb = _make_cb()
        # notional = 1000 * 2000 = 2_000_000 > default max_order_size 100_000
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1000.0, "price": 2000.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert "size" in reason.lower() or "limit" in reason.lower()

    def test_records_order_timestamp(self):
        cb = _make_cb()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 0.1, "price": 1900.0}
        cb.pre_trade_check(order)
        assert len(cb.orders_last_minute) == 1

    def test_half_open_reduces_size(self):
        cb = _make_cb()
        cb.state = CircuitState.HALF_OPEN
        order = {"symbol": "XAUUSD", "side": "buy", "size": 2.0, "price": 1900.0}
        allowed, _ = cb.pre_trade_check(order)
        assert allowed is True
        assert order["size"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# update_trade_result
# ---------------------------------------------------------------------------


class TestUpdateTradeResult:
    def test_loss_increments_streak(self):
        cb = _make_cb()
        cb.update_trade_result(-500.0)
        assert cb.consecutive_losses == 1
        assert cb.loss_streak_amount == pytest.approx(500.0)

    def test_win_resets_streak(self):
        cb = _make_cb()
        cb.update_trade_result(-500.0)
        cb.update_trade_result(200.0)
        assert cb.consecutive_losses == 0
        assert cb.loss_streak_amount == pytest.approx(0.0)

    def test_multiple_losses_accumulate(self):
        cb = _make_cb()
        cb.update_trade_result(-100.0)
        cb.update_trade_result(-200.0)
        assert cb.consecutive_losses == 2
        assert cb.loss_streak_amount == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# manual_override
# ---------------------------------------------------------------------------


class TestManualOverride:
    def test_enable_override(self):
        cb = _make_cb()
        cb.manual_override(enable=True, reason="ops decision", authorized_by="admin")
        assert cb._manual_override is True
        assert cb._override_reason == "ops decision"

    @pytest.mark.asyncio
    async def test_disable_override(self):
        cb = _make_cb()
        cb.manual_override(enable=True, reason="test", authorized_by="admin")
        cb.manual_override(enable=False, reason="cleared", authorized_by="admin")
        assert cb._manual_override is False
        assert cb._override_reason is None

    def test_audit_trail_recorded(self):
        cb = _make_cb()
        cb.manual_override(enable=True, reason="test", authorized_by="admin")
        assert len(cb.state_changes) >= 1
        assert cb.state_changes[-1]["authorized_by"] == "admin"


# ---------------------------------------------------------------------------
# async trigger
# ---------------------------------------------------------------------------


class TestAsyncTrigger:
    @pytest.mark.asyncio
    async def test_trigger_opens_circuit(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("TEST", "unit test trigger")
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_trigger_records_breach(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("DAILY_DRAWDOWN", "drawdown exceeded")
        assert len(cb.breach_history) == 1
        assert cb.breach_history[0]["reason"] == "DAILY_DRAWDOWN"

    @pytest.mark.asyncio
    async def test_double_trigger_no_duplicate(self):
        cb = _make_cb()
        await cb._trigger_circuit_breaker("TEST", "first")
        await cb._trigger_circuit_breaker("TEST", "second")
        # Second call is a no-op when already OPEN
        assert len(cb.breach_history) == 1


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_retrieve(self):
        cb = _make_cb()
        register_circuit_breaker("test_broker", cb)
        registry = get_circuit_breakers()
        assert "test_broker" in registry
        assert registry["test_broker"] is cb
