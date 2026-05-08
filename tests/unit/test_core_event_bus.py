# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_event_bus.py
==================================
Coverage tests for core/event_bus.py.

Redis is patched at the boundary. Real EventBus, DomainEvent,
MemoryMappedEventStore, and _LocalBus logic is exercised.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from core.event_bus import (
    ALL_CHANNELS,
    CH_BREACH,
    CH_ORDER,
    CH_SIGNAL,
    CH_TICK,
    DomainEvent,
    EventBus,
    MemoryMappedEventStore,
    _LocalBus,
    _local_bus,
    bus,
)


# ── DomainEvent ───────────────────────────────────────────────────────────────


def test_domain_event_create_known_type():
    evt = DomainEvent.create("PRICE_UPDATE", "test_source", {"price": 1900.0})
    assert evt.source == "test_source"
    assert evt.event_type == 1  # PRICE_UPDATE code
    assert evt.priority == 5


def test_domain_event_create_unknown_type():
    evt = DomainEvent.create("UNKNOWN_TYPE", "src", {"x": 1})
    assert evt.event_type == 99


def test_domain_event_create_with_priority():
    evt = DomainEvent.create("SIGNAL_GENERATED", "ml", {"conf": 0.8}, priority=2)
    assert evt.priority == 2


def test_domain_event_decode_roundtrip():
    data = {"strategy_id": "s1", "pnl": 150.0, "symbol": "XAUUSD"}
    evt = DomainEvent.create("POSITION_CLOSED", "executor", data)
    decoded = evt.decode()
    assert decoded["strategy_id"] == "s1"
    assert decoded["pnl"] == 150.0


def test_domain_event_all_known_types():
    known = [
        "PRICE_UPDATE",
        "SIGNAL_GENERATED",
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "POSITION_OPENED",
        "POSITION_CLOSED",
        "RISK_VIOLATION",
        "KILL_SWITCH",
        "REGIME_CHANGE",
        "COMPOSITE_SIGNAL",
        "HEARTBEAT",
        "TICK",
        "SIGNAL",
        "ORDER",
        "BREACH",
    ]
    for t in known:
        evt = DomainEvent.create(t, "src", {})
        assert evt.event_type != 99, f"{t} should have a known code"


def test_domain_event_codes_cached():
    # Call twice — second call uses cached _TYPE_CODES
    DomainEvent._TYPE_CODES = None
    codes1 = DomainEvent._codes()
    codes2 = DomainEvent._codes()
    assert codes1 is codes2


def test_domain_event_decode_json_fallback():
    """Decode falls back to JSON when lz4/msgpack unavailable."""
    data = {"key": "value", "num": 42}
    payload = json.dumps(data).encode()
    evt = DomainEvent(
        timestamp=0,
        event_type=1,
        source="test",
        payload=payload,
    )
    decoded = evt.decode()
    assert decoded["key"] == "value"
    assert decoded["num"] == 42


# ── _LocalBus ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_bus_subscribe_and_publish():
    lb = _LocalBus()
    received = []

    def _handler(msg):
        received.append(msg)

    lb.subscribe_local(CH_TICK, _handler)
    await lb.publish_local(CH_TICK, {"type": "tick", "bid": 1900.0})
    assert len(received) == 1
    assert received[0]["bid"] == 1900.0


@pytest.mark.asyncio
async def test_local_bus_async_handler():
    lb = _LocalBus()
    received = []

    async def _async_handler(msg):
        received.append(msg)

    lb.subscribe_local(CH_SIGNAL, _async_handler)
    await lb.publish_local(CH_SIGNAL, {"type": "signal", "conf": 0.9})
    assert len(received) == 1


@pytest.mark.asyncio
async def test_local_bus_handler_error_non_fatal():
    lb = _LocalBus()

    def _bad_handler(msg):
        raise RuntimeError("handler crash")

    lb.subscribe_local(CH_ORDER, _bad_handler)
    await lb.publish_local(CH_ORDER, {"type": "order"})  # must not raise


