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
# Emit the plaintext-TLS dev warning only once per process to avoid log flood.
_tls_warning_emitted: bool = False


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
            socket_timeout=1.0,
            socket_connect_timeout=0.5,
            # Cluster mode ignores db parameter — always db=0
            skip_full_coverage_check=True,
            retry_on_timeout=False,
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
            sentinel_kwargs={"password": password, "socket_timeout": 0.5},
            password=password,
            socket_timeout=1.0,
            socket_connect_timeout=0.5,
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
    Setting REDIS_TLS_SKIP_VERIFY=true with APP_ENV=production raises
    RuntimeError at connection time — this is intentional.
    """
    app_env = os.getenv("APP_ENV", "development").lower()
    # IS_FORCE_TLS is the canonical env var (user-facing); REDIS_FORCE_TLS is
    # the legacy alias.  IS_FORCE_TLS takes precedence when both are set.
    _is_force = os.getenv("IS_FORCE_TLS", "").lower()
    _redis_force = os.getenv("REDIS_FORCE_TLS", "false").lower()
    force_tls = (_is_force == "true") or (_redis_force == "true")
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

    # Warn once per process — plaintext in non-production is allowed but notable.
    global _tls_warning_emitted
    if not _tls_warning_emitted:
        logger.warning(
            "Redis: plaintext redis:// connection in %s environment. "
            "Use rediss:// in production or set REDIS_FORCE_TLS=true.",
            app_env,
        )
        _tls_warning_emitted = True
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
            app_env = os.getenv("APP_ENV", "development").lower()

            if skip_verify and app_env == "production":
                # Hard failure — disabling certificate verification in production
                # allows MITM attacks against the Redis connection, which carries
                # session tokens and the JWT revocation blacklist.
                raise RuntimeError(
                    "REDIS_TLS_SKIP_VERIFY=true is not permitted when APP_ENV=production. "
                    "Certificate verification must be enabled in production. "
                    "Provide a valid CA certificate via REDIS_TLS_CA_CERT, or use a "
                    "Redis server with a certificate signed by a trusted CA."
                )

            if skip_verify:
                logger.warning(
                    "Redis TLS: certificate verification disabled (REDIS_TLS_SKIP_VERIFY=true). "
                    "Only acceptable in controlled test environments with self-signed certs."
                )

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
                socket_timeout=1.0,
                socket_connect_timeout=0.5,
                **ssl_kwargs,
            )
            client = aioredis.Redis(connection_pool=pool)
        else:
            # Plaintext connection — from_url() is sufficient.
            client = aioredis.from_url(
                redis_url,
                decode_responses=decode_responses,
                db=db,
                socket_timeout=1.0,
                socket_connect_timeout=0.5,
                retry_on_timeout=False,
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

    Returns None if no Redis is configured, all connection attempts fail, or
    the redis_breaker circuit is OPEN (repeated failures detected).
    Callers degrade gracefully without crashing.
    """
    global _redis_instance, _sentinel_instance, _connection_mode, _no_config_warned

    # Fast-fail when the circuit breaker is open — don't attempt reconnect
    try:
        from resilience.service_circuit_breakers import redis_breaker as _rb

        if _rb.is_open:
            logger.debug(
                "get_redis: Redis circuit breaker OPEN — returning None. Retry in %.0fs.", _rb._seconds_until_probe()
            )
            return None
    except Exception:  # nosec B110 — circuit breaker is non-fatal  # noqa: S110
        pass

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
            "REDIS_SENTINEL_HOSTS / REDIS_URL) — trying fakeredis fallback"
        )
        _no_config_warned = True
    else:
        logger.debug("Redis: still unconfigured — trying fakeredis (suppressed repeat)")

    # Async fakeredis fallback — keeps all cache-dependent code paths working
    # in development/CI environments without a real Redis server.
    try:
        import fakeredis.aioredis as _fake_aio  # type: ignore[import]

        if _redis_instance is None:
            _redis_instance = _fake_aio.FakeRedis(decode_responses=decode_responses)
            _connection_mode = "fakeredis"
            logger.info("Using fakeredis async in-process Redis substitute")
        return _redis_instance
    except ImportError:  # nosec B110
        pass

    _connection_mode = "none"
    return None


