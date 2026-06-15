# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/compat_router.py
=====================
Convenience alias endpoints that preserve backwards-compatible URL paths for
external clients, mobile apps, and integration dashboards.

Every endpoint here delegates to the canonical API layer via HTTP redirect
(307 Temporary Redirect) or direct function call — **no hard-coded /
synthetic data is returned from this module**.

Routes exposed (all require ****** unless noted):
    GET  /api/dashboard/stats         → /api/performance/metrics  (307)
    GET  /api/trades                  → /api/trading/trades        (307)
    GET  /api/market-data/live        → /api/trading/price/XAUUSD  (307)
    GET  /api/ai/signals              → /api/trading/signals       (307)
    GET  /api/nuclear/status          → /api/nuclear/status        (307)
    GET  /api/system/health           → /api/health/live           (307, public)
    GET  /api/risk/metrics            → /api/trading/risk          (307)
    GET  /api/performance/metrics     → /api/performance/metrics   (307)
    GET  /api/calendar/events         → /api/calendar              (307)
    GET  /api/marketplace/items       → /api/monetization/marketplace/featured (307)
    GET  /api/prop-firm/status        → /api/risk/prop-firm-status (307)
    GET  /api/copy-trading/status     → /api/social/copy/active    (307)
    GET  /api/admin/users             → /api/admin/all-users       (307, admin)
    GET  /api/superadmin/overview     → /api/superadmin/overview   (307, superadmin)
"""

import logging

from fastapi import APIRouter, Depends
from starlette.responses import RedirectResponse

from api.auth import TokenPayload
from api.auth import get_current_user as _get_current_user
from api.auth import require_role as _require_role

logger = logging.getLogger(__name__)

compat_router = APIRouter(prefix="/api", tags=["Convenience Aliases"])


@compat_router.get("/dashboard/stats", summary="Trading dashboard summary stats")
async def dashboard_stats(user: TokenPayload = Depends(_get_current_user)):
    """Aggregate stats for the main trading dashboard — delegates to /api/performance/metrics."""
    return RedirectResponse(url="/api/performance/metrics", status_code=307)


@compat_router.get("/trades", summary="Recent trade history (alias for /trading/trades)")
async def trades_alias(limit: int = 50, user: TokenPayload = Depends(_get_current_user)):
    """Return recent closed trades — delegates to /api/trading/trades."""
    # Clamp limit to a safe integer range before embedding in the redirect URL
    # (CodeQL: avoid untrusted input flowing unsanitised into the redirect URL).
    _safe_limit = max(1, min(int(limit), 1000))
    return RedirectResponse(url=f"/api/trading/trades?limit={_safe_limit}", status_code=307)


@compat_router.get("/market-data/live", summary="Live XAU/USD market data")
async def market_data_live(user: TokenPayload = Depends(_get_current_user)):
    """Return live or last-known XAU/USD price data — delegates to /api/trading/price/XAUUSD."""
    return RedirectResponse(url="/api/trading/price/XAUUSD", status_code=307)


@compat_router.get("/ai/signals", summary="AI trading signals (alias for /trading/signals)")
async def ai_signals_alias(user: TokenPayload = Depends(_get_current_user)):
    """Return active AI trading signals — delegates to /api/trading/signals."""
    return RedirectResponse(url="/api/trading/signals", status_code=307)


@compat_router.get("/nuclear/status", summary="Nuclear AI engine status")
async def nuclear_status(user: TokenPayload = Depends(_get_current_user)):
    """Return Nuclear AI engine status — delegates to /api/nuclear/status."""
    return RedirectResponse(url="/api/nuclear/status", status_code=307)


@compat_router.get("/system/health", summary="System health overview (alias for /api/health/live)")
async def system_health_alias():
    """Return system health status — delegates to /api/health/live (public endpoint)."""
    return RedirectResponse(url="/api/health/live", status_code=307)


@compat_router.get("/risk/metrics", summary="Risk metrics snapshot (alias for /trading/risk)")
async def risk_metrics_alias(user: TokenPayload = Depends(_get_current_user)):
    """Return current risk metrics — delegates to /api/trading/risk."""
    return RedirectResponse(url="/api/trading/risk", status_code=307)


@compat_router.get("/performance/metrics", summary="Performance metrics (alias for /performance/metrics)")
async def perf_metrics_alias(user: TokenPayload = Depends(_get_current_user)):
    """Return performance metrics — delegates to /api/performance/metrics."""
    return RedirectResponse(url="/api/performance/metrics", status_code=307)


@compat_router.get("/calendar/events", summary="Economic calendar events (alias for /calendar)")
async def calendar_events_alias(user: TokenPayload = Depends(_get_current_user)):
    """Return upcoming economic calendar events — delegates to /api/calendar."""
    return RedirectResponse(url="/api/calendar", status_code=307)


@compat_router.get("/marketplace/items", summary="Marketplace strategies and items")
async def marketplace_items(user: TokenPayload = Depends(_get_current_user)):
    """Return featured marketplace items — delegates to /api/monetization/marketplace/featured."""
    return RedirectResponse(url="/api/monetization/marketplace/featured", status_code=307)


@compat_router.get("/prop-firm/status", summary="Prop firm challenge status")
async def prop_firm_status(user: TokenPayload = Depends(_get_current_user)):
    """Return active prop firm challenge status — delegates to /api/risk/prop-firm-status."""
    return RedirectResponse(url="/api/risk/prop-firm-status", status_code=307)


@compat_router.get("/copy-trading/status", summary="Copy trading status")
async def copy_trading_status(user: TokenPayload = Depends(_get_current_user)):
    """Return copy trading relationships — delegates to /api/social/copy/active."""
    return RedirectResponse(url="/api/social/copy/active", status_code=307)


@compat_router.get("/admin/users", summary="Admin: list users (alias for /admin/all-users)")
async def admin_users_alias(_user: TokenPayload = Depends(_require_role("admin"))):
    """Return user list — admin role required; delegates to /api/admin/all-users."""
    return RedirectResponse(url="/api/admin/all-users", status_code=307)


@compat_router.get("/superadmin/overview", summary="Super-admin platform overview")
async def superadmin_overview_alias(_user: TokenPayload = Depends(_require_role("superadmin"))):
    """Return platform overview for super-admin — delegates to /api/superadmin/overview."""
    return RedirectResponse(url="/api/superadmin/overview", status_code=307)
