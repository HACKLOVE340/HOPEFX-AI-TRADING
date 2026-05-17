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
from collections.abc import AsyncIterator, Callable
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
CH_TICK = "hopefx:tick"  # raw market tick (bid/ask/timestamp)
CH_SIGNAL = "hopefx:signal"  # ML/RL trade signal (direction, confidence)
CH_ORDER = "hopefx:order"  # order request / fill confirmation
CH_BREACH = "hopefx:breach"  # risk breach / kill event

# Market microstructure channels (ws_live chart-bot)
CH_MICROSTRUCTURE = "hopefx:microstructure"  # L2 order book snapshot
CH_VOLUME_DELTA = "hopefx:volume_delta"  # cumulative delta bar

# Risk & equity channels
CH_RISK_UPDATE = "hopefx:risk_update"  # risk engine snapshot
CH_EQUITY_UPDATE = "hopefx:equity_update"  # account equity snapshot

# News & sentiment channels
CH_NEWS_ITEM = "hopefx:news_item"  # single news article
CH_SENTIMENT = "hopefx:sentiment"  # sentiment signal + recent articles

# System / admin channels
CH_SYSTEM = "hopefx:system"  # system-level events (halt, maintenance)
CH_HEARTBEAT = "hopefx:heartbeat"  # liveness heartbeat

# Convenience groupings
MARKET_CHANNELS = (CH_TICK, CH_MICROSTRUCTURE, CH_VOLUME_DELTA)
TRADING_CHANNELS = (CH_SIGNAL, CH_ORDER, CH_BREACH)
ACCOUNT_CHANNELS = (CH_RISK_UPDATE, CH_EQUITY_UPDATE)
INFO_CHANNELS = (CH_NEWS_ITEM, CH_SENTIMENT)
SYSTEM_CHANNELS = (CH_SYSTEM, CH_HEARTBEAT)

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
# Module-level constant so the maxsize is evaluated once at import time,
# not re-read from the environment on every subscribe() call.
_LOCAL_QUEUE_MAXSIZE: int = int(os.environ.get("EVENT_BUS_LOCAL_QUEUE_MAXSIZE", "10000"))

# Prometheus counter for fallback queue drops (optional — degrades gracefully)
try:
    from prometheus_client import Counter as _PCounter

    _EVENT_BUS_QUEUE_DROPS = _PCounter(
        "hopefx_event_bus_queue_drops_total",
        "Messages dropped from the in-process fallback queue when full",
        ["channel"],
    )
