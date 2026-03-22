"""Chaos engineering tests."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_broker_failover():
    """Test failover when primary broker fails."""
    from hopefx.execution.router import SmartRouter
    from hopefx.execution.brokers.base import BaseBroker
    
    router = SmartRouter()
    
    # Create mock brokers
    primary = MagicMock(spec=BaseBroker)
    primary.connected = True
    primary.place_order = MagicMock(side_effect=Exception("Network error"))
    
    backup = MagicMock(spec=BaseBroker)
    backup.connected = True
    backup.place_order = MagicMock(return_value=OrderResult(
        order_id="backup_123",
        status=OrderStatus.FILLED,
        filled_qty=Decimal("1.0"),
        filled_price=Decimal("2000"),
        remaining_qty=Decimal("0"),
        commission=Decimal("0"),
        slippage=Decimal("0"),
        timestamp="",
        raw_response=None
    ))
    
    router.register_broker("primary", primary)
    router.register_broker("backup", backup)
    
    # Route should failover to backup
    order = Order(symbol="XAUUSD", side="buy", quantity=Decimal("1.0"), order_type=OrderType.MARKET)
    result = await router.route_order(order)
    
    assert result.order_id == "backup_123"
    backup.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_ml_model_failure_graceful_degradation():
    """Test system continues when ML model fails."""
    from hopefx.ml.pipeline import ml_pipeline
    
    # Corrupt model
    ml_pipeline.models = {}
    
    # System should still process ticks (rule-based fallback)
    tick = TickData(
        symbol="XAUUSD",
        timestamp=datetime.utcnow(),
        bid=Decimal("2000"),
        ask=Decimal("2000.10"),
        volume=Decimal("100")
    )
    
    # Should not raise exception
    await event_bus.publish(Event(type=EventType.TICK, payload=tick, source="test"))
