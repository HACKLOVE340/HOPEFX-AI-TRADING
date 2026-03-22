"""End-to-end integration tests."""

import pytest
import asyncio
from decimal import Decimal

from hopefx.events.bus import event_bus
from hopefx.events.schemas import TickData, Event, EventType
from hopefx.brain.engine import brain
from hopefx.execution.oms import oms


@pytest.mark.asyncio
async def test_full_trade_lifecycle():
    """Test complete flow: tick -> features -> prediction -> signal -> order -> fill."""
    
    # Initialize components
    await event_bus.start()
    await oms.start()
    await brain.start()

    try:
        # 1. Inject tick
        tick = TickData(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            bid=Decimal("2034.50"),
            ask=Decimal("2034.70"),
            volume=Decimal("100")
        )

        await event_bus.publish(Event(
            type=EventType.TICK,
            payload=tick,
            source="test"
        ))

        # 2. Wait for feature computation
        await asyncio.sleep(0.1)

        # 3. Inject prediction
        from hopefx.events.schemas import Prediction, FeatureVector
        
        prediction = Prediction(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            model_id="test_model",
            model_version="1.0",
            direction="long",
            confidence=0.85,
            feature_vector=FeatureVector(
                symbol="XAUUSD",
                timestamp=datetime.utcnow(),
                features={"rsi_14": 65.0, "trend": 1.0}
            )
        )

        await event_bus.publish(Event(
            type=EventType.PREDICTION,
            payload=prediction,
            source="test"
        ))

        # 4. Wait for signal generation
        await asyncio.sleep(0.1)

        # 5. Verify signal created
        assert len(oms._orders) > 0, "Order should be created"

        # 6. Simulate fill
        from hopefx.events.schemas import OrderFill
        
        fill = OrderFill(
            order_id=list(oms._orders.keys())[0],
            symbol="XAUUSD",
            timestamp=datetime.utcnow().isoformat(),
            side="buy",
            filled_qty=Decimal("0.1"),
            filled_price=Decimal("2034.60"),
            commission=Decimal("3.5"),
            slippage=Decimal("0.01")
        )

        await event_bus.publish(Event(
            type=EventType.ORDER_FILL,
            payload=fill,
            source="test"
        ))

        # 7. Verify position updated
        position = oms.get_position("XAUUSD")
        assert position is not None
        assert position["side"] == "buy"

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
