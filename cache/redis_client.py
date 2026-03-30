# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
cache/redis_client.py
=====================
Sentinel-aware Redis client factory.

Priority
--------
1. REDIS_SENTINEL_HOSTS set  → connect via Sentinel (HA mode)
2. REDIS_URL set             → connect directly (single-node / dev)
3. Neither                   → return None (caller degrades gracefully)

Usage
-----
    from cache.redis_client import get_redis

    redis = await get_redis()
    if redis:
        await redis.set("key", "value")

The returned client is a standard redis.asyncio.Redis instance regardless
of whether Sentinel or direct mode is used — callers need no changes.

Sentinel reconnection
---------------------
redis-py's Sentinel client handles master discovery and automatic reconnection
after failover transparently. The app does not need to handle failover events.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level singleton — one client per process
_redis_instance: Optional[object] = None
_sentinel_instance: Optional[object] = None


def _parse_sentinel_hosts(hosts_str: str) -> list[tuple[str, int]]:
    """Parse 'host1:port1,host2:port2' into [(host, port), ...]."""
    result = []
    for entry in hosts_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            host, port_str = entry.rsplit(":", 1)
            result.append((host.strip(), int(port_str.strip())))
        else:
            result.append((entry, 26379))
    return result


async def get_redis(
    *,
    db: int = 0,
    decode_responses: bool = True,
) -> Optional[object]:
    """
    Return a connected Redis client (Sentinel-aware).

    Returns None if neither REDIS_SENTINEL_HOSTS nor REDIS_URL is configured,
    so callers can degrade gracefully without crashing.
    """
    global _redis_instance, _sentinel_instance

    if _redis_instance is not None:
        return _redis_instance

    sentinel_hosts_str = os.getenv("REDIS_SENTINEL_HOSTS", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    password = os.getenv("REDIS_PASSWORD", "") or None
    master_name = os.getenv("REDIS_SENTINEL_MASTER", "hopefx-master")

    # ── Sentinel mode ─────────────────────────────────────────────────────────
    if sentinel_hosts_str:
        try:
            from redis.asyncio.sentinel import Sentinel

            hosts = _parse_sentinel_hosts(sentinel_hosts_str)
            logger.info(
                "Redis: connecting via Sentinel (master=%s, sentinels=%s)",
                master_name, hosts,
            )
            sentinel = Sentinel(
                hosts,
                sentinel_kwargs={"password": password, "socket_timeout": 2.0},
                password=password,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
                decode_responses=decode_responses,
                db=db,
            )
            # master_for() returns a client that always points to the current master
            client = sentinel.master_for(master_name)
            # Verify connectivity
            await client.ping()
            _sentinel_instance = sentinel
            _redis_instance = client
            logger.info("Redis Sentinel connected (master=%s)", master_name)
            return _redis_instance
        except Exception as exc:
            logger.error(
                "Redis Sentinel connection failed: %s — falling back to direct URL", exc
            )

    # ── Direct URL mode ───────────────────────────────────────────────────────
    if redis_url:
        try:
            import redis.asyncio as aioredis

            logger.info("Redis: connecting directly via URL")
            client = aioredis.from_url(
                redis_url,
                decode_responses=decode_responses,
                db=db,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
            )
            await client.ping()
            _redis_instance = client
            logger.info("Redis direct connection established")
            return _redis_instance
        except Exception as exc:
            logger.error("Redis direct connection failed: %s", exc)
            return None

    logger.warning(
        "Redis: neither REDIS_SENTINEL_HOSTS nor REDIS_URL configured — "
        "running without Redis (degraded mode)"
    )
    return None


def reset_redis_client() -> None:
    """Force re-initialisation on next get_redis() call. Used in tests."""
    global _redis_instance, _sentinel_instance
    _redis_instance = None
    _sentinel_instance = None


async def get_sentinel() -> Optional[object]:
    """Return the raw Sentinel instance (for replica reads, monitoring)."""
    await get_redis()  # ensure initialised
    return _sentinel_instance
