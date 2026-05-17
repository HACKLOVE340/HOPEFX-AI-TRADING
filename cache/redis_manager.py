# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# pylint: disable=broad-exception-caught
# cache/redis_manager.py
"""
Redis cache manager with JSON serialization, distributed locking,
pub/sub management, and Redis Streams consumer group support.

Serialization uses JSON (not pickle) to prevent remote code execution
if Redis is compromised. pandas DataFrames are serialized via
DataFrame.to_json / pd.read_json.

New in this version
-------------------
- DistributedLock: SET NX PX-based lock with auto-renewal and context manager
- PubSubManager: subscribe/publish with per-channel callbacks and reconnect
- StreamConsumerGroup: Redis Streams XADD/XREADGROUP/XACK with dead-letter
- RedisCacheManager: delete(), mget(), mset(), health_check(), stats()
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def _serialize(value: Any) -> bytes:
    """Serialize value to JSON bytes. DataFrames use orient='split'."""
    if PANDAS_AVAILABLE and isinstance(value, pd.DataFrame):
        payload = {"__type__": "dataframe", "data": value.to_json(orient="split")}
    elif PANDAS_AVAILABLE and isinstance(value, pd.Series):
        payload = {"__type__": "series", "data": value.to_json(orient="split")}
    else:
        payload = {"__type__": "json", "data": value}
    return json.dumps(payload, default=str).encode()


def _deserialize(raw: bytes) -> Any:
    """Deserialize JSON bytes back to Python object."""
    payload = json.loads(raw.decode())
    t = payload.get("__type__")
    if t == "dataframe" and PANDAS_AVAILABLE:
        return pd.read_json(payload["data"], orient="split")
    if t == "series" and PANDAS_AVAILABLE:
        return pd.read_json(payload["data"], orient="split", typ="series")
    return payload.get("data")


class RedisCacheManager:
    """Production-ready Redis cache with JSON serialization."""

    _DEFAULT_REDIS_PORT = 6379

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        if not REDIS_AVAILABLE:
            raise ImportError("redis package required: pip install redis")

        # Use the shared connection pool when the caller hasn't specified a
        # non-default host/port, otherwise fall back to a dedicated pool so
        # that explicit host/port configs still work (e.g. multi-Redis setups).

        default_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        uses_defaults = (
            host == "localhost" and port == self._DEFAULT_REDIS_PORT and db == 0 and "localhost:6379" in default_url
        )
        if uses_defaults:
            try:
                from cache.redis_pool import get_sync_client

                self.client = get_sync_client()
            except Exception:
                # Fallback: create a direct client if pool import fails
                self.client = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    decode_responses=False,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    health_check_interval=30,
                )
        else:
            # Non-default target: create a dedicated pool for this instance.
            pool = redis.ConnectionPool(
                host=host,
                port=port,
                db=db,
                max_connections=20,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30,
            )
            self.client = redis.Redis(connection_pool=pool)
        self.default_ttl = timedelta(hours=1)

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        try:
            data = self.client.get(key)
            if data:
                return _deserialize(data)
            return None
        except Exception as e:
            logger.warning("Redis get failed for key=%s: %s", key, e)
            return None

    def set(self, key: str, value: Any, ttl: timedelta | None = None) -> bool:
        """Set value in cache with TTL."""
        try:
            serialized = _serialize(value)
            expiry = int((ttl or self.default_ttl).total_seconds())
            return bool(self.client.setex(key, expiry, serialized))
        except Exception as e:
            logger.warning("Redis set failed for key=%s: %s", key, e)
            return False

    def get_market_data(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """Get cached market data."""
        key = f"ohlcv:{symbol}:{timeframe}"
        return self.get(key)

    def set_market_data(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame,
        ttl: timedelta | None = None,
    ):
        """Cache market data."""
        key = f"ohlcv:{symbol}:{timeframe}"
        self.set(key, data, ttl or timedelta(minutes=5))

    def delete(self, key: str) -> bool:
        """Delete a single key. Returns True if the key existed."""
        try:
            return bool(self.client.delete(key))
        except Exception as exc:
            logger.warning("Redis delete failed for key=%s: %s", key, exc)
            return False

    def mget(self, keys: list[str]) -> list[Any | None]:
        """Fetch multiple keys in one round-trip. Returns list aligned to keys."""
        if not keys:
            return []
        try:
            raw_values = self.client.mget(keys)
            return [_deserialize(v) if v is not None else None for v in raw_values]
        except Exception as exc:
            logger.warning("Redis mget failed: %s", exc)
            return [None] * len(keys)

    def mset(self, mapping: dict[str, Any], ttl: timedelta | None = None) -> bool:
        """Set multiple keys in one pipeline. All keys get the same TTL."""
        if not mapping:
            return True
        expiry = int((ttl or self.default_ttl).total_seconds())
        try:
            pipe = self.client.pipeline(transaction=False)
            for key, value in mapping.items():
                pipe.setex(key, expiry, _serialize(value))
            pipe.execute()
            return True
        except Exception as exc:
            logger.warning("Redis mset failed: %s", exc)
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern. Returns count deleted."""
        deleted = 0
        try:
            for key in self.client.scan_iter(match=pattern, count=100):
                deleted += self.client.delete(key)
        except Exception as exc:
            logger.warning("Redis invalidate_pattern failed for %r: %s", pattern, exc)
        return deleted

    def health_check(self) -> dict:
        """Return a health snapshot for this cache manager instance."""
        try:
            t0 = time.perf_counter()
            self.client.ping()
            latency_ms = (time.perf_counter() - t0) * 1000
            info = self.client.info("server")
            return {
                "status": "ok",
                "ping_ms": round(latency_ms, 2),
                "redis_version": info.get("redis_version", "unknown"),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    def stats(self) -> dict:
        """Return keyspace and memory stats."""
        try:
            info = self.client.info()
            keyspace = self.client.info("keyspace")
            return {
                "used_memory_bytes": info.get("used_memory", 0),
                "used_memory_human": info.get("used_memory_human", ""),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
                "keyspace": keyspace,
            }
        except Exception as exc:
            logger.warning("Redis stats failed: %s", exc)
            return {}


# ── Distributed lock ──────────────────────────────────────────────────────────


class DistributedLock:
    """
    Redis-backed distributed lock using SET NX PX.

    Guarantees:
    - Only one holder at a time (SET NX).
    - Auto-expiry prevents deadlocks when the holder crashes (PX TTL).
    - Owner token (UUID) prevents accidental release by non-owners.
    - Optional auto-renewal thread extends TTL while the lock is held.

    Usage::

        lock = DistributedLock(redis_client, "hopefx:lock:order_submit")
        with lock:
            # critical section
            submit_order()

        # Or async-style:
        if lock.acquire(timeout=5.0):
            try:
                submit_order()
            finally:
                lock.release()
    """

    # Lua script for atomic release: only delete if we own the lock.
    _RELEASE_SCRIPT = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
    """
    # Lua script for atomic renewal: only extend TTL if we still own the lock.
    _RENEW_SCRIPT = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]))
        end
        return 0
    """

    def __init__(
        self,
        client: Any,
        name: str,
        ttl_ms: int = 30_000,
        retry_interval_ms: int = 100,
        auto_renew: bool = True,
    ) -> None:
        self._client = client
        self._name = name
        self._ttl_ms = ttl_ms
        self._retry_interval = retry_interval_ms / 1000.0
        self._auto_renew = auto_renew
        self._token: str | None = None
        self._renew_thread: threading.Thread | None = None
        self._stop_renew = threading.Event()

    def acquire(self, timeout: float = 10.0) -> bool:
        """
        Try to acquire the lock within ``timeout`` seconds.

        Returns True if acquired, False if timed out.
        """
        token = str(uuid.uuid4())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                ok = self._client.set(self._name, token, nx=True, px=self._ttl_ms)
                if ok:
                    self._token = token
                    if self._auto_renew:
                        self._start_renew()
                    return True
            except Exception as exc:
                logger.warning("DistributedLock.acquire error: %s", exc)
            time.sleep(self._retry_interval)
        return False

    def release(self) -> bool:
        """Release the lock. Returns True if this caller owned it."""
        if self._token is None:
            return False
        self._stop_renew.set()
        if self._renew_thread and self._renew_thread.is_alive():
            self._renew_thread.join(timeout=1.0)
        token = self._token
        self._token = None
        try:
            result = self._client.eval(self._RELEASE_SCRIPT, 1, self._name, token)
            return bool(result)
        except Exception as exc:
            # Fallback for environments where EVAL is unavailable (e.g. fakeredis):
            # check ownership manually then delete.
            logger.debug("DistributedLock.release eval failed (%s) — using GET/DEL fallback", exc)
            try:
                current = self._client.get(self._name)
                if isinstance(current, bytes):
                    current = current.decode()
                if current == token:
                    self._client.delete(self._name)
                    return True
            except Exception as exc2:
                logger.warning("DistributedLock.release fallback error: %s", exc2)
            return False

    def _start_renew(self) -> None:
        """Start a background thread that renews the lock TTL at half-TTL intervals."""
        self._stop_renew.clear()
        interval = self._ttl_ms / 2000.0  # half TTL in seconds

        def _renew_loop() -> None:
            while not self._stop_renew.wait(timeout=interval):
                if self._token is None:
                    break
                try:
                    self._client.eval(self._RENEW_SCRIPT, 1, self._name, self._token, self._ttl_ms)
                except Exception as exc:
                    # Fallback: extend TTL without ownership check
                    with contextlib.suppress(Exception):
                        self._client.pexpire(self._name, self._ttl_ms)
                    logger.debug("DistributedLock renew eval error (used pexpire fallback): %s", exc)

        self._renew_thread = threading.Thread(target=_renew_loop, daemon=True, name=f"lock-renew:{self._name}")
        self._renew_thread.start()

    def __enter__(self) -> DistributedLock:
        if not self.acquire():
            raise TimeoutError(f"Could not acquire lock {self._name!r}")
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()

    @property
    def is_held(self) -> bool:
        """True if this instance currently holds the lock."""
        return self._token is not None


# ── Pub/Sub manager ───────────────────────────────────────────────────────────


class PubSubManager:
    """
    Manages Redis pub/sub subscriptions with per-channel callbacks and
    automatic reconnection on connection loss.

    Usage::

        psm = PubSubManager(redis_client)
        psm.subscribe("hopefx:tick:XAU_USD", lambda msg: handle_tick(msg))
        psm.start()   # starts background listener thread
        ...
        psm.stop()

    Publishing::

        psm.publish("hopefx:tick:XAU_USD", {"bid": 2300.0, "ask": 2301.0})
    """

    def __init__(self, client: Any, reconnect_delay: float = 2.0) -> None:
        self._client = client
        self._reconnect_delay = reconnect_delay
        self._callbacks: dict[str, list[Callable]] = {}
        self._pubsub: Any = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def subscribe(self, channel: str, callback: Callable[[dict], None]) -> None:
        """Register a callback for messages on ``channel``."""
        with self._lock:
            self._callbacks.setdefault(channel, []).append(callback)
        if self._pubsub is not None:
            try:
                self._pubsub.subscribe(channel)
            except Exception as exc:
                logger.warning("PubSubManager.subscribe error: %s", exc)

    def unsubscribe(self, channel: str) -> None:
        """Remove all callbacks for ``channel``."""
        with self._lock:
            self._callbacks.pop(channel, None)
        if self._pubsub is not None:
            try:
                self._pubsub.unsubscribe(channel)
            except Exception as exc:
                logger.warning("PubSubManager.unsubscribe error: %s", exc)

    def publish(self, channel: str, message: Any) -> int:
        """
        Publish a message to ``channel``.

        Returns the number of subscribers that received the message.
        """
        try:
            payload = json.dumps(message, default=str)
            return int(self._client.publish(channel, payload))
        except Exception as exc:
            logger.warning("PubSubManager.publish error on %r: %s", channel, exc)
            return 0

    def start(self) -> None:
        """Start the background listener thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="pubsub-listener")
        self._thread.start()
        logger.info("PubSubManager: listener started")

    def stop(self) -> None:
        """Stop the background listener thread."""
        self._stop_event.set()
        if self._pubsub:
            with contextlib.suppress(Exception):
                self._pubsub.close()
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("PubSubManager: listener stopped")

    def _listen_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
                with self._lock:
                    channels = list(self._callbacks.keys())
                if channels:
                    self._pubsub.subscribe(*channels)
                for message in self._pubsub.listen():
                    if self._stop_event.is_set():
                        break
                    if message and message.get("type") == "message":
                        channel = message.get("channel", "")
                        if isinstance(channel, bytes):
                            channel = channel.decode()
                        try:
                            data = json.loads(message.get("data", "{}"))
                        except Exception:
                            data = message.get("data")
                        with self._lock:
                            cbs = list(self._callbacks.get(channel, []))
                        for cb in cbs:
                            try:
                                cb(data)
                            except Exception as exc:
                                logger.warning("PubSubManager callback error on %r: %s", channel, exc)
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning(
                        "PubSubManager: connection lost (%s) — reconnecting in %.1fs",
                        exc,
                        self._reconnect_delay,
                    )
                    time.sleep(self._reconnect_delay)


# ── Redis Streams consumer group ──────────────────────────────────────────────


class StreamConsumerGroup:
    """
    Redis Streams producer/consumer with consumer group semantics.

    Provides:
    - XADD for publishing messages to a stream
    - XREADGROUP for consuming messages as part of a named group
    - XACK for acknowledging processed messages
    - Dead-letter handling: messages that fail ``max_retries`` times are
      moved to a dead-letter stream (``{stream_name}:dead``)
    - Automatic group creation on first use

    Usage::

        scg = StreamConsumerGroup(
            client=redis_client,
            stream="hopefx:ticks",
            group="ml-pipeline",
            consumer="worker-1",
        )
        # Producer
        scg.publish({"bid": 2300.0, "ask": 2301.0, "symbol": "XAU_USD"})

        # Consumer
        for msg_id, fields in scg.read(count=10, block_ms=1000):
            process(fields)
            scg.ack(msg_id)
    """

    def __init__(
        self,
        client: Any,
        stream: str,
        group: str,
        consumer: str,
        max_len: int = 100_000,
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._max_len = max_len
        self._max_retries = max_retries
        self._dead_stream = f"{stream}:dead"
        self._ensure_group()

    def _ensure_group(self) -> None:
        """Create the consumer group if it does not exist."""
        try:
            self._client.xgroup_create(self._stream, self._group, id="0", mkstream=True)
            logger.info(
                "StreamConsumerGroup: created group %r on stream %r",
                self._group,
                self._stream,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                logger.debug("StreamConsumerGroup._ensure_group: %s", exc)

    def publish(self, fields: dict[str, Any]) -> str | None:
        """
        Append a message to the stream.

        Args:
            fields: Dict of field→value pairs. Values are JSON-serialised.

        Returns:
            The message ID assigned by Redis, or None on failure.
        """
        try:
            serialised = {k: json.dumps(v, default=str) for k, v in fields.items()}
            msg_id = self._client.xadd(self._stream, serialised, maxlen=self._max_len, approximate=True)
            return msg_id.decode() if isinstance(msg_id, bytes) else msg_id
        except Exception as exc:
            logger.warning("StreamConsumerGroup.publish error: %s", exc)
            return None

    def read(self, count: int = 10, block_ms: int = 0) -> list[tuple[str, dict[str, Any]]]:
        """
        Read up to ``count`` unacknowledged messages from the group.

        Args:
            count: Maximum messages to return.
            block_ms: Milliseconds to block waiting for new messages (0 = no block).

        Returns:
            List of (message_id, fields_dict) tuples.
        """
        try:
            raw = self._client.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: ">"},
                count=count,
                block=block_ms if block_ms > 0 else None,
            )
            if not raw:
                return []
            results = []
            for _stream_name, messages in raw:
                for msg_id, fields in messages:
                    mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                    decoded = {}
                    for k, v in fields.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        try:
                            decoded[key] = json.loads(val)
                        except Exception:
                            decoded[key] = val
                    results.append((mid, decoded))
            return results
        except Exception as exc:
            logger.warning("StreamConsumerGroup.read error: %s", exc)
            return []

    def ack(self, *message_ids: str, _retry: bool = True) -> int:
        """
        Acknowledge one or more message IDs. Returns count acknowledged.

        On transient Redis errors the XACK is retried once after a short
        delay.  If the retry also fails the error is logged and 0 is returned
        so the caller can decide whether to re-queue or dead-letter the message.
        Unacknowledged messages remain in the PEL and will be reclaimed by
        reprocess_pending() on the next cycle.
        """
        if not message_ids:
            return 0
        try:
            return int(self._client.xack(self._stream, self._group, *message_ids))
        except Exception as exc:
            if _retry:
                logger.warning("StreamConsumerGroup.ack error (will retry once): %s", exc)
                import time as _time

                _time.sleep(0.1)
                return self.ack(*message_ids, _retry=False)
            logger.error(
                "StreamConsumerGroup.ack failed after retry for ids=%s stream=%s group=%s: %s",
                message_ids,
                self._stream,
                self._group,
                exc,
            )
            return 0

    def reprocess_pending(self, idle_ms: int = 60_000) -> list[tuple[str, dict]]:
        """
        Claim and return messages that have been pending longer than ``idle_ms``.

        Messages that have been claimed more than ``max_retries`` times are
        moved to the dead-letter stream and acknowledged.
        """
        results = []
        try:
            pending = self._client.xpending_range(self._stream, self._group, min="-", max="+", count=50)
            for entry in pending:
                msg_id = entry["message_id"]
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode()
                delivery_count = entry.get("times_delivered", 0)
                idle = entry.get("time_since_delivered", 0)

                if idle < idle_ms:
                    continue

                if delivery_count > self._max_retries:
                    # Move to dead-letter stream, then XACK regardless of
                    # whether the XADD succeeded.  Without the unconditional
                    # XACK the message stays in the PEL forever and
                    # reprocess_pending() loops on it indefinitely.
                    dead_letter_written = False
                    try:
                        raw = self._client.xrange(self._stream, min=msg_id, max=msg_id)
                        if raw:
                            _, fields = raw[0]
                            # Annotate with provenance metadata.
                            dl_fields = dict(fields)
                            dl_fields[b"_original_id"] = msg_id.encode() if isinstance(msg_id, str) else msg_id
                            dl_fields[b"_delivery_count"] = str(delivery_count).encode()
                            dl_fields[b"_dead_lettered_at"] = str(time.time()).encode()
                            self._client.xadd(self._dead_stream, dl_fields, maxlen=10_000, approximate=True)
                            dead_letter_written = True
                    except Exception as exc:
                        logger.error(
                            "StreamConsumerGroup: dead-letter XADD failed for %r: %s — "
                            "will XACK anyway to prevent infinite PEL loop.",
                            msg_id,
                            exc,
                        )
                    finally:
                        # Always XACK: if dead-letter write failed the message
                        # is lost, but that is preferable to an infinite loop.
                        acked = self.ack(msg_id)
                        if dead_letter_written:
                            logger.warning(
                                "StreamConsumerGroup: dead-lettered %r after %d retries (acked=%d)",
                                msg_id,
                                delivery_count,
                                acked,
                            )
                        else:
                            logger.error(
                                "StreamConsumerGroup: dropped %r after %d retries (dead-letter write failed, acked=%d)",
                                msg_id,
                                delivery_count,
                                acked,
                            )
                    continue

                # Claim the message
                try:
                    claimed = self._client.xclaim(
                        self._stream,
                        self._group,
                        self._consumer,
                        min_idle_time=idle_ms,
                        message_ids=[msg_id],
                    )
                    for cid, fields in claimed:
                        cid_str = cid.decode() if isinstance(cid, bytes) else cid
                        decoded = {}
                        for k, v in fields.items():
                            key = k.decode() if isinstance(k, bytes) else k
                            val = v.decode() if isinstance(v, bytes) else v
                            try:
                                decoded[key] = json.loads(val)
                            except Exception:
                                decoded[key] = val
                        results.append((cid_str, decoded))
                except Exception as exc:
                    logger.debug("StreamConsumerGroup.xclaim error for %r: %s", msg_id, exc)
        except Exception as exc:
            logger.warning("StreamConsumerGroup.reprocess_pending error: %s", exc)
        return results

    def stream_info(self) -> dict:
        """Return stream length and group lag."""
        try:
            length = self._client.xlen(self._stream)
            groups = self._client.xinfo_groups(self._stream)
            group_info = next(
                (g for g in groups if (g.get("name") or b"").decode() == self._group),
                {},
            )
            return {
                "stream": self._stream,
                "length": length,
                "group": self._group,
                "pending": group_info.get("pending", 0),
                "last_delivered_id": (group_info.get("last-delivered-id") or b"").decode(),
            }
        except Exception as exc:
            logger.warning("StreamConsumerGroup.stream_info error: %s", exc)
            return {"stream": self._stream, "error": str(exc)}
