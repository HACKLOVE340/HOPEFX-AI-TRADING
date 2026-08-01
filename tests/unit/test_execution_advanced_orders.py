from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from execution.advanced_orders import (
    AdvancedOrderManager,
    AdvancedOrderState,
    BrokerOrderAdapter,
    FillType,
    OCOOrder,
    StopLimitOrder,
    TrailingStopOrder,
    get_advanced_order_manager,
)

UTC = timezone.utc


class FakeBroker:
    def __init__(self, fail_market_close_times: int = 0) -> None:
        self.cancelled: list[str] = []
        self.fail_market_close_times = fail_market_close_times
        self.market_close_calls = 0

    async def place_oco_order(self, **_: object) -> dict[str, str]:
        return {"sl_order_id": "sl-1", "tp_order_id": "tp-1"}

    async def place_trailing_stop(self, **_: object) -> dict[str, str]:
        return {"order_id": "trail-1"}

    async def place_stop_limit(self, **_: object) -> dict[str, str]:
        return {"order_id": "stop-1"}

    async def place_order(self, **kwargs: object) -> dict[str, object]:
        self.market_close_calls += 1
        if self.market_close_calls <= self.fail_market_close_times:
            raise RuntimeError("broker close failed")
        return {"status": "ok", **kwargs}

    async def cancel_order(self, broker_order_id: str) -> None:
        self.cancelled.append(broker_order_id)


class LocalEventBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, object]] = []
        self.events: list[tuple[str, dict[str, object]]] = []

    def subscribe_local(self, channel: str, handler: object) -> None:
        self.subscriptions.append((channel, handler))

    async def publish(self, channel: str, event: dict[str, object]) -> None:
        self.events.append((channel, event))


class PublishLocalEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def publish_local(self, channel: str, event: dict[str, object]) -> None:
        self.events.append((channel, event))


def test_order_models_to_dict_include_runtime_fields() -> None:
    filled_at = datetime.now(UTC)

    oco = OCOOrder(
        order_id="oco-1",
        position_id="pos-1",
        symbol="XAU/USD",
        side="SELL",
        quantity=1.0,
        stop_loss_price=3300.0,
        take_profit_price=3350.0,
        state=AdvancedOrderState.FILLED,
        broker_sl_order_id="sl-1",
        broker_tp_order_id="tp-1",
        fill_type=FillType.TAKE_PROFIT,
        fill_price=3350.0,
        filled_at=filled_at,
        native_broker_support=True,
    )
    trailing = TrailingStopOrder(
        order_id="trail-1",
        position_id="pos-2",
        symbol="XAU/USD",
        side="BUY",
        quantity=2.0,
        trail_distance_pips=50.0,
        current_stop_price=3310.0,
        highest_price=3320.0,
        lowest_price=3290.0,
        state=AdvancedOrderState.ACTIVE,
        broker_order_id="trail-broker-1",
        filled_at=filled_at,
        activated=True,
    )
    stop_limit = StopLimitOrder(
        order_id="stop-1",
        position_id="pos-3",
        symbol="XAU/USD",
        side="BUY",
        quantity=3.0,
        stop_price=3330.0,
        limit_price=3335.0,
        state=AdvancedOrderState.ACTIVE,
        triggered=True,
        broker_order_id="stop-broker-1",
        filled_at=filled_at,
        expires_at=filled_at + timedelta(minutes=5),
    )

    assert oco.to_dict()["fill_type"] == FillType.TAKE_PROFIT.value
    assert trailing.to_dict()["activated"] is True
    assert stop_limit.to_dict()["triggered"] is True


@pytest.mark.asyncio
async def test_broker_order_adapter_detects_capabilities_and_delegates() -> None:
    broker = FakeBroker()
    adapter = BrokerOrderAdapter(broker)

    assert adapter.supports_native_oco is True
    assert adapter.supports_native_trailing_stop is True
    assert adapter.supports_native_stop_limit is True
    assert await adapter.submit_native_oco("XAU/USD", "SELL", 1.0, 3300.0, 3350.0) == ("sl-1", "tp-1")
    assert await adapter.submit_native_trailing_stop("XAU/USD", "SELL", 1.0, 50.0) == "trail-1"
    assert await adapter.submit_native_stop_limit("XAU/USD", "BUY", 1.0, 3330.0, 3335.0) == "stop-1"
    assert (await adapter.submit_market_close("XAU/USD", "BUY", 1.0))["order_type"] == "market"
    assert await adapter.cancel_order("broker-order-1") is True
    assert broker.cancelled == ["broker-order-1"]
    assert await BrokerOrderAdapter(None).cancel_order("missing") is False


