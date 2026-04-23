# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
rate_limiting — Advanced rate limiting for REST and WebSocket endpoints.

Public API
----------
    WebSocketRateLimiter    Per-connection and per-user WebSocket rate limiter
                            with Redis-backed sliding window counters.
    AdvancedRateLimiter     Token bucket + sliding window rate limiter for
                            REST endpoints with per-route configuration.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from rate_limiting.websocket_limiter import WebSocketRateLimiter
except Exception as _exc:
    logger.debug("rate_limiting.websocket_limiter unavailable: %s", _exc)
    WebSocketRateLimiter = None  # type: ignore[assignment,misc]

try:
    from rate_limiting.advanced import AdvancedRateLimiter
except Exception as _exc:
    logger.debug("rate_limiting.advanced unavailable: %s", _exc)
    AdvancedRateLimiter = None  # type: ignore[assignment,misc]

__all__ = ["AdvancedRateLimiter", "WebSocketRateLimiter"]
