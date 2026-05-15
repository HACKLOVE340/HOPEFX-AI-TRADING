# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/redis_tick_writer.py
================================
RedisTickWriter — canonical Redis tick persistence layer with backpressure.

Key schema
----------
  tick:{SYMBOL}                  SET (JSON, TTL=30 s)  — latest tick snapshot
  hopefx:dl:tick:{SYMBOL}        SET (JSON, TTL=30 s)  — data_layer compat key
  price:XAUUSD                   SET (JSON, TTL=30 s)  — legacy price key

Pub/sub channels
----------------
  hopefx:tick:{SYMBOL}           per-symbol channel (e.g. hopefx:tick:XAUUSD)
  hopefx:tick                    CH_TICK — consumed by strategy engine / ws_live

Legacy list
-----------
  price_queue                    RPUSH (NuclearStreamer compat, trimmed to 1000)

Backpressure design
-------------------
Ticks are enqueued into a bounded asyncio.Queue (default 2 000 entries).
A single background worker drains the queue and writes to Redis via pipeline.
When the queue is full, the OLDEST tick is evicted (ticks are ephemeral —
the latest price is what matters, not historical queue entries).

This decouples the caller from Redis latency: write() returns immediately
after enqueuing, never blocking the event loop.  If Redis is slow, the queue
absorbs the burst up to its capacity; beyond that, old ticks are dropped and
a counter is incremented.

Usage
-----
    writer = RedisTickWriter()
    await writer.start()                    # connect + start background worker
    await writer.write("XAUUSD", 1923.5, "yfinance")
    await writer.stop()                     # drain queue + stop worker

    # Or use the module-level singleton:
    from data_feed.redis_tick_writer import get_tick_writer
    writer = await get_tick_writer()
    await writer.write("XAUUSD", 1923.5, "yfinance")
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

# Key / channel constants — single source of truth for the entire system.
TICK_KEY_PREFIX = "tick"  # tick:SYMBOL
DL_TICK_KEY_PREFIX = "hopefx:dl:tick"  # hopefx:dl:tick:SYMBOL
PRICE_KEY_PREFIX = "price"  # price:SYMBOL (legacy)
PUBSUB_CHANNEL_PREFIX = "hopefx:tick"  # hopefx:tick:SYMBOL
CH_TICK = "hopefx:tick"  # legacy broadcast channel
LEGACY_QUEUE = "price_queue"  # NuclearStreamer compat list

TICK_KEY_TTL = int(os.getenv("TICK_KEY_TTL", "30"))  # seconds
LEGACY_QUEUE_MAX = 1000  # max entries in price_queue

# Backpressure: maximum number of ticks buffered in the internal write queue.
# When full, the oldest entry is evicted (ticks are ephemeral).
# Tune via TICK_WRITER_QUEUE_MAXSIZE env var.
_WRITE_QUEUE_MAXSIZE: int = int(os.getenv("TICK_WRITER_QUEUE_MAXSIZE", "2000"))

# Prometheus metrics (optional — degrades gracefully when prometheus_client is absent)
try:
    from prometheus_client import Counter as _PCounter, Gauge as _PGauge

    _TICK_WRITES_TOTAL = _PCounter(
        "hopefx_tick_writer_writes_total",
        "Total ticks successfully written to Redis",
    )
    _TICK_WRITE_ERRORS = _PCounter(
        "hopefx_tick_writer_errors_total",
        "Total Redis write errors in tick writer",
    )
    _TICK_QUEUE_DROPS = _PCounter(
        "hopefx_tick_writer_queue_drops_total",
        "Ticks dropped because the write queue was full",
    )
    _TICK_QUEUE_DEPTH = _PGauge(
        "hopefx_tick_writer_queue_depth",
        "Current depth of the internal write queue",
    )
except Exception:  # pragma: no cover

    class _NoopMetric:  # type: ignore[no-redef]
        def inc(self, _n: float = 1) -> None:
            pass

        def set(self, _v: float) -> None:
            pass

        def labels(self, **_kw):
            return self

    _TICK_WRITES_TOTAL = _NoopMetric()  # type: ignore[assignment]
    _TICK_WRITE_ERRORS = _NoopMetric()  # type: ignore[assignment]
    _TICK_QUEUE_DROPS = _NoopMetric()  # type: ignore[assignment]
    _TICK_QUEUE_DEPTH = _NoopMetric()  # type: ignore[assignment]


def build_tick_payload(
    symbol: str,
    price: float,
    source: str,
    bid: float | None = None,
    ask: float | None = None,
) -> dict:
    """Build the canonical tick payload dict."""
    now = time.time()
    payload: dict[str, Any] = {
        "symbol": symbol,
        "price": price,
        "source": source,
        "ts": now,
        "timestamp": datetime.fromtimestamp(now, tz=UTC).isoformat(),
    }
    if bid is not None:
        payload["bid"] = bid
    if ask is not None:
        payload["ask"] = ask
    return payload