@pytest.mark.asyncio
async def test_manager_start_submit_query_and_stop_without_native_support() -> None:
    manager = AdvancedOrderManager()
    event_bus = LocalEventBus()

    await manager.start(event_bus=event_bus)
    manager._on_tick({"symbol": "XAU/USD", "mid": 3333.5})

    oco_id = await manager.submit_oco("pos-1", "XAU/USD", "SELL", 1.0, 3300.0, 3350.0)
    trailing_id = await manager.submit_trailing_stop("pos-2", "XAU/USD", "SELL", 1.0, 50.0)
    stop_limit_id = await manager.submit_stop_limit("pos-3", "XAU/USD", "BUY", 1.0, 3340.0, 3345.0)

    oco_order = manager.get_order(oco_id)
    trailing_order = manager.get_order(trailing_id)
    stop_limit_order = manager.get_order(stop_limit_id)
    health = manager.health()

    assert event_bus.subscriptions
    assert oco_order is not None and oco_order["state"] == AdvancedOrderState.ACTIVE.value
    assert trailing_order is not None and trailing_order["current_stop_price"] == pytest.approx(3333.0)
    assert stop_limit_order is not None and stop_limit_order["state"] == AdvancedOrderState.ACTIVE.value
    assert len(manager.get_active_orders()) == 3
    assert len(manager.get_active_orders("pos-2")) == 1
    assert health["tracked_symbols"] == ["XAU/USD"]
    assert health["native_oco"] is False

    await manager.stop()
    assert manager.health()["running"] is False


@pytest.mark.asyncio
async def test_cancel_order_cancels_native_broker_orders() -> None:
    broker = FakeBroker()
    manager = AdvancedOrderManager()
    manager._adapter = BrokerOrderAdapter(broker)

    oco_id = await manager.submit_oco("pos-1", "XAU/USD", "SELL", 1.0, 3300.0, 3350.0)
    trailing_id = await manager.submit_trailing_stop("pos-2", "XAU/USD", "SELL", 1.0, 50.0)
    stop_limit_id = await manager.submit_stop_limit("pos-3", "XAU/USD", "BUY", 1.0, 3340.0, 3345.0)

    assert await manager.cancel_order(oco_id) is True
    assert await manager.cancel_order(trailing_id) is True
    assert await manager.cancel_order(stop_limit_id) is True
    assert await manager.cancel_order("unknown-order") is False
    assert broker.cancelled == ["sl-1", "tp-1", "trail-1", "stop-1"]


@pytest.mark.asyncio
async def test_oco_monitor_executes_stop_loss_and_take_profit_paths() -> None:
    manager = AdvancedOrderManager()
    manager._adapter = BrokerOrderAdapter(FakeBroker())
    manager._event_bus = LocalEventBus()

    stop_loss_order = OCOOrder(
        order_id="oco-stop",
        position_id="pos-stop",
        symbol="XAU/USD",
        side="SELL",
        quantity=1.0,
        stop_loss_price=3300.0,
        take_profit_price=3360.0,
        state=AdvancedOrderState.ACTIVE,
    )
    take_profit_order = OCOOrder(
        order_id="oco-profit",
        position_id="pos-profit",
        symbol="XAG/USD",
        side="BUY",
        quantity=1.0,
        stop_loss_price=25.0,
        take_profit_price=20.0,
        state=AdvancedOrderState.ACTIVE,
    )
    manager._oco_orders = {
        stop_loss_order.order_id: stop_loss_order,
        take_profit_order.order_id: take_profit_order,
    }
    manager._latest_prices = {"XAU/USD": 3299.5, "XAG/USD": 19.9}

    await manager._check_oco_orders()

    assert stop_loss_order.state == AdvancedOrderState.FILLED
    assert stop_loss_order.fill_type == FillType.STOP_LOSS
    assert stop_loss_order.slippage == pytest.approx(0.5)
    assert take_profit_order.state == AdvancedOrderState.FILLED
    assert take_profit_order.fill_type == FillType.TAKE_PROFIT
    assert len(manager._event_bus.events) == 2


@pytest.mark.asyncio
async def test_trailing_monitor_activates_updates_and_fills_orders() -> None:
    manager = AdvancedOrderManager()
    manager._adapter = BrokerOrderAdapter(FakeBroker())
    manager._event_bus = PublishLocalEventBus()

    sell_order = TrailingStopOrder(
        order_id="trail-sell",
        position_id="pos-sell",
        symbol="XAU/USD",
        side="SELL",
        quantity=1.0,
        trail_distance_pips=50.0,
        activation_price=3330.0,
        state=AdvancedOrderState.ACTIVE,
    )
    buy_order = TrailingStopOrder(
        order_id="trail-buy",
        position_id="pos-buy",
        symbol="XAG/USD",
        side="BUY",
        quantity=1.0,
        trail_distance_pips=20.0,
        state=AdvancedOrderState.ACTIVE,
        activated=True,
        lowest_price=24.0,
        current_stop_price=24.2,
    )
    manager._trailing_orders = {sell_order.order_id: sell_order, buy_order.order_id: buy_order}

    manager._latest_prices = {"XAU/USD": 3331.0, "XAG/USD": 23.8}
    await manager._check_trailing_orders()
    assert sell_order.activated is True
    assert sell_order.current_stop_price == pytest.approx(3330.5)
    assert buy_order.current_stop_price == pytest.approx(24.0)

    manager._latest_prices = {"XAU/USD": 3340.0, "XAG/USD": 24.1}
    await manager._check_trailing_orders()
    assert sell_order.highest_price == 3340.0
    assert sell_order.current_stop_price == pytest.approx(3339.5)
    assert buy_order.state == AdvancedOrderState.FILLED

    manager._latest_prices = {"XAU/USD": 3339.4}
    await manager._check_trailing_orders()
    assert sell_order.state == AdvancedOrderState.FILLED
    assert len(manager._event_bus.events) == 2