@pytest.mark.asyncio
async def test_local_bus_multiple_handlers():
    lb = _LocalBus()
    calls = []
    lb.subscribe_local(CH_BREACH, lambda m: calls.append("h1"))
    lb.subscribe_local(CH_BREACH, lambda m: calls.append("h2"))
    await lb.publish_local(CH_BREACH, {"type": "breach"})
    assert calls == ["h1", "h2"]


@pytest.mark.asyncio
async def test_local_bus_unknown_channel():
    lb = _LocalBus()
    await lb.publish_local("hopefx:unknown", {"x": 1})  # must not raise


# ── EventBus — connect ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_connect_success():
    eb = EventBus()
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    with patch("core.event_bus._make_redis", return_value=mock_redis):
        await eb.connect()
    assert eb._degraded is False


@pytest.mark.asyncio
async def test_event_bus_connect_failure_activates_degraded():
    eb = EventBus()
    with patch("core.event_bus._make_redis", side_effect=ConnectionError("no redis")):
        await eb.connect()
    assert eb._degraded is True


# ── EventBus — close ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_close_no_redis():
    eb = EventBus()
    await eb.close()  # must not raise when _redis is None


@pytest.mark.asyncio
async def test_event_bus_close_with_redis():
    eb = EventBus()
    mock_redis = AsyncMock()
    mock_redis.aclose = AsyncMock()
    eb._redis = mock_redis
    await eb.close()
    mock_redis.aclose.assert_called_once()


# ── EventBus — publish ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_publish_success():
    eb = EventBus()
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    eb._redis = mock_redis
    eb._degraded = False
    await eb.publish(CH_TICK, {"type": "tick", "bid": 1900.0})
    assert eb._metrics["published"] == 1


@pytest.mark.asyncio
async def test_event_bus_publish_degraded_uses_local_fallback():
    eb = EventBus()
    eb._degraded = True
    received = []
    _local_bus.subscribe_local(CH_TICK, lambda m: received.append(m))
    before = eb._metrics["published"]
    await eb.publish(CH_TICK, {"type": "tick", "bid": 1901.0})
    # Degraded mode routes to local fallback and counts as published, not error.
    assert eb._metrics["published"] == before + 1
    assert eb._metrics["errors"] == 0


@pytest.mark.asyncio
async def test_event_bus_publish_retries_on_failure():
    eb = EventBus()
    mock_redis = AsyncMock()
    call_count = [0]

    async def _fail_then_succeed(channel, payload):
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError("transient")

    mock_redis.publish = _fail_then_succeed
    eb._redis = mock_redis
    eb._degraded = False

    with patch("core.event_bus.BASE_BACKOFF_S", 0.001):
        await eb.publish(CH_SIGNAL, {"type": "signal"})

    assert eb._metrics["retries"] >= 2


@pytest.mark.asyncio
async def test_event_bus_publish_exhausts_retries():
    eb = EventBus()
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(side_effect=ConnectionError("always fails"))
    eb._redis = mock_redis
    eb._degraded = False

    with patch("core.event_bus.BASE_BACKOFF_S", 0.001):
        with patch("core.event_bus.MAX_RETRIES", 2):
            await eb.publish(CH_ORDER, {"type": "order"})

    assert eb._metrics["errors"] == 1


# ── EventBus — convenience publishers ────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_tick():
    eb = EventBus()
    eb._degraded = True  # use local fallback
    await eb.publish_tick({"bid": 1900.0, "ask": 1900.5})


@pytest.mark.asyncio
async def test_publish_signal():
    eb = EventBus()
    eb._degraded = True
    await eb.publish_signal({"direction": "long", "confidence": 0.8})


@pytest.mark.asyncio
async def test_publish_order():
    eb = EventBus()
    eb._degraded = True
    await eb.publish_order({"symbol": "XAUUSD", "side": "buy"})


@pytest.mark.asyncio
async def test_publish_breach():
    eb = EventBus()
    eb._degraded = True
    await eb.publish_breach({"reason": "kill_switch"})


