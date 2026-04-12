# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comprehensive tests for execution/oms.py."""
from __future__ import annotations
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from execution.oms import ComplexOrderManager, Order, OrderLifecycleManager, OrderStatus, TimeInForce

def _oms(broker=None):
    return OrderLifecycleManager(broker=broker)

def _new_order(symbol="XAUUSD", side="BUY", qty="1.0", order_type="LIMIT", price="2000.0"):
    return Order(symbol=symbol, side=side, order_type=order_type,
                 quantity=Decimal(qty), price=Decimal(price) if price else None)

def _active_order(oms, symbol="XAUUSD", side="BUY", qty="1.0", order_type="LIMIT", price="2000.0"):
    o = _new_order(symbol=symbol, side=side, qty=qty, order_type=order_type, price=price)
    oms.orders[o.id] = o
    o.status = OrderStatus.NEW
    oms.active_orders.add(o.id)
    return o

class TestOrderDataclass:
    def test_remaining_quantity_unfilled(self):
        o = _new_order(qty="2.0")
        assert o.remaining_quantity == Decimal("2.0")
    def test_remaining_quantity_partial(self):
        o = _new_order(qty="2.0"); o.filled_quantity = Decimal("0.5")
        assert o.remaining_quantity == Decimal("1.5")
    def test_is_active_new(self):
        o = _new_order(); o.status = OrderStatus.NEW
        assert o.is_active is True
    def test_is_active_partially_filled(self):
        o = _new_order(); o.status = OrderStatus.PARTIALLY_FILLED
        assert o.is_active is True
    def test_is_active_pending_new(self):
        o = _new_order(); o.status = OrderStatus.PENDING_NEW
        assert o.is_active is True
    def test_is_active_pending_cancel(self):
        o = _new_order(); o.status = OrderStatus.PENDING_CANCEL
        assert o.is_active is True
    def test_is_active_filled_false(self):
        o = _new_order(); o.status = OrderStatus.FILLED
        assert o.is_active is False
    def test_is_active_cancelled_false(self):
        o = _new_order(); o.status = OrderStatus.CANCELLED
        assert o.is_active is False
    def test_is_active_rejected_false(self):
        o = _new_order(); o.status = OrderStatus.REJECTED
        assert o.is_active is False
    def test_can_fill_market_new(self):
        o = _new_order(order_type="MARKET"); o.status = OrderStatus.NEW
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is True
    def test_can_fill_limit_buy_price_ok(self):
        o = _new_order(order_type="LIMIT", price="2010.0"); o.status = OrderStatus.NEW
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is True
    def test_can_fill_limit_buy_price_too_high(self):
        o = _new_order(order_type="LIMIT", price="1990.0"); o.status = OrderStatus.NEW
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is False
    def test_can_fill_limit_sell_price_ok(self):
        o = _new_order(side="SELL", order_type="LIMIT", price="1990.0"); o.status = OrderStatus.NEW
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is True
    def test_can_fill_limit_sell_price_too_low(self):
        o = _new_order(side="SELL", order_type="LIMIT", price="2010.0"); o.status = OrderStatus.NEW
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is False
    def test_can_fill_exceeds_remaining(self):
        o = _new_order(qty="1.0", order_type="MARKET"); o.status = OrderStatus.NEW
        assert o.can_fill(Decimal("2.0"), Decimal("2000.0")) is False
    def test_can_fill_wrong_status(self):
        o = _new_order(order_type="MARKET"); o.status = OrderStatus.FILLED
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is False
    def test_can_fill_partially_filled_status(self):
        o = _new_order(qty="2.0", order_type="MARKET"); o.status = OrderStatus.PARTIALLY_FILLED
        o.filled_quantity = Decimal("1.0")
        assert o.can_fill(Decimal("1.0"), Decimal("2000.0")) is True
    def test_default_time_in_force_gtc(self):
        assert _new_order().time_in_force == TimeInForce.GTC
    def test_default_status_created(self):
        assert _new_order().status == OrderStatus.CREATED
    def test_child_orders_default_empty(self):
        assert _new_order().child_orders == []
    def test_tags_default_empty(self):
        assert _new_order().tags == []
    def test_metadata_default_empty(self):
        assert _new_order().metadata == {}

class TestOLMCreateOrder:
    def test_create_order_stored(self):
        oms = _oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        assert o.id in oms.orders
    def test_create_order_status_created(self):
        oms = _oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        assert o.status == OrderStatus.CREATED
    def test_create_order_history_entry_after_transition(self):
        oms = _oms()
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        # Manually do a valid transition to generate history
        oms._transition(o, OrderStatus.PENDING_NEW)
        assert any(e["to_status"] == "PENDING_NEW" for e in oms.order_history)

