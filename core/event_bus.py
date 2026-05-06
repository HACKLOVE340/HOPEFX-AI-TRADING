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
import contextlib
import json
import logging
import mmap
import os
import struct
import threading
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

try:
    import redis.asyncio as aioredis  # redis-py >= 4.2  # pylint: disable=no-name-in-module
    import redis.exceptions as _redis_exc

    _REDIS_ASYNCIO_AVAILABLE = True
except (ImportError, AttributeError):
    aioredis = None  # type: ignore[assignment]
    _redis_exc = None  # type: ignore[assignment]
    _REDIS_ASYNCIO_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── channel names ─────────────────────────────────────────────────────────────
# Core trading channels
CH_TICK          = "hopefx:tick"           # raw market tick (bid/ask/timestamp)
CH_SIGNAL        = "hopefx:signal"         # ML/RL trade signal (direction, confidence)
CH_ORDER         = "hopefx:order"          # order request / fill confirmation
CH_BREACH        = "hopefx:breach"         # risk breach / kill event

# Market microstructure channels (ws_live chart-bot)
CH_MICROSTRUCTURE = "hopefx:microstructure"  # L2 order book snapshot
CH_VOLUME_DELTA   = "hopefx:volume_delta"    # cumulative delta bar

# Risk & equity channels
CH_RISK_UPDATE   = "hopefx:risk_update"    # risk engine snapshot
CH_EQUITY_UPDATE = "hopefx:equity_update"  # account equity snapshot

# News & sentiment channels
CH_NEWS_ITEM     = "hopefx:news_item"      # single news article
CH_SENTIMENT     = "hopefx:sentiment"      # sentiment signal + recent articles

# System / admin channels
CH_SYSTEM        = "hopefx:system"         # system-level events (halt, maintenance)
CH_HEARTBEAT     = "hopefx:heartbeat"      # liveness heartbeat

# Convenience groupings
MARKET_CHANNELS = (CH_TICK, CH_MICROSTRUCTURE, CH_VOLUME_DELTA)
TRADING_CHANNELS = (CH_SIGNAL, CH_ORDER, CH_BREACH)
ACCOUNT_CHANNELS = (CH_RISK_UPDATE, CH_EQUITY_UPDATE)
INFO_CHANNELS    = (CH_NEWS_ITEM, CH_SENTIMENT)
SYSTEM_CHANNELS  = (CH_SYSTEM, CH_HEARTBEAT)

