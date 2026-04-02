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

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ── Import config ─────────────────────────────────────────────────────────────
try:
    from rate_limiting_configuration import (
        GLOBAL_DEFAULT_RATE,
        AUTH_RATE,
        TRADING_RATE,
        MARKET_DATA_RATE,
        ADMIN_RATE,
        WEBSOCKET_RATE,
        BACKTEST_RATE,
        WITHDRAWAL_RATE,
        REDIS_URL,
        KEY_PREFIX,
        ENDPOINT_RATES,
    )
except ImportError:
    GLOBAL_DEFAULT_RATE = "120 per minute"
    AUTH_RATE = "10 per minute"
    TRADING_RATE = "60 per minute"
    MARKET_DATA_RATE = "300 per minute"
    ADMIN_RATE = "30 per minute"
    WEBSOCKET_RATE = "20 per minute"
    BACKTEST_RATE = "10 per minute"
    WITHDRAWAL_RATE = "5 per minute"
    REDIS_URL = "redis://localhost:6379/1"
    KEY_PREFIX = "hopefx:rl:"
    ENDPOINT_RATES = {"default": GLOBAL_DEFAULT_RATE}


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
    first = rate_str.split(";")[0].strip()
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


async def _get_redis():
    """Lazy-initialise the async Redis client."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1.0)
        await client.ping()
        _redis_client = client
        _redis_available = True
        logger.info("Rate limiter: Redis backend connected at %s", REDIS_URL)
    except Exception as exc:
        logger.warning(
            "Rate limiter: Redis unavailable (%s) — using in-process fallback. "
            "This does NOT enforce limits across multiple pods.",
            exc,
        )
        _redis_available = False
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
        logger.warning("Redis rate-limit check failed (%s) — falling back", exc)
        global _redis_available
        _redis_available = False
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
    from fastapi import Request, HTTPException, status

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