class RedisTickWriter:
    """
    Writes validated ticks to Redis using the canonical key schema.

    Backpressure is enforced via a bounded asyncio.Queue.  write() enqueues
    immediately and returns; a background worker drains the queue and writes
    to Redis via pipeline.  When the queue is full, the oldest tick is evicted
    so the writer never blocks the caller's event loop.

    Parameters
    ----------
    tick_key_ttl:
        TTL in seconds for tick:SYMBOL and hopefx:dl:tick:SYMBOL keys.
    legacy_queue_max:
        Maximum entries kept in the price_queue list.
    write_queue_maxsize:
        Maximum number of ticks buffered before eviction begins.
    """

    def __init__(
        self,
        tick_key_ttl: int = TICK_KEY_TTL,
        legacy_queue_max: int = LEGACY_QUEUE_MAX,
        write_queue_maxsize: int = _WRITE_QUEUE_MAXSIZE,
    ) -> None:
        self._ttl = tick_key_ttl
        self._queue_max = legacy_queue_max
        self._redis: Any | None = None
        self._error_count: int = 0
        self._write_count: int = 0
        self._drop_count: int = 0

        # Bounded write queue — the core backpressure mechanism.
        # maxsize=0 would be unbounded; we always set an explicit limit.
        self._write_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max(1, write_queue_maxsize))
        self._worker_task: asyncio.Task[None] | None = None
        self._stopping: bool = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Acquire the shared Redis client from cache.redis_client.

        Returns True if Redis is reachable, False otherwise.
        Non-fatal — callers continue without Redis when False.
        """
        try:
            from cache.redis_client import get_redis

            self._redis = await get_redis()
            if self._redis is None:
                logger.warning(
                    "RedisTickWriter: Redis unavailable — tick persistence disabled. "
                    "Set REDIS_URL or REDIS_HOST to enable."
                )
                return False
            await self._redis.ping()
            logger.info("RedisTickWriter: connected to Redis")
            return True
        except Exception as exc:
            logger.warning("RedisTickWriter: connection failed: %s", exc)
            self._redis = None
            return False

    async def start(self) -> bool:
        """
        Connect to Redis and start the background write worker.

        Safe to call multiple times — subsequent calls while already running
        are no-ops.  Returns True if Redis is reachable.
        """
        if self._worker_task is not None and not self._worker_task.done():
            return self._redis is not None

        connected = await self.connect()
        self._stopping = False
        self._worker_task = asyncio.create_task(self._write_worker(), name="redis_tick_writer_worker")
        return connected

    async def stop(self) -> None:
        """
        Drain the write queue and stop the background worker.

        Waits up to 5 s for the queue to drain before cancelling the worker.
        """
        self._stopping = True
        if self._worker_task is not None and not self._worker_task.done():
            try:
                await asyncio.wait_for(self._write_queue.join(), timeout=5.0)
            except (TimeoutError, asyncio.TimeoutError):
                logger.warning(
                    "RedisTickWriter: queue did not drain within 5 s — %d ticks may be lost",
                    self._write_queue.qsize(),
                )
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        self._redis = None

    async def close(self) -> None:
        """Alias for stop() — kept for backward compatibility."""
        await self.stop()

    # ── write (non-blocking, backpressure-aware) ──────────────────────────────

    async def write(
        self,
        symbol: str,
        price: float,
        source: str,
        bid: float | None = None,
        ask: float | None = None,
    ) -> bool:
        """
        Enqueue one tick for async Redis persistence.

        Returns immediately — never blocks the caller's event loop.

        Backpressure: if the internal queue is full, the OLDEST tick is
        evicted to make room for the new one.  A drop counter is incremented
        and a warning is logged (rate-limited to once per 100 drops).

        Returns True if the tick was enqueued, False if Redis is not connected.
        """
        if self._redis is None:
            return False

        payload = build_tick_payload(symbol, price, source, bid, ask)

        if self._write_queue.full():
            # Evict the oldest tick — ticks are ephemeral; latest wins.
            try:
                self._write_queue.get_nowait()
                self._write_queue.task_done()
            except asyncio.QueueEmpty:  # nosec B110
                pass
            self._drop_count += 1
            _TICK_QUEUE_DROPS.inc()
            if self._drop_count % 100 == 1:
                logger.warning(
                    "RedisTickWriter: write queue full (maxsize=%d) — evicting oldest tick. Total drops so far: %d",
                    self._write_queue.maxsize,
                    self._drop_count,
                )

        try:
            self._write_queue.put_nowait(payload)
            _TICK_QUEUE_DEPTH.set(self._write_queue.qsize())
            return True
        except asyncio.QueueFull:
            # Race condition: queue filled between the full() check and put_nowait().
            self._drop_count += 1
            _TICK_QUEUE_DROPS.inc()
            return False

    # ── background worker ─────────────────────────────────────────────────────

    async def _write_worker(self) -> None:
        """
        Background coroutine that drains the write queue and writes to Redis.

        Runs until stop() is called.  Reconnects automatically on Redis errors
        using exponential back-off.  A single worker serialises all writes so
        pipeline ordering is preserved.
        """
        _backoff_s: float = 0.1
        _max_backoff_s: float = 30.0

        while True:
            try:
                # When stopping, drain remaining items without waiting for new ones.
                # Use get_nowait() so we don't block on an empty queue during shutdown.
                if self._stopping:
                    try:
                        payload = self._write_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break  # queue drained — exit cleanly
                else:
                    try:
                        payload = await asyncio.wait_for(self._write_queue.get(), timeout=0.5)
                    except (TimeoutError, asyncio.TimeoutError):
                        continue

                await self._flush_one(payload)
                self._write_queue.task_done()
                _TICK_QUEUE_DEPTH.set(self._write_queue.qsize())
                _backoff_s = 0.1  # reset on success

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._error_count += 1
                _TICK_WRITE_ERRORS.inc()
                logger.error(
                    "RedisTickWriter worker error (will retry in %.1fs): %s",
                    _backoff_s,
                    exc,
                )
                await asyncio.sleep(_backoff_s)
                _backoff_s = min(_backoff_s * 2, _max_backoff_s)
                await self.connect()

    async def _flush_one(self, payload: dict) -> None:
        """Write a single tick payload to Redis via pipeline."""
        if self._redis is None:
            return

        symbol = payload["symbol"]
        payload_bytes = json.dumps(payload).encode()

        tick_key = f"{TICK_KEY_PREFIX}:{symbol}"
        dl_key = f"{DL_TICK_KEY_PREFIX}:{symbol}"
        price_key = f"{PRICE_KEY_PREFIX}:{symbol}"
        pubsub_sym = f"{PUBSUB_CHANNEL_PREFIX}:{symbol}"

        pipe = self._redis.pipeline(transaction=False)
        pipe.setex(tick_key, self._ttl, payload_bytes)
        pipe.setex(dl_key, self._ttl, payload_bytes)
        pipe.setex(price_key, self._ttl, payload_bytes)
        pipe.publish(pubsub_sym, payload_bytes)
        pipe.publish(CH_TICK, payload_bytes)
        pipe.rpush(LEGACY_QUEUE, payload_bytes)
        pipe.ltrim(LEGACY_QUEUE, -self._queue_max, -1)
        await pipe.execute()

        self._write_count += 1
        self._error_count = 0
        _TICK_WRITES_TOTAL.inc()

    # ── read helpers ──────────────────────────────────────────────────────────

    async def read_latest(self, symbol: str) -> dict | None:
        """
        Read the latest tick for *symbol* from Redis.

        Tries tick:SYMBOL first, then hopefx:dl:tick:SYMBOL, then price:SYMBOL.
        Returns the parsed dict or None if no key exists.
        """
        if self._redis is None:
            return None

        for key in (
            f"{TICK_KEY_PREFIX}:{symbol}",
            f"{DL_TICK_KEY_PREFIX}:{symbol}",
            f"{PRICE_KEY_PREFIX}:{symbol}",
        ):
            try:
                raw = await self._redis.get(key)
                if raw:
                    return json.loads(raw)
            except Exception as exc:
                logger.debug("RedisTickWriter.read_latest[%s]: %s", key, exc)

        return None

    async def get_tick_age(self, symbol: str) -> float | None:
        """
        Return the age in seconds of the latest tick for *symbol*.

        Returns None if no tick exists or the timestamp cannot be parsed.
        """
        tick = await self.read_latest(symbol)
        if tick is None:
            return None
        ts = tick.get("ts") or tick.get("timestamp")
        if ts is None:
            return None
        try:
            ts_float = float(ts) if isinstance(ts, int | float) else datetime.fromisoformat(str(ts)).timestamp()
            return time.time() - ts_float
        except Exception:
            return None

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "redis_connected": self._redis is not None,
            "write_count": self._write_count,
            "error_count": self._error_count,
            "drop_count": self._drop_count,
            "queue_depth": self._write_queue.qsize(),
            "queue_maxsize": self._write_queue.maxsize,
            "worker_running": (self._worker_task is not None and not self._worker_task.done()),
            "tick_key_ttl": self._ttl,
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_writer_instance: RedisTickWriter | None = None
_writer_lock: asyncio.Lock | None = None


def _get_writer_lock() -> asyncio.Lock:
    """Return the module-level lock, creating it lazily inside the running loop."""
    global _writer_lock
    if _writer_lock is None:
        _writer_lock = asyncio.Lock()
    return _writer_lock


async def get_tick_writer() -> RedisTickWriter:
    """
    Return the module-level RedisTickWriter singleton.

    Thread-safe: uses an asyncio.Lock to prevent duplicate instances when
    multiple coroutines call get_tick_writer() concurrently on first use.
    The background worker is started automatically on first call.
    """
    global _writer_instance
    async with _get_writer_lock():
        if _writer_instance is None:
            _writer_instance = RedisTickWriter()
            await _writer_instance.start()
    return _writer_instance