ALL_CHANNELS = (
    CH_TICK,
    CH_SIGNAL,
    CH_ORDER,
    CH_BREACH,
    CH_MICROSTRUCTURE,
    CH_VOLUME_DELTA,
    CH_RISK_UPDATE,
    CH_EQUITY_UPDATE,
    CH_NEWS_ITEM,
    CH_SENTIMENT,
    CH_SYSTEM,
    CH_HEARTBEAT,
)

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
        except Exception:
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
        Path(base_path).mkdir(parents=True, exist_ok=True)
        self._rotate_file()

    def _rotate_file(self) -> None:
        if self.current_mmap:
            self.current_mmap.flush()
            self.current_mmap.close()
            self.current_file.close()
        filename = f"{self.base_path}events_{self.file_counter:06d}.bin"
        self.file_counter += 1
        with Path(filename).open("wb") as f:
            f.write(b"\x00" * self.max_file_size)
        self.current_file = Path(filename).open("r+b")  # noqa: SIM115 — kept open for mmap lifetime
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
        if not Path(filename).exists():
            return None
        with Path(filename).open("rb") as f:
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
        # Pre-populate all known channels so callers can subscribe before
        # the first publish without triggering a KeyError.
        self._handlers: dict[str, list[Callable]] = {ch: [] for ch in ALL_CHANNELS}

    def subscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        self._handlers.setdefault(channel, []).append(handler)

    def unsubscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Remove a previously registered handler.

        Called by subscribe() on cleanup so handlers don't accumulate across
        repeated subscribe() calls, which would cause duplicate delivery and
        unbounded memory growth.
        """
        handlers = self._handlers.get(channel, [])
        try:
            handlers.remove(handler)
        except ValueError:
            # Handler not in list — idempotent unsubscribe is intentional  # nosec B110
            logger.debug("unsubscribe_local: handler not found for channel %s (already removed)", channel)

    async def publish_local(self, channel: str, message: dict) -> None:
        for handler in list(self._handlers.get(channel, [])):
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
            from redis.asyncio.sentinel import Sentinel as _Sentinel  # pylint: disable=no-name-in-module

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

    # Inject REDIS_PASSWORD into the URL when it is not already embedded.
    # from_url() only picks up credentials that are part of the URL string;
    # a standalone REDIS_PASSWORD env var is ignored on the standard path
    # (unlike the Sentinel path above which passes password= explicitly).
    # We only inject when the URL has no userinfo component to avoid
    # overwriting credentials that were intentionally embedded in REDIS_URL.
    if password and "@" not in url.split("://", 1)[-1]:
        scheme, rest = url.split("://", 1)
        url = f"{scheme}://:{password}@{rest}"

    # socket_timeout=None: pub/sub connections must not time out on idle channels.
    # socket_connect_timeout=5: fail fast if Redis is unreachable at connect time.
    return aioredis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=None,
    )


def _make_redis_pubsub() -> aioredis.Redis:
    """Create a dedicated Redis client for pub/sub subscriptions.

    Identical to _make_redis() — kept as a separate factory so callers can
    be replaced independently if pubsub-specific tuning is needed later.
    socket_timeout=None is intentional: listen() must block indefinitely.
    """
    return _make_redis()


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
        """Open Redis connection; activate local fallback on failure.

        Safe to call multiple times — subsequent calls while already connected
        are no-ops. If already in degraded mode, re-attempts the connection
        and only logs if the state changes.

        Closes the previous connection before creating a new one to prevent
        connection leaks on repeated reconnect attempts.
        """
        if self._redis is not None and not self._degraded:
            # Already connected and healthy — skip redundant connect attempt.
            return
        # Close the stale connection before creating a new one.
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None
        try:
            self._redis = _make_redis()
            await self._redis.ping()
            if self._degraded:
                logger.info("EventBus reconnected to Redis — exiting local fallback mode.")
            else:
                logger.info("EventBus connected to Redis.")
            self._degraded = False
        except Exception as exc:
            if not self._degraded:
                # Log the warning only on the first failure, not on every
                # repeated connect() call while Redis remains unavailable.
                logger.warning(
                    "EventBus: Redis unavailable (%s) — local fallback active.",
                    exc,
                )
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
        # NOTE: The wire format is JSON over Redis pub/sub.  For ultra-low-latency
        # paths (sub-millisecond, co-located with CME) consider upgrading to a
        # binary protocol such as MessagePack (already used in DomainEvent above)
        # or FlatBuffers/SBE, which can reduce serialisation overhead ~10×.
        # That optimisation is tracked as a future improvement.

        # Fast-path: if already in degraded mode skip Redis entirely and go
        # straight to the local fallback.  This prevents the log from being
        # flooded with "attempt N/5 failed" lines when Redis is persistently
        # unavailable — the degraded state is already logged at connect time.
        # Do NOT increment errors here — routing to local fallback in degraded
        # mode is expected behaviour, not an error condition.
        if self._degraded or self._redis is None:
            self._metrics["published"] += 1
            logger.debug("EventBus: Redis degraded — routing %s to local fallback.", channel)
            await _local_bus.publish_local(channel, message)
            return

        attempt = 0
        backoff = BASE_BACKOFF_S

        while attempt < MAX_RETRIES:
            try:
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

        # Exhausted retries — mark degraded so future publishes skip Redis
        # immediately, then route through local fallback.
        self._degraded = True
        self._metrics["errors"] += 1
        logger.error(
            "EventBus: all retries exhausted for %s — switching to local fallback. "
            "Redis will be retried on next connect() call.",
            channel,
        )
        await _local_bus.publish_local(channel, message)

    # ── subscribe ─────────────────────────────────────────────────────────────

    async def subscribe(self, *channels: str) -> AsyncGenerator[dict, None]:
        """
        Async generator yielding decoded dicts from the given channels.

        Reconnects automatically when the Redis connection drops using
        exponential back-off (1 s → 2 s → 4 s … capped at MAX_BACKOFF_S).

        When Redis is permanently unavailable (or already degraded at call
        time) the generator transparently switches to the in-process local
        fallback queue so callers keep receiving messages without restarting.
        The generator never returns on its own — it runs until cancelled.

        Cleanup guarantee: local-bus handlers registered for the fallback
        queue are always removed when the generator is cancelled or exits,
        preventing handler accumulation across repeated subscribe() calls.
        """
        _LOCAL_QUEUE_MAXSIZE = int(os.environ.get("EVENT_BUS_LOCAL_QUEUE_MAXSIZE", "10000"))

        def _make_local_queue() -> tuple[asyncio.Queue, list]:  # type: ignore[type-arg]
            """Wire up a local queue and register handlers for all channels.

            Returns (queue, handlers) so callers can unregister on cleanup.
            """
            q: asyncio.Queue[dict] = asyncio.Queue(maxsize=_LOCAL_QUEUE_MAXSIZE)
            registered: list = []

            async def _enqueue(msg: dict) -> None:
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    # Evict oldest to make room — prefer freshness over completeness.
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:  # nosec B110
                        pass
                    try:
                        q.put_nowait(msg)
                    except asyncio.QueueFull:
                        logger.warning(
                            "EventBus local queue full — dropping message on %s", channels
                        )

            for ch in channels:
                _local_bus.subscribe_local(ch, _enqueue)
                registered.append((ch, _enqueue))
            return q, registered

        def _cleanup_handlers(registered: list) -> None:
            """Unregister all local-bus handlers to prevent accumulation."""
            for ch, handler in registered:
                _local_bus.unsubscribe_local(ch, handler)

        # ── Local fallback path (degraded=True at entry) ──────────────────────
        if self._degraded:
            q, registered = _make_local_queue()
            try:
                while True:
                    msg = await q.get()
                    self._metrics["delivered"] += 1
                    yield msg
            except asyncio.CancelledError:
                raise
            finally:
                # Always unregister handlers — prevents accumulation on repeated calls.
                _cleanup_handlers(registered)

        # ── Redis path with exponential back-off reconnect ────────────────────
        _pubsub_redis: aioredis.Redis | None = None
        _reconnect_backoff: float = BASE_BACKOFF_S
        # How many consecutive Redis failures before giving up and falling back.
        _MAX_CONSECUTIVE_FAILURES = int(
            os.environ.get("EVENT_BUS_MAX_FAILURES", "5")
        )
        _consecutive_failures: int = 0
        _local_registered: list = []

        try:
            while True:
                # If we transitioned to degraded mid-loop, switch to local queue.
                if self._degraded:
                    logger.info(
                        "EventBus subscribe: Redis degraded — switching to local fallback for %s",
                        channels,
                    )
                    q, _local_registered = _make_local_queue()
                    while True:
                        msg = await q.get()
                        self._metrics["delivered"] += 1
                        yield msg
                    # Unreachable — loop exits only via CancelledError caught below.

                pubsub = None
                try:
                    if _pubsub_redis is None:
                        _pubsub_redis = _make_redis_pubsub()
                    pubsub = _pubsub_redis.pubsub()
                    await pubsub.subscribe(*channels)
                    logger.info("EventBus subscribed to channels: %s", channels)
                    # Successful subscribe — reset failure counter and back-off.
                    _consecutive_failures = 0
                    _reconnect_backoff = BASE_BACKOFF_S

                    while True:
                        try:
                            raw = await pubsub.get_message(
                                ignore_subscribe_messages=True,
                                timeout=1.0,
                            )
                        except TimeoutError:
                            # No message within poll window — normal on idle channels.
                            continue
                        except Exception:
                            raise  # propagate real errors to outer handler

                        if raw is None:
                            await asyncio.sleep(0.01)
                            continue

                        if raw.get("type") != "message":
                            continue

                        try:
                            msg = json.loads(raw["data"])
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
                            logger.warning(
                                "EventBus: bad JSON on %s: %s", raw.get("channel"), exc
                            )

                except asyncio.CancelledError:
                    if pubsub:
                        with contextlib.suppress(Exception):
                            await pubsub.unsubscribe()
                    if _pubsub_redis:
                        with contextlib.suppress(Exception):
                            await _pubsub_redis.aclose()
                    raise  # propagate to outer try/finally for handler cleanup

                except (TimeoutError, _redis_exc.TimeoutError) if _redis_exc else (TimeoutError,):
                    # Idle pubsub timeout — normal on quiet channels; re-subscribe silently.
                    _pubsub_redis = None
                    continue

                except Exception as exc:
                    self._metrics["errors"] += 1
                    _consecutive_failures += 1
                    _pubsub_redis = None

                    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "EventBus: Redis unavailable after %d attempts — switching to local fallback.",
                            _consecutive_failures,
                        )
                        self._degraded = True
                        # Fall through to the degraded check at the top of the loop.
                        continue

                    wait = min(_reconnect_backoff, MAX_BACKOFF_S)
                    logger.warning(
                        "EventBus subscribe error: %s — reconnecting in %.0f s",
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    _reconnect_backoff = min(_reconnect_backoff * 2, MAX_BACKOFF_S)

                    # Attempt to re-establish the main Redis connection.
                    # Use connect() so the connection-leak fix applies here too
                    # (closes old _redis before creating a new one).
                    await self.connect()

        finally:
            # Always clean up local-bus handlers on exit (cancellation or error).
            _cleanup_handlers(_local_registered)

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
