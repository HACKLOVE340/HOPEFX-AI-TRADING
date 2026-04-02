# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
core/event_bus.py
=================
Redis-backed async pub/sub event bus.

Channels
--------
  hopefx:tick      — raw market tick (bid/ask/timestamp)
  hopefx:signal    — ML/RL trade signal (direction, confidence)
  hopefx:order     — order request / fill confirmation
  hopefx:breach    — risk breach / kill event

Design
------
- All messages are JSON-serialised dicts with a mandatory 'type' key.
- publish() retries up to MAX_RETRIES times with exponential back-off.
- subscribe() yields decoded dicts; reconnects automatically on Redis drop.
- A lightweight in-process fallback (asyncio.Queue) activates when Redis
  is unreachable so the rest of the system keeps running in degraded mode.
- Legacy in-memory MemoryMappedEventStore and DomainEvent are preserved
  below for backward compatibility with existing callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mmap
import os
import struct
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any
from collections.abc import AsyncIterator, Callable

import redis.asyncio as aioredis  # redis-py >= 4.2

logger = logging.getLogger(__name__)

# ── channel names ─────────────────────────────────────────────────────────────
CH_TICK = "hopefx:tick"
CH_SIGNAL = "hopefx:signal"
CH_ORDER = "hopefx:order"
CH_BREACH = "hopefx:breach"

ALL_CHANNELS = (CH_TICK, CH_SIGNAL, CH_ORDER, CH_BREACH)

# ── retry / back-off config ───────────────────────────────────────────────────
MAX_RETRIES: int = 5
BASE_BACKOFF_S: float = 0.25  # first retry after 250 ms
MAX_BACKOFF_S: float = 30.0  # cap at 30 s


# ─────────────────────────────────────────────────────────────────────────────
# Legacy domain model (kept for backward compatibility)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DomainEvent:
    """Compact event envelope used by the legacy in-memory store."""

    timestamp: int
    event_type: int
    source: str
    payload: bytes
    priority: int = 5

    _TYPE_CODES: dict[str, int] = None  # populated lazily

    @classmethod
    def _codes(cls) -> dict[str, int]:
        if cls._TYPE_CODES is None:
            cls._TYPE_CODES = {
                "PRICE_UPDATE": 1,
                "SIGNAL_GENERATED": 2,
                "ORDER_SUBMITTED": 3,
                "ORDER_FILLED": 4,
                "POSITION_OPENED": 5,
                "POSITION_CLOSED": 6,
                "RISK_VIOLATION": 7,
                "KILL_SWITCH": 8,
                "REGIME_CHANGE": 9,
                "COMPOSITE_SIGNAL": 10,
                "HEARTBEAT": 11,
                # New event types aligned with Redis channels
                "TICK": 12,
                "SIGNAL": 13,
                "ORDER": 14,
                "BREACH": 15,
            }
        return cls._TYPE_CODES

    @classmethod
    def create(cls, event_type: str, source: str, data: dict, priority: int = 5) -> DomainEvent:
        try:
            import lz4.frame
            import msgpack

            packed = msgpack.packb(data, use_bin_type=True)
            payload = lz4.frame.compress(packed)
        except ImportError:
            payload = json.dumps(data).encode()
        return cls(
            timestamp=int(datetime.now(UTC).timestamp() * 1e9),
            event_type=cls._codes().get(event_type, 99),
            source=source,
            payload=payload,
            priority=priority,
        )

    def decode(self) -> dict:
        try:
            import lz4.frame
            import msgpack

            return msgpack.unpackb(lz4.frame.decompress(self.payload), raw=False)
        except ImportError:
            return json.loads(self.payload.decode())


