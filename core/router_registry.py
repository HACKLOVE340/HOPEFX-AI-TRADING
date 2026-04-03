# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/router_registry.py
=======================
All FastAPI router registrations in one place.

Extracted from app.py to keep the application entry point under 300 lines.

Usage
-----
    from core.router_registry import register_routers
    register_routers(app, feature_flags, graphql_router, signals_router)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def register_routers(
    app: FastAPI,
    feature_flags: Any,
    graphql_router: Any | None = None,
    graphql_available: bool = False,
    signals_router: Any | None = None,
) -> None:
    """Register all API routers on *app*, respecting feature flags."""

    # ── Core routers (always on) ──────────────────────────────────────────────
    from api.accounts import router as accounts_router
    from api.admin import router as admin_router
    from api.backtesting import router as backtesting_router
    from api.brain import router as brain_router
    from api.broker import router as broker_router
    from api.calendar import router as calendar_router
    from api.chat import router as chat_router
    from api.explain import router as explain_router
    from api.landing import router as landing_router
    from api.macro import router as macro_router
    from api.ml import router as ml_router
    from api.mobile import router as mobile_router
    from api.monetization import router as monetization_router
    from api.online_learner import router as online_learner_router
    from api.payments import router as payments_router
    from api.performance import router as performance_router
    from api.platform import router as platform_router
    from api.portfolio import router as portfolio_router
    from api.profiles import router as profiles_router
    from api.prop_firm import router as prop_firm_router
    from api.settings import router as settings_router
    from api.settings_extended import router as settings_extended_router
    from api.settings_new_endpoints import router as settings_new_router
    from api.social_feed import leaderboard_router as social_leaderboard_router
    from api.social_feed import router as social_feed_router
    from api.status import router as status_router
    from api.trading import router as trading_router
    from api.whitelabel_admin import router as whitelabel_router
    from auth.router import router as auth_router

    for _router in [
        auth_router,
        trading_router,
        admin_router,
        monetization_router,
        backtesting_router,
        online_learner_router,
        chat_router,
        prop_firm_router,
        performance_router,
        explain_router,
        macro_router,
        broker_router,
        landing_router,
        payments_router,
        settings_router,
        settings_extended_router,
        settings_new_router,
        status_router,
        brain_router,
        calendar_router,
        profiles_router,
        social_feed_router,
        social_leaderboard_router,
        mobile_router,
        whitelabel_router,
        platform_router,
        ml_router,
        accounts_router,
        portfolio_router,
    ]:
        app.include_router(_router)

    # ── Feature-gated routers ─────────────────────────────────────────────────
    if feature_flags.TWO_FACTOR_AUTH:
        from api.two_factor import router as two_factor_router

        app.include_router(two_factor_router)
        logger.info("Two-factor auth router registered (/api/2fa)")
    else:
        logger.debug("TWO_FACTOR_AUTH disabled — set FEATURE_TWO_FACTOR_AUTH=true to enable")

    if feature_flags.WATCHLIST:
        from api.watchlist import router as watchlist_router

        app.include_router(watchlist_router)
        logger.info("Watchlist router registered (/api/watchlist)")
    else:
        logger.debug("WATCHLIST disabled — set FEATURE_WATCHLIST=true to enable")

    if feature_flags.TRADE_JOURNAL:
        from api.journal import router as journal_router

        app.include_router(journal_router)
        logger.info("Trade journal router registered (/api/journal)")
    else:
        logger.debug("TRADE_JOURNAL disabled — set FEATURE_TRADE_JOURNAL=true to enable")

    if feature_flags.BILLING_SUBSCRIPTION:
        from api.billing import router as billing_router

        app.include_router(billing_router)
        logger.info("Billing router registered (/api/billing)")
    else:
        logger.debug("BILLING_SUBSCRIPTION disabled — set FEATURE_BILLING_SUBSCRIPTION=true to enable")

    if feature_flags.ADVANCED_TRADING:
        from api.advanced_trading import router as advanced_router

        app.include_router(advanced_router)
        logger.info("Advanced trading router registered (/api/advanced)")
    else:
        logger.debug("ADVANCED_TRADING disabled — set FEATURE_ADVANCED_TRADING=true to enable")

    if feature_flags.PRICE_ALERTS:
        from api.alerts import router as alerts_router

        app.include_router(alerts_router)
        logger.info("Price alerts router registered (/api/alerts)")
    else:
        logger.debug("PRICE_ALERTS disabled — set FEATURE_PRICE_ALERTS=true to enable")

    # ── Signals router ────────────────────────────────────────────────────────
    if signals_router is not None:
        app.include_router(signals_router)
        logger.info("Signals router registered (/api/signals)")

    # ── GraphQL ───────────────────────────────────────────────────────────────
    if feature_flags.GRAPHQL_API and graphql_available and graphql_router is not None:
        app.include_router(graphql_router, prefix="/graphql")
        logger.info("GraphQL endpoint mounted at /graphql")
    elif graphql_available and not feature_flags.GRAPHQL_API:
        logger.debug("GRAPHQL_API disabled — set FEATURE_GRAPHQL_API=true to enable")

    # ── TCA (Transaction Cost Analysis) ──────────────────────────────────────
    try:
        from api.tca import router as tca_router

        app.include_router(tca_router)
        logger.info("TCA router registered (/tca)")
    except Exception as _tca_err:
        logger.warning("TCA router not registered: %s", _tca_err)

    # ── Security fixes (LLM auto-heal queue + GitHub PR pipeline) ─────────────
    try:
        from api.security.fixes import router as fixes_router

        app.include_router(fixes_router)
        logger.info("Security fixes router registered (/api/security/fixes)")
    except Exception as _fixes_err:
        logger.warning("Security fixes router not registered: %s", _fixes_err)

    # ── Live WebSocket ────────────────────────────────────────────────────────
    try:
        from api.ws_live import router as ws_live_router

        app.include_router(ws_live_router)
        logger.info("Live WebSocket router registered (/ws/live)")
    except Exception as _ws_live_err:
        logger.warning("Live WebSocket router not registered: %s", _ws_live_err)
