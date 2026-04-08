# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
whitelabel/config.py
====================
Tier-based configuration for white-label tenants.

Defines rate limits, feature quotas, and API access rules per reseller tier.
Used by the API key auth middleware to enforce per-tenant limits.

Tiers
-----
STARTER   — small prop firms / academies, limited API calls
GROWTH    — mid-size brokers, higher limits, more features
ENTERPRISE— institutional, unlimited API calls, all features

Rate limits are enforced per API key using a sliding-window counter
stored in Redis (falls back to in-memory if Redis unavailable).
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


class TierName(StrEnum):
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class TierConfig:
    """Immutable configuration for a white-label tier."""

    name: TierName
    # API rate limits
    requests_per_minute: int
    requests_per_day: int
    # WebSocket connections
    max_ws_connections: int
    # Trading limits
    max_symbols: int  # number of symbols accessible via API
    max_positions: int  # concurrent open positions via API
    # Data access
    max_history_days: int  # historical data lookback
    # Feature flags available at this tier
    allowed_features: set[str]
    # Revenue share (fraction of subscription revenue paid to reseller)
    revenue_share_pct: float
    # Monthly platform fee (USD)
    platform_fee_usd: float


# ── Tier definitions ──────────────────────────────────────────────────────────

TIER_CONFIGS: dict[TierName, TierConfig] = {
    TierName.STARTER: TierConfig(
        name=TierName.STARTER,
        requests_per_minute=60,
        requests_per_day=5_000,
        max_ws_connections=5,
        max_symbols=10,
        max_positions=5,
        max_history_days=90,
        allowed_features={
            "trading",
            "risk_management",
            "analytics",
            "backtesting",
        },
        revenue_share_pct=0.20,
        platform_fee_usd=299.0,
    ),
    TierName.GROWTH: TierConfig(
        name=TierName.GROWTH,
        requests_per_minute=300,
        requests_per_day=50_000,
        max_ws_connections=25,
        max_symbols=50,
        max_positions=25,
        max_history_days=365,
        allowed_features={
            "trading",
            "risk_management",
            "analytics",
            "backtesting",
            "ml_signals",
            "copy_trading",
            "social_feed",
            "marketplace",
        },
        revenue_share_pct=0.30,
        platform_fee_usd=999.0,
    ),
    TierName.ENTERPRISE: TierConfig(
        name=TierName.ENTERPRISE,
        requests_per_minute=3_000,
        requests_per_day=1_000_000,
        max_ws_connections=500,
        max_symbols=200,
        max_positions=500,
        max_history_days=3650,
        allowed_features={
            "trading",
            "risk_management",
            "analytics",
            "backtesting",
            "ml_signals",
            "copy_trading",
            "social_feed",
            "marketplace",
            "prop_firm",
            "multi_account",
            "audit_trail",
            "custom_branding",
            "api_access",
            "webhooks",
        },
        revenue_share_pct=0.40,
        platform_fee_usd=2_999.0,
    ),
}


def get_tier_config(tier: TierName) -> TierConfig:
    """Return the TierConfig for the given tier name."""
    return TIER_CONFIGS[tier]


def get_tier_for_name(name: str) -> TierConfig | None:
    """Look up TierConfig by string name, returning None if not found."""
    try:
        return TIER_CONFIGS[TierName(name.lower())]
    except (ValueError, KeyError):
        return None
