# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
rate_limiting — Advanced rate limiting for REST and WebSocket endpoints.

Public API
----------
    WebSocketConnectionLimiter (alias: WebSocketRateLimiter)
        Per-connection and per-IP WebSocket limiter with Redis-backed sliding
        window counters. Use ``get_ws_limiter()`` for the process-wide
        singleton and ``get_client_ip(ws)`` to derive the limit key.
    rate_limit_dependency(rate_str, key_func=None)
        FastAPI dependency factory — token-bucket / sliding-window REST limiter
        with per-route configuration (Redis-backed, in-memory fallback).
    auth_rate_limit / trading_rate_limit / market_data_rate_limit
        Pre-configured ``rate_limit_dependency`` instances for common routes.

Notes
-----
The previous public names ``WebSocketRateLimiter`` / ``AdvancedRateLimiter`` did
not match the implementation (the real classes are ``WebSocketConnectionLimiter``
and the ``rate_limit_dependency`` factory), so the package-level imports failed
silently and logged "unavailable" at debug. This module now exports the real
surface; ``WebSocketRateLimiter`` is kept as a back-compat alias.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from rate_limiting.websocket_limiter import (
        WebSocketConnectionLimiter,
        get_client_ip,
        get_ws_limiter,
    )

    # Documented/back-compat alias — the WS limiter class.
    WebSocketRateLimiter = WebSocketConnectionLimiter
except Exception as _exc:  # pragma: no cover — optional at import time
    logger.debug("rate_limiting.websocket_limiter unavailable: %s", _exc)
    WebSocketConnectionLimiter = None  # type: ignore[assignment,misc]
    WebSocketRateLimiter = None  # type: ignore[assignment,misc]
    get_ws_limiter = None  # type: ignore[assignment]
    get_client_ip = None  # type: ignore[assignment]

try:
    from rate_limiting.advanced import (
        auth_rate_limit,
        market_data_rate_limit,
        rate_limit_dependency,
        trading_rate_limit,
    )
except Exception as _exc:  # pragma: no cover — optional at import time
    logger.debug("rate_limiting.advanced unavailable: %s", _exc)
    rate_limit_dependency = None  # type: ignore[assignment]
    auth_rate_limit = None  # type: ignore[assignment]
    trading_rate_limit = None  # type: ignore[assignment]
    market_data_rate_limit = None  # type: ignore[assignment]

__all__ = [
    "WebSocketConnectionLimiter",
    "WebSocketRateLimiter",
    "auth_rate_limit",
    "get_client_ip",
    "get_ws_limiter",
    "market_data_rate_limit",
    "rate_limit_dependency",
    "trading_rate_limit",
]
