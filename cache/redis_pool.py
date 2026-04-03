# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
cache/redis_pool.py
===================
Centralised Redis connection-pool singleton.

Why a singleton pool?
---------------------
Creating a new ``redis.Redis`` instance per request allocates a new TCP socket
each time.  Under load this exhausts file descriptors and adds 10-50 ms of
TCP handshake latency per operation.  A ``ConnectionPool`` keeps a bounded set
of persistent connections and reuses them across threads.

Usage
-----
    from cache.redis_pool import get_redis_pool, get_sync_client, get_async_client

    # Synchronous (threaded) code
    r = get_sync_client()
    r.set("key", "value", ex=60)

    # Asynchronous code (FastAPI / asyncio)
    r = await get_async_client()
    await r.set("key", "value", ex=60)

Configuration (environment variables)
--------------------------------------
REDIS_URL          — Full Redis URL (default: redis://localhost:6379/0)
REDIS_MAX_CONNECTIONS   — Pool upper bound (default: 50)
REDIS_SOCKET_TIMEOUT    — Socket read/write timeout in seconds (default: 5)
REDIS_SOCKET_CONNECT_TIMEOUT — Socket connect timeout in seconds (default: 3)
REDIS_SOCKET_KEEPALIVE  — Enable TCP keepalive (default: true)
REDIS_HEALTH_CHECK_INTERVAL — Seconds between health pings (default: 30)
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    import redis
    from redis import ConnectionPool, Redis

    SYNC_REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    SYNC_REDIS_AVAILABLE = False
    ConnectionPool = None  # type: ignore[assignment,misc]
    Redis = None  # type: ignore[assignment,misc]

try:
    from redis import asyncio as aioredis

    ASYNC_REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    ASYNC_REDIS_AVAILABLE = False
    aioredis = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_MAX_CONNECTIONS: int = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
_SOCKET_TIMEOUT: float = float(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
_SOCKET_CONNECT_TIMEOUT: float = float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "3"))
_KEEPALIVE: bool = os.getenv("REDIS_SOCKET_KEEPALIVE", "true").lower() in ("true", "1", "yes")
_HEALTH_CHECK_INTERVAL: int = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))

# ---------------------------------------------------------------------------
# Singleton state — protected by a threading.Lock for thread safety
# ---------------------------------------------------------------------------

_lock: threading.Lock = threading.Lock()
_sync_pool: "ConnectionPool | None" = None
_sync_client: "Redis | None" = None
_async_client: "aioredis.Redis | None" = None  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_redis_pool() -> "ConnectionPool":
    """
    Return the process-wide synchronous Redis ``ConnectionPool``, creating it
    on first call.

    Raises:
        RuntimeError: If the ``redis`` package is not installed.
    """
    global _sync_pool  # noqa: PLW0603
    if not SYNC_REDIS_AVAILABLE:
        raise RuntimeError(
            "redis package not installed.  "
            "Fix with: pip install 'redis[hiredis]>=4.2'"
        )
    if _sync_pool is not None:
        return _sync_pool
    with _lock:
        if _sync_pool is None:
            _sync_pool = ConnectionPool.from_url(
                _REDIS_URL,
                max_connections=_MAX_CONNECTIONS,
                socket_timeout=_SOCKET_TIMEOUT,
                socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT,
                socket_keepalive=_KEEPALIVE,
                health_check_interval=_HEALTH_CHECK_INTERVAL,
                decode_responses=False,
            )
            logger.info(
                "Redis connection pool created: url=%s max_connections=%d",
                _REDIS_URL,
                _MAX_CONNECTIONS,
            )
    return _sync_pool


def get_sync_client() -> "Redis":
    """
    Return a synchronous ``redis.Redis`` client backed by the shared pool.

    The client is a process-wide singleton — it is safe to share across
    threads because the underlying ``ConnectionPool`` serialises checkouts.

    Raises:
        RuntimeError: If the ``redis`` package is not installed.
    """
    global _sync_client  # noqa: PLW0603
    if _sync_client is not None:
        return _sync_client
    with _lock:
        if _sync_client is None:
            pool = get_redis_pool()
            _sync_client = Redis(connection_pool=pool)
            logger.debug("Shared sync Redis client created from pool")
    return _sync_client


async def get_async_client() -> "aioredis.Redis":  # type: ignore[name-defined]
    """
    Return an async ``redis.asyncio.Redis`` client backed by its own pool.

    A new client is created the first time this coroutine is awaited; the
    same client is reused afterwards.

    Raises:
        RuntimeError: If the ``redis`` package is not installed.
    """
    global _async_client  # noqa: PLW0603
    if not ASYNC_REDIS_AVAILABLE:
        raise RuntimeError(
            "redis[asyncio] not installed.  "
            "Fix with: pip install 'redis[hiredis]>=4.2'"
        )
    if _async_client is not None:
        return _async_client
    with _lock:
        if _async_client is None:
            _async_client = aioredis.from_url(
                _REDIS_URL,
                max_connections=_MAX_CONNECTIONS,
                socket_timeout=_SOCKET_TIMEOUT,
                socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT,
                socket_keepalive=_KEEPALIVE,
                health_check_interval=_HEALTH_CHECK_INTERVAL,
                decode_responses=False,
            )
            logger.debug("Shared async Redis client created from pool")
    return _async_client


def reset_pool() -> None:
    """
    Tear down and reset the connection pool (used in tests and graceful
    shutdown paths).  All existing connections are closed.
    """
    global _sync_pool, _sync_client, _async_client  # noqa: PLW0603
    with _lock:
        if _sync_pool is not None:
            try:
                _sync_pool.disconnect()
            except Exception as exc:  # pragma: no cover
                logger.debug("Pool disconnect error: %s", exc)
        _sync_pool = None
        _sync_client = None
        _async_client = None
        logger.info("Redis connection pool reset")


def pool_stats() -> dict:
    """
    Return diagnostic statistics about the current pool state.

    Returns:
        Dict with keys: ``available``, ``in_use``, ``max_connections``,
        ``url``, ``pool_created``.  All counts are 0 when the pool has not
        yet been initialised.
    """
    if _sync_pool is None:
        return {
            "pool_created": False,
            "available": 0,
            "in_use": 0,
            "max_connections": _MAX_CONNECTIONS,
            "url": _REDIS_URL,
        }
    # ConnectionPool exposes _created_connections and _available_connections
    # as implementation details — access defensively.
    created = getattr(_sync_pool, "_created_connections", 0)
    available_set = getattr(_sync_pool, "_available_connections", set())
    available = len(available_set) if hasattr(available_set, "__len__") else 0
    return {
        "pool_created": True,
        "available": available,
        "in_use": created - available,
        "max_connections": _MAX_CONNECTIONS,
        "url": _REDIS_URL,
    }