async def _ping_or_reset() -> None:
    """Ping the current client; reset singleton on failure so next call reconnects."""
    global _redis_instance, _sentinel_instance, _connection_mode, _last_health_check
    _last_health_check = time.monotonic()
    try:
        await _redis_instance.ping()
        # Record success so the breaker can transition HALF_OPEN → CLOSED
        try:
            from resilience.service_circuit_breakers import redis_breaker as _rb

            _rb.record_success()
        except Exception:  # nosec B110  # noqa: S110
            pass
    except Exception as exc:
        logger.warning("Redis health check failed (%s) — will reconnect on next call", exc)
        _redis_instance = None
        _sentinel_instance = None
        _connection_mode = "none"
        # Record failure in circuit breaker
        try:
            from resilience.service_circuit_breakers import redis_breaker as _rb

            _rb.record_failure(exc)
        except Exception:  # nosec B110  # noqa: S110
            pass


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
        logger.exception("Redis health check failed")
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


async def execute_with_readonly_retry(
    client: Any,
    command: str,
    *args: Any,
    max_retries: int = 2,
    **kwargs: Any,
) -> Any:
    """
    Execute a Redis command with automatic retry on READONLY errors.

    In Sentinel mode a failover can briefly cause the client to be connected
    to a replica that returns ``READONLY You can't write against a read only
    replica``.  This helper catches that error, forces a client re-initialisation
    (which will discover the new master), and retries the command.

    Also handles RedisCluster MOVED/ASK redirects transparently — the
    redis-py Cluster client handles those internally, but we add an outer
    retry for transient connection errors during slot migration.

    Usage::

        await execute_with_readonly_retry(rc, "set", "key", "value", ex=30)
        await execute_with_readonly_retry(rc, "hset", "hash", "field", "value")
    """
    if client is None:
        return None

    for attempt in range(max_retries + 1):
        try:
            method = getattr(client, command)
            return await method(*args, **kwargs)
        except Exception as exc:
            exc_str = str(exc).upper()
            is_readonly = "READONLY" in exc_str
            is_moved = "MOVED" in exc_str or "ASK" in exc_str
            is_connection = "CONNECTION" in exc_str or "TIMEOUT" in exc_str

            if attempt < max_retries and (is_readonly or is_moved or is_connection):
                logger.warning(
                    "Redis %s error on attempt %d/%d (%s) — re-initialising client",
                    command,
                    attempt + 1,
                    max_retries,
                    exc_str[:80],
                )
                # Force re-initialisation so the next get_redis() discovers
                # the new master (Sentinel) or updated slot map (Cluster)
                global _redis_instance
                _redis_instance = None
                client = await get_redis()
                if client is None:
                    logger.error("Redis re-initialisation failed — giving up")
                    return None
                continue
            raise


# Module-level fakeredis singleton — shared across all callers so state is
# consistent within a single process (same as a real Redis server would be).
_fakeredis_instance: Any | None = None


def _get_or_create_fakeredis() -> Any:
    """Return the process-wide fakeredis instance, creating it on first call."""
    global _fakeredis_instance
    if _fakeredis_instance is None:
        import fakeredis as _fakeredis  # type: ignore[import]

        _fakeredis_instance = _fakeredis.FakeRedis(decode_responses=True)
    return _fakeredis_instance


def get_sync_redis() -> Any | None:
    """
    Return a synchronous Redis client using the same env-var configuration as
    get_redis().  Falls back gracefully to None when Redis is unavailable.

    Used by components that cannot run in an async context (e.g. superadmin
    endpoints, TCA recorder, Celery tasks).

    Password injection: if REDIS_PASSWORD is set and not already embedded in
    REDIS_URL, it is injected into the URL before connecting — matching the
    same logic used by EventBus, MarketDataCache, and ConfigStore.
    """
    try:
        import redis as _redis_sync
    except ImportError:
        logger.debug("redis package not available for sync client")
        return None

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    password = os.getenv("REDIS_PASSWORD", "") or None

    # Inject password when not already embedded in the URL.
    if password and "@" not in redis_url.split("://", 1)[-1]:
        scheme, rest = redis_url.split("://", 1)
        redis_url = f"{scheme}://:{password}@{rest}"

    try:
        client = _redis_sync.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=1.0,
        )
        client.ping()
        return client
    except Exception as exc:
        logger.debug("Sync Redis connection failed: %s — trying fakeredis fallback", exc)
        # In development/CI environments without a real Redis server, use
        # fakeredis as an in-process drop-in so all cache-dependent code paths
        # work correctly without requiring a running Redis instance.
        try:
            _fake = _get_or_create_fakeredis()
            logger.info("Using fakeredis in-process Redis substitute (no real Redis available)")
            return _fake
        except ImportError:
            logger.debug("fakeredis not installed — Redis unavailable")
            return None


# ── Aliases ───────────────────────────────────────────────────────────────────
# get_redis_client is the ASYNC client factory (aliased to get_redis).
# Always await it: `rc = await get_redis_client()`.
# For synchronous contexts use get_sync_redis() or get_sync_redis_client().
get_redis_client = get_redis

