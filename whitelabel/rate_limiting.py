# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
whitelabel/rate_limiting.py
===========================
Starlette middleware for per-tenant rate limiting on white-label API routes.

Applies rate limits based on the X-API-Key header before the request
reaches any route handler. Complements the FastAPI dependency in api_auth.py
by providing a middleware-level gate (useful for non-FastAPI routes or
early rejection before expensive auth checks).

Usage (add to FastAPI app):
    from whitelabel.rate_limiting import WhitelabelRateLimitMiddleware
    app.add_middleware(WhitelabelRateLimitMiddleware, path_prefix="/api/v1/wl")
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from whitelabel.api_auth import _hash_key, _key_store
from whitelabel.config import get_tier_config

logger = logging.getLogger(__name__)

# In-memory counters: key_hash → {window: (count, reset_ts)}
# In-process fallback counters (used when Redis is unavailable)
_counters: dict[str, dict[str, list]] = defaultdict(lambda: {"min": [0, 0.0], "day": [0, 0.0]})


def _get_sync_redis():
    try:
        from cache.redis_pool import get_sync_client
        return get_sync_client()
    except Exception:
        return None


def _redis_incr_window(key_hash: str, window: str, window_seconds: int) -> int:
    """
    Atomically increment a sliding-window counter in Redis.
    Returns the new count, or -1 when Redis is unavailable (caller uses fallback).
    Uses a fixed-window approach: key expires after window_seconds.
    """
    r = _get_sync_redis()
    if not r:
        return -1
    try:
        redis_key = f"wl:rl:{key_hash}:{window}"
        pipe = r.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = pipe.execute()
        return int(results[0])
    except Exception:
        return -1


class WhitelabelRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces per-tier rate limits on white-label API paths.

    Only applies to requests that include an X-API-Key header on routes
    matching path_prefix. All other requests pass through unchanged.
    """

    def __init__(self, app, path_prefix: str = "/api/v1/wl") -> None:
        super().__init__(app)
        self.path_prefix = path_prefix

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Only gate requests on the white-label path prefix
        if not request.url.path.startswith(self.path_prefix):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return await call_next(request)

        key_hash = _hash_key(api_key)
        entry = _key_store.get(key_hash)
        if entry is None:
            # Unknown key — let the auth dependency handle the 401
            return await call_next(request)

        _, tier_name = entry
        tier_config = get_tier_config(tier_name)

        now = time.monotonic()

        # Try Redis-backed atomic counters first; fall back to in-process dict
        min_count = _redis_incr_window(key_hash, "min", 60)
        day_count = _redis_incr_window(key_hash, "day", 86400)

        if min_count == -1 or day_count == -1:
            # Redis unavailable — use in-process fallback
            c = _counters[key_hash]
            if now - c["min"][1] >= 60.0:
                c["min"] = [0, now]
            c["min"][0] += 1
            if now - c["day"][1] >= 86400.0:
                c["day"] = [0, now]
            c["day"][0] += 1
            min_count = c["min"][0]
            day_count = c["day"][0]

        if min_count > tier_config.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "window": "minute",
                    "limit": tier_config.requests_per_minute,
                    "retry_after_seconds": 60,
                },
                headers={"Retry-After": "60"},
            )

        if day_count > tier_config.requests_per_day:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "window": "day",
                    "limit": tier_config.requests_per_day,
                    "retry_after_seconds": 86400,
                },
                headers={"Retry-After": "86400"},
            )

        # Add rate-limit headers to the response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit-Minute"] = str(tier_config.requests_per_minute)
        response.headers["X-RateLimit-Remaining-Minute"] = str(max(0, tier_config.requests_per_minute - min_count))
        response.headers["X-RateLimit-Limit-Day"] = str(tier_config.requests_per_day)
        response.headers["X-RateLimit-Remaining-Day"] = str(max(0, tier_config.requests_per_day - day_count))
        return response
