# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/pricing.py
==============
Public pricing catalogue endpoint.

Routes
------
GET  /api/pricing/plans          — full 5-tier plan catalogue with feature matrix
GET  /api/pricing/compare        — side-by-side feature comparison for two tiers
GET  /api/pricing/upgrade-path   — available upgrade options from current tier
GET  /api/pricing/faq            — pricing FAQ content
POST /api/pricing/estimate       — estimate monthly cost given usage parameters

All routes are public (no auth required) so the landing page and pricing page
can render without a session.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    logger.warning("FastAPI not available — pricing router disabled")

# ---------------------------------------------------------------------------
# Canonical plan catalogue
# Mirrors api/billing.py _PLANS and monetization/pricing.py PricingManager.
# Single source of truth for the pricing page.
# ---------------------------------------------------------------------------

_PLANS: list[dict[str, Any]] = [
    {
        "id": "free",
        "name": "Free",
        "tagline": "Paper trading and market exploration",
        "price_usd_monthly": 0,
        "price_usd_annual": 0,
        "annual_savings_pct": 0,
        "commission_rate": 0.010,
        "commission_label": "1.0% per trade",
        "badge": None,
        "cta": "Get started",
        "cta_href": "/register",
        "features": {
            "paper_trading": True,
            "live_trading": False,
            "ai_signals": False,
            "backtesting": False,
            "backtesting_unlimited": False,
            "pattern_recognition": False,
            "api_access": False,
            "news_integration": False,
            "priority_support": False,
            "white_label": False,
            "dedicated_support": False,
            "custom_development": False,
            "rl_agent": False,
            "ml_features": False,
        },
        "limits": {
            "signals_per_day": 5,
            "backtests_per_month": 3,
            "live_accounts": 0,
            "max_strategies": 1,
            "max_brokers": 1,
        },
        "highlights": [
            "Paper trading terminal",
            "5 AI signals/day",
            "Economic calendar",
            "Leaderboard access",
            "Community marketplace",
        ],
    },
    {
        "id": "starter",
        "name": "Starter",
        "tagline": "Live trading for individual traders",
        "price_usd_monthly": 1800,
        "price_usd_annual": 18000,
        "annual_savings_pct": 17,
        "commission_rate": 0.005,
        "commission_label": "0.5% per trade",
        "badge": None,
        "cta": "Start trading",
        "cta_href": "/register?plan=starter",
        "features": {
            "paper_trading": True,
            "live_trading": True,
            "ai_signals": False,
            "backtesting": True,
            "backtesting_unlimited": False,
            "pattern_recognition": False,
            "api_access": False,
            "news_integration": False,
            "priority_support": False,
            "white_label": False,
            "dedicated_support": False,
            "custom_development": False,
            "rl_agent": False,
            "ml_features": False,
        },
        "limits": {
            "signals_per_day": 20,
            "backtests_per_month": 10,
            "live_accounts": 1,
            "max_strategies": 3,
            "max_brokers": 1,
        },
        "highlights": [
            "Live trading (1 broker)",
            "20 AI signals/day",
            "Trade journal",
            "Performance analytics",
            "Risk calculator",
            "Price alerts",
        ],
    },
    {
        "id": "professional",
        "name": "Professional",
        "tagline": "AI-powered trading for serious traders",
        "price_usd_monthly": 4500,
        "price_usd_annual": 45000,
        "annual_savings_pct": 17,
        "commission_rate": 0.003,
        "commission_label": "0.3% per trade",
        "badge": "Most popular",
        "cta": "Start free trial",
        "cta_href": "/register?plan=professional",
        "features": {
            "paper_trading": True,
            "live_trading": True,
            "ai_signals": True,
            "backtesting": True,
            "backtesting_unlimited": True,
            "pattern_recognition": True,
            "api_access": True,
            "news_integration": False,
            "priority_support": True,
            "white_label": False,
            "dedicated_support": False,
            "custom_development": False,
            "rl_agent": True,
            "ml_features": True,
        },
        "limits": {
            "signals_per_day": 100,
            "backtests_per_month": 50,
            "live_accounts": 3,
            "max_strategies": 7,
            "max_brokers": 3,
        },
        "highlights": [
            "Live trading (3 brokers)",
            "100 AI signals/day",
            "Unlimited backtesting",
            "RL agent + ML features",
            "Pattern recognition",
            "API access",
            "Priority support",
            "Copy trading",
            "Prop firm tracker",
            "Walk-forward analysis",
        ],
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "tagline": "Institutional-grade platform for trading firms",
        "price_usd_monthly": 7500,
        "price_usd_annual": 75000,
        "annual_savings_pct": 17,
        "commission_rate": 0.002,
        "commission_label": "0.2% per trade",
        "badge": None,
        "cta": "Contact sales",
        "cta_href": "/register?plan=enterprise",
        "features": {
            "paper_trading": True,
            "live_trading": True,
            "ai_signals": True,
            "backtesting": True,
            "backtesting_unlimited": True,
            "pattern_recognition": True,
            "api_access": True,
            "news_integration": True,
            "priority_support": True,
            "white_label": True,
            "dedicated_support": False,
            "custom_development": False,
            "rl_agent": True,
            "ml_features": True,
        },
        "limits": {
            "signals_per_day": -1,
            "backtests_per_month": -1,
            "live_accounts": -1,
            "max_strategies": -1,
            "max_brokers": -1,
        },
        "highlights": [
            "Unlimited brokers & strategies",
            "Unlimited AI signals",
            "News & geopolitical intelligence",
            "White-label platform",
            "Team workspaces",
            "Market replay engine",
            "Research notebooks",
            "Full API access",
        ],
    },
    {
        "id": "elite",
        "name": "Elite",
        "tagline": "Bespoke solution for hedge funds and prop desks",
        "price_usd_monthly": 10000,
        "price_usd_annual": 100000,
        "annual_savings_pct": 17,
        "commission_rate": 0.001,
        "commission_label": "0.1% per trade",
        "badge": "Best value",
        "cta": "Contact sales",
        "cta_href": "/register?plan=elite",
        "features": {
            "paper_trading": True,
            "live_trading": True,
            "ai_signals": True,
            "backtesting": True,
            "backtesting_unlimited": True,
            "pattern_recognition": True,
            "api_access": True,
            "news_integration": True,
            "priority_support": True,
            "white_label": True,
            "dedicated_support": True,
            "custom_development": True,
            "rl_agent": True,
            "ml_features": True,
        },
        "limits": {
            "signals_per_day": -1,
            "backtests_per_month": -1,
            "live_accounts": -1,
            "max_strategies": -1,
            "max_brokers": -1,
        },
        "highlights": [
            "Everything in Enterprise",
            "Dedicated account manager",
            "Custom strategy development",
            "SLA guarantees",
            "On-premise deployment option",
            "Sub-accounts management",
            "Lowest commission rate (0.1%)",
        ],
    },
]

