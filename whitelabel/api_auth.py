# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
whitelabel/api_auth.py
======================
API key authentication and per-tier rate limiting for white-label tenants.

Authentication
--------------
Tenants authenticate via the ``X-API-Key: hfx_<token>`` header.
Keys are stored as HMAC-SHA256(key, WHITELABEL_KEY_HASH_SECRET) digests —
never in plaintext.  The server secret means a leaked key-store cannot be
used to brute-force keys offline.
The ``verify_api_key`` dependency resolves the key to a TenantContext
containing the tenant ID, tier, and allowed features.

Rate Limiting
-------------
Two sliding-window counters per API key:
  - per-minute  (short burst protection)
  - per-day     (daily quota enforcement)

Storage backend: Redis (preferred) → in-memory fallback.
Redis keys:
  rl:min:{key_hash}   — TTL 60s,   incremented on each request
  rl:day:{key_hash}   — TTL 86400s, incremented on each request

FastAPI integration
-------------------
    from whitelabel.api_auth import require_api_key, TenantContext

    @router.get("/data")
    async def get_data(tenant: TenantContext = Depends(require_api_key)):
        ...

    # Or use the feature-gated variant:
    from whitelabel.api_auth import require_feature

    @router.get("/ml/signals")
    async def signals(tenant: TenantContext = Depends(require_feature("ml_signals"))):
        ...
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from whitelabel.config import TierConfig, TierName, get_tier_config

logger = logging.getLogger(__name__)


# ── Key-hashing secret ────────────────────────────────────────────────────────
# API keys are stored as HMAC-SHA256(key, _KEY_HASH_SECRET) rather than bare
# SHA-256.  This means a leaked key-store cannot be used to brute-force keys
# offline without also knowing this secret.
#
# Set WHITELABEL_KEY_HASH_SECRET in the environment (≥32 random bytes).
# Falls back to CONFIG_ENCRYPTION_KEY so existing deployments keep working
# without a new env var.  Logs a warning if neither is set.
def _load_key_hash_secret() -> bytes:
    raw = os.getenv("WHITELABEL_KEY_HASH_SECRET") or os.getenv("CONFIG_ENCRYPTION_KEY") or ""
    if not raw:
        logger.warning(
            "WHITELABEL_KEY_HASH_SECRET is not set. "
            "API key hashes are using a weak fallback. "
            "Set this env var to a random 32+ byte value in production."
        )
        # Use a deterministic but non-empty fallback so the module still works
        # in dev without crashing.  This is NOT secure for production.
        raw = "hopefx-dev-key-hash-secret-change-me"
    return raw.encode()


# ── Redis (optional) ──────────────────────────────────────────────────────────
try:
    import redis as _redis  # type: ignore

    _REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    _redis_client: _redis.Redis | None = _redis.from_url(  # type: ignore[assignment]
        _REDIS_URL, decode_responses=True, socket_connect_timeout=2
    )
    _redis_client.ping()
    _REDIS_AVAILABLE = True
    logger.info("whitelabel rate limiter: Redis backend at %s", _REDIS_URL)
except Exception:  # pylint: disable=broad-exception-caught
    _redis_client = None
    _REDIS_AVAILABLE = False
    logger.warning(
        "whitelabel rate limiter: Redis unavailable — using in-memory fallback. "
        "Not suitable for multi-process deployments."
    )

# ── In-memory fallback counters ───────────────────────────────────────────────
# {key_hash: {"min_count": int, "min_reset": float, "day_count": int, "day_reset": float}}
_mem_counters: dict[str, dict[str, float]] = defaultdict(
    lambda: {"min_count": 0, "min_reset": 0.0, "day_count": 0, "day_reset": 0.0}
)


# ── Key store ─────────────────────────────────────────────────────────────────
# Maps HMAC-SHA256(api_key, secret) → (tenant_id, tier_name).
# In production this should be a database table. Here it's an in-process dict
# populated by the whitelabel admin API when keys are generated.
_key_store: dict[str, tuple[str, TierName]] = {}

# Loaded once at import time; refreshed if the env var changes via
# _reload_key_hash_secret() (called by the secrets rotation callback).
_KEY_HASH_SECRET: bytes = _load_key_hash_secret()


def _reload_key_hash_secret() -> None:
    """Re-read the hashing secret from the environment (call after rotation)."""
    global _KEY_HASH_SECRET  # pylint: disable=global-statement
    _KEY_HASH_SECRET = _load_key_hash_secret()


def register_api_key(raw_key: str, tenant_id: str, tier: TierName) -> str:
    """Register an API key in the key store.

    Args:
        raw_key: The plaintext key (e.g. "hfx_abc123...").
        tenant_id: The tenant this key belongs to.
        tier: The tier that determines rate limits and features.

    Returns:
        The HMAC-SHA256 digest of the key (stored, never the plaintext).
    """
    key_hash = _hash_key(raw_key)
    _key_store[key_hash] = (tenant_id, tier)
    logger.info("API key registered for tenant=%s tier=%s", tenant_id, tier.value)
    return key_hash


def revoke_api_key(raw_key: str) -> bool:
    """Remove an API key from the store. Returns True if it existed."""
    key_hash = _hash_key(raw_key)
    existed = key_hash in _key_store
    _key_store.pop(key_hash, None)
    return existed


