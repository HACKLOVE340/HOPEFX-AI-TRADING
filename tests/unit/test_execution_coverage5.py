# tests/unit/test_execution_coverage5.py
"""Coverage tests for execution/oms.py — OrderLifecycleManager, ComplexOrderManager."""

from __future__ import annotations

from decimal import Decimal


class TestOrderLifecycleManager:
    def setup_method(self):
        from execution.oms import Order, OrderLifecycleManager, OrderStatus

        self.OLM = OrderLifecycleManager
        self.Order = Order
        self.Status = OrderStatus

    def _mgr(self):
        return self.OLM()

    def test_create_order(self):
        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        assert order.id in mgr.orders
        assert order.status == self.Status.CREATED

    def test_fill_order_full(self):
        mgr = self._mgr()
        order = mgr.create_order(
            symbol="XAUUSD",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("1"),
            price=Decimal("2350"),
        )
        # Manually transition to NEW so fill is valid
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        ok = mgr.fill_order(order.id, Decimal("1"), Decimal("2349"))
        assert ok
        assert order.status == self.Status.FILLED

    def test_fill_order_partial(self):
        mgr = self._mgr()
        order = mgr.create_order(
            symbol="XAUUSD",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("2"),
        )
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        ok = mgr.fill_order(order.id, Decimal("1"), Decimal("2350"))
        assert ok
        assert order.status == self.Status.PARTIALLY_FILLED

    def test_fill_order_unknown_id(self):
        mgr = self._mgr()
        ok = mgr.fill_order("nonexistent", Decimal("1"), Decimal("2350"))
        assert not ok

    def test_cancel_order(self):
        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        ok = mgr.cancel_order(order.id)
        assert ok
        assert order.status == self.Status.PENDING_CANCEL

    def test_cancel_inactive_order_fails(self):
        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        # CREATED is not active
        ok = mgr.cancel_order(order.id)
        assert not ok

    def test_cancel_unknown_id(self):
        mgr = self._mgr()
        ok = mgr.cancel_order("bad_id")
        assert not ok

    def test_invalid_transition_returns_false(self):
        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        # CREATED → FILLED is invalid
        ok = mgr._transition(order, self.Status.FILLED)
        assert not ok

    def test_expire_orders(self):
        from datetime import datetime, timedelta, timezone

        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        order.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        mgr.expire_orders()
        assert order.status == self.Status.EXPIRED

    def test_expire_orders_no_expiry(self):
        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        # No expires_at set — should not expire
        mgr.expire_orders()
        assert order.status == self.Status.NEW

    def test_get_order_book(self):
        mgr = self._mgr()
        order = mgr.create_order(
            symbol="XAUUSD",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("1"),
            price=Decimal("2350"),
        )
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        book = mgr.get_order_book("XAUUSD")
        assert "bids" in book
        assert "asks" in book
        assert len(book["bids"]) == 1

    def test_get_order_book_sell(self):
        mgr = self._mgr()
        order = mgr.create_order(
            symbol="XAUUSD",
            side="SELL",
            order_type="LIMIT",
            quantity=Decimal("1"),
            price=Decimal("2360"),
        )
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        book = mgr.get_order_book("XAUUSD")
        assert len(book["asks"]) == 1

    def test_register_callback_fires(self):
        fired = []
        mgr = self._mgr()
        mgr.register_callback(self.Status.PENDING_NEW, lambda o, ctx: fired.append(o.id))
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        mgr._transition(order, self.Status.PENDING_NEW)
        assert len(fired) == 1

    def test_callback_exception_does_not_propagate(self):
        def bad_cb(o, ctx):
            raise RuntimeError("cb error")

        mgr = self._mgr()
        mgr.register_callback(self.Status.PENDING_NEW, bad_cb)
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        # Should not raise
        mgr._transition(order, self.Status.PENDING_NEW)

    def test_order_history_recorded(self):
        mgr = self._mgr()
        order = mgr.create_order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"))
        mgr._transition(order, self.Status.PENDING_NEW)
        # create_order records CREATED transition; _transition records PENDING_NEW
        assert len(mgr.order_history) >= 1

    def test_order_remaining_quantity(self):
        from execution.oms import Order

        o = Order(quantity=Decimal("2"), filled_quantity=Decimal("1"))
        assert o.remaining_quantity == Decimal("1")

    def test_order_is_active(self):
        from execution.oms import Order, OrderStatus

        o = Order(status=OrderStatus.NEW)
        assert o.is_active

    def test_order_is_not_active_when_filled(self):
        from execution.oms import Order, OrderStatus

        o = Order(status=OrderStatus.FILLED)
        assert not o.is_active

    def test_can_fill_limit_buy_price_check(self):
        from execution.oms import Order, OrderStatus

        o = Order(
            status=OrderStatus.NEW,
            order_type="LIMIT",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("2350"),
        )
        # Fill price above limit → rejected
        assert not o.can_fill(Decimal("1"), Decimal("2351"))
        # Fill price at limit → ok
        assert o.can_fill(Decimal("1"), Decimal("2350"))

    def test_can_fill_limit_sell_price_check(self):
        from execution.oms import Order, OrderStatus

        o = Order(
            status=OrderStatus.NEW,
            order_type="LIMIT",
            side="SELL",
            quantity=Decimal("1"),
            price=Decimal("2350"),
        )
        assert not o.can_fill(Decimal("1"), Decimal("2349"))
        assert o.can_fill(Decimal("1"), Decimal("2350"))

    def test_can_fill_exceeds_remaining(self):
        from execution.oms import Order, OrderStatus

        o = Order(
            status=OrderStatus.NEW,
            order_type="MARKET",
            quantity=Decimal("1"),
            filled_quantity=Decimal("0.5"),
        )
        assert not o.can_fill(Decimal("1"), Decimal("2350"))

    def test_fill_updates_avg_price(self):
        mgr = self._mgr()
        order = mgr.create_order(
            symbol="XAUUSD",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("2"),
        )
        mgr._transition(order, self.Status.PENDING_NEW)
        mgr._transition(order, self.Status.NEW)
        mgr.active_orders.add(order.id)
        mgr.fill_order(order.id, Decimal("1"), Decimal("2350"))
        mgr.fill_order(order.id, Decimal("1"), Decimal("2360"))
        assert order.avg_fill_price == Decimal("2355")


