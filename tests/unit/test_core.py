# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for core components.
"""

import asyncio
import pytest

from core.exceptions import HopeFXError, RiskViolation
from config.settings import Settings
from core.event_bus import EventBus, MemoryMappedEventStore, DomainEvent


@pytest.mark.asyncio
async def test_event_bus(tmp_path):
    """Test event bus publish/subscribe."""
    # Use a small max_file_size (1 MB) to avoid pre-allocating the 1 GB default
    # which exhausts /tmp in CI environments.
    store = MemoryMappedEventStore(
        base_path=str(tmp_path / "events") + "/", max_file_size=1_048_576
    )
    bus = EventBus(store=store)

    received = []

    def handler(event: DomainEvent):
        received.append(event)

    bus.subscribe("PRICE_UPDATE", handler)

    event = DomainEvent.create(
        "PRICE_UPDATE",
        "test",
        {"symbol": "XAUUSD", "bid": 1800.0, "ask": 1800.1},
    )

    # Start the bus, publish, let it process, then stop
    run_task = asyncio.create_task(bus.run())
    await bus.publish(event)
    await asyncio.sleep(0.2)
    bus._running = False
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    data = received[0].decode()
    assert data["symbol"] == "XAUUSD"


def test_settings_validation():
    """Test Settings loads with defaults and env field works."""
    settings = Settings()
    # Default env is development
    assert settings.env in ("development", "staging", "production")
    assert isinstance(settings.debug, bool)


def test_settings_production():
    """Test Settings accepts production env."""
    settings = Settings(env="production", debug=False)
    assert settings.env == "production"
    assert settings.debug is False


def test_exceptions():
    """Test custom exceptions carry structured context."""
    error = RiskViolation(
        message="Test violation",
        rule="max_position",
        limit=100.0,
        actual=150.0,
    )

    assert error.rule == "max_position"
    assert error.limit == 100.0
    assert error.actual == 150.0
    assert isinstance(error, HopeFXError)
