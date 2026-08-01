# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Focused coverage for execution.advanced_orders."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from execution.advanced_orders import (
    UTC,
    AdvancedOrderManager,
    AdvancedOrderState,
    BrokerOrderAdapter,
    FillType,
    OCOOrder,
    StopLimitOrder,
    TrailingStopOrder,
    get_advanced_order_manager,
)


class FakeBroker:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def place_oco_order(self, **_: object) -> dict[str, str]:
        return {"sl_order_id": "sl-1", "tp_order_id": "tp-1"}

    async def place_trailing_stop(self, **_: object) -> dict[str, str]:
        return {"order_id": "trail-1"}

    async def place_stop_limit(self, **_: object) -> dict[str, str]:
        return {"order_id": "stop-1"}

    async def place_order(self, **kwargs: object) -> dict[str, object]:
        return {"status": "filled", **kwargs}

    async def cancel_order(self, broker_order_id: str) -> None:
        self.cancelled.append(broker_order_id)


class FakeEventBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, object]] = []
        self.published: list[tuple[str, dict[str, object]]] = []

    def subscribe_local(self, channel: str, handler: object) -> None:
        self.subscriptions.append((channel, handler))

    async def publish(self, channel: str, event: dict[str, object]) -> None:
        self.published.append((channel, event))

    async def publish_local(self, channel: str, event: dict[str, object]) -> None:
        self.published.append((channel, event))


def _event_bus_module() -> ModuleType:
    module = ModuleType("core.event_bus")
    module.CH_ORDER = "order"
    module.CH_TICK = "tick"
    return module


def _oco_order(side: str = "SELL") -> OCOOrder:
    return OCOOrder(
        order_id="oco-1",
        position_id="pos-1",
        symbol="XAU/USD",
        side=side,
        quantity=1.0,
        stop_loss_price=1900.0,
        take_profit_price=2100.0,
        state=AdvancedOrderState.ACTIVE,
    )


def _trailing_order(side: str = "SELL") -> TrailingStopOrder:
    return TrailingStopOrder(
        order_id="trail-1",
        position_id="pos-1",
        symbol="XAU/USD",
        side=side,
        quantity=1.0,
        trail_distance_pips=50.0,
        state=AdvancedOrderState.ACTIVE,
        activated=True,
        current_stop_price=1999.5 if side == "SELL" else 2000.5,
        highest_price=2000.0 if side == "SELL" else 0.0,
        lowest_price=float("inf") if side == "SELL" else 2000.0,
    )


class TestAdvancedOrderDataclasses:
    def test_oco_to_dict_serializes_fill_metadata(self):
        filled_at = datetime.now(UTC)
        order = _oco_order()
        order.fill_type = FillType.TAKE_PROFIT
        order.fill_price = 2100.5
        order.filled_at = filled_at
        payload = order.to_dict()
        assert payload["type"] == "oco"
        assert payload["fill_type"] == "take_profit"
        assert payload["filled_at"] == filled_at.isoformat()

    def test_trailing_stop_to_dict_normalizes_unset_lowest_price(self):
        payload = _trailing_order("SELL").to_dict()
        assert payload["type"] == "trailing_stop"
        assert payload["lowest_price"] is None

    def test_stop_limit_to_dict_serializes_expiry(self):
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        order = StopLimitOrder(
            order_id="stop-1",
            position_id="pos-1",
            symbol="XAU/USD",
            side="BUY",
            quantity=1.0,
            stop_price=2100.0,
            limit_price=2100.5,
            triggered=True,
            expires_at=expires_at,
        )
        payload = order.to_dict()
        assert payload["type"] == "stop_limit"
        assert payload["triggered"] is True
        assert payload["expires_at"] == expires_at.isoformat()


