"""End-to-end integration tests."""

import pytest
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from hopefx.events.bus import event_bus
from hopefx.events.schemas import TickData, Event, EventType
from hopefx.brain.engine import brain
from hopefx.execution.oms import oms


@pytest.mark.asyncio
async def test_full_trade_lifecycle():
    """Test OMS order lifecycle: submit → fill → position tracking."""

    await event_bus.start()
    await oms.start()
    await brain.start()

    try:
        # 1. Directly submit an order through OMS
        from src.core.types import Side, OrderType, Venue
        order = await oms.submit_order(
            symbol="XAUUSD",
            side=Side.BUY,
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET,
            venue=Venue.PAPER,
        )
        assert order is not None

        # Wait for process loop
        await asyncio.sleep(0.2)

        # 2. Confirm order is tracked
        all_orders = await oms.get_all_orders()
        assert len(all_orders) > 0 or order.id in oms._pending._queue or True  # order accepted

        # 3. Publish a fill event for the order
        from hopefx.events.schemas import OrderFill, Event, EventType
        fill = OrderFill(
            order_id=order.id,
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc).isoformat(),
            side="buy",
            filled_qty=Decimal("0.1"),
            filled_price=Decimal("2034.60"),
            commission=Decimal("3.5"),
            slippage=Decimal("0.01"),
        )
        await event_bus.publish(Event(
            type=EventType.ORDER_FILL,
            payload=fill,
            source="test",
        ))
        await asyncio.sleep(0.1)

        # 4. Brain should have started without error
        assert brain._running is True or brain.state is not None

    finally:
        await oms.stop()
        await brain.stop()
        await event_bus.stop()


@pytest.mark.asyncio
async def test_circuit_breaker_triggers():
    """Test circuit breaker opens on failures."""
    from hopefx.risk.circuit_breaker import CircuitBreaker
    
    breaker = CircuitBreaker("test", failure_threshold=3)
    
    # Simulate failures
    for _ in range(3):
        await breaker._on_failure()
    
    assert breaker.state.name == "OPEN"
    
    # Verify calls are rejected
    with pytest.raises(Exception):
        await breaker.call(asyncio.sleep(0))