class TestOLMSubmitOrder:
    def test_submit_nonexistent_returns_false(self):
        oms = _oms()
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            assert oms.submit_order("ghost_id") is False
    def test_submit_kill_switch_active_blocks(self):
        oms = _oms()
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = True
            MockKS.return_value.reason = "halt"
            o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
            assert oms.submit_order(o.id) is False
    def test_submit_kill_switch_raises_blocks(self):
        oms = _oms()
        with patch("kill_switch.KillSwitch", side_effect=RuntimeError("ks error")):
            o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
            assert oms.submit_order(o.id) is False
    def test_submit_valid_order_transitions_to_pending_new(self):
        oms = _oms()
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            with patch("asyncio.create_task"):
                o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
                result = oms.submit_order(o.id)
        assert result is True
        assert o.status == OrderStatus.PENDING_NEW

    @pytest.mark.asyncio
    async def test_async_submit_no_broker_transitions_to_new(self):
        oms = _oms(broker=None)
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        oms._transition(o, OrderStatus.PENDING_NEW)
        await oms._async_submit(o)
        assert o.status == OrderStatus.NEW
        assert o.id in oms.active_orders

    @pytest.mark.asyncio
    async def test_async_submit_broker_accepted(self):
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value={"status": "accepted"})
        oms = _oms(broker=broker)
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        oms._transition(o, OrderStatus.PENDING_NEW)
        await oms._async_submit(o)
        assert o.status == OrderStatus.NEW

    @pytest.mark.asyncio
    async def test_async_submit_broker_rejected(self):
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value={"status": "rejected", "reason": "MARGIN"})
        oms = _oms(broker=broker)
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        oms._transition(o, OrderStatus.PENDING_NEW)
        await oms._async_submit(o)
        assert o.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_async_submit_broker_raises_rejected(self):
        broker = MagicMock()
        broker.place_order = AsyncMock(side_effect=ConnectionError("timeout"))
        oms = _oms(broker=broker)
        o = oms.create_order(symbol="XAUUSD", side="BUY", order_type="MARKET", quantity=Decimal("1.0"))
        oms._transition(o, OrderStatus.PENDING_NEW)
        await oms._async_submit(o)
        assert o.status == OrderStatus.REJECTED

class TestOLMFillOrder:
    def test_fill_nonexistent_returns_false(self):
        assert _oms().fill_order("ghost", Decimal("1.0"), Decimal("2000.0")) is False
    def test_fill_full_transitions_to_filled(self):
        oms = _oms(); o = _active_order(oms)
        assert oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0")) is True
        assert o.status == OrderStatus.FILLED
    def test_fill_partial_transitions_to_partially_filled(self):
        oms = _oms(); o = _active_order(oms, qty="2.0")
        oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0"))
        assert o.status == OrderStatus.PARTIALLY_FILLED
    def test_fill_updates_filled_quantity(self):
        oms = _oms(); o = _active_order(oms, qty="2.0")
        oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0"))
        assert o.filled_quantity == Decimal("1.0")
    def test_fill_updates_avg_price_first_fill(self):
        oms = _oms(); o = _active_order(oms)
        oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0"))
        assert o.avg_fill_price == Decimal("2000.0")
    def test_fill_updates_avg_price_second_fill(self):
        oms = _oms(); o = _active_order(oms, qty="2.0", order_type="MARKET", price="2000.0")
        o.order_type = "MARKET"  # ensure no price check
        oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0"))
        oms.fill_order(o.id, Decimal("1.0"), Decimal("2100.0"))
        assert o.avg_fill_price == Decimal("2050.0")
    def test_fill_removes_from_active_on_complete(self):
        oms = _oms(); o = _active_order(oms)
        oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0"))
        assert o.id not in oms.active_orders
    def test_fill_invalid_price_returns_false(self):
        oms = _oms(); o = _active_order(oms, order_type="LIMIT", price="1990.0")
        assert oms.fill_order(o.id, Decimal("1.0"), Decimal("2000.0")) is False

class TestOLMCancelOrder:
    def test_cancel_nonexistent_returns_false(self):
        assert _oms().cancel_order("ghost") is False
    def test_cancel_active_order_succeeds(self):
        oms = _oms(); o = _active_order(oms)
        assert oms.cancel_order(o.id) is True
        assert o.status == OrderStatus.PENDING_CANCEL
    def test_cancel_filled_order_returns_false(self):
        oms = _oms(); o = _new_order(); o.status = OrderStatus.FILLED; oms.orders[o.id] = o
        assert oms.cancel_order(o.id) is False
    def test_cancel_rejected_order_returns_false(self):
        oms = _oms(); o = _new_order(); o.status = OrderStatus.REJECTED; oms.orders[o.id] = o
        assert oms.cancel_order(o.id) is False