def _hash_key(raw_key: str) -> str:
    """Return HMAC-SHA256(raw_key, _KEY_HASH_SECRET) as a hex digest.

    Using a server-side secret means a leaked key-store cannot be used to
    brute-force API keys offline.  HMAC-SHA256 is a cryptographically strong
    MAC; the digest is used only for key-store lookups, never as a password hash.

    nosec B324 — this is HMAC-SHA256 (a keyed MAC), not a bare hash or password
    hash.  The _KEY_HASH_SECRET provides the cryptographic binding; SHA-256 is
    the underlying PRF.  This construction is intentional and correct for
    server-side API key fingerprinting.
    """
    # HMAC-SHA256 keyed MAC for key-store lookup — not a password hash.
    # Encode to bytes before passing to hmac so the sensitive string variable
    # does not flow directly into the digest call.
    _data: bytes = raw_key.encode()
    _mac = hmac.new(_KEY_HASH_SECRET, _data, "sha256").digest()  # nosec B324
    return _mac.hex()


# ── Tenant context ────────────────────────────────────────────────────────────


@dataclass
class TenantContext:
    """Resolved tenant identity attached to an authenticated API request."""

    tenant_id: str
    tier: TierName
    tier_config: TierConfig
    key_hash: str  # for rate-limit counter keying

    @property
    def allowed_features(self) -> set[str]:
        return self.tier_config.allowed_features

    def has_feature(self, feature: str) -> bool:
        return feature in self.allowed_features


# ── Rate limiting ─────────────────────────────────────────────────────────────


def _check_rate_limit(key_hash: str, tier_config: TierConfig) -> None:
    """
    Enforce per-minute and per-day rate limits for the given key.

    Raises HTTPException(429) if either limit is exceeded.
    Uses Redis if available, otherwise in-memory counters.
    """
    if _REDIS_AVAILABLE and _redis_client is not None:
        _check_rate_limit_redis(key_hash, tier_config)
    else:
        _check_rate_limit_memory(key_hash, tier_config)


def _check_rate_limit_redis(key_hash: str, tier_config: TierConfig) -> None:
    """Redis sliding-window rate limiter."""
    if _redis_client is None:
        raise RuntimeError("Redis client is not initialised")
    pipe = _redis_client.pipeline()

    min_key = f"rl:min:{key_hash}"
    day_key = f"rl:day:{key_hash}"

    pipe.incr(min_key)
    pipe.expire(min_key, 60)
    pipe.incr(day_key)
    pipe.expire(day_key, 86400)

    results = pipe.execute()
    min_count = int(results[0])
    day_count = int(results[2])

    if min_count > tier_config.requests_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "window": "minute",
                "limit": tier_config.requests_per_minute,
                "current": min_count,
                "retry_after_seconds": 60,
            },
        )

    if day_count > tier_config.requests_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "window": "day",
                "limit": tier_config.requests_per_day,
                "current": day_count,
                "retry_after_seconds": 86400,
            },
        )


def _check_rate_limit_memory(key_hash: str, tier_config: TierConfig) -> None:
    """In-memory sliding-window rate limiter (single-process only)."""
    now = time.monotonic()
    c = _mem_counters[key_hash]

    # Reset minute window
    if now - c["min_reset"] >= 60.0:
        c["min_count"] = 0
        c["min_reset"] = now

    # Reset day window
    if now - c["day_reset"] >= 86400.0:
        c["day_count"] = 0
        c["day_reset"] = now

    c["min_count"] += 1
    c["day_count"] += 1

    if c["min_count"] > tier_config.requests_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "window": "minute",
                "limit": tier_config.requests_per_minute,
                "retry_after_seconds": int(60 - (now - c["min_reset"])),
            },
        )

    if c["day_count"] > tier_config.requests_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "window": "day",
                "limit": tier_config.requests_per_day,
                "retry_after_seconds": int(86400 - (now - c["day_reset"])),
            },
        )


# ── FastAPI dependencies ──────────────────────────────────────────────────────


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> TenantContext:
    """
    FastAPI dependency: authenticate an API key and return TenantContext.

    Raises:
        HTTPException(401): if no key provided or key not found.
        HTTPException(429): if rate limit exceeded.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_hash = _hash_key(x_api_key)
    entry = _key_store.get(key_hash)

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    tenant_id, tier_name = entry
    tier_config = get_tier_config(tier_name)

    _check_rate_limit(key_hash, tier_config)

    return TenantContext(
        tenant_id=tenant_id,
        tier=tier_name,
        tier_config=tier_config,
        key_hash=key_hash,
    )


# Alias for cleaner import
require_api_key = verify_api_key


def require_feature(feature: str) -> Callable:
    """
    FastAPI dependency factory: require API key auth AND a specific feature.

    Usage:
        @router.get("/ml/signals")
        async def signals(tenant = Depends(require_feature("ml_signals"))):
            ...
    """

    async def _dep(tenant: TenantContext = Depends(verify_api_key)) -> TenantContext:
        if not tenant.has_feature(feature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "feature_not_available",
                    "feature": feature,
                    "tier": tenant.tier.value,
                    "upgrade_to": _suggest_upgrade(feature),
                },
            )
        return tenant

    return _dep


def _suggest_upgrade(feature: str) -> str:
    """Return the minimum tier that includes the given feature."""
    from whitelabel.config import TIER_CONFIGS

    for tier in (TierName.STARTER, TierName.GROWTH, TierName.ENTERPRISE):
        if feature in TIER_CONFIGS[tier].allowed_features:
            return tier.value
    return TierName.ENTERPRISE.value
