# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/stream/publisher.py
================================
Redis Streams-based real-time tick publisher with consumer groups.

Architecture
------------
``TickPublisher`` writes validated ticks to a Redis Stream using XADD.
Each tick is a flat dict of string fields (Redis Streams requirement).
The stream is capped via MAXLEN ~ to bound memory usage.

``TickConsumer`` reads from the stream using a consumer group (XREADGROUP).
Multiple consumer instances can run in parallel; each processes a disjoint
subset of messages.  Unacknowledged messages are reclaimed after a
configurable idle timeout via XAUTOCLAIM / XPENDING + XCLAIM.

Stream key schema
-----------------
  hopefx:ticks:{symbol}          — per-symbol tick stream
  hopefx:ticks:all               — fan-out stream (all symbols)

Consumer group
--------------
  Group name:    configurable (default "hopefx-consumers")
  Consumer name: configurable (default hostname + PID)

Dead-letter handling
--------------------
Messages that fail delivery more than ``max_delivery_attempts`` times are
moved to a dead-letter stream (``hopefx:ticks:dead``) and acknowledged so
they do not block the pending-entry list.

Metrics
-------
  published_count   — total ticks published
  consumed_count    — total ticks consumed by this instance
  ack_count         — total messages acknowledged
  dlq_count         — total messages sent to dead-letter stream
  pending_count     — current PEL size (polled periodically)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# ── Optional async Redis ───────────────────────────────────────────────────────