class TestBrokerOrderAdapter:
    @pytest.mark.asyncio
    async def test_adapter_detects_capabilities_and_forwards_calls(self):
        broker = FakeBroker()
        adapter = BrokerOrderAdapter(broker)
        assert adapter.supports_native_oco is True
        assert adapter.supports_native_trailing_stop is True
        assert adapter.supports_native_stop_limit is True
        assert await adapter.submit_native_oco("XAU/USD", "SELL", 1.0, 1900.0, 2100.0) == ("sl-1", "tp-1")
        assert await adapter.submit_native_trailing_stop("XAU/USD", "SELL", 1.0, 50.0) == "trail-1"
        assert await adapter.submit_native_stop_limit("XAU/USD", "BUY", 1.0, 2100.0, 2100.5) == "stop-1"
        assert await adapter.submit_market_close("XAU/USD", "SELL", 1.0) == {
            "status": "filled",
            "symbol": "XAU/USD",
            "side": "SELL",
            "quantity": 1.0,
            "order_type": "market",
        }
        assert await adapter.cancel_order("broker-1") is True
        assert broker.cancelled == ["broker-1"]

    @pytest.mark.asyncio
    async def test_adapter_handles_missing_broker_methods(self):
        class MinimalBroker:
            pass

        adapter = BrokerOrderAdapter(MinimalBroker())
        assert adapter.supports_native_oco is False
        assert adapter.supports_native_trailing_stop is False
        assert adapter.supports_native_stop_limit is False
        assert await adapter.cancel_order("broker-1") is False
        with pytest.raises(RuntimeError, match="place_order"):
            await adapter.submit_market_close("XAU/USD", "SELL", 1.0)