class MemoryMappedEventStore:
    """Persistent event store backed by memory-mapped files (legacy)."""

    def __init__(self, base_path: str = "data/events/", max_file_size: int = 1_073_741_824) -> None:
        self.base_path = base_path
        self.max_file_size = max_file_size
        self.current_file = None
        self.current_mmap = None
        self.current_offset = 0
        self.file_counter = 0
        self._lock = threading.RLock()
        self._index: dict[str, list] = defaultdict(list)
        self._sequence = 0
        os.makedirs(base_path, exist_ok=True)
        self._rotate_file()

    def _rotate_file(self) -> None:
        if self.current_mmap:
            self.current_mmap.flush()
            self.current_mmap.close()
            self.current_file.close()
        filename = f"{self.base_path}events_{self.file_counter:06d}.bin"
        self.file_counter += 1
        with open(filename, "wb") as f:
            f.write(b"\x00" * self.max_file_size)
        self.current_file = open(filename, "r+b")
        self.current_mmap = mmap.mmap(self.current_file.fileno(), self.max_file_size)
        self.current_offset = 0

    def append(self, event: DomainEvent) -> int:
        with self._lock:
            self._sequence += 1
            src_bytes = event.source.encode()
            header = struct.pack(">QQH", self._sequence, event.timestamp, event.event_type)
            header += struct.pack("B", len(src_bytes)) + src_bytes
            header += struct.pack(">I", len(event.payload))
            record = header + event.payload
            if self.current_offset + len(record) > self.max_file_size:
                self._rotate_file()
            self.current_mmap[self.current_offset : self.current_offset + len(record)] = record
            self.current_offset += len(record)
            self._index[event.source].append((self.file_counter - 1, self.current_offset - len(record)))
            return self._sequence

    def query(
        self,
        source: str | None = None,
        event_type: int | None = None,
        limit: int = 1000,
    ) -> list:
        results = []
        sources = [source] if source else list(self._index.keys())
        for src in sources:
            for file_num, offset in self._index[src][-limit:]:
                event = self._read_at(file_num, offset)
                if event and (not event_type or event.event_type == event_type):
                    results.append(event)
        return sorted(results, key=lambda e: e.timestamp)[:limit]

    def _read_at(self, file_num: int, offset: int) -> DomainEvent | None:
        filename = f"{self.base_path}events_{file_num:06d}.bin"
        if not os.path.exists(filename):
            return None
        with open(filename, "rb") as f:
            f.seek(offset)
            header = f.read(19)
            if len(header) < 19:
                return None
            _, ts, evt_type = struct.unpack(">QQH", header[:18])
            src_len = header[18]
            src = f.read(src_len).decode()
            payload_len = struct.unpack(">I", f.read(4))[0]
            payload = f.read(payload_len)
            return DomainEvent(timestamp=ts, event_type=evt_type, source=src, payload=payload)


# ─────────────────────────────────────────────────────────────────────────────
# In-process fallback bus (active when Redis is unreachable)
# ─────────────────────────────────────────────────────────────────────────────


