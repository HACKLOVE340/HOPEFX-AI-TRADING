# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
rate_limiting/advanced.py
==========================
FastAPI-compatible rate limiting middleware and helpers.

Replaces the previous Flask-based stub that was not wired into the FastAPI
app and used a hardcoded in-memory counter that did not work across pods.

Architecture
------------
- Primary storage: Redis (shared across all replicas).
- Fallback: asyncio-safe in-process sliding-window counter (single-pod only).
- Limits are read from rate_limiting_configuration.py so they can be tuned
  via environment variables without code changes.
- The FastAPI integration uses slowapi (wraps the `limits` library).
  setup_rate_limiting() in api/platform.py is the canonical entry point;
  this module provides the per-endpoint dependency helpers and the Redis-backed
  sliding-window implementation for endpoints that need custom key functions.

Usage
-----
    # In a route file:
    from fastapi import Depends, Request
    from rate_limiting.advanced import rate_limit_dependency
    from rate_limiting_configuration import TRADING_RATE

    @router.post("/order")
    async def place_order(
        request: Request,
        _rl: None = Depends(rate_limit_dependency(TRADING_RATE)),
    ):
        ...
"""

import asyncio
import contextlib
import logging
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from utils.redaction import redact_url

logger = logging.getLogger(__name__)

# ── Import config ─────────────────────────────────────────────────────────────
try:
    from rate_limiting_configuration import (
        ADMIN_RATE,
        AUTH_RATE,
        BACKTEST_RATE,
        KEY_PREFIX,
        MARKET_DATA_RATE,
        REDIS_URL,
        TRADING_RATE,
        WEBSOCKET_RATE,
        WITHDRAWAL_RATE,
    )
except ImportError:
    AUTH_RATE = "10 per minute"
    TRADING_RATE = "60 per minute"
    MARKET_DATA_RATE = "300 per minute"
    ADMIN_RATE = "30 per minute"
    WEBSOCKET_RATE = "20 per minute"
    BACKTEST_RATE = "10 per minute"
    WITHDRAWAL_RATE = "5 per minute"
    REDIS_URL = "redis://localhost:6379/1"
    KEY_PREFIX = "hopefx:rl:"


# ── Parse a rate string into (count, window_seconds) ─────────────────────────

_PERIOD_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}


def _parse_rate(rate_str: str) -> tuple:
    """
    Parse a rate string like "60 per minute" into (60, 60).

    Only the first clause is used when multiple are joined with "; ".
    """
    first = rate_str.split(";", maxsplit=1)[0].strip()
    parts = first.lower().split()
    if len(parts) != 3 or parts[1] != "per":
        raise ValueError(f"Invalid rate string: {rate_str!r}")
    count = int(parts[0])
    period = _PERIOD_SECONDS.get(parts[2])
    if period is None:
        raise ValueError(f"Unknown period {parts[2]!r} in rate string {rate_str!r}")
    return count, period


# ── In-process sliding-window fallback ───────────────────────────────────────


class _InMemoryRateLimiter:
    """
    Asyncio-safe sliding-window rate limiter backed by in-process memory.

    Used as a fallback when Redis is unavailable.  Does NOT enforce limits
    across multiple pods — use only in single-replica or development deployments.
    """

    def __init__(self) -> None:
        self._windows: dict = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds

        async with self._lock:
            dq = self._windows[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True


_fallback_limiter = _InMemoryRateLimiter()

# ── Redis-backed limiter ──────────────────────────────────────────────────────

_redis_client = None
_redis_available: bool = False
# The event loop the cached client was created on. redis.asyncio binds its
# connection pool to a loop; using it from another raises "Event loop is closed".
_redis_loop = None
# When Redis is marked unavailable, the earliest time to try again. Without this
# the first failure was permanent for the process — see _redis_is_allowed.
_redis_retry_after: float = 0.0
# How long to stay on the fallback before re-probing.
_REDIS_RETRY_COOLDOWN = float(os.getenv("RATE_LIMIT_REDIS_RETRY_SECONDS", "30"))


async def _get_redis():
    """Return a Redis client bound to the *current* event loop, or None.

    Two failure modes this guards against, both of which silently downgraded the
    limiter to per-process counting:

    1. **Loop rebinding.** The client used to be cached once, forever.
       ``redis.asyncio`` ties its pool to the loop it was created on, so any
       second loop in the process (a worker that recreates its loop, anything
       driving the app under test) hit "Event loop is closed" on every call.
       The client is now rebuilt when the running loop changes.

    2. **Permanent disable.** A single exception set ``_redis_available = False``
       and this function then returned None for the rest of the process's life,
       because the cached client was non-None so the reconnect branch was never
       reached again. One Redis failover — seconds of downtime — therefore turned
       a fleet-wide rate limit into a per-worker one indefinitely, with no
       further log line to say so. Availability is now re-probed after a
       cooldown.
    """
    global _redis_client, _redis_available, _redis_loop, _redis_retry_after

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    loop_changed = _redis_client is not None and running_loop is not _redis_loop
    if loop_changed:
        logger.debug("Rate limiter: event loop changed — rebuilding the Redis client")
        with contextlib.suppress(Exception):
            await _redis_client.aclose()
        _redis_client = None
        _redis_available = False
        _redis_retry_after = 0.0

    if _redis_client is not None and _redis_available:
        return _redis_client

    # Marked unavailable and still inside the cooldown — stay on the fallback.
    if _redis_client is not None and not _redis_available and time.monotonic() < _redis_retry_after:
        return None

    try:
        import redis.asyncio as aioredis  # pylint: disable=no-name-in-module

        client = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1.0)
        await client.ping()
        _redis_client = client
        _redis_loop = running_loop
        _redis_available = True
        _redis_retry_after = 0.0
        logger.info("Rate limiter: Redis backend connected at %s", redact_url(REDIS_URL))
    except Exception as exc:
        logger.warning(
            "Rate limiter: Redis unavailable (%s) — using in-process fallback for "
            "%.0fs. This does NOT enforce limits across multiple pods.",
            exc,
            _REDIS_RETRY_COOLDOWN,
        )
        _redis_available = False
        _redis_retry_after = time.monotonic() + _REDIS_RETRY_COOLDOWN
        # Keep a non-None client so the cooldown branch above is reachable; it is
        # only ever returned once _redis_available flips back to True.
        _redis_client = _redis_client or object()
    return _redis_client if _redis_available else None


async def _redis_is_allowed(key: str, limit: int, window_seconds: int) -> bool:
    """
    Sliding-window rate check using Redis sorted sets.

    Uses a pipeline for atomicity.  Falls back to the in-process limiter
    if Redis is unreachable.
    """
    redis = await _get_redis()
    if redis is None:
        return await _fallback_limiter.is_allowed(key, limit, window_seconds)

    full_key = f"{KEY_PREFIX}{key}"
    now = time.time()
    cutoff = now - window_seconds

    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(full_key, "-inf", cutoff)
            pipe.zcard(full_key)
            pipe.zadd(full_key, {str(now): now})
            pipe.expire(full_key, window_seconds + 1)
            results = await pipe.execute()

        current_count = results[1]  # zcard before the new entry
        if current_count >= limit:
            await redis.zrem(full_key, str(now))
            return False
        return True
    except Exception as exc:
        logger.warning(
            "Redis rate-limit check failed (%s) — falling back for %.0fs",
            exc,
            _REDIS_RETRY_COOLDOWN,
        )
        global _redis_available, _redis_retry_after
        _redis_available = False
        # Set the cooldown rather than disabling outright: this used to be a
        # one-way switch, so a single transient error left the whole process on
        # per-worker counting permanently.
        _redis_retry_after = time.monotonic() + _REDIS_RETRY_COOLDOWN
        return await _fallback_limiter.is_allowed(key, limit, window_seconds)


# ── FastAPI dependency factory ────────────────────────────────────────────────


def rate_limit_dependency(rate_str: str, key_func: Callable | None = None):
    """
    Return a FastAPI dependency that enforces *rate_str* per client IP
    (or per the value returned by *key_func(request)*).

    Example
    -------
        from fastapi import Depends, Request
        from rate_limiting.advanced import rate_limit_dependency
        from rate_limiting_configuration import TRADING_RATE

        @router.post("/order")
        async def place_order(
            request: Request,
            _rl: None = Depends(rate_limit_dependency(TRADING_RATE)),
        ):
            ...
    """
    from fastapi import HTTPException, Request, status

    try:
        limit, window = _parse_rate(rate_str)
    except ValueError:
        logger.error("Invalid rate string %r — rate limiting disabled for this route", rate_str)
        limit, window = 10_000, 60  # effectively unlimited

    async def _dependency(request: Request) -> None:
        if key_func is not None:
            key = str(key_func(request))
        else:
            forwarded = request.headers.get("X-Forwarded-For")
            key = (
                forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
            )

        route_key = f"{request.url.path}:{key}"
        allowed = await _redis_is_allowed(route_key, limit, window)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Limit: {rate_str}.",
                    "retry_after_seconds": window,
                },
                headers={"Retry-After": str(window)},
            )

    return _dependency


# ── Convenience pre-built dependencies ───────────────────────────────────────

auth_rate_limit = rate_limit_dependency(AUTH_RATE)
trading_rate_limit = rate_limit_dependency(TRADING_RATE)
market_data_rate_limit = rate_limit_dependency(MARKET_DATA_RATE)
admin_rate_limit = rate_limit_dependency(ADMIN_RATE)
websocket_rate_limit = rate_limit_dependency(WEBSOCKET_RATE)
backtest_rate_limit = rate_limit_dependency(BACKTEST_RATE)
withdrawal_rate_limit = rate_limit_dependency(WITHDRAWAL_RATE)


# ── Public alias ─────────────────────────────────────────────────────────────
# Superadmin and other modules import ``RateLimiter`` by name.
# This is a thin public wrapper around the internal _InMemoryRateLimiter so
# callers don't need to know the private name.


class RateLimiter(_InMemoryRateLimiter):
    """Public, importable rate-limiter class.

    Wraps :class:`_InMemoryRateLimiter` and adds convenience helpers used by
    the superadmin infrastructure dashboard.

    Usage::

        limiter = RateLimiter()
        allowed = await limiter.is_allowed("user:123", limit=10, window_seconds=60)
    """

    async def check(self, key: str, limit: int, window_seconds: int) -> bool:
        """Check whether *key* is within its rate limit.

        Alias for :meth:`is_allowed` with positional-argument style.

        Args:
            key:            Unique identifier (e.g. ``"user:123"``).
            limit:          Maximum allowed requests in *window_seconds*.
            window_seconds: Sliding window duration in seconds.

        Returns:
            ``True`` if the request is allowed, ``False`` if it is rate-limited.
        """
        return await self.is_allowed(key, limit, window_seconds)

    def status(self) -> dict:
        """Return a summary of current window state for monitoring."""
        return {
            "backend": "in-memory",
            "tracked_keys": len(self._windows),
        }