except Exception:  # pragma: no cover

    class _NoopCounter:  # type: ignore[no-redef]
        def labels(self, **_kw):
            return self

        def inc(self, _n: float = 1) -> None:
            pass

    _EVENT_BUS_QUEUE_DROPS = _NoopCounter()  # type: ignore[assignment]


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
        """Register a handler for a channel. Idempotent — duplicate handlers are not added."""
        handlers = self._handlers.setdefault(channel, [])
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Remove a previously registered handler. No-op if handler is not registered."""
        import contextlib

        with contextlib.suppress(ValueError):
            self._handlers.get(channel, []).remove(handler)

    def clear_channel(self, channel: str) -> None:
        """Remove all handlers for a channel (e.g. on reconnect to avoid duplicates)."""
        self._handlers[channel] = []

    async def publish_local(self, channel: str, message: dict) -> None:
        """
        Dispatch *message* to every handler registered on *channel*.

        Per-handler isolation: an exception in one handler is caught, logged,
        and does NOT prevent subsequent handlers from receiving the message.
        This is the core guarantee — a misbehaving subscriber cannot kill the bus.
        """
        for handler in list(self._handlers.get(channel, [])):
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                # Propagate cancellation — do not swallow it.
                raise
            except Exception as exc:
                # Log with full traceback so the root cause is visible in logs.
                # The bus continues delivering to remaining handlers.
                logger.exception(
                    "LocalBus: handler %r raised on channel %s — skipping this handler. Error: %s",
                    getattr(handler, "__qualname__", repr(handler)),
                    channel,
                    exc,
                )


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
        silently and only logs if the state changes.
        """
        if self._redis is not None and not self._degraded:
            # Already connected — skip redundant connect attempt
            return
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
        if self._degraded or self._redis is None:
            self._metrics["published"] += 1  # counts as delivered via local bus
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

    async def subscribe(self, *channels: str) -> AsyncIterator[dict]:
        """
        Async generator yielding decoded dicts from the given channels.

        Reconnects automatically when the Redis connection drops.
        Switches to local fallback when Redis is permanently unavailable.
        """
        if self._degraded:
            # Local fallback: feed a bounded queue from _local_bus handlers.
            # _LOCAL_QUEUE_MAXSIZE is a module-level constant (default 10 000)
            # so it is evaluated once at import time, not on every subscribe().
            queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_LOCAL_QUEUE_MAXSIZE)

            async def _enqueue(msg: dict) -> None:
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    # Drop oldest message to make room (LIFO-style eviction)
                    import contextlib

                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                    try:
                        queue.put_nowait(msg)
                    except asyncio.QueueFull:
                        ch_label = channels[0] if channels else "unknown"
                        logger.warning(
                            "EventBus local queue full (maxsize=%d) — dropping message on %s",
                            _LOCAL_QUEUE_MAXSIZE,
                            channels,
                        )
                        _EVENT_BUS_QUEUE_DROPS.labels(channel=ch_label).inc()

            for ch in channels:
                _local_bus.subscribe_local(ch, _enqueue)

            try:
                while True:
                    msg = await queue.get()
                    self._metrics["delivered"] += 1
                    yield msg
            finally:
                # Always unregister the handler when the generator exits (normal
                # or via GeneratorExit / cancellation) to prevent handler list
                # growth and the associated memory leak.
                for ch in channels:
                    _local_bus.unsubscribe_local(ch, _enqueue)
            return  # unreachable; satisfies type checker

        # Redis path with auto-reconnect.
        # Circuit-breaker: after _RECONNECT_MAX_ATTEMPTS consecutive failures the
        # loop gives up and falls through to local fallback — it does NOT loop
        # forever consuming CPU and filling logs when Redis is permanently down.
        _RECONNECT_MAX_ATTEMPTS = 10
        _RECONNECT_BASE_S = 1.0
        _RECONNECT_MAX_S = 60.0

        _pubsub_redis: aioredis.Redis | None = None
        _consecutive_errors: int = 0
        while True:
            pubsub = None
            try:
                if _pubsub_redis is None:
                    _pubsub_redis = _make_redis_pubsub()
                pubsub = _pubsub_redis.pubsub()
                await pubsub.subscribe(*channels)
                logger.info("EventBus subscribed to channels: %s", channels)
                _consecutive_errors = 0  # reset on successful subscribe

                while True:
                    try:
                        # get_message with a timeout avoids blocking the event loop
                        # indefinitely and prevents spurious "Timeout reading" errors
                        # that occur when socket_timeout fires on an idle connection.
                        raw = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=1.0,
                        )
                    except TimeoutError:
                        # No message within the poll window — normal for idle channels
                        continue
                    except Exception:
                        raise  # propagate real errors to the outer except

                    if raw is None:
                        # No message ready — yield control and poll again
                        await asyncio.sleep(0.01)
                        continue

                    if raw.get("type") != "message":
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
                        # FIX: wrap yield in try/except so an exception thrown
                        # into the generator by the caller (e.g. from inside an
                        # `async for` body) does NOT crash the subscription loop.
                        # GeneratorExit is re-raised so the generator can be
                        # properly closed by the runtime.
                        try:
                            yield msg
                        except GeneratorExit:
                            raise
                        except asyncio.CancelledError:
                            raise
                        except Exception as _caller_exc:
                            logger.exception(
                                "EventBus: caller raised inside async-for on channel %s — "
                                "subscription loop continues. Error: %s",
                                raw.get("channel"),
                                _caller_exc,
                            )
                    except json.JSONDecodeError as exc:
                        logger.warning("EventBus: bad JSON on %s: %s", raw.get("channel"), exc)

            except asyncio.CancelledError:
                if pubsub:
                    await pubsub.unsubscribe()
                return
            except (TimeoutError, _redis_exc.TimeoutError):
                # Idle pubsub timeout — no messages received within socket_timeout.
                # This is normal on quiet channels; just re-subscribe without logging.
                _pubsub_redis = None
                continue
            except Exception as exc:
                self._metrics["errors"] += 1
                _consecutive_errors += 1

                if _consecutive_errors >= _RECONNECT_MAX_ATTEMPTS:
                    self._degraded = True
                    logger.error(
                        "EventBus: %d consecutive reconnect failures — giving up, "
                        "switching to local fallback. Last error: %s",
                        _consecutive_errors,
                        exc,
                    )
                    return

                # Exponential backoff capped at _RECONNECT_MAX_S
                backoff_s = min(_RECONNECT_BASE_S * (2 ** (_consecutive_errors - 1)), _RECONNECT_MAX_S)
                logger.error(
                    "EventBus subscribe error (attempt %d/%d): %s — reconnecting in %.0fs",
                    _consecutive_errors,
                    _RECONNECT_MAX_ATTEMPTS,
                    exc,
                    backoff_s,
                )
                _pubsub_redis = None
                await asyncio.sleep(backoff_s)
                try:
                    self._redis = _make_redis()
                    await self._redis.ping()
                    logger.info("EventBus reconnected to Redis.")
                    _consecutive_errors = 0
                except Exception as _reconnect_exc:
                    self._degraded = True
                    logger.error(
                        "EventBus: Redis reconnect failed (attempt %d/%d): %s",
                        _consecutive_errors,
                        _RECONNECT_MAX_ATTEMPTS,
                        _reconnect_exc,
                    )

    # ── local subscription (in-process handlers) ──────────────────────────────

    def subscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Register a handler for local fallback delivery on a channel."""
        _local_bus.subscribe_local(channel, handler)

    def unsubscribe_local(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Remove a previously registered local handler. No-op if not registered."""
        _local_bus.unsubscribe_local(channel, handler)

    def clear_local_channel(self, channel: str) -> None:
        """Remove all local handlers for a channel (use on reconnect to prevent duplicates)."""
        _local_bus.clear_channel(channel)

    async def publish_local(self, channel: str, message: dict) -> None:
        """Publish directly to in-process handlers without Redis transport."""
        await _local_bus.publish_local(channel, message)

    async def dispatch_to_handlers(
        self,
        channel: str,
        message: dict,
        handlers: list[Callable[[dict], Any]],
    ) -> None:
        """
        Fan out *message* to every handler in *handlers* with per-handler isolation.

        An exception in one handler is caught and logged; remaining handlers
        still receive the message.  This is the correct way to call multiple
        subscribers from a single Redis message — it prevents one bad handler
        from killing the entire bus.

        Usage::

            async for msg in bus.subscribe(CH_TICK):
                await bus.dispatch_to_handlers(CH_TICK, msg, [handler_a, handler_b])

        CancelledError and GeneratorExit are re-raised immediately so the
        caller's cancellation is not swallowed.
        """
        for handler in handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                logger.exception(
                    "EventBus.dispatch_to_handlers: handler %r raised on channel %s — "
                    "continuing with remaining handlers. Error: %s",
                    getattr(handler, "__qualname__", repr(handler)),
                    channel,
                    exc,
                )

    async def run_subscriber(
        self,
        channel: str,
        handler: Callable[[dict], Any],
        *extra_channels: str,
    ) -> None:
        """
        Long-running coroutine that subscribes to *channel* (and any
        *extra_channels*) and dispatches every message to *handler* with
        full exception isolation.

        Designed to be run as an asyncio.Task::

            task = asyncio.create_task(bus.run_subscriber(CH_TICK, on_tick))

        The task runs until cancelled.  A handler exception is logged but
        does NOT stop the subscription — the next message is delivered normally.
        """
        async for msg in self.subscribe(channel, *extra_channels):
            try:
                result = handler(msg)
                if asyncio.iscoroutine(result):
                    await result
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                logger.exception(
                    "EventBus.run_subscriber: handler %r raised on channel %s — subscription continues. Error: %s",
                    getattr(handler, "__qualname__", repr(handler)),
                    channel,
                    exc,
                )

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


async def publish(channel: str, message: dict) -> None:
    """Module-level convenience wrapper — delegates to the global bus singleton.

    Allows callers to write::

        from core.event_bus import publish, CH_TICK
        await publish(CH_TICK, {...})

    instead of importing ``bus`` directly.
    """
    await bus.publish(channel, message)
