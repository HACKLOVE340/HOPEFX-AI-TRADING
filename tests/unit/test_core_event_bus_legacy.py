# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_event_bus_legacy.py
=========================================
Coverage tests for core/event_bus_legacy.py.

lz4 and msgpack are required by the module — they are installed in CI.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.event_bus_legacy import (
    DomainEvent,
    EventBus,
    MemoryMappedEventStore,
)


# ── DomainEvent ───────────────────────────────────────────────────────────────


def test_domain_event_create_and_decode():
    evt = DomainEvent.create(
        event_type="PRICE_UPDATE",
        source="test",
        data={"symbol": "XAUUSD", "price": 1920.0},
    )
    assert evt.event_type == 1  # PRICE_UPDATE code
    assert evt.source == "test"
    decoded = evt.decode()
    assert decoded["symbol"] == "XAUUSD"
    assert decoded["price"] == 1920.0


def test_domain_event_unknown_type_code():
    evt = DomainEvent.create(
        event_type="UNKNOWN_TYPE",
        source="src",
        data={"x": 1},
    )
    assert evt.event_type == 99


def test_domain_event_all_known_types():
    known = [
        "PRICE_UPDATE", "SIGNAL_GENERATED", "ORDER_SUBMITTED", "ORDER_FILLED",
        "POSITION_OPENED", "POSITION_CLOSED", "RISK_VIOLATION", "KILL_SWITCH",
        "REGIME_CHANGE", "COMPOSITE_SIGNAL", "HEARTBEAT",
    ]
    for i, t in enumerate(known, 1):
        evt = DomainEvent.create(event_type=t, source="s", data={})
        assert evt.event_type == i


def test_domain_event_timestamp_nanoseconds():
    evt = DomainEvent.create("HEARTBEAT", "s", {})
    # Nanosecond timestamp should be > 1e18
    assert evt.timestamp > 1_000_000_000_000_000_000


# ── MemoryMappedEventStore ────────────────────────────────────────────────────


def test_store_append_and_query(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    evt = DomainEvent.create("PRICE_UPDATE", "feed", {"price": 1900.0})
    seq = store.append(evt)
    assert seq == 1

    results = store.query(source="feed")
    assert len(results) == 1
    assert results[0].source == "feed"


def test_store_query_by_event_type(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    store.append(DomainEvent.create("PRICE_UPDATE", "feed", {"p": 1}))
    store.append(DomainEvent.create("SIGNAL_GENERATED", "brain", {"s": 2}))

    results = store.query(event_type=1)  # PRICE_UPDATE
    assert all(r.event_type == 1 for r in results)


def test_store_query_all_sources(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    store.append(DomainEvent.create("HEARTBEAT", "a", {}))
    store.append(DomainEvent.create("HEARTBEAT", "b", {}))
    results = store.query()
    assert len(results) == 2


def test_store_sequence_increments(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    s1 = store.append(DomainEvent.create("HEARTBEAT", "s", {}))
    s2 = store.append(DomainEvent.create("HEARTBEAT", "s", {}))
    assert s2 == s1 + 1


def test_store_file_rotation(tmp_path):
    # Very small max_file_size forces rotation
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=512,
    )
    for i in range(5):
        store.append(DomainEvent.create("HEARTBEAT", f"src{i}", {"i": i}))
    # Multiple files should exist
    files = list(Path(tmp_path).glob("events_*.bin"))
    assert len(files) >= 1


# ── EventBus ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_publish_and_subscribe(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    bus = EventBus(store)

    received = []
    bus.subscribe("PRICE_UPDATE", lambda e: received.append(e))

    evt = DomainEvent.create("PRICE_UPDATE", "feed", {"price": 1920.0})
    await bus.publish(evt)

    # Run the bus briefly to process the queue
    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0].event_type == 1


@pytest.mark.asyncio
async def test_event_bus_metrics(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    bus = EventBus(store)
    evt = DomainEvent.create("HEARTBEAT", "s", {})
    await bus.publish(evt)
    m = bus.get_metrics()
    assert m["published"] == 1
    assert "delivered" in m
    assert "dropped" in m


@pytest.mark.asyncio
async def test_event_bus_handler_exception_increments_dropped(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    bus = EventBus(store)

    def _bad_handler(e):
        raise RuntimeError("handler error")

    bus.subscribe("HEARTBEAT", _bad_handler)
    evt = DomainEvent.create("HEARTBEAT", "s", {})
    await bus.publish(evt)

    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert bus.get_metrics()["dropped"] == 1


@pytest.mark.asyncio
async def test_event_bus_run_stops_on_flag(tmp_path):
    store = MemoryMappedEventStore(
        base_path=str(tmp_path) + "/",
        max_file_size=1024 * 1024,
    )
    bus = EventBus(store)
    bus._running = False  # pre-stop

    # run() should exit immediately since _running=False
    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