# Explicit sync alias for callers that need a synchronous client.
# Prefer this over get_redis_client in non-async code to avoid the
# "coroutine object has no attribute" error from forgetting await.
get_sync_redis_client = get_sync_redis


# ── Pipeline batching helper ──────────────────────────────────────────────────


class RedisPipelineBatch:
    """
    Async context manager that accumulates commands and executes them in a
    single pipeline flush, reducing round-trip overhead for bulk writes.

    Usage::

        async with RedisPipelineBatch(await get_redis()) as pipe:
            pipe.set("key1", "val1")
            pipe.set("key2", "val2")
            pipe.expire("key1", 60)
        # All three commands sent in one round-trip on __aexit__

    Falls back gracefully when the client is None (degraded mode).
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._pipe: Any = None

    async def __aenter__(self) -> RedisPipelineBatch:
        if self._client is not None:
            try:
                self._pipe = self._client.pipeline(transaction=False)
            except Exception as exc:
                logger.debug("RedisPipelineBatch: pipeline() failed: %s", exc)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._pipe is not None and exc_type is None:
            try:
                await self._pipe.execute()
            except Exception as exc:
                logger.warning("RedisPipelineBatch: execute() failed: %s", exc)
        self._pipe = None

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the underlying pipeline."""
        if self._pipe is not None:
            return getattr(self._pipe, name)

        # Return a no-op callable when pipeline is unavailable.
        # Intentional: callers queue pipeline commands that are silently
        # discarded when no pipeline connection exists, preventing crashes
        # during Redis unavailability.
        def _noop(*args: Any, **kwargs: Any) -> None:
            """No-op pipeline command — pipeline unavailable."""
            return None  # explicit return so body is not just pass/...

        return _noop


async def pipeline_batch(commands: list[tuple]) -> list[Any]:
    """
    Execute a list of (command_name, *args) tuples in a single pipeline.

    Args:
        commands: e.g. [("set", "k", "v"), ("expire", "k", 60)]

    Returns:
        List of results from each command, or empty list on failure.
    """
    client = await get_redis()
    if client is None:
        return []
    try:
        pipe = client.pipeline(transaction=False)
        for cmd, *args in commands:
            getattr(pipe, cmd)(*args)
        return await pipe.execute()
    except Exception as exc:
        logger.warning("pipeline_batch failed: %s", exc)
        return []


# ── Lua scripting support ─────────────────────────────────────────────────────

# Pre-defined Lua scripts for atomic operations.
# Scripts are registered once and called by SHA1 digest (EVALSHA) for
# minimal overhead on subsequent calls.

_LUA_SCRIPTS: dict[str, str] = {
    # Atomic compare-and-set: set key=value only if current value matches expected.
    # KEYS[1]=key, ARGV[1]=expected, ARGV[2]=new_value, ARGV[3]=ttl_seconds
    # Returns 1 on success, 0 if value did not match.
    "cas": """
        local cur = redis.call('GET', KEYS[1])
        if cur == ARGV[1] then
            redis.call('SETEX', KEYS[1], tonumber(ARGV[3]), ARGV[2])
            return 1
        end
        return 0
    """,
    # Atomic increment with TTL reset: increment counter and reset TTL.
    # KEYS[1]=key, ARGV[1]=increment, ARGV[2]=ttl_seconds
    # Returns new value.
    "incr_with_ttl": """
        local val = redis.call('INCRBY', KEYS[1], tonumber(ARGV[1]))
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        return val
    """,
    # Atomic get-and-delete: return value and delete key in one round-trip.
    # KEYS[1]=key
    # Returns the value or false.
    "get_del": """
        local val = redis.call('GET', KEYS[1])
        if val then
            redis.call('DEL', KEYS[1])
        end
        return val
    """,
    # Sliding-window rate limiter: allow at most ARGV[1] requests per ARGV[2] seconds.
    # KEYS[1]=rate_limit_key, ARGV[1]=max_requests, ARGV[2]=window_seconds
    # Returns 1 if allowed, 0 if rate-limited.
    "rate_limit": """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        local now = tonumber(redis.call('TIME')[1])
        local count = redis.call('INCR', key)
        if count == 1 then
            redis.call('EXPIRE', key, window)
        end
        if count > limit then
            return 0
        end
        return 1
    """,
}

# SHA1 digest cache — populated on first use
_script_shas: dict[str, str] = {}


