# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/redis_tick_writer.py
================================
RedisTickWriter — canonical Redis tick persistence layer.

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

Usage
-----
    writer = RedisTickWriter()
    await writer.connect()
    await writer.write(symbol="XAUUSD", price=1923.5, source="yfinance")
    await writer.close()

    # Or use the module-level singleton:
    from data_feed.redis_tick_writer import get_tick_writer
    writer = await get_tick_writer()
    await writer.write("XAUUSD", 1923.5, "yfinance")
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

# Key / channel constants — single source of truth for the entire system.
TICK_KEY_PREFIX = "tick"                    # tick:SYMBOL
DL_TICK_KEY_PREFIX = "hopefx:dl:tick"      # hopefx:dl:tick:SYMBOL
PRICE_KEY_PREFIX = "price"                  # price:SYMBOL (legacy)
PUBSUB_CHANNEL_PREFIX = "hopefx:tick"      # hopefx:tick:SYMBOL
CH_TICK = "hopefx:tick"                     # legacy broadcast channel
LEGACY_QUEUE = "price_queue"               # NuclearStreamer compat list

TICK_KEY_TTL = int(os.getenv("TICK_KEY_TTL", "30"))   # seconds
LEGACY_QUEUE_MAX = 1000                                 # max entries in price_queue


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

    Uses cache.redis_client.get_redis() so it shares the same Sentinel /
    Cluster / direct connection as the rest of the application.

    Parameters
    ----------
    tick_key_ttl:
        TTL in seconds for tick:SYMBOL and hopefx:dl:tick:SYMBOL keys.
    legacy_queue_max:
        Maximum entries kept in the price_queue list.
    """

    def __init__(
        self,
        tick_key_ttl: int = TICK_KEY_TTL,
        legacy_queue_max: int = LEGACY_QUEUE_MAX,
    ) -> None:
        self._ttl = tick_key_ttl
        self._queue_max = legacy_queue_max
        self._redis: Any | None = None
        self._error_count: int = 0
        self._write_count: int = 0

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
            # Verify connectivity
            await self._redis.ping()
            logger.info("RedisTickWriter: connected to Redis")
            return True
        except Exception as exc:
            logger.warning("RedisTickWriter: connection failed: %s", exc)
            self._redis = None
            return False

    async def write(
        self,
        symbol: str,
        price: float,
        source: str,
        bid: float | None = None,
        ask: float | None = None,
    ) -> bool:
        """
        Persist one tick to Redis.

        Writes atomically via a pipeline:
          1. SET tick:SYMBOL (TTL)
          2. SET hopefx:dl:tick:SYMBOL (TTL)
          3. SET price:SYMBOL (TTL)
          4. PUBLISH hopefx:tick:SYMBOL
          5. PUBLISH hopefx:tick  (CH_TICK)
          6. RPUSH price_queue + LTRIM

        Returns True on success, False on Redis error.
        """
        if self._redis is None:
            return False

        payload = build_tick_payload(symbol, price, source, bid, ask)
        payload_bytes = json.dumps(payload).encode()

        tick_key = f"{TICK_KEY_PREFIX}:{symbol}"
        dl_key = f"{DL_TICK_KEY_PREFIX}:{symbol}"
        price_key = f"{PRICE_KEY_PREFIX}:{symbol}"
        pubsub_sym = f"{PUBSUB_CHANNEL_PREFIX}:{symbol}"

        try:
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
            return True

        except Exception as exc:
            self._error_count += 1
            if self._error_count == 1:
                logger.error("RedisTickWriter[%s]: write error: %s", symbol, exc)
            else:
                logger.debug(
                    "RedisTickWriter[%s]: write error #%d: %s",
                    symbol,
                    self._error_count,
                    exc,
                )
            return False

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
            ts_float = float(ts) if isinstance(ts, (int, float)) else datetime.fromisoformat(str(ts)).timestamp()
            return time.time() - ts_float
        except Exception:
            return None

    async def close(self) -> None:
        """Release the Redis client reference (does not close the shared pool)."""
        self._redis = None

    def status(self) -> dict:
        return {
            "redis_connected": self._redis is not None,
            "write_count": self._write_count,
            "error_count": self._error_count,
            "tick_key_ttl": self._ttl,
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_writer_instance: RedisTickWriter | None = None


async def get_tick_writer() -> RedisTickWriter:
    """
    Return the module-level RedisTickWriter singleton, connecting on first call.
    """
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = RedisTickWriter()
        await _writer_instance.connect()
    return _writer_instance
