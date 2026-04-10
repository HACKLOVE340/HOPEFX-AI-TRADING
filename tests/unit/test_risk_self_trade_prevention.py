# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/self_trade_prevention.py — SelfTradePrevention, Order, SelfTradeAction."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from risk.self_trade_prevention import Order, SelfTradeAction, SelfTradePrevention

UTC = timezone.utc


def _order(
    oid: str = "o1",
    symbol: str = "XAUUSD",
    side: str = "buy",
    size: float = 1.0,
    price: float = 1900.0,
    account_id: str = "acc1",
    strategy_id: str | None = "strat1",
) -> Order:
    return Order(
        id=oid,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        timestamp=datetime.now(UTC),
        account_id=account_id,
        strategy_id=strategy_id,
    )


class TestSelfTradePreventionInit:
    def test_default_level(self):
        stp = SelfTradePrevention()
        assert stp.level == "account"

    def test_custom_action(self):
        stp = SelfTradePrevention(action=SelfTradeAction.CANCEL_BOTH)
        assert stp.action == SelfTradeAction.CANCEL_BOTH

    def test_empty_resting_orders(self):
        stp = SelfTradePrevention()
        assert stp.resting_orders == {}


class TestAddAndRemoveResting:
    def test_add_resting_order(self):
        stp = SelfTradePrevention()
        o = _order("r1", side="sell")
        stp.add_resting_order(o)
        assert "XAUUSD" in stp.resting_orders
        assert len(stp.resting_orders["XAUUSD"]) == 1

    def test_remove_resting_order(self):
        stp = SelfTradePrevention()
        o = _order("r1", side="sell")
        stp.add_resting_order(o)
        stp.remove_resting_order("r1", "XAUUSD")
        assert len(stp.resting_orders["XAUUSD"]) == 0

    def test_remove_nonexistent_no_crash(self):
        stp = SelfTradePrevention()
        stp.remove_resting_order("ghost", "XAUUSD")  # should not raise


class TestCheckSelfTrade:
    def test_no_resting_orders_returns_none(self):
        stp = SelfTradePrevention()
        result = stp.check_self_trade(_order("n1", side="buy"))
        assert result is None

    def test_same_side_no_cross(self):
        stp = SelfTradePrevention()
        stp.add_resting_order(_order("r1", side="buy", price=1900.0))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0))
        assert result is None

    def test_different_account_no_cross(self):
        stp = SelfTradePrevention(prevention_level="account")
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, account_id="acc2"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0, account_id="acc1"))
        assert result is None

    def test_self_trade_detected_cancel_resting(self):
        stp = SelfTradePrevention(action=SelfTradeAction.CANCEL_RESTING)
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, account_id="acc1"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0, account_id="acc1"))
        assert result is not None
        assert result["action"] == "cancel"
        assert result["order_to_cancel"] == "r1"
        assert result["allow_new"] is True

    def test_self_trade_cancel_new(self):
        stp = SelfTradePrevention(action=SelfTradeAction.CANCEL_NEW)
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, account_id="acc1"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0, account_id="acc1"))
        assert result is not None
        assert result["action"] == "reject"

    def test_self_trade_cancel_both(self):
        stp = SelfTradePrevention(action=SelfTradeAction.CANCEL_BOTH)
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, account_id="acc1"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0, account_id="acc1"))
        assert result is not None
        assert result["action"] == "cancel_both"
        assert result["reject_new"] is True

    def test_self_trade_decrement_size(self):
        stp = SelfTradePrevention(action=SelfTradeAction.DECREMENT_SIZE)
        stp.add_resting_order(_order("r1", side="sell", size=3.0, price=1900.0, account_id="acc1"))
        result = stp.check_self_trade(_order("n1", side="buy", size=2.0, price=1900.0, account_id="acc1"))
        assert result is not None
        assert result["action"] == "decrement"
        # min(2, 3) = 2; new_order_size = 2-2=0, resting_order_size = 3-2=1
        assert result["new_order_size"] == pytest.approx(0.0)
        assert result["resting_order_size"] == pytest.approx(1.0)

    def test_buy_price_below_resting_no_cross(self):
        """Buy at 1890 does not cross sell resting at 1900."""
        stp = SelfTradePrevention()
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, account_id="acc1"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1890.0, account_id="acc1"))
        assert result is None

    def test_sell_price_above_resting_no_cross(self):
        """Sell at 1910 does not cross buy resting at 1900."""
        stp = SelfTradePrevention()
        stp.add_resting_order(_order("r1", side="buy", price=1900.0, account_id="acc1"))
        result = stp.check_self_trade(_order("n1", side="sell", price=1910.0, account_id="acc1"))
        assert result is None

    def test_firm_level_always_same_entity(self):
        stp = SelfTradePrevention(prevention_level="firm")
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, account_id="acc_x"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0, account_id="acc_y"))
        assert result is not None  # firm level: all orders are same entity

    def test_strategy_level_different_strategy_no_cross(self):
        stp = SelfTradePrevention(prevention_level="strategy")
        stp.add_resting_order(_order("r1", side="sell", price=1900.0, strategy_id="stratA"))
        result = stp.check_self_trade(_order("n1", side="buy", price=1900.0, strategy_id="stratB"))
        assert result is None