async def eval_script(script_name: str, keys: list[str], args: list[str]) -> Any:
    """
    Execute a named Lua script via EVALSHA (cached) or EVAL (first call).

    Args:
        script_name: Key in _LUA_SCRIPTS.
        keys: KEYS array passed to the script.
        args: ARGV array passed to the script.

    Returns:
        Script return value, or None on failure.
    """
    if script_name not in _LUA_SCRIPTS:
        raise ValueError(f"Unknown Lua script {script_name!r}. Available: {sorted(_LUA_SCRIPTS)}")

    client = await get_redis()
    if client is None:
        return None

    script_body = _LUA_SCRIPTS[script_name]

    # Try EVALSHA first (uses cached SHA)
    if script_name in _script_shas:
        try:
            return await client.evalsha(_script_shas[script_name], len(keys), *keys, *args)
        except Exception as exc:
            if "NOSCRIPT" in str(exc):
                # Script was flushed from Redis script cache — fall through to EVAL
                del _script_shas[script_name]
            else:
                logger.warning("eval_script EVALSHA failed: %s", exc)
                return None

    # EVAL and cache the SHA
    try:
        result = await client.eval(script_body, len(keys), *keys, *args)
        # Cache the SHA for future calls
        try:
            sha = await client.script_load(script_body)
            _script_shas[script_name] = sha
        except Exception:  # nosec B110  # noqa: S110
            pass  # SHA caching is best-effort
        return result
    except Exception as exc:
        logger.warning("eval_script EVAL failed for %r: %s", script_name, exc)
        return None


# ── Connection health telemetry ───────────────────────────────────────────────

import threading as _threading


class RedisHealthTelemetry:
    """
    Tracks Redis connection health metrics over a rolling window.

    Metrics collected:
    - ping_latency_ms: rolling 50-sample window
    - command_latency_ms: rolling 200-sample window
    - error_count: total errors since last reset
    - reconnect_count: total reconnections
    - last_error: most recent error message
    - uptime_s: seconds since first successful connection
    """

    def __init__(self, window: int = 50) -> None:
        self._lock = _threading.Lock()
        self._ping_latencies: list[float] = []
        self._cmd_latencies: list[float] = []
        self._window = window
        self._error_count = 0
        self._reconnect_count = 0
        self._last_error: str = ""
        self._first_connected_at: float | None = None
        self._last_ping_at: float = 0.0

    def record_ping(self, latency_ms: float) -> None:
        with self._lock:
            if self._first_connected_at is None:
                self._first_connected_at = time.monotonic()
            self._ping_latencies.append(latency_ms)
            if len(self._ping_latencies) > self._window:
                self._ping_latencies.pop(0)
            self._last_ping_at = time.monotonic()

    def record_command(self, latency_ms: float) -> None:
        with self._lock:
            self._cmd_latencies.append(latency_ms)
            if len(self._cmd_latencies) > self._window * 4:
                self._cmd_latencies.pop(0)

    def record_error(self, exc: Exception) -> None:
        with self._lock:
            self._error_count += 1
            self._last_error = str(exc)[:200]

    def record_reconnect(self) -> None:
        with self._lock:
            self._reconnect_count += 1

    def _percentile(self, samples: list[float], pct: float) -> float:
        if not samples:
            return 0.0
        s = sorted(samples)
        idx = int(len(s) * pct / 100)
        return round(s[min(idx, len(s) - 1)], 3)

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.monotonic() - self._first_connected_at if self._first_connected_at else 0.0
            return {
                "ping_p50_ms": self._percentile(self._ping_latencies, 50),
                "ping_p99_ms": self._percentile(self._ping_latencies, 99),
                "cmd_p50_ms": self._percentile(self._cmd_latencies, 50),
                "cmd_p99_ms": self._percentile(self._cmd_latencies, 99),
                "error_count": self._error_count,
                "reconnect_count": self._reconnect_count,
                "last_error": self._last_error,
                "uptime_s": round(uptime, 1),
                "last_ping_age_s": round(time.monotonic() - self._last_ping_at, 1),
                "connection_mode": _connection_mode,
            }

    def reset(self) -> None:
        with self._lock:
            self._ping_latencies.clear()
            self._cmd_latencies.clear()
            self._error_count = 0
            self._reconnect_count = 0
            self._last_error = ""


# Module-level telemetry singleton
redis_telemetry = RedisHealthTelemetry()


async def ping_with_telemetry() -> bool:
    """
    Ping Redis and record the round-trip latency in redis_telemetry.

    Returns True if the ping succeeded, False otherwise.
    """
    client = await get_redis()
    if client is None:
        redis_telemetry.record_error(ConnectionError("No Redis client available"))
        return False
    t0 = time.perf_counter()
    try:
        await client.ping()
        latency_ms = (time.perf_counter() - t0) * 1000
        redis_telemetry.record_ping(latency_ms)
        return True
    except Exception as exc:
        redis_telemetry.record_error(exc)
        return False
