# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
# pylint: disable=broad-exception-caught,global-statement
"""
cache/redis_client.py
=====================
Sentinel-aware, Cluster-aware Redis client factory with health monitoring.

Priority
--------
1. REDIS_CLUSTER_HOSTS set   → connect via Redis Cluster (sharded HA mode)
2. REDIS_SENTINEL_HOSTS set  → connect via Sentinel (replicated HA mode)
3. REDIS_URL set             → connect directly (single-node / dev)
4. Neither                   → return None (caller degrades gracefully)

Usage
-----
    from cache.redis_client import get_redis, get_health

    redis = await get_redis()
    if redis:
        await redis.set("key", "value")

    health = await get_health()
    # {"mode": "sentinel", "connected": True, "master": "hopefx-master", ...}

Sentinel reconnection
---------------------
redis-py's Sentinel client handles master discovery and automatic reconnection
after failover transparently. The app does not need to handle failover events.

Cluster mode
------------
RedisCluster handles slot routing, node discovery, and automatic failover.
Use REDIS_CLUSTER_HOSTS=node1:6379,node2:6379,node3:6379 to enable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Module-level singletons — one client per process
_redis_instance: Any | None = None
_sentinel_instance: Any | None = None
_connection_mode: str = "none"  # "cluster" | "sentinel" | "direct" | "none"
_last_health_check: float = 0.0
_health_check_interval: float = float(os.getenv("REDIS_HEALTH_INTERVAL", "30"))


def _parse_hosts(hosts_str: str, default_port: int = 6379) -> list[tuple[str, int]]:
    """Parse 'host1:port1,host2:port2' into [(host, port), ...]."""
    result = []
    for _entry in hosts_str.split(","):
        entry = _entry.strip()
        if not entry:
            continue
        if ":" in entry:
            host, port_str = entry.rsplit(":", 1)
            result.append((host.strip(), int(port_str.strip())))
        else:
            result.append((entry, default_port))
    return result


async def _try_cluster(
    hosts_str: str,
    password: str | None,
    decode_responses: bool,
    db: int,  # pylint: disable=unused-argument  # cluster mode ignores db
) -> Any | None:
    """Attempt Redis Cluster connection. Returns client or None."""
    try:
        from redis.asyncio.cluster import RedisCluster
        from redis.asyncio.cluster import ClusterNode

        hosts = _parse_hosts(hosts_str)
        startup_nodes = [ClusterNode(h, p) for h, p in hosts]
        logger.info("Redis: connecting via Cluster (nodes=%s)", hosts)
        client = RedisCluster(
            startup_nodes=startup_nodes,
            password=password,
            decode_responses=decode_responses,
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            # Cluster mode ignores db parameter — always db=0
            skip_full_coverage_check=True,
            retry_on_timeout=True,
        )
        await client.ping()
        logger.info("Redis Cluster connected (%d startup nodes)", len(startup_nodes))
        return client
    except ImportError:
        logger.warning("redis-py cluster support not available — install redis[hiredis]>=4.6")
        return None
    except Exception as exc:
        logger.error("Redis Cluster connection failed: %s", exc)
        return None


async def _try_sentinel(
    hosts_str: str,
    master_name: str,
    password: str | None,
    decode_responses: bool,
    db: int,
) -> tuple[Any | None, Any | None]:
    """Attempt Redis Sentinel connection. Returns (client, sentinel) or (None, None)."""
    try:
        from redis.asyncio.sentinel import Sentinel

        hosts = _parse_hosts(hosts_str, default_port=26379)
        logger.info(
            "Redis: connecting via Sentinel (master=%s, sentinels=%s)",
            master_name,
            hosts,
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
        await client.ping()
        logger.info("Redis Sentinel connected (master=%s)", master_name)
        return client, sentinel
    except Exception as exc:
        logger.error("Redis Sentinel connection failed: %s — falling back to direct URL", exc)
        return None, None


async def _try_direct(
    redis_url: str,
    decode_responses: bool,
    db: int,
) -> Any | None:
    """Attempt direct Redis URL connection. Returns client or None."""
    try:
        import redis.asyncio as aioredis

        logger.info("Redis: connecting directly via URL")
        client = aioredis.from_url(
            redis_url,
            decode_responses=decode_responses,
            db=db,
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            retry_on_timeout=True,
        )
        await client.ping()
        logger.info("Redis direct connection established")
        return client
    except Exception as exc:
        logger.error("Redis direct connection failed: %s", exc)
        return None


async def get_redis(
    *,
    db: int = 0,
    decode_responses: bool = True,
) -> Any | None:
    """
    Return a connected Redis client (Cluster → Sentinel → direct fallback chain).

    Returns None if no Redis is configured or all connection attempts fail,
    so callers can degrade gracefully without crashing.
    """
    global _redis_instance, _sentinel_instance, _connection_mode

    if _redis_instance is not None:
        # Periodic health check — reconnect if stale
        now = time.monotonic()
        if now - _last_health_check > _health_check_interval:
            await _ping_or_reset()
        return _redis_instance

    cluster_hosts = os.getenv("REDIS_CLUSTER_HOSTS", "").strip()
    sentinel_hosts = os.getenv("REDIS_SENTINEL_HOSTS", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    password = os.getenv("REDIS_PASSWORD", "") or None
    master_name = os.getenv("REDIS_SENTINEL_MASTER", "hopefx-master")

    # ── 1. Cluster mode ───────────────────────────────────────────────────────
    if cluster_hosts:
        client = await _try_cluster(cluster_hosts, password, decode_responses, db)
        if client is not None:
            _redis_instance = client
            _connection_mode = "cluster"
            return _redis_instance

    # ── 2. Sentinel mode ──────────────────────────────────────────────────────
    if sentinel_hosts:
        client, sentinel = await _try_sentinel(sentinel_hosts, master_name, password, decode_responses, db)
        if client is not None:
            _redis_instance = client
            _sentinel_instance = sentinel
            _connection_mode = "sentinel"
            return _redis_instance

    # ── 3. Direct URL mode ────────────────────────────────────────────────────
    if redis_url:
        client = await _try_direct(redis_url, decode_responses, db)
        if client is not None:
            _redis_instance = client
            _connection_mode = "direct"
            return _redis_instance

    logger.warning(
        "Redis: no connection configured (REDIS_CLUSTER_HOSTS / "
        "REDIS_SENTINEL_HOSTS / REDIS_URL) — running in degraded mode"
    )
    _connection_mode = "none"
    return None


async def _ping_or_reset() -> None:
    """Ping the current client; reset singleton on failure so next call reconnects."""
    global _redis_instance, _sentinel_instance, _connection_mode, _last_health_check
    _last_health_check = time.monotonic()
    try:
        await _redis_instance.ping()
    except Exception as exc:
        logger.warning("Redis health check failed (%s) — will reconnect on next call", exc)
        _redis_instance = None
        _sentinel_instance = None
        _connection_mode = "none"


async def get_health() -> dict[str, Any]:
    """
    Return a health snapshot for the current Redis connection.

    Used by /health endpoints and monitoring dashboards.
    """
    client = await get_redis()
    if client is None:
        return {"mode": _connection_mode, "connected": False, "error": "no client"}

    try:
        latency_start = time.monotonic()
        await client.ping()
        latency_ms = (time.monotonic() - latency_start) * 1000

        info: dict[str, Any] = {
            "mode": _connection_mode,
            "connected": True,
            "latency_ms": round(latency_ms, 2),
        }

        # Sentinel: report current master address
        if _connection_mode == "sentinel" and _sentinel_instance is not None:
            try:
                master_name = os.getenv("REDIS_SENTINEL_MASTER", "hopefx-master")
                master_info = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _sentinel_instance.discover_master(master_name),
                )
                info["master"] = f"{master_info[0]}:{master_info[1]}"
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # Cluster: report cluster info
        if _connection_mode == "cluster":
            try:
                cluster_info = await client.cluster_info()
                info["cluster_state"] = cluster_info.get("cluster_state", "unknown")
                info["cluster_slots_ok"] = cluster_info.get("cluster_slots_ok", 0)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        return info
    except Exception as exc:
        return {"mode": _connection_mode, "connected": False, "error": str(exc)}


def reset_redis_client() -> None:
    """Force re-initialisation on next get_redis() call. Used in tests."""
    global _redis_instance, _sentinel_instance, _connection_mode
    _redis_instance = None
    _sentinel_instance = None
    _connection_mode = "none"


async def get_sentinel() -> Any | None:
    """Return the raw Sentinel instance (for replica reads, monitoring)."""
    await get_redis()  # ensure initialised
    return _sentinel_instance


def get_connection_mode() -> str:
    """Return the active connection mode: 'cluster' | 'sentinel' | 'direct' | 'none'."""
    return _connection_mode
