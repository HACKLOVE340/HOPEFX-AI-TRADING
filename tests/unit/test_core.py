"""
Unit tests for core components.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from core.exceptions import HopeFXError
# Settings, EventBus, TickReceived, RiskViolation — redirect to root equivalents
try:
    from config import Settings  # type: ignore[import]
except ImportError:
    Settings = None  # type: ignore[assignment,misc]
try:
    from core.event_bus import EventBus  # type: ignore[import]
    TickReceived = None  # type: ignore[assignment]
    Event = None  # type: ignore[assignment]
except ImportError:
    EventBus = None  # type: ignore[assignment,misc]
    TickReceived = None  # type: ignore[assignment]
    Event = None  # type: ignore[assignment]
try:
    from core.exceptions import RiskViolation  # type: ignore[import]
except ImportError:
    RiskViolation = None  # type: ignore[assignment,misc]


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