try:
    import redis.asyncio as aioredis  # type: ignore[import]

    _REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False
    logger.warning("redis[asyncio] not installed — TickPublisher unavailable")

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_STREAM_PREFIX: str = "hopefx:ticks:"
_DEFAULT_GROUP: str = "hopefx-consumers"
_DEFAULT_FANOUT_STREAM: str = "hopefx:ticks:all"
_DEFAULT_DLQ_STREAM: str = "hopefx:ticks:dead"
_DEFAULT_MAXLEN: int = int(os.environ.get("TICK_STREAM_MAXLEN", "100000"))
_DEFAULT_BLOCK_MS: int = int(os.environ.get("TICK_STREAM_BLOCK_MS", "1000"))
_DEFAULT_BATCH_SIZE: int = int(os.environ.get("TICK_STREAM_BATCH_SIZE", "100"))
_DEFAULT_RECLAIM_IDLE_MS: int = int(os.environ.get("TICK_STREAM_RECLAIM_IDLE_MS", "30000"))
_DEFAULT_MAX_DELIVERIES: int = int(os.environ.get("TICK_STREAM_MAX_DELIVERIES", "3"))


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass
class StreamConfig:
    """Configuration for TickPublisher and TickConsumer."""

    redis_url: str = field(default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    stream_prefix: str = _DEFAULT_STREAM_PREFIX
    group_name: str = _DEFAULT_GROUP
    consumer_name: str = field(default_factory=lambda: f"{socket.gethostname()}-{os.getpid()}")
    fanout_stream: str = _DEFAULT_FANOUT_STREAM
    dlq_stream: str = _DEFAULT_DLQ_STREAM
    maxlen: int = _DEFAULT_MAXLEN
    block_ms: int = _DEFAULT_BLOCK_MS
    batch_size: int = _DEFAULT_BATCH_SIZE
    reclaim_idle_ms: int = _DEFAULT_RECLAIM_IDLE_MS
    max_delivery_attempts: int = _DEFAULT_MAX_DELIVERIES
    # Publish to per-symbol stream only, fanout stream, or both.
    publish_per_symbol: bool = True
    publish_fanout: bool = True


# ── Publisher ─────────────────────────────────────────────────────────────────


class TickPublisher:
    """
    Publishes validated ticks to Redis Streams.

    Each call to ``publish()`` writes to:
      - ``hopefx:ticks:{symbol}``  (if config.publish_per_symbol)
      - ``hopefx:ticks:all``       (if config.publish_fanout)

    Both streams are capped at ``config.maxlen`` entries (MAXLEN ~).

    Usage::

        config = StreamConfig()
        publisher = TickPublisher(config)
        await publisher.connect()
        await publisher.publish("XAUUSD", {"price": 1905.5, "timestamp": 1234567890.0, "source": "finnhub"})
        await publisher.close()

    Or as an async context manager::

        async with TickPublisher(config) as pub:
            await pub.publish("XAUUSD", tick_dict)
    """

    def __init__(self, config: StreamConfig | None = None) -> None:
        self.config = config or StreamConfig()
        self._redis: Any | None = None
        self._connected: bool = False

        # Metrics
        self.published_count: int = 0
        self.error_count: int = 0
        self._last_error: str | None = None

    async def connect(self) -> None:
        """Create the async Redis connection."""
        if not _REDIS_AVAILABLE:
            raise RuntimeError("redis[asyncio] is required: pip install 'redis[asyncio]>=5.0'")
        self._redis = await aioredis.from_url(
            self.config.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5.0,
            socket_timeout=5.0,
        )
        self._connected = True
        logger.info(
            "TickPublisher connected: url=%s maxlen=%d",
            self.config.redis_url,
            self.config.maxlen,
        )

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._connected = False
            logger.info("TickPublisher closed")

    async def __aenter__(self) -> TickPublisher:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def _stream_key(self, symbol: str) -> str:
        return f"{self.config.stream_prefix}{symbol}"

    def _tick_to_fields(self, symbol: str, tick: dict[str, Any]) -> dict[str, str]:
        """
        Flatten a tick dict to Redis Stream field format (all values as strings).

        Nested dicts/lists are JSON-encoded.  The symbol is always included.
        """
        fields: dict[str, str] = {"symbol": symbol}
        for k, v in tick.items():
            if isinstance(v, dict | list):
                fields[k] = json.dumps(v)
            elif v is None:
                fields[k] = ""
            else:
                fields[k] = str(v)
        # Always include a server-side received_at for latency measurement.
        fields.setdefault("received_at", str(time.time()))
        return fields

    async def publish(self, symbol: str, tick: dict[str, Any]) -> str | None:
        """
        Publish a single tick to the Redis Stream(s).

        Parameters
        ----------
        symbol:
            Instrument symbol (e.g. ``"XAUUSD"``).
        tick:
            Tick data dict.  All values are coerced to strings for Redis.

        Returns
        -------
        str | None
            The Redis Stream message ID (``"<ms>-<seq>"``), or None on error.
        """
        if not self._connected or self._redis is None:
            raise RuntimeError("TickPublisher not connected — call connect() first")

        fields = self._tick_to_fields(symbol, tick)
        msg_id: str | None = None

        try:
            pipe = self._redis.pipeline(transaction=False)
            if self.config.publish_per_symbol:
                pipe.xadd(
                    self._stream_key(symbol),
                    fields,
                    maxlen=self.config.maxlen,
                    approximate=True,
                )
            if self.config.publish_fanout:
                pipe.xadd(
                    self.config.fanout_stream,
                    fields,
                    maxlen=self.config.maxlen,
                    approximate=True,
                )
            results = await pipe.execute()
            # Return the per-symbol stream ID (first result), or fanout ID.
            msg_id = results[0] if results else None
            self.published_count += 1
            logger.debug("Published tick symbol=%s id=%s", symbol, msg_id)
        except Exception as exc:
            self.error_count += 1
            self._last_error = str(exc)
            logger.error("TickPublisher.publish error: %s", exc)

        return msg_id

    async def publish_batch(self, ticks: list[tuple[str, dict[str, Any]]]) -> int:
        """
        Publish multiple ticks in a single pipeline.

        Parameters
        ----------
        ticks:
            List of ``(symbol, tick_dict)`` tuples.

        Returns
        -------
        int
            Number of ticks successfully published.
        """
        if not self._connected or self._redis is None:
            raise RuntimeError("TickPublisher not connected")

        if not ticks:
            return 0

        pipe = self._redis.pipeline(transaction=False)
        for symbol, tick in ticks:
            fields = self._tick_to_fields(symbol, tick)
            if self.config.publish_per_symbol:
                pipe.xadd(
                    self._stream_key(symbol),
                    fields,
                    maxlen=self.config.maxlen,
                    approximate=True,
                )
            if self.config.publish_fanout:
                pipe.xadd(
                    self.config.fanout_stream,
                    fields,
                    maxlen=self.config.maxlen,
                    approximate=True,
                )

        try:
            await pipe.execute()
            self.published_count += len(ticks)
            return len(ticks)
        except Exception as exc:
            self.error_count += 1
            self._last_error = str(exc)
            logger.error("TickPublisher.publish_batch error: %s", exc)
            return 0

    async def ensure_consumer_group(self, symbol: str) -> None:
        """
        Create the consumer group on the stream if it does not exist.

        Uses ``XGROUP CREATE ... MKSTREAM`` so the stream is also created
        if it does not yet exist.  Safe to call multiple times.
        """
        stream_key = self._stream_key(symbol)
        try:
            await self._redis.xgroup_create(
                stream_key,
                self.config.group_name,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Consumer group '%s' created on stream '%s'",
                self.config.group_name,
                stream_key,
            )
        except Exception as exc:
            # BUSYGROUP means the group already exists — not an error.
            if "BUSYGROUP" in str(exc):
                logger.debug(
                    "Consumer group '%s' already exists on '%s'",
                    self.config.group_name,
                    stream_key,
                )
            else:
                logger.error("ensure_consumer_group error: %s", exc)

    async def stream_info(self, symbol: str) -> dict[str, Any]:
        """Return XINFO STREAM summary for *symbol*'s stream."""
        try:
            info = await self._redis.xinfo_stream(self._stream_key(symbol))
            return dict(info) if info else {}
        except Exception as exc:
            logger.error("stream_info error: %s", exc)
            return {}

    def stats(self) -> dict[str, Any]:
        return {
            "published_count": self.published_count,
            "error_count": self.error_count,
            "last_error": self._last_error,
            "connected": self._connected,
        }


# ── Consumer ──────────────────────────────────────────────────────────────────


class TickConsumer:
    """
    Reads ticks from a Redis Stream consumer group.

    Each instance processes messages from one or more streams using
    XREADGROUP.  Processed messages are acknowledged with XACK.
    Idle messages in the pending-entry list (PEL) are reclaimed via
    XAUTOCLAIM after ``config.reclaim_idle_ms`` milliseconds.
    Messages exceeding ``config.max_delivery_attempts`` are moved to the
    dead-letter stream and acknowledged.

    Usage::

        consumer = TickConsumer(config, symbols=["XAUUSD"])
        consumer.register_handler(my_async_handler)
        await consumer.connect()
        await consumer.run()   # blocks; call stop() to exit

    Handler signature::

        async def handler(symbol: str, tick: dict[str, Any], msg_id: str) -> None:
            ...
    """

    def __init__(
        self,
        config: StreamConfig | None = None,
        symbols: list[str] | None = None,
        use_fanout: bool = False,
    ) -> None:
        self.config = config or StreamConfig()
        self.symbols = symbols or []
        self.use_fanout = use_fanout
        self._redis: Any | None = None
        self._running: bool = False
        self._handlers: list[Callable[[str, dict[str, Any], str], Awaitable[None]]] = []

        # Metrics
        self.consumed_count: int = 0
        self.ack_count: int = 0
        self.dlq_count: int = 0
        self.error_count: int = 0
        self._last_reclaim_at: float = 0.0

    async def connect(self) -> None:
        """Create the async Redis connection and ensure consumer groups exist."""
        if not _REDIS_AVAILABLE:
            raise RuntimeError("redis[asyncio] is required")
        self._redis = await aioredis.from_url(
            self.config.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5.0,
            socket_timeout=5.0,
        )
        # Ensure groups exist on all subscribed streams.
        for symbol in self.streams:
            await self._ensure_group(symbol)
        logger.info(
            "TickConsumer connected: consumer=%s group=%s streams=%s",
            self.config.consumer_name,
            self.config.group_name,
            self.streams,
        )

    async def close(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()

    async def __aenter__(self) -> TickConsumer:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    @property
    def streams(self) -> list[str]:
        """Return the list of stream keys this consumer reads from."""
        keys = []
        if self.use_fanout:
            keys.append(self.config.fanout_stream)
        else:
            keys.extend(f"{self.config.stream_prefix}{sym}" for sym in self.symbols)
        return keys

    def register_handler(
        self,
        handler: Callable[[str, dict[str, Any], str], Awaitable[None]],
    ) -> None:
        """Register an async handler called for each consumed tick."""
        self._handlers.append(handler)

    async def _ensure_group(self, stream_key: str) -> None:
        try:
            await self._redis.xgroup_create(
                stream_key,
                self.config.group_name,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                logger.error("_ensure_group error on %s: %s", stream_key, exc)

    def stop(self) -> None:
        """Signal the consume loop to exit after the current batch."""
        self._running = False

    async def run(self) -> None:
        """
        Main consume loop.  Blocks until ``stop()`` is called.

        Reads batches of messages from all subscribed streams using
        XREADGROUP with a blocking timeout.  After each batch, checks
        whether any PEL messages need reclaiming.
        """
        if not self._redis:
            raise RuntimeError("TickConsumer not connected — call connect() first")

        self._running = True
        stream_keys = self.streams
        if not stream_keys:
            logger.warning("TickConsumer: no streams configured")
            return

        # Build the streams dict for XREADGROUP: {stream_key: ">"} means
        # "deliver new messages not yet delivered to any consumer".
        streams_arg = dict.fromkeys(stream_keys, ">")

        logger.info(
            "TickConsumer starting: consumer=%s streams=%s",
            self.config.consumer_name,
            stream_keys,
        )

        while self._running:
            try:
                # Read a batch of new messages.
                results = await self._redis.xreadgroup(
                    groupname=self.config.group_name,
                    consumername=self.config.consumer_name,
                    streams=streams_arg,
                    count=self.config.batch_size,
                    block=self.config.block_ms,
                )
                if results:
                    await self._process_results(results)

                # Periodically reclaim idle PEL messages.
                now = time.monotonic()
                if now - self._last_reclaim_at > self.config.reclaim_idle_ms / 1000.0:
                    await self._reclaim_idle(stream_keys)
                    self._last_reclaim_at = now

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.error_count += 1
                logger.error("TickConsumer.run error: %s", exc)
                await asyncio.sleep(1.0)

        logger.info("TickConsumer stopped: consumer=%s", self.config.consumer_name)

    async def _process_results(
        self,
        results: list[tuple[str, list[tuple[str, dict[str, str]]]]],
    ) -> None:
        """Process a batch of XREADGROUP results."""
        for stream_key, messages in results:
            for msg_id, fields in messages:
                symbol = fields.get("symbol", "")
                tick = self._fields_to_tick(fields)
                self.consumed_count += 1

                # Dispatch to all registered handlers.
                for handler in self._handlers:
                    try:
                        await handler(symbol, tick, msg_id)
                    except Exception as exc:
                        self.error_count += 1
                        logger.error("Handler error for msg_id=%s: %s", msg_id, exc)

                # Acknowledge the message.
                try:
                    await self._redis.xack(stream_key, self.config.group_name, msg_id)
                    self.ack_count += 1
                except Exception as exc:
                    logger.error("XACK error for msg_id=%s: %s", msg_id, exc)

    async def _reclaim_idle(self, stream_keys: list[str]) -> None:
        """
        Reclaim idle PEL messages using XAUTOCLAIM (Redis 7+) with fallback
        to XPENDING + XCLAIM for older Redis versions.
        """
        for stream_key in stream_keys:
            try:
                # Try XAUTOCLAIM (Redis 7+).
                result = await self._redis.xautoclaim(
                    stream_key,
                    self.config.group_name,
                    self.config.consumer_name,
                    min_idle_time=self.config.reclaim_idle_ms,
                    start_id="0-0",
                    count=self.config.batch_size,
                )
                # result = (next_start_id, [(msg_id, fields), ...], [deleted_ids])
                reclaimed = result[1] if result and len(result) > 1 else []
                if reclaimed:
                    logger.info(
                        "Reclaimed %d idle messages from %s",
                        len(reclaimed),
                        stream_key,
                    )
                    await self._handle_reclaimed(stream_key, reclaimed)
            except Exception as exc:
                # XAUTOCLAIM not available (Redis < 7) — use XPENDING + XCLAIM.
                if "unknown command" in str(exc).lower() or "ERR" in str(exc):
                    await self._reclaim_via_xpending(stream_key)
                else:
                    logger.debug("_reclaim_idle error on %s: %s", stream_key, exc)

    async def _handle_reclaimed(
        self,
        stream_key: str,
        messages: list[tuple[str, dict[str, str]]],
    ) -> None:
        """Process reclaimed messages; send to DLQ if over delivery limit."""
        for msg_id, fields in messages:
            delivery_count = int(fields.get("_delivery_count", "1"))
            if delivery_count >= self.config.max_delivery_attempts:
                await self._send_to_dlq(stream_key, msg_id, fields)
            else:
                # Re-process.
                symbol = fields.get("symbol", "")
                tick = self._fields_to_tick(fields)
                for handler in self._handlers:
                    try:
                        await handler(symbol, tick, msg_id)
                    except Exception as exc:
                        logger.error("Reclaim handler error: %s", exc)
                try:
                    await self._redis.xack(stream_key, self.config.group_name, msg_id)
                    self.ack_count += 1
                except Exception as exc:
                    logger.error("XACK reclaim error: %s", exc)

    async def _reclaim_via_xpending(self, stream_key: str) -> None:
        """Fallback reclaim using XPENDING + XCLAIM for Redis < 7."""
        try:
            pending = await self._redis.xpending_range(
                stream_key,
                self.config.group_name,
                min="-",
                max="+",
                count=self.config.batch_size,
                idle=self.config.reclaim_idle_ms,
            )
            if not pending:
                return
            for entry in pending:
                msg_id = entry["message_id"]
                delivery_count = entry.get("times_delivered", 1)
                if delivery_count >= self.config.max_delivery_attempts:
                    # Claim then DLQ.
                    claimed = await self._redis.xclaim(
                        stream_key,
                        self.config.group_name,
                        self.config.consumer_name,
                        min_idle_time=self.config.reclaim_idle_ms,
                        message_ids=[msg_id],
                    )
                    for cid, fields in claimed:
                        await self._send_to_dlq(stream_key, cid, fields)
        except Exception as exc:
            logger.debug("_reclaim_via_xpending error: %s", exc)

    async def _send_to_dlq(
        self,
        source_stream: str,
        msg_id: str,
        fields: dict[str, str],
    ) -> None:
        """Move a message to the dead-letter stream and acknowledge it."""
        dlq_fields = dict(fields)
        dlq_fields["_source_stream"] = source_stream
        dlq_fields["_original_id"] = msg_id
        dlq_fields["_dlq_at"] = str(time.time())
        try:
            await self._redis.xadd(
                self.config.dlq_stream,
                dlq_fields,
                maxlen=10000,
                approximate=True,
            )
            await self._redis.xack(source_stream, self.config.group_name, msg_id)
            self.dlq_count += 1
            logger.warning("Message %s moved to DLQ from stream %s", msg_id, source_stream)
        except Exception as exc:
            logger.error("_send_to_dlq error: %s", exc)

    @staticmethod
    def _fields_to_tick(fields: dict[str, str]) -> dict[str, Any]:
        """
        Reconstruct a tick dict from Redis Stream string fields.

        Numeric strings are coerced to float.  JSON-encoded nested values
        are decoded.  Internal fields (prefixed with ``_``) are excluded.
        """
        tick: dict[str, Any] = {}
        for k, v in fields.items():
            if k.startswith("_"):
                continue
            if not v:
                tick[k] = None
                continue
            # Try JSON decode for nested structures.
            if v.startswith("{") or v.startswith("["):
                try:
                    tick[k] = json.loads(v)
                    continue
                except (json.JSONDecodeError, ValueError):  # nosec B110
                    pass
            # Try numeric coercion.
            try:
                tick[k] = float(v)
                continue
            except ValueError:  # nosec B110
                pass
            tick[k] = v
        return tick

    def stats(self) -> dict[str, Any]:
        return {
            "consumer_name": self.config.consumer_name,
            "group_name": self.config.group_name,
            "streams": self.streams,
            "consumed_count": self.consumed_count,
            "ack_count": self.ack_count,
            "dlq_count": self.dlq_count,
            "error_count": self.error_count,
            "running": self._running,
        }
