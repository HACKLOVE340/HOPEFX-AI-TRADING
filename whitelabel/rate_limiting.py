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
_counters: dict[str, dict[str, list]] = defaultdict(lambda: {"min": [0, 0.0], "day": [0, 0.0]})


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
        c = _counters[key_hash]

        # Minute window
        if now - c["min"][1] >= 60.0:
            c["min"] = [0, now]
        c["min"][0] += 1

        # Day window
        if now - c["day"][1] >= 86400.0:
            c["day"] = [0, now]
        c["day"][0] += 1

        if c["min"][0] > tier_config.requests_per_minute:
            retry = int(60 - (now - c["min"][1]))
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "window": "minute",
                    "limit": tier_config.requests_per_minute,
                    "retry_after_seconds": retry,
                },
                headers={"Retry-After": str(retry)},
            )

        if c["day"][0] > tier_config.requests_per_day:
            retry = int(86400 - (now - c["day"][1]))
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "window": "day",
                    "limit": tier_config.requests_per_day,
                    "retry_after_seconds": retry,
                },
                headers={"Retry-After": str(retry)},
            )

        # Add rate-limit headers to the response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit-Minute"] = str(tier_config.requests_per_minute)
        response.headers["X-RateLimit-Remaining-Minute"] = str(max(0, tier_config.requests_per_minute - c["min"][0]))
        response.headers["X-RateLimit-Limit-Day"] = str(tier_config.requests_per_day)
        response.headers["X-RateLimit-Remaining-Day"] = str(max(0, tier_config.requests_per_day - c["day"][0]))
        return response