class TestComplexOrderManager:
    def setup_method(self):
        from execution.oms import ComplexOrderManager, Order, OrderLifecycleManager, OrderStatus

        self.oms = OrderLifecycleManager()
        self.mgr = ComplexOrderManager(self.oms)
        self.Order = Order
        self.Status = OrderStatus

    def test_create_oco(self):
        from decimal import Decimal

        o1 = self.Order(symbol="XAUUSD", side="BUY", quantity=Decimal("1"), price=Decimal("2350"))
        o2 = self.Order(symbol="XAUUSD", side="SELL", quantity=Decimal("1"), price=Decimal("2360"))
        parent_id = self.mgr.create_oco([o1, o2])
        assert parent_id is not None
        assert len(parent_id) > 0

    def test_cancel_siblings_on_fill(self):
        from decimal import Decimal

        o1 = self.Order(
            symbol="XAUUSD",
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("1"),
            price=Decimal("2350"),
        )
        o2 = self.Order(
            symbol="XAUUSD",
            side="SELL",
            order_type="LIMIT",
            quantity=Decimal("1"),
            price=Decimal("2360"),
        )
        self.mgr.create_oco([o1, o2])
        # Retrieve the registered copies from the OMS (create_oco calls create_order)
        registered = list(self.oms.orders.values())
        r1 = next(r for r in registered if r.side == "BUY")
        r2 = next(r for r in registered if r.side == "SELL")
        # Transition both to NEW
        self.oms._transition(r1, self.Status.PENDING_NEW)
        self.oms._transition(r1, self.Status.NEW)
        self.oms.active_orders.add(r1.id)
        self.oms._transition(r2, self.Status.PENDING_NEW)
        self.oms._transition(r2, self.Status.NEW)
        self.oms.active_orders.add(r2.id)
        # Fill r1 → OCO callback should cancel r2
        self.oms.fill_order(r1.id, Decimal("1"), Decimal("2350"))
        assert r2.status == self.Status.PENDING_CANCEL

    def test_create_bracket(self):
        from decimal import Decimal

        entry = self.Order(
            symbol="XAUUSD",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("1"),
        )
        bracket_id = self.mgr.create_bracket(entry, Decimal("2400"), Decimal("2300"))
        assert bracket_id is not None
