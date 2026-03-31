# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
rate_limiting_configuration.py
================================
Central rate-limit configuration consumed by api/platform.py::setup_rate_limiting()
and rate_limiting/advanced.py.

All values are overridable via environment variables so they can be tuned
per-environment without code changes.

Tiers
-----
  GLOBAL_DEFAULT   — applied to every endpoint that has no explicit decorator
  AUTH             — login / token endpoints (tighter to slow brute-force)
  TRADING          — order submission (protects exchange quotas)
  MARKET_DATA      — price / OHLCV reads (higher, read-only)
  ADMIN            — admin panel (very tight)
  WEBSOCKET        — WS upgrade handshakes
  BACKTEST         — CPU-intensive backtest submission
  WITHDRAWAL       — extra-tight to limit AML surface

Storage
-------
  Redis is preferred (shared across pods).  Falls back to in-process memory
  when Redis is unreachable so the app keeps running in degraded mode.
  Set REDIS_HOST / REDIS_PORT / REDIS_PASSWORD to point at your Redis instance.

Usage in route handlers (slowapi)
----------------------------------
    from api.platform import get_limiter
    from rate_limiting_configuration import TRADING_RATE

    @router.post("/order")
    @get_limiter().limit(TRADING_RATE)
    async def place_order(request: Request, ...):
        ...
"""

from __future__ import annotations

import os


def _env(key: str, default: str) -> str:
    """Read an env var, falling back to *default*."""
    return os.getenv(key, default)


# ── Per-tier rate strings (slowapi / limits library format) ──────────────────
# Format: "<count> per <period>"  e.g. "60 per minute", "1000 per hour"

GLOBAL_DEFAULT_RATE: str = _env("RATE_GLOBAL_DEFAULT", "120 per minute")
"""Fallback applied to every endpoint without an explicit @limiter.limit()."""

AUTH_RATE: str = _env("RATE_AUTH", "10 per minute")
"""Login, token-refresh, and password-reset endpoints."""

TRADING_RATE: str = _env("RATE_TRADING", "60 per minute")
"""Order placement, modification, and cancellation."""

MARKET_DATA_RATE: str = _env("RATE_MARKET_DATA", "300 per minute")
"""Price quotes, OHLCV, and order-book reads."""

ADMIN_RATE: str = _env("RATE_ADMIN", "30 per minute")
"""Admin panel and management API endpoints."""

WEBSOCKET_RATE: str = _env("RATE_WEBSOCKET", "20 per minute")
"""WebSocket upgrade handshakes (per IP)."""

BACKTEST_RATE: str = _env("RATE_BACKTEST", "10 per minute")
"""Backtest submission — CPU-intensive, kept low."""

WITHDRAWAL_RATE: str = _env("RATE_WITHDRAWAL", "5 per minute")
"""Withdrawal requests — extra-tight to limit AML surface."""

# ── Storage configuration ─────────────────────────────────────────────────────

REDIS_HOST: str = _env("REDIS_HOST", "localhost")
REDIS_PORT: int = int(_env("REDIS_PORT", "6379"))
REDIS_PASSWORD: str = _env("REDIS_PASSWORD", "")
REDIS_DB: int = int(_env("REDIS_RATE_LIMIT_DB", "1"))
"""Separate Redis DB index for rate-limit keys (avoids key collisions)."""

REDIS_URL: str = (
    f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    if REDIS_PASSWORD
    else f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
)

# ── Key strategy ──────────────────────────────────────────────────────────────

KEY_PREFIX: str = _env("RATE_KEY_PREFIX", "hopefx:rl:")
"""Prefix applied to all rate-limit keys in Redis."""

# ── Burst allowance ───────────────────────────────────────────────────────────
# slowapi supports multiple limit strings separated by "; "
# e.g. "60 per minute; 500 per hour" — both must pass.

TRADING_BURST_RATE: str = _env("RATE_TRADING_BURST", f"{TRADING_RATE}; 500 per hour")
"""Trading endpoints: per-minute burst + hourly cap."""

AUTH_BURST_RATE: str = _env("RATE_AUTH_BURST", f"{AUTH_RATE}; 50 per hour")
"""Auth endpoints: per-minute burst + hourly cap."""


# ── Convenience mapping (used by middleware / decorators) ─────────────────────

ENDPOINT_RATES: dict = {
    "auth": AUTH_BURST_RATE,
    "trading": TRADING_BURST_RATE,
    "market_data": MARKET_DATA_RATE,
    "admin": ADMIN_RATE,
    "websocket": WEBSOCKET_RATE,
    "backtest": BACKTEST_RATE,
    "withdrawal": WITHDRAWAL_RATE,
    "default": GLOBAL_DEFAULT_RATE,
}