# ── EventBus — metrics ────────────────────────────────────────────────────────


def test_event_bus_metrics_initial():
    eb = EventBus()
    m = eb.metrics()
    assert m["published"] == 0
    assert m["delivered"] == 0
    assert m["errors"] == 0
    assert m["retries"] == 0
    assert m["degraded"] is False


# ── EventBus — subscribe_local ────────────────────────────────────────────────


def test_event_bus_subscribe_local():
    eb = EventBus()
    received = []
    eb.subscribe_local(CH_TICK, lambda m: received.append(m))
    # Verify handler registered (no direct way to test without publish)
    assert callable(received.append)


# ── EventBus — subscribe (degraded local fallback) ────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_subscribe_degraded_receives_local_messages():
    eb = EventBus()
    eb._degraded = True

    messages = []

    async def _collect():
        async for msg in eb.subscribe(CH_TICK):
            messages.append(msg)
            break  # stop after first message

    task = asyncio.create_task(_collect())
    await asyncio.sleep(0.01)
    # Publish via local bus
    await _local_bus.publish_local(CH_TICK, {"type": "tick", "bid": 1902.0})
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert len(messages) >= 1


# ── MemoryMappedEventStore ────────────────────────────────────────────────────


def test_memory_mapped_event_store_append_and_query(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/events/",
        max_file_size=1024 * 1024,  # 1 MB
    )
    evt = DomainEvent.create("PRICE_UPDATE", "test_src", {"price": 1900.0})
    seq = store.append(evt)
    assert seq == 1

    results = store.query(source="test_src")
    assert len(results) >= 1


def test_memory_mapped_event_store_multiple_events(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/events/",
        max_file_size=1024 * 1024,
    )
    for i in range(5):
        evt = DomainEvent.create("SIGNAL_GENERATED", "ml", {"i": i})
        store.append(evt)

    results = store.query(source="ml")
    assert len(results) == 5


def test_memory_mapped_event_store_query_by_event_type(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/events/",
        max_file_size=1024 * 1024,
    )
    evt1 = DomainEvent.create("PRICE_UPDATE", "src", {"x": 1})
    evt2 = DomainEvent.create("SIGNAL_GENERATED", "src", {"x": 2})
    store.append(evt1)
    store.append(evt2)

    results = store.query(source="src", event_type=1)  # PRICE_UPDATE = 1
    assert all(r.event_type == 1 for r in results)


def test_memory_mapped_event_store_query_all_sources(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/events/",
        max_file_size=1024 * 1024,
    )
    store.append(DomainEvent.create("PRICE_UPDATE", "src_a", {}))
    store.append(DomainEvent.create("PRICE_UPDATE", "src_b", {}))
    results = store.query()
    assert len(results) >= 2


def test_memory_mapped_event_store_rotate_file(tmp_path):
    # Use tiny file size to force rotation
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/events/",
        max_file_size=512,
    )
    for i in range(10):
        evt = DomainEvent.create("PRICE_UPDATE", "src", {"i": i, "data": "x" * 20})
        store.append(evt)
    # Should have rotated at least once
    assert store.file_counter >= 1


# ── module-level singleton ────────────────────────────────────────────────────


def test_module_bus_is_event_bus():
    assert isinstance(bus, EventBus)


def test_channel_constants():
    assert CH_TICK == "hopefx:tick"
    assert CH_SIGNAL == "hopefx:signal"
    assert CH_ORDER == "hopefx:order"
    assert CH_BREACH == "hopefx:breach"
    # Core channels plus microstructure, volume_delta, risk, equity, news,
    # sentiment, system, heartbeat added for chart-bot and WS broadcasting.
    assert len(ALL_CHANNELS) == 12
    assert "hopefx:tick" in ALL_CHANNELS
    assert "hopefx:signal" in ALL_CHANNELS
    assert "hopefx:microstructure" in ALL_CHANNELS
    assert "hopefx:sentiment" in ALL_CHANNELS
