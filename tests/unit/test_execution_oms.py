# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for execution/oms.py — Order, OrderLifecycleManager.
"""

import asyncio
from decimal import Decimal

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Order dataclass
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOMSOrder:
    def _make(self, qty=Decimal("1.0"), filled=Decimal("0"), status=None):
        from execution.oms import Order, OrderStatus
        o = Order(symbol="XAUUSD", side="BUY", order_type="LIMIT",
                  quantity=qty, filled_quantity=filled)
        if status:
            o.status = status
        return o

    def test_remaining_quantity_unfilled(self):
        o = self._make(qty=Decimal("2.0"), filled=Decimal("0"))
        assert o.remaining_quantity == Decimal("2.0")

    def test_remaining_quantity_partial(self):
        o = self._make(qty=Decimal("2.0"), filled=Decimal("0.5"))
        assert o.remaining_quantity == Decimal("1.5")

    def test_is_active_new(self):
        from execution.oms import OrderStatus
        o = self._make(status=OrderStatus.NEW)
        assert o.is_active is True

    def test_is_active_partially_filled(self):
        from execution.oms import OrderStatus
        o = self._make(status=OrderStatus.PARTIALLY_FILLED)
        assert o.is_active is True

    def test_is_active_filled_false(self):
        from execution.oms import OrderStatus
        o = self._make(status=OrderStatus.FILLED)
        assert o.is_active is False

    def test_is_active_cancelled_false(self):
        from execution.oms import OrderStatus
        o = self._make(status=OrderStatus.CANCELLED)
        assert o.is_active is False

    def test_can_fill_valid_market(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.NEW
        o.order_type = "MARKET"
        assert o.can_fill(Decimal("1.0"), Decimal("1950.0")) is True

    def test_can_fill_limit_buy_price_ok(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.NEW
        o.order_type = "LIMIT"
        o.price = Decimal("1960.0")
        assert o.can_fill(Decimal("1.0"), Decimal("1950.0")) is True

    def test_can_fill_limit_buy_price_too_high(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.NEW
        o.order_type = "LIMIT"
        o.price = Decimal("1940.0")
        assert o.can_fill(Decimal("1.0"), Decimal("1950.0")) is False

    def test_can_fill_limit_sell_price_ok(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.NEW
        o.order_type = "LIMIT"
        o.side = "SELL"
        o.price = Decimal("1940.0")
        assert o.can_fill(Decimal("1.0"), Decimal("1950.0")) is True

    def test_can_fill_limit_sell_price_too_low(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.NEW
        o.order_type = "LIMIT"
        o.side = "SELL"
        o.price = Decimal("1960.0")
        assert o.can_fill(Decimal("1.0"), Decimal("1950.0")) is False

    def test_can_fill_exceeds_remaining(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.NEW
        o.order_type = "MARKET"
        assert o.can_fill(Decimal("2.0"), Decimal("1950.0")) is False

    def test_can_fill_wrong_status(self):
        from execution.oms import OrderStatus
        o = self._make(qty=Decimal("1.0"))
        o.status = OrderStatus.CANCELLED
        assert o.can_fill(Decimal("1.0"), Decimal("1950.0")) is False

    def test_default_id_generated(self):
        from execution.oms import Order
        o1 = Order()
        o2 = Order()
        assert o1.id != o2.id

    def test_time_in_force_default_gtc(self):
        from execution.oms import Order, TimeInForce
        o = Order()
        assert o.time_in_force == TimeInForce.GTC


@pytest.mark.unit
class TestOrderLifecycleManager:
    def _make_olm(self):
        from execution.oms import OrderLifecycleManager
        return OrderLifecycleManager()

    def test_create_order_returns_order(self):
        from execution.oms import OrderStatus
        olm = self._make_olm()
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  quantity=Decimal("1.0"))
        assert order is not None
        assert order.status == OrderStatus.CREATED

    def test_order_stored_in_orders(self):
        olm = self._make_olm()
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  quantity=Decimal("1.0"))
        assert order.id in olm.orders

    def test_fill_order_partial(self):
        from execution.oms import OrderStatus
        olm = self._make_olm()
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  order_type="MARKET", quantity=Decimal("2.0"))
        order.status = OrderStatus.NEW
        result = olm.fill_order(order.id, Decimal("1.0"), Decimal("1950.0"))
        assert result is True
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == Decimal("1.0")

    def test_fill_order_complete(self):
        from execution.oms import OrderStatus
        olm = self._make_olm()
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  order_type="MARKET", quantity=Decimal("1.0"))
        order.status = OrderStatus.NEW
        result = olm.fill_order(order.id, Decimal("1.0"), Decimal("1950.0"))
        assert result is True
        assert order.status == OrderStatus.FILLED

    def test_fill_nonexistent_order_returns_false(self):
        olm = self._make_olm()
        result = olm.fill_order("ghost", Decimal("1.0"), Decimal("1950.0"))
        assert result is False

    def test_cancel_order(self):
        from execution.oms import OrderStatus
        olm = self._make_olm()
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  quantity=Decimal("1.0"))
        order.status = OrderStatus.NEW
        result = olm.cancel_order(order.id)
        assert result is True
        # cancel_order transitions to PENDING_CANCEL (not CANCELLED directly)
        assert order.status == OrderStatus.PENDING_CANCEL

    def test_cancel_nonexistent_returns_false(self):
        olm = self._make_olm()
        assert olm.cancel_order("ghost") is False

    def test_active_orders_empty_initially(self):
        olm = self._make_olm()
        assert len(olm.active_orders) == 0

    def test_get_order_history_after_valid_transition(self):
        from execution.oms import OrderStatus
        olm = self._make_olm()
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  quantity=Decimal("1.0"))
        # CREATED → PENDING_NEW is a valid transition
        olm._transition(order, OrderStatus.PENDING_NEW)
        assert len(olm.order_history) > 0

    def test_register_callback_fires_on_status(self):
        from execution.oms import OrderStatus
        olm = self._make_olm()
        fired = []
        # Callbacks receive (order, context) — capture order id
        olm.register_callback(OrderStatus.PENDING_NEW,
                               lambda o, ctx: fired.append(o.id))
        order = olm.create_order(symbol="XAUUSD", side="BUY",
                                  quantity=Decimal("1.0"))
        olm._transition(order, OrderStatus.PENDING_NEW)
        assert order.id in fired

    def test_valid_transitions_defined(self):
        from execution.oms import OrderLifecycleManager, OrderStatus
        assert OrderStatus.CREATED in OrderLifecycleManager.VALID_TRANSITIONS
        assert OrderStatus.FILLED in OrderLifecycleManager.VALID_TRANSITIONS
