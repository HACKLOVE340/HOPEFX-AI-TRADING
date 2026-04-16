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

# Suppress repeated "no config" / "connection failed" log noise.
# After the first warning we downgrade subsequent identical messages to DEBUG.
_no_config_warned: bool = False
_connect_failed_warned: bool = False


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
    global _connect_failed_warned
    try:
        from redis.asyncio.cluster import ClusterNode, RedisCluster  # pylint: disable=no-name-in-module

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
        _connect_failed_warned = False  # reset on success
        return client
    except ImportError:
        logger.warning("redis-py cluster support not available — install redis[hiredis]>=4.6")
        return None
    except Exception as exc:
        if not _connect_failed_warned:
            logger.error("Redis Cluster connection failed: %s", exc)
            _connect_failed_warned = True
        else:
            logger.debug("Redis Cluster connection failed (suppressed repeat): %s", exc)
        return None


async def _try_sentinel(
    hosts_str: str,
    master_name: str,
    password: str | None,
    decode_responses: bool,
    db: int,
) -> tuple[Any | None, Any | None]:
    """Attempt Redis Sentinel connection. Returns (client, sentinel) or (None, None)."""
    global _connect_failed_warned
    try:
        from redis.asyncio.sentinel import Sentinel  # pylint: disable=no-name-in-module

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
        _connect_failed_warned = False  # reset on success
        return client, sentinel
    except Exception as exc:
        if not _connect_failed_warned:
            logger.error("Redis Sentinel connection failed: %s — falling back to direct URL", exc)
            _connect_failed_warned = True
        else:
            logger.debug("Redis Sentinel connection failed (suppressed repeat): %s", exc)
        return None, None


def _enforce_tls(redis_url: str) -> str:
    """
    Enforce TLS in production environments.

    In production (APP_ENV=production) a plaintext redis:// URL is a
    security misconfiguration — credentials and session tokens travel in
    the clear.  This function:
      - Raises RuntimeError if APP_ENV=production and the URL is redis://
        (not rediss://).  The caller must fix the URL before deploying.
      - Automatically upgrades redis:// → rediss:// when
        REDIS_FORCE_TLS=true is set (useful for staging environments that
        share the same config as production but haven't updated the URL).
      - Logs a WARNING in non-production environments so operators notice
        the plaintext connection without blocking startup.

    Set REDIS_TLS_SKIP_VERIFY=true only in controlled test environments
    where the Redis server uses a self-signed certificate.
    """
    app_env = os.getenv("APP_ENV", "development").lower()
    force_tls = os.getenv("REDIS_FORCE_TLS", "false").lower() == "true"
    is_plaintext = redis_url.startswith("redis://")

    if not is_plaintext:
        return redis_url  # already rediss:// or unix socket — nothing to do

    if force_tls:
        upgraded = "rediss://" + redis_url[len("redis://") :]
        logger.info("Redis: REDIS_FORCE_TLS=true — upgraded URL to rediss://")
        return upgraded

    if app_env == "production":
        raise RuntimeError(
            "Redis TLS required in production: REDIS_URL must use rediss:// (not redis://). "
            "Update REDIS_URL to rediss://<host>:<port>/<db> or set REDIS_FORCE_TLS=true "
            "to auto-upgrade. This check prevents credentials from being sent in plaintext."
        )

    logger.warning(
        "Redis: plaintext redis:// connection in %s environment. "
        "Use rediss:// in production or set REDIS_FORCE_TLS=true.",
        app_env,
    )
    return redis_url


