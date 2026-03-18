"""
Unit tests for core components.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from src.core.config import Settings
from src.core.events import Event, EventBus, TickReceived
from src.core.exceptions import HopeFXError, RiskViolation


@pytest.mark.asyncio
async def test_event_bus():
    """Test event bus functionality."""
    bus = EventBus()
    await bus.start()
    
    received = []
    
    async def handler(event):
        received.append(event)
    
    bus.subscribe(TickReceived, handler)
    
    event = Event.create(
        TickReceived(
            symbol="XAUUSD",
            bid=1800.0,
            ask=1800.1,
            volume=100,
            timestamp=datetime.now(timezone.utc)
        ),
        source="test"
    )
    
    await bus.emit(event)
    await asyncio.sleep(0.1)  # Allow processing
    
    assert len(received) == 1
    assert received[0].payload.symbol == "XAUUSD"
    
    await bus.stop()


def test_settings_validation():
    """Test settings validation."""
    settings = Settings(
        environment="production",
        debug=False
    )
    
    assert settings.is_production is True
    
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            debug=True  # Should fail
        )


def test_exceptions():
    """Test custom exceptions."""
    error = RiskViolation(
        message="Test violation",
        rule="max_position",
        limit=100.0,
        actual=150.0
    )
    
    assert error.rule == "max_position"
    assert error.limit == 100.0
    assert error.actual == 150.0