class _LocalBus:
    """
    asyncio.Queue-based fallback for when Redis is unavailable.

    Handlers registered via subscribe_local() receive every published message
    on their channel without going through Redis.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {ch: [] for ch in ALL_CHANNELS}

    def subscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        self._handlers.setdefault(channel, []).append(handler)

    async def publish_local(self, channel: str, message: dict) -> None:
        for handler in self._handlers.get(channel, []):
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("LocalBus handler error on %s: %s", channel, exc)


_local_bus = _LocalBus()


# ─────────────────────────────────────────────────────────────────────────────
# Redis connection factory
# ─────────────────────────────────────────────────────────────────────────────


def _make_redis() -> aioredis.Redis:
    """
    Create a Redis client — Sentinel-aware.

    If REDIS_SENTINEL_HOSTS is set, connects via Sentinel for HA.
    Falls back to REDIS_URL for single-node / dev environments.
    """
    sentinel_hosts_str = os.environ.get("REDIS_SENTINEL_HOSTS", "").strip()
    password = os.environ.get("REDIS_PASSWORD", "") or None
    master_name = os.environ.get("REDIS_SENTINEL_MASTER", "hopefx-master")

    if sentinel_hosts_str:
        try:
            from redis.asyncio.sentinel import Sentinel as _Sentinel

            hosts = []
            for _entry in sentinel_hosts_str.split(","):
                entry = _entry.strip()
                if ":" in entry:
                    h, p = entry.rsplit(":", 1)
                    hosts.append((h.strip(), int(p.strip())))
                else:
                    hosts.append((entry, 26379))

            sentinel = _Sentinel(
                hosts,
                sentinel_kwargs={"password": password, "socket_timeout": 2.0},
                password=password,
                socket_timeout=5,
                decode_responses=True,
            )
            logger.info("EventBus: using Redis Sentinel (master=%s)", master_name)
            return sentinel.master_for(master_name)
        except Exception as exc:
            logger.warning("EventBus: Sentinel init failed (%s) — falling back to REDIS_URL", exc)

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return aioredis.from_url(url, decode_responses=True, socket_timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# EventBus — Redis pub/sub with retry/backoff + local fallback
# ─────────────────────────────────────────────────────────────────────────────


class EventBus:
    """
    Async Redis pub/sub event bus.

    Quick start
    -----------
    bus = EventBus()
    await bus.connect()

    await bus.publish(CH_TICK, {"type": "tick", "bid": 1923.5, "ask": 1923.7})

    async for msg in bus.subscribe(CH_SIGNAL):
        process(msg)

    await bus.close()
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._degraded: bool = False
        self._metrics: dict[str, int] = {
            "published": 0,
            "delivered": 0,
            "errors": 0,
            "retries": 0,
        }

    # ── connection ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open Redis connection; activate local fallback on failure."""
        try:
            self._redis = _make_redis()
            await self._redis.ping()
            self._degraded = False
            logger.info("EventBus connected to Redis.")
        except Exception as exc:
            logger.warning("EventBus: Redis unavailable (%s) — local fallback active.", exc)
            self._degraded = True

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        if self._redis:
            await self._redis.aclose()
            logger.info("EventBus Redis connection closed.")

    # ── publish ───────────────────────────────────────────────────────────────

    async def publish(self, channel: str, message: dict) -> None:
        """
        Publish a dict to a Redis channel.

        Injects the current OpenTelemetry trace context (W3C traceparent/
        tracestate) into the message payload so consumers can create child
        spans linked to the publisher's trace.

        Retries MAX_RETRIES times with exponential back-off before falling
        back to the local in-process bus.
        """
        # Inject trace context for cross-service propagation
        try:
            from tracing.setup import inject_trace_context

            trace_headers = inject_trace_context()
            if trace_headers:
                message = {**message, "_trace": trace_headers}
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        payload = json.dumps(message)
        attempt = 0
        backoff = BASE_BACKOFF_S

        while attempt < MAX_RETRIES:
            try:
                if self._degraded or self._redis is None:
                    raise ConnectionError("Redis degraded")
                await self._redis.publish(channel, payload)
                self._metrics["published"] += 1
                return
            except Exception as exc:
                attempt += 1
                self._metrics["retries"] += 1
                logger.warning(
                    "EventBus publish attempt %d/%d failed on %s: %s",
                    attempt,
                    MAX_RETRIES,
                    channel,
                    exc,
                )
                if attempt >= MAX_RETRIES:
                    break
                await asyncio.sleep(min(backoff, MAX_BACKOFF_S))
                backoff *= 2  # exponential back-off

        # Exhausted retries — route through local fallback
        self._metrics["errors"] += 1
        logger.error("EventBus: all retries exhausted for %s — using local fallback.", channel)
        await _local_bus.publish_local(channel, message)

    # ── subscribe ─────────────────────────────────────────────────────────────

    async def subscribe(self, *channels: str) -> AsyncIterator[dict]:
        """
        Async generator yielding decoded dicts from the given channels.

        Reconnects automatically when the Redis connection drops.
        Switches to local fallback when Redis is permanently unavailable.
        """
        if self._degraded:
            # Local fallback: feed a queue from _local_bus handlers
            queue: asyncio.Queue[dict] = asyncio.Queue()

            async def _enqueue(msg: dict) -> None:
                await queue.put(msg)

            for ch in channels:
                _local_bus.subscribe_local(ch, _enqueue)

            while True:
                msg = await queue.get()
                self._metrics["delivered"] += 1
                yield msg
            return  # unreachable; satisfies type checker

        # Redis path with auto-reconnect
        while True:
            pubsub = None
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(*channels)
                logger.info("EventBus subscribed to channels: %s", channels)

                async for raw in pubsub.listen():
                    if raw["type"] != "message":
                        continue
                    try:
                        msg = json.loads(raw["data"])
                        # Restore trace context from publisher so this consumer's
                        # spans appear as children in the same distributed trace.
                        try:
                            from tracing.setup import extract_trace_context

                            trace_carrier = msg.pop("_trace", {})
                            if trace_carrier:
                                msg["_trace_context"] = extract_trace_context(trace_carrier)
                        except Exception as _exc:
                            logger.debug("Suppressed exception: %s", _exc)
                        self._metrics["delivered"] += 1
                        yield msg
                    except json.JSONDecodeError as exc:
                        logger.warning("EventBus: bad JSON on %s: %s", raw.get("channel"), exc)

            except asyncio.CancelledError:
                if pubsub:
                    await pubsub.unsubscribe()
                return
            except Exception as exc:
                self._metrics["errors"] += 1
                logger.error("EventBus subscribe error: %s — reconnecting in 5 s", exc)
                await asyncio.sleep(5)
                try:
                    self._redis = _make_redis()
                    await self._redis.ping()
                    logger.info("EventBus reconnected to Redis.")
                except Exception:  # nosec B110 — Redis reconnect resilience
                    self._degraded = True
                    logger.error("EventBus: Redis reconnect failed — switching to local fallback.")
                    return

    # ── local subscription (in-process handlers) ──────────────────────────────

    def subscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Register a handler for local fallback delivery on a channel."""
        _local_bus.subscribe_local(channel, handler)

    # ── convenience publishers ────────────────────────────────────────────────

    async def publish_tick(self, data: dict) -> None:
        await self.publish(CH_TICK, {"type": "tick", **data})

    async def publish_signal(self, data: dict) -> None:
        await self.publish(CH_SIGNAL, {"type": "signal", **data})

    async def publish_order(self, data: dict) -> None:
        await self.publish(CH_ORDER, {"type": "order", **data})

    async def publish_breach(self, data: dict) -> None:
        await self.publish(CH_BREACH, {"type": "breach", **data})

    def metrics(self) -> dict:
        return {**self._metrics, "degraded": self._degraded}


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton — imported by all sub-systems
# ─────────────────────────────────────────────────────────────────────────────

bus: EventBus = EventBus()