async def _try_direct(
    redis_url: str,
    decode_responses: bool,
    db: int,
) -> Any | None:
    """Attempt direct Redis URL connection. Returns client or None.

    TLS notes (redis-py 7.x)
    ------------------------
    redis-py 7.x does not accept an ``ssl.SSLContext`` object via the
    ``ssl=`` kwarg — ``AbstractConnection.__init__`` only knows the
    individual ``ssl_*`` keyword arguments.  For TLS connections we
    therefore build a ``ConnectionPool`` explicitly using ``SSLConnection``
    and the individual cert/key/ca params, rather than passing a context
    object through ``from_url()``.
    """
    global _connect_failed_warned
    try:
        import redis.asyncio as aioredis  # pylint: disable=no-name-in-module

        # Enforce TLS policy before connecting.
        redis_url = _enforce_tls(redis_url)

        is_tls = redis_url.startswith("rediss://")

        if is_tls:
            # Build a ConnectionPool with SSLConnection so we can pass the
            # individual ssl_* params that redis-py 7.x actually accepts.
            skip_verify = os.getenv("REDIS_TLS_SKIP_VERIFY", "false").lower() == "true"
            if skip_verify:
                logger.warning("Redis TLS: certificate verification disabled (REDIS_TLS_SKIP_VERIFY=true)")

            ssl_kwargs: dict = {
                "ssl_cert_reqs": "none" if skip_verify else "required",
            }
            ca_cert = os.getenv("REDIS_TLS_CA_CERT", "")
            client_cert = os.getenv("REDIS_TLS_CLIENT_CERT", "")
            client_key = os.getenv("REDIS_TLS_CLIENT_KEY", "")
            if ca_cert:
                ssl_kwargs["ssl_ca_certs"] = ca_cert
            if client_cert:
                ssl_kwargs["ssl_certfile"] = client_cert
            if client_key:
                ssl_kwargs["ssl_keyfile"] = client_key

            pool = aioredis.ConnectionPool.from_url(
                redis_url,
                decode_responses=decode_responses,
                db=db,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
                **ssl_kwargs,
            )
            client = aioredis.Redis(connection_pool=pool)
        else:
            # Plaintext connection — from_url() is sufficient.
            client = aioredis.from_url(
                redis_url,
                decode_responses=decode_responses,
                db=db,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
                retry_on_timeout=True,
            )

        logger.info("Redis: connecting directly via URL (tls=%s)", is_tls)
        await client.ping()
        logger.info("Redis direct connection established (tls=%s)", is_tls)
        _connect_failed_warned = False  # reset on success
        return client
    except RuntimeError:
        raise  # re-raise TLS enforcement errors — do not swallow
    except Exception as exc:
        if not _connect_failed_warned:
            logger.error("Redis direct connection failed: %s", exc)
            _connect_failed_warned = True
        else:
            logger.debug("Redis direct connection failed (suppressed repeat): %s", exc)
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
    global _redis_instance, _sentinel_instance, _connection_mode, _no_config_warned

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
            _no_config_warned = False
            return _redis_instance

    # ── 2. Sentinel mode ──────────────────────────────────────────────────────
    if sentinel_hosts:
        client, sentinel = await _try_sentinel(sentinel_hosts, master_name, password, decode_responses, db)
        if client is not None:
            _redis_instance = client
            _sentinel_instance = sentinel
            _connection_mode = "sentinel"
            _no_config_warned = False
            return _redis_instance

    # ── 3. Direct URL mode ────────────────────────────────────────────────────
    if redis_url:
        client = await _try_direct(redis_url, decode_responses, db)
        if client is not None:
            _redis_instance = client
            _connection_mode = "direct"
            _no_config_warned = False
            return _redis_instance

    if not _no_config_warned:
        logger.warning(
            "Redis: no connection configured (REDIS_CLUSTER_HOSTS / "
            "REDIS_SENTINEL_HOSTS / REDIS_URL) — running in degraded mode"
        )
        _no_config_warned = True
    else:
        logger.debug("Redis: still unconfigured — degraded mode (suppressed repeat)")
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
                master_info = await asyncio.get_running_loop().run_in_executor(
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
    except Exception:
        logger.exception("Redis health check failed: %s")
        return {"mode": _connection_mode, "connected": False, "error": "Redis unavailable — check server logs"}


def reset_redis_client() -> None:
    """Force re-initialisation on next get_redis() call. Used in tests."""
    global _redis_instance, _sentinel_instance, _connection_mode
    global _no_config_warned, _connect_failed_warned
    _redis_instance = None
    _sentinel_instance = None
    _connection_mode = "none"
    _no_config_warned = False
    _connect_failed_warned = False


async def get_sentinel() -> Any | None:
    """Return the raw Sentinel instance (for replica reads, monitoring)."""
    await get_redis()  # ensure initialised
    return _sentinel_instance


def get_connection_mode() -> str:
    """Return the active connection mode: 'cluster' | 'sentinel' | 'direct' | 'none'."""
    return _connection_mode


def get_sync_redis() -> Any | None:
    """
    Return a synchronous Redis client using the same env-var configuration as
    get_redis().  Falls back gracefully to None when Redis is unavailable.

    Used by components that cannot run in an async context (e.g. TCA recorder).
    """
    try:
        import redis as _redis_sync
    except ImportError:
        logger.debug("redis package not available for sync client")
        return None

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = _redis_sync.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception as exc:
        logger.debug("Sync Redis connection failed: %s", exc)
        return None


# Convenience alias used by many modules that call `get_redis_client()`
get_redis_client = get_redis