class TestAdvancedOrderManager:
    @pytest.mark.asyncio
    async def test_start_and_stop_manage_monitor_and_tick_subscription(self, monkeypatch):
        manager = AdvancedOrderManager()
        broker = FakeBroker()
        event_bus = FakeEventBus()
        monkeypatch.setitem(__import__("sys").modules, "core.event_bus", _event_bus_module())
        await manager.start(broker=broker, event_bus=event_bus)
        assert manager.health()["running"] is True
        assert event_bus.subscriptions[0][0] == "tick"
        manager._on_tick({"symbol": "XAU/USD", "mid": "2350.5"})
        assert manager.health()["tracked_symbols"] == ["XAU/USD"]
        await manager.stop()
        assert manager.health()["running"] is False

    @pytest.mark.asyncio
    async def test_submit_oco_uses_native_broker_when_available(self):
        manager = AdvancedOrderManager()
        await manager.start(broker=FakeBroker())
        order_id = await manager.submit_oco("pos-1", "XAU/USD", "SELL", 1.0, 1900.0, 2100.0)
        order = manager.get_order(order_id)
        assert order is not None
        assert order["state"] == "active"
        assert order["native_broker_support"] is True
        assert order["broker_sl_order_id"] == "sl-1"
        await manager.stop()

    @pytest.mark.asyncio
    async def test_submit_oco_falls_back_when_native_submission_fails(self):
        manager = AdvancedOrderManager()
        manager._adapter = AsyncMock()
        manager._adapter.supports_native_oco = True
        manager._adapter.submit_native_oco.side_effect = RuntimeError("boom")
        order_id = await manager.submit_oco("pos-1", "XAU/USD", "SELL", 1.0, 1900.0, 2100.0)
        order = manager.get_order(order_id)
        assert order is not None
        assert order["state"] == "active"
        assert order["native_broker_support"] is False

    @pytest.mark.asyncio
    async def test_submit_trailing_stop_initializes_from_current_price_for_both_sides(self):
        manager = AdvancedOrderManager()
        manager._latest_prices["XAU/USD"] = 2350.0
        sell_id = await manager.submit_trailing_stop("pos-1", "XAU/USD", "SELL", 1.0, 50.0)
        buy_id = await manager.submit_trailing_stop("pos-2", "XAU/USD", "BUY", 1.0, 50.0)
        sell_order = manager.get_order(sell_id)
        buy_order = manager.get_order(buy_id)
        assert sell_order["highest_price"] == 2350.0
        assert sell_order["current_stop_price"] == pytest.approx(2349.5)
        assert buy_order["lowest_price"] == 2350.0
        assert buy_order["current_stop_price"] == pytest.approx(2350.5)

    @pytest.mark.asyncio
    async def test_submit_stop_limit_uses_native_broker(self):
        manager = AdvancedOrderManager()
        await manager.start(broker=FakeBroker())
        order_id = await manager.submit_stop_limit("pos-1", "XAU/USD", "BUY", 1.0, 2100.0, 2100.5)
        order = manager.get_order(order_id)
        assert order is not None
        assert order["native_broker_support"] is True
        assert order["broker_order_id"] == "stop-1"
        await manager.stop()

    @pytest.mark.asyncio
    async def test_cancel_order_cancels_native_order_legs(self):
        manager = AdvancedOrderManager()
        broker = FakeBroker()
        await manager.start(broker=broker)
        order_id = await manager.submit_oco("pos-1", "XAU/USD", "SELL", 1.0, 1900.0, 2100.0)
        assert await manager.cancel_order(order_id) is True
        assert broker.cancelled == ["sl-1", "tp-1"]
        assert manager.get_order(order_id)["state"] == "cancelled"
        await manager.stop()

    @pytest.mark.asyncio
    async def test_check_oco_orders_triggers_stop_loss_and_take_profit(self):
        manager = AdvancedOrderManager()
        stop_order = _oco_order("SELL")
        take_profit_order = _oco_order("BUY")
        take_profit_order.order_id = "oco-2"
        take_profit_order.stop_loss_price = 2100.0
        take_profit_order.take_profit_price = 1900.0
        manager._oco_orders = {stop_order.order_id: stop_order, take_profit_order.order_id: take_profit_order}
        manager._latest_prices = {"XAU/USD": 1899.0}
        manager._execute_oco_fill = AsyncMock()
        await manager._check_oco_orders()
        manager._execute_oco_fill.assert_any_await(stop_order, 1899.0, FillType.STOP_LOSS)
        manager._execute_oco_fill.assert_any_await(take_profit_order, 1899.0, FillType.TAKE_PROFIT)

    @pytest.mark.asyncio
    async def test_check_trailing_orders_activates_updates_and_triggers(self):
        manager = AdvancedOrderManager()
        order = TrailingStopOrder(
            order_id="trail-1",
            position_id="pos-1",
            symbol="XAU/USD",
            side="SELL",
            quantity=1.0,
            trail_distance_pips=50.0,
            activation_price=2000.0,
            state=AdvancedOrderState.ACTIVE,
        )
        manager._trailing_orders = {order.order_id: order}
        manager._execute_trailing_fill = AsyncMock()

        manager._latest_prices["XAU/USD"] = 2001.0
        await manager._check_trailing_orders()
        assert order.activated is True
        assert order.current_stop_price == pytest.approx(2000.5)

        manager._latest_prices["XAU/USD"] = 2005.0
        await manager._check_trailing_orders()
        assert order.highest_price == 2005.0
        assert order.current_stop_price == pytest.approx(2004.5)

        manager._latest_prices["XAU/USD"] = 2004.0
        await manager._check_trailing_orders()
        manager._execute_trailing_fill.assert_awaited_once_with(order, 2004.0)

    @pytest.mark.asyncio
    async def test_check_trailing_orders_handles_short_position_branch(self):
        manager = AdvancedOrderManager()
        order = _trailing_order("BUY")
        manager._trailing_orders = {order.order_id: order}
        manager._execute_trailing_fill = AsyncMock()

        manager._latest_prices["XAU/USD"] = 1995.0
        await manager._check_trailing_orders()
        assert order.lowest_price == 1995.0
        assert order.current_stop_price == pytest.approx(1995.5)

        manager._latest_prices["XAU/USD"] = 1996.0
        await manager._check_trailing_orders()
        manager._execute_trailing_fill.assert_awaited_once_with(order, 1996.0)

    @pytest.mark.asyncio
    async def test_check_stop_limit_orders_handles_expiry_and_trigger(self):
        manager = AdvancedOrderManager()
        expired = StopLimitOrder(
            order_id="expired",
            position_id="pos-1",
            symbol="XAU/USD",
            side="BUY",
            quantity=1.0,
            stop_price=2100.0,
            limit_price=2100.5,
            state=AdvancedOrderState.ACTIVE,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        triggered = StopLimitOrder(
            order_id="triggered",
            position_id="pos-2",
            symbol="XAU/USD",
            side="BUY",
            quantity=1.0,
            stop_price=2100.0,
            limit_price=2100.5,
            state=AdvancedOrderState.ACTIVE,
        )
        manager._stop_limit_orders = {expired.order_id: expired, triggered.order_id: triggered}
        manager._latest_prices["XAU/USD"] = 2100.25
        manager._execute_stop_limit = AsyncMock()
        await manager._check_stop_limit_orders()
        assert expired.state == AdvancedOrderState.EXPIRED
        assert triggered.triggered is True
        manager._execute_stop_limit.assert_awaited_once_with(triggered, 2100.25)

    @pytest.mark.asyncio
    async def test_execute_fill_paths_publish_events_and_track_health(self, monkeypatch):
        manager = AdvancedOrderManager()
        manager._adapter = BrokerOrderAdapter(FakeBroker())
        manager._event_bus = FakeEventBus()
        monkeypatch.setitem(__import__("sys").modules, "core.event_bus", _event_bus_module())

        oco_order = _oco_order()
        await manager._execute_oco_fill(oco_order, 1899.5, FillType.STOP_LOSS)
        assert oco_order.state == AdvancedOrderState.FILLED
        assert manager._event_bus.published[-1][1]["fill_type"] == "stop_loss"

        trailing_order = _trailing_order()
        await manager._execute_trailing_fill(trailing_order, 1999.0)
        assert trailing_order.state == AdvancedOrderState.FILLED

        stop_limit_order = StopLimitOrder(
            order_id="stop-1",
            position_id="pos-3",
            symbol="XAU/USD",
            side="BUY",
            quantity=1.0,
            stop_price=2100.0,
            limit_price=2100.5,
            state=AdvancedOrderState.ACTIVE,
        )
        await manager._execute_stop_limit(stop_limit_order, 2100.25)
        assert stop_limit_order.state == AdvancedOrderState.FILLED

    @pytest.mark.asyncio
    async def test_execute_oco_fill_marks_order_failed_after_retries(self, monkeypatch):
        manager = AdvancedOrderManager()
        failing_adapter = AsyncMock()
        failing_adapter.submit_market_close.side_effect = RuntimeError("fail")
        manager._adapter = failing_adapter
        monkeypatch.setattr("execution.advanced_orders._MAX_RETRIES", 1)
        monkeypatch.setattr("execution.advanced_orders._RETRY_DELAY_S", 0.0)
        order = _oco_order()
        await manager._execute_oco_fill(order, 1899.0, FillType.STOP_LOSS)
        assert order.state == AdvancedOrderState.FAILED

    def test_query_helpers_and_singleton_return_expected_state(self):
        manager = AdvancedOrderManager()
        active = _oco_order()
        cancelled = _oco_order()
        cancelled.order_id = "oco-2"
        cancelled.position_id = "pos-2"
        cancelled.state = AdvancedOrderState.CANCELLED
        manager._oco_orders = {active.order_id: active, cancelled.order_id: cancelled}
        assert manager.get_order(active.order_id)["order_id"] == active.order_id
        assert manager.get_active_orders() == [active.to_dict()]
        assert manager.get_active_orders("pos-2") == []
        assert get_advanced_order_manager() is get_advanced_order_manager()