@pytest.mark.asyncio
async def test_stop_limit_monitor_expires_and_fills_triggered_orders() -> None:
    manager = AdvancedOrderManager()
    manager._adapter = BrokerOrderAdapter(FakeBroker())
    manager._event_bus = LocalEventBus()

    expired_order = StopLimitOrder(
        order_id="stop-expired",
        position_id="pos-expired",
        symbol="XAU/USD",
        side="BUY",
        quantity=1.0,
        stop_price=3330.0,
        limit_price=3335.0,
        state=AdvancedOrderState.ACTIVE,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    fillable_order = StopLimitOrder(
        order_id="stop-fill",
        position_id="pos-fill",
        symbol="XAG/USD",
        side="BUY",
        quantity=1.0,
        stop_price=24.5,
        limit_price=24.8,
        state=AdvancedOrderState.ACTIVE,
    )
    waiting_order = StopLimitOrder(
        order_id="stop-wait",
        position_id="pos-wait",
        symbol="EUR/USD",
        side="SELL",
        quantity=1.0,
        stop_price=1.08,
        limit_price=1.09,
        state=AdvancedOrderState.ACTIVE,
    )
    manager._stop_limit_orders = {
        expired_order.order_id: expired_order,
        fillable_order.order_id: fillable_order,
        waiting_order.order_id: waiting_order,
    }
    manager._latest_prices = {"XAG/USD": 24.6, "EUR/USD": 1.07}

    await manager._check_stop_limit_orders()

    assert expired_order.state == AdvancedOrderState.EXPIRED
    assert fillable_order.triggered is True
    assert fillable_order.state == AdvancedOrderState.FILLED
    assert waiting_order.triggered is True
    assert waiting_order.state == AdvancedOrderState.ACTIVE
    assert len(manager._event_bus.events) == 1


@pytest.mark.asyncio
async def test_execute_paths_mark_orders_failed_after_retry_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    import execution.advanced_orders as advanced_orders

    monkeypatch.setattr(advanced_orders, "_RETRY_DELAY_S", 0.0)

    failing_adapter = BrokerOrderAdapter(FakeBroker(fail_market_close_times=advanced_orders._MAX_RETRIES))
    manager = AdvancedOrderManager()
    manager._adapter = failing_adapter

    oco_order = OCOOrder(
        order_id="oco-fail",
        position_id="pos-1",
        symbol="XAU/USD",
        side="SELL",
        quantity=1.0,
        stop_loss_price=3300.0,
        take_profit_price=3350.0,
        state=AdvancedOrderState.ACTIVE,
    )
    trailing_order = TrailingStopOrder(
        order_id="trail-fail",
        position_id="pos-2",
        symbol="XAU/USD",
        side="SELL",
        quantity=1.0,
        trail_distance_pips=50.0,
        state=AdvancedOrderState.ACTIVE,
    )
    stop_limit_order = StopLimitOrder(
        order_id="stop-fail",
        position_id="pos-3",
        symbol="XAU/USD",
        side="BUY",
        quantity=1.0,
        stop_price=3330.0,
        limit_price=3340.0,
        state=AdvancedOrderState.ACTIVE,
    )

    await manager._execute_oco_fill(oco_order, 3299.0, FillType.STOP_LOSS)
    manager._adapter = BrokerOrderAdapter(FakeBroker(fail_market_close_times=advanced_orders._MAX_RETRIES))
    await manager._execute_trailing_fill(trailing_order, 3299.0)
    manager._adapter = BrokerOrderAdapter(FakeBroker(fail_market_close_times=advanced_orders._MAX_RETRIES))
    await manager._execute_stop_limit(stop_limit_order, 3335.0)

    assert oco_order.state == AdvancedOrderState.FAILED
    assert trailing_order.state == AdvancedOrderState.FAILED
    assert stop_limit_order.state == AdvancedOrderState.FAILED


def test_get_advanced_order_manager_returns_singleton() -> None:
    first = get_advanced_order_manager()
    second = get_advanced_order_manager()
    assert first is second