class TestOLMExpireOrders:
    def test_expire_gtd_order_past_expiry(self):
        from datetime import datetime, timezone, timedelta
        oms = _oms(); o = _active_order(oms)
        o.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        oms.expire_orders()
        assert o.status == OrderStatus.EXPIRED
        assert o.id not in oms.active_orders
    def test_expire_does_not_expire_future_order(self):
        from datetime import datetime, timezone, timedelta
        oms = _oms(); o = _active_order(oms)
        o.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        oms.expire_orders()
        assert o.status == OrderStatus.NEW
    def test_expire_no_expiry_date_unchanged(self):
        oms = _oms(); o = _active_order(oms); o.expires_at = None
        oms.expire_orders()
        assert o.status == OrderStatus.NEW

class TestOLMStateMachine:
    def test_invalid_transition_returns_false(self):
        oms = _oms(); o = _new_order(); o.status = OrderStatus.FILLED; oms.orders[o.id] = o
        assert oms._transition(o, OrderStatus.NEW) is False
    def test_valid_transition_returns_true(self):
        oms = _oms(); o = _new_order(); oms.orders[o.id] = o
        assert oms._transition(o, OrderStatus.PENDING_NEW) is True
    def test_transition_logs_history(self):
        oms = _oms(); o = _new_order(); oms.orders[o.id] = o
        oms._transition(o, OrderStatus.PENDING_NEW)
        assert any(e["to_status"] == "PENDING_NEW" for e in oms.order_history)
    def test_callback_called_on_transition(self):
        oms = _oms(); calls = []
        oms.register_callback(OrderStatus.PENDING_NEW, lambda o, ctx: calls.append(o))
        o = _new_order(); oms.orders[o.id] = o
        oms._transition(o, OrderStatus.PENDING_NEW)
        assert len(calls) == 1
    def test_callback_error_does_not_propagate(self):
        oms = _oms()
        oms.register_callback(OrderStatus.PENDING_NEW, lambda o, ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        o = _new_order(); oms.orders[o.id] = o
        oms._transition(o, OrderStatus.PENDING_NEW)  # must not raise
    def test_filled_terminal_no_further_transitions(self):
        oms = _oms(); o = _new_order(); o.status = OrderStatus.FILLED; oms.orders[o.id] = o
        assert oms._transition(o, OrderStatus.CANCELLED) is False
    def test_cancelled_terminal_no_further_transitions(self):
        oms = _oms(); o = _new_order(); o.status = OrderStatus.CANCELLED; oms.orders[o.id] = o
        assert oms._transition(o, OrderStatus.NEW) is False
    def test_rejected_terminal_no_further_transitions(self):
        oms = _oms(); o = _new_order(); o.status = OrderStatus.REJECTED; oms.orders[o.id] = o
        assert oms._transition(o, OrderStatus.NEW) is False

class TestOLMOrderBook:
    def test_order_book_empty_symbol(self):
        book = _oms().get_order_book("XAUUSD")
        assert book["symbol"] == "XAUUSD"
        assert book["bids"] == [] and book["asks"] == []
    def test_order_book_buy_in_bids(self):
        oms = _oms(); _active_order(oms, side="BUY", price="2000.0")
        assert len(oms.get_order_book("XAUUSD")["bids"]) == 1
    def test_order_book_sell_in_asks(self):
        oms = _oms(); _active_order(oms, side="SELL", price="2010.0")
        assert len(oms.get_order_book("XAUUSD")["asks"]) == 1
    def test_order_book_filters_by_symbol(self):
        oms = _oms()
        _active_order(oms, symbol="XAUUSD", side="BUY", price="2000.0")
        _active_order(oms, symbol="EURUSD", side="BUY", price="1.08")
        assert len(oms.get_order_book("XAUUSD")["bids"]) == 1
    def test_order_book_bids_sorted_descending(self):
        oms = _oms()
        _active_order(oms, side="BUY", price="1990.0")
        _active_order(oms, side="BUY", price="2000.0")
        prices = [b["price"] for b in oms.get_order_book("XAUUSD")["bids"]]
        assert prices == sorted(prices, reverse=True)
    def test_order_book_asks_sorted_ascending(self):
        oms = _oms()
        _active_order(oms, side="SELL", price="2010.0")
        _active_order(oms, side="SELL", price="2005.0")
        prices = [a["price"] for a in oms.get_order_book("XAUUSD")["asks"]]
        assert prices == sorted(prices)
    def test_order_book_has_timestamp(self):
        assert "timestamp" in _oms().get_order_book("XAUUSD")

class TestComplexOrderManagerOCO:
    def test_create_oco_returns_parent_id(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        o1 = _new_order(price="2000.0"); o2 = _new_order(price="1950.0")
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            pid = com.create_oco([o1, o2])
        assert isinstance(pid, str) and len(pid) > 0
    def test_create_oco_tags_orders(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        o1 = _new_order(price="2000.0"); o2 = _new_order(price="1950.0")
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            com.create_oco([o1, o2])
        assert "OCO" in o1.tags and "OCO" in o2.tags
    def test_cancel_siblings_on_fill(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        o1 = _new_order(price="2000.0"); o2 = _new_order(price="1950.0")
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            pid = com.create_oco([o1, o2])
        # Get the actual stored orders (create_oco stores copies)
        stored = list(oms.orders.values())
        assert len(stored) == 2
        # Make both active so cancel can work
        for s in stored:
            s.status = OrderStatus.NEW
            oms.active_orders.add(s.id)
        # Simulate first order fill — cancel siblings
        filled = stored[0]
        com._cancel_siblings(filled)
        sibling = stored[1]
        assert sibling.status == OrderStatus.PENDING_CANCEL
    def test_cancel_siblings_no_parent_id_noop(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        o = _new_order(); o.parent_order_id = None
        com._cancel_siblings(o)  # must not raise

class TestComplexOrderManagerBracket:
    def test_create_bracket_returns_id(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        entry = _new_order(order_type="MARKET", price=None)
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            bid = com.create_bracket(entry, Decimal("2100.0"), Decimal("1900.0"))
        assert isinstance(bid, str)
    def test_create_bracket_tags_entry(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        entry = _new_order(order_type="MARKET", price=None)
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            com.create_bracket(entry, Decimal("2100.0"), Decimal("1900.0"))
        assert "BRACKET_ENTRY" in entry.tags
    def test_place_bracket_exits_creates_orders(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        entry = _new_order(order_type="MARKET", price=None)
        entry.filled_quantity = Decimal("1.0"); entry.side = "BUY"; entry.symbol = "XAUUSD"
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            com._place_bracket_exits(entry, Decimal("2100.0"), Decimal("1900.0"), "b1")
        tags = set(t for o in oms.orders.values() for t in o.tags)
        assert "BRACKET_TP" in tags or "OCO" in tags

class TestComplexOrderManagerIceberg:
    def test_create_iceberg_returns_parent_id(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            with patch("asyncio.create_task"):
                pid = com.create_iceberg(Decimal("5.0"), Decimal("1.0"), "XAUUSD", "BUY", Decimal("2000.0"))
        assert isinstance(pid, str)
    def test_create_iceberg_parent_tagged(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            with patch("asyncio.create_task"):
                pid = com.create_iceberg(Decimal("5.0"), Decimal("1.0"), "XAUUSD", "BUY", Decimal("2000.0"))
        assert "ICEBERG_PARENT" in oms.orders[pid].tags
    def test_reveal_slice_nonexistent_parent_noop(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        com._reveal_slice("nonexistent", Decimal("1.0"))  # must not raise
    def test_reveal_slice_zero_remaining_noop(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        parent = _new_order(qty="1.0"); parent.metadata = {"revealed": 1.0}; oms.orders[parent.id] = parent
        n = len(oms.orders)
        com._reveal_slice(parent.id, Decimal("1.0"))
        assert len(oms.orders) == n
    def test_check_reveal_next_fully_filled_reveals(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        parent = _new_order(qty="5.0")
        parent.metadata = {"display_size": 1.0, "revealed": 1.0}
        parent.symbol = "XAUUSD"; parent.side = "BUY"; parent.price = Decimal("2000.0")
        oms.orders[parent.id] = parent
        sl = _new_order(qty="1.0"); sl.filled_quantity = Decimal("1.0")
        with patch("kill_switch.KillSwitch") as MockKS:
            MockKS.return_value.is_active.return_value = False
            with patch("asyncio.create_task"):
                com._check_reveal_next(sl, parent.id, Decimal("1.0"))
        assert len(oms.orders) >= 2
    def test_check_reveal_next_partial_fill_no_reveal(self):
        oms = _oms(); com = ComplexOrderManager(oms)
        parent = _new_order(qty="5.0"); parent.metadata = {"display_size": 1.0, "revealed": 1.0}
        oms.orders[parent.id] = parent
        sl = _new_order(qty="1.0"); sl.filled_quantity = Decimal("0.5")
        n = len(oms.orders)
        com._check_reveal_next(sl, parent.id, Decimal("1.0"))
        assert len(oms.orders) == n