# Feature display labels for the comparison table
_FEATURE_LABELS: dict[str, str] = {
    "paper_trading": "Paper trading",
    "live_trading": "Live trading",
    "ai_signals": "AI trading signals",
    "backtesting": "Backtesting",
    "backtesting_unlimited": "Unlimited backtesting",
    "pattern_recognition": "Chart pattern recognition",
    "api_access": "REST API access",
    "news_integration": "News & geopolitical intelligence",
    "priority_support": "Priority support",
    "white_label": "White-label platform",
    "dedicated_support": "Dedicated account manager",
    "custom_development": "Custom strategy development",
    "rl_agent": "Reinforcement learning agent",
    "ml_features": "Full ML feature suite",
}

_FAQ: list[dict[str, str]] = [
    {
        "question": "Can I switch plans at any time?",
        "answer": (
            "Yes. Upgrades take effect immediately and are prorated. "
            "Downgrades take effect at the end of your current billing period."
        ),
    },
    {
        "question": "What payment methods do you accept?",
        "answer": (
            "We accept all major credit/debit cards via Stripe, bank transfers, "
            "Flutterwave (Africa), Paystack, and cryptocurrency (BTC, ETH, USDT)."
        ),
    },
    {
        "question": "Is there a free trial?",
        "answer": (
            "The Free plan is available indefinitely with no credit card required. "
            "Professional plan includes a 14-day free trial."
        ),
    },
    {
        "question": "What does the commission rate mean?",
        "answer": (
            "The commission rate is charged on the notional value of each executed trade "
            "routed through the HOPEFX platform. It is in addition to your broker's spread."
        ),
    },
    {
        "question": "What is the annual discount?",
        "answer": (
            "Annual billing gives you 2 months free (approximately 17% off). "
            "The annual price is the monthly price × 10."
        ),
    },
    {
        "question": "Can I use my own broker?",
        "answer": (
            "Yes. HOPEFX connects to OANDA, MetaTrader 5, Interactive Brokers, Alpaca, "
            "Binance, Bybit, and 100+ exchanges via CCXT. Starter supports 1 broker, "
            "Professional supports 3, Enterprise and Elite support unlimited brokers."
        ),
    },
    {
        "question": "What is white-labelling?",
        "answer": (
            "Enterprise and Elite plans allow you to rebrand the platform with your own "
            "logo, domain, and colour scheme for your clients."
        ),
    },
    {
        "question": "Do you offer refunds?",
        "answer": (
            "We offer a 7-day money-back guarantee on first-time subscriptions. "
            "Contact support@hopefx.ai within 7 days of your first payment."
        ),
    },
]

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if _FASTAPI_AVAILABLE:
    router = APIRouter(prefix="/api/pricing", tags=["Pricing"])

    class EstimateRequest(BaseModel):
        tier: str
        billing_cycle: str = "monthly"  # "monthly" | "annual"
        trade_volume_usd: float = 0.0   # monthly notional volume

    @router.get("/plans", summary="List all subscription plans with full feature matrix")
    async def get_plans(billing_cycle: str = Query("monthly", pattern="^(monthly|annual)$")):
        """
        Return the full 5-tier plan catalogue.

        Query params:
          billing_cycle: 'monthly' (default) or 'annual'

        Returns price in the requested billing cycle alongside all feature flags,
        limits, highlights, and CTA metadata.
        """
        annual = billing_cycle == "annual"
        result = []
        for plan in _PLANS:
            p = dict(plan)
            p["price_usd"] = p["price_usd_annual"] if annual else p["price_usd_monthly"]
            p["billing_cycle"] = billing_cycle
            result.append(p)
        return {"plans": result, "billing_cycle": billing_cycle}

    @router.get("/compare", summary="Side-by-side feature comparison for two tiers")
    async def compare_plans(
        tier_a: str = Query(..., description="First tier ID (e.g. 'professional')"),
        tier_b: str = Query(..., description="Second tier ID (e.g. 'enterprise')"),
    ):
        """
        Return a structured feature comparison between two tiers.

        Useful for upgrade prompts — shows exactly which features are gained.
        """
        plan_map = {p["id"]: p for p in _PLANS}
        if tier_a not in plan_map:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {tier_a}")
        if tier_b not in plan_map:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {tier_b}")

        a = plan_map[tier_a]
        b = plan_map[tier_b]

        comparison = []
        for key, label in _FEATURE_LABELS.items():
            val_a = a["features"].get(key, False)
            val_b = b["features"].get(key, False)
            comparison.append({
                "feature": key,
                "label": label,
                tier_a: val_a,
                tier_b: val_b,
                "gained": (not val_a) and val_b,
                "lost": val_a and (not val_b),
            })

        return {
            "tier_a": {"id": tier_a, "name": a["name"], "price_usd_monthly": a["price_usd_monthly"]},
            "tier_b": {"id": tier_b, "name": b["name"], "price_usd_monthly": b["price_usd_monthly"]},
            "price_delta_monthly": b["price_usd_monthly"] - a["price_usd_monthly"],
            "features_gained": [c for c in comparison if c["gained"]],
            "features_lost": [c for c in comparison if c["lost"]],
            "all_features": comparison,
        }

    @router.get("/upgrade-path", summary="Available upgrade options from current tier")
    async def get_upgrade_path(current_tier: str = Query("free")):
        """
        Return the ordered list of tiers the user can upgrade to from their current tier.

        Used by upgrade prompts and the subscription settings page.
        """
        tier_order = ["free", "starter", "professional", "enterprise", "elite"]
        if current_tier not in tier_order:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {current_tier}")

        current_idx = tier_order.index(current_tier)
        plan_map = {p["id"]: p for p in _PLANS}

        upgrades = []
        for tier_id in tier_order[current_idx + 1:]:
            p = plan_map[tier_id]
            upgrades.append({
                "id": tier_id,
                "name": p["name"],
                "price_usd_monthly": p["price_usd_monthly"],
                "price_usd_annual": p["price_usd_annual"],
                "badge": p["badge"],
                "cta": p["cta"],
                "cta_href": p["cta_href"],
                "highlights": p["highlights"],
            })

        return {
            "current_tier": current_tier,
            "upgrade_options": upgrades,
        }

    @router.get("/faq", summary="Pricing FAQ")
    async def get_faq():
        """Return pricing FAQ entries for the pricing page."""
        return {"faq": _FAQ}

    @router.post("/estimate", summary="Estimate monthly cost given usage parameters")
    async def estimate_cost(req: EstimateRequest):
        """
        Estimate the total monthly cost for a given tier and trading volume.

        Returns:
          - subscription_cost: flat monthly/annual fee
          - commission_cost: estimated commission on trade_volume_usd
          - total_cost: sum of both
        """
        plan_map = {p["id"]: p for p in _PLANS}
        if req.tier not in plan_map:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {req.tier}")

        plan = plan_map[req.tier]
        annual = req.billing_cycle == "annual"
        sub_cost = plan["price_usd_annual"] if annual else plan["price_usd_monthly"]
        commission_cost = req.trade_volume_usd * plan["commission_rate"]
        total = sub_cost + commission_cost

        return {
            "tier": req.tier,
            "billing_cycle": req.billing_cycle,
            "subscription_cost_usd": sub_cost,
            "commission_rate": plan["commission_rate"],
            "commission_cost_usd": round(commission_cost, 2),
            "total_cost_usd": round(total, 2),
            "trade_volume_usd": req.trade_volume_usd,
        }

else:
    # Graceful no-op when FastAPI is not installed
    router = None  # type: ignore[assignment]
