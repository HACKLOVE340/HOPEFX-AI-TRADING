# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
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
    """Test EventBus local-fallback pub/sub (no Redis required).

    The current EventBus uses Redis pub/sub with an in-process fallback when
    Redis is unavailable.  In CI Redis is not running, so we exercise the
    local-fallback path: subscribe_local() + publish() routes through
    _local_bus when Redis is unreachable.
    """
    from core.event_bus import CH_TICK

    bus = EventBus()
    # Force degraded mode so publish() routes through the local fallback
    # without attempting Redis (which is not available in CI).
    bus._degraded = True

    received: list = []

    def handler(msg: dict) -> None:
        received.append(msg)

    bus.subscribe_local(CH_TICK, handler)

    await bus.publish(CH_TICK, {"type": "tick", "symbol": "XAUUSD", "bid": 1800.0, "ask": 1800.1})

    # Local fallback is synchronous — no sleep needed, but yield once to let
    # any pending coroutines complete.
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0]["symbol"] == "XAUUSD"
    assert received[0]["bid"] == 1800.0


@pytest.mark.asyncio
async def test_memory_mapped_event_store(tmp_path):
    """Test MemoryMappedEventStore append and query."""
    store = MemoryMappedEventStore(base_path=str(tmp_path / "events") + "/", max_file_size=1_048_576)

    event = DomainEvent.create(
        "PRICE_UPDATE",
        "test",
        {"symbol": "XAUUSD", "bid": 1800.0, "ask": 1800.1},
    )
    seq = store.append(event)
    assert seq == 1

    results = store.query(source="test")
    assert len(results) == 1
    data = results[0].decode()
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
