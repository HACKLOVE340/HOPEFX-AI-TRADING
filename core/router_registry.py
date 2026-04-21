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

# ── Deduplication registry ────────────────────────────────────────────────────
# Tracks (method, path) pairs already registered so that compat/alias routers
# do not create duplicate routes that cause FastAPI to match the wrong handler.
_registered_routes: set[tuple[str, str]] = set()


def _include_router_deduped(app: FastAPI, router: Any, **kwargs: Any) -> None:
    """
    Include a router on *app*, skipping any routes whose (method, path) pair
    is already registered.  This prevents duplicate route warnings and ensures
    the first-registered handler wins (primary router takes precedence over
    compat/alias routers).
    """
    from fastapi.routing import APIRoute as _APIRoute

    skipped = 0
    for route in router.routes:
        if not isinstance(route, _APIRoute):
            continue
        for method in route.methods or {"GET"}:
            key = (method.upper(), route.path)
            if key in _registered_routes:
                skipped += 1
                logger.debug(
                    "Router dedup: skipping duplicate %s %s (already registered)",
                    method,
                    route.path,
                )

    if skipped:
        # Build a filtered router with only non-duplicate routes
        from fastapi import APIRouter as _APIRouter

        filtered = _APIRouter(
            prefix=router.prefix,
            tags=router.tags,
            dependencies=router.dependencies,
            default_response_class=router.default_response_class,
        )
        for route in router.routes:
            if not isinstance(route, _APIRoute):
                # Non-API routes (WebSocket, Mount, etc.) — always include
                filtered.routes.append(route)
                continue
            methods = route.methods or {"GET"}
            if any((m.upper(), route.path) in _registered_routes for m in methods):
                continue
            filtered.add_api_route(
                route.path,
                route.endpoint,
                methods=list(methods),
                response_model=route.response_model,
                status_code=route.status_code,
                tags=list(route.tags) if route.tags else None,
                summary=route.summary,
                description=route.description,
                include_in_schema=route.include_in_schema,
                dependencies=route.dependencies,
                name=route.name,
            )
        app.include_router(filtered, **kwargs)
    else:
        app.include_router(router, **kwargs)

    # Record all routes now on the app
    for route in app.routes:
        if isinstance(route, _APIRoute):
            for method in route.methods or {"GET"}:
                _registered_routes.add((method.upper(), route.path))


def register_routers(
    app: FastAPI,
    feature_flags: Any,
    graphql_router: Any | None = None,
    graphql_available: bool = False,
    signals_router: Any | None = None,
) -> None:
    """Register all API routers on *app*, respecting feature flags."""
    # Reset dedup registry for this registration pass (supports test isolation)
    _registered_routes.clear()

    # ── Core routers (always on) ──────────────────────────────────────────────
    from api.accounts import router as accounts_router
    from api.admin import router as admin_router
    from api.analysis import router as analysis_router
    from api.backtesting import _compat_router as backtesting_compat_router
    from api.backtesting import router as backtesting_router
    from api.brain import router as brain_router
    from api.broker import router as broker_router
    from api.calendar import router as calendar_router
    from api.chat import router as chat_router
    from api.explain import router as explain_router
    from api.health import router as health_router
    from api.landing import router as landing_router
    from api.pages import router as pages_router
    from api.macro import router as macro_router
    from api.ml import router as ml_router
    from api.ml_anomaly import router as ml_anomaly_router
    from api.mobile import router as mobile_router
    from api.monetization import router as monetization_router
    from api.online_learner import router as online_learner_router
    from api.payments import router as payments_router
    from api.performance import router as performance_router
    from api.platform import router as platform_router
    from api.portfolio import router as portfolio_router
    from api.portfolio_allocator import router as portfolio_allocator_router
    from api.profiles import router as profiles_router
    from api.prop_firm import router as prop_firm_router
    from api.settings import router as settings_router
    from api.settings_extended import router as settings_extended_router
    from api.settings_new_endpoints import router as settings_new_router
    from api.social_feed import _copy_router as social_copy_router
    from api.social_feed import _lb_compat_router as social_lb_compat_router
    from api.social_feed import leaderboard_router as social_leaderboard_router
    from api.social_feed import router as social_feed_router
    from api.status import router as status_router
    from api.tracing import router as tracing_router
    from api.trading import router as trading_router
    from api.whitelabel_admin import router as whitelabel_router
    from auth.router import router as auth_router

    for _router in [
        auth_router,
        trading_router,
        admin_router,
        analysis_router,
        monetization_router,
        backtesting_router,
        backtesting_compat_router,
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
        social_copy_router,
        social_lb_compat_router,
        mobile_router,
        whitelabel_router,
        platform_router,
        ml_router,
        ml_anomaly_router,
        accounts_router,
        portfolio_router,
        portfolio_allocator_router,
        health_router,
        tracing_router,
        pages_router,
    ]:
        _include_router_deduped(app, _router)

    logger.info("Health router registered (/api/health)")
    logger.info("Analysis router registered (/api/analysis)")
    logger.info("Tracing router registered (/api/tracing)")
    logger.info("ML anomaly router registered (/api/ml/anomaly)")
    logger.info("Portfolio allocator router registered (/api/portfolio/allocator)")
    logger.info("Pages router registered (/login, /register, /about, /privacy, /terms, /security, /marketplace, /affiliate, /docs/*)")

    # ── Feature-gated routers ─────────────────────────────────────────────────
    if feature_flags.TWO_FACTOR_AUTH:
        from api.two_factor import router as two_factor_router

        _include_router_deduped(app, two_factor_router)
        logger.info("Two-factor auth router registered (/api/2fa)")
    else:
        logger.debug("TWO_FACTOR_AUTH disabled — set FEATURE_TWO_FACTOR_AUTH=true to enable")

    if feature_flags.WATCHLIST:
        from api.watchlist import router as watchlist_router

        _include_router_deduped(app, watchlist_router)
        logger.info("Watchlist router registered (/api/watchlist)")
    else:
        logger.debug("WATCHLIST disabled — set FEATURE_WATCHLIST=true to enable")

    if feature_flags.TRADE_JOURNAL:
        from api.journal import router as journal_router

        _include_router_deduped(app, journal_router)
        logger.info("Trade journal router registered (/api/journal)")
    else:
        logger.debug("TRADE_JOURNAL disabled — set FEATURE_TRADE_JOURNAL=true to enable")

    if feature_flags.BILLING_SUBSCRIPTION:
        from api.billing import router as billing_router

        _include_router_deduped(app, billing_router)
        logger.info("Billing router registered (/api/billing)")
    else:
        logger.debug("BILLING_SUBSCRIPTION disabled — set FEATURE_BILLING_SUBSCRIPTION=true to enable")

    # ── Public pricing catalogue (/api/pricing) — no auth required ────────────
    try:
        from api.pricing import router as pricing_router

        if pricing_router is not None:
            _include_router_deduped(app, pricing_router)
            logger.info("Pricing router registered (/api/pricing)")
    except Exception as _pricing_err:
        logger.warning("Pricing router not registered: %s", _pricing_err)

    if feature_flags.ADVANCED_TRADING:
        from api.advanced_trading import _adv_router as advanced_compat_router
        from api.advanced_trading import public_router as advanced_public_router
        from api.advanced_trading import router as advanced_router

        _include_router_deduped(app, advanced_router)
        _include_router_deduped(app, advanced_compat_router)
        # public_router carries no auth dependency — shared backtest view
        _include_router_deduped(app, advanced_public_router)
        logger.info("Advanced trading router registered (/api/advanced)")
    else:
        logger.debug("ADVANCED_TRADING disabled — set FEATURE_ADVANCED_TRADING=true to enable")

    if feature_flags.PRICE_ALERTS:
        from api.alerts import router as alerts_router

        _include_router_deduped(app, alerts_router)
        logger.info("Price alerts router registered (/api/alerts)")
    else:
        logger.debug("PRICE_ALERTS disabled — set FEATURE_PRICE_ALERTS=true to enable")

    # ── Signals router ────────────────────────────────────────────────────────
    if signals_router is not None:
        _include_router_deduped(app, signals_router)
        logger.info("Signals router registered (/api/signals)")

    # ── GraphQL ───────────────────────────────────────────────────────────────
    if feature_flags.GRAPHQL_API and graphql_available and graphql_router is not None:
        _include_router_deduped(app, graphql_router, prefix="/graphql")
        logger.info("GraphQL endpoint mounted at /graphql")
    elif graphql_available and not feature_flags.GRAPHQL_API:
        logger.debug("GRAPHQL_API disabled — set FEATURE_GRAPHQL_API=true to enable")

    # ── Security: HOPEFXBrain (/api/security/*) ───────────────────────────────
    # Eager module-level router — delegates to get_brain() at request time so
    # the live instance created by start_brain() is used once startup completes.
    try:
        from security.global_fortress import security_router as _security_router

        _include_router_deduped(app, _security_router)
        logger.info("Security brain router registered (/api/security/*)")
    except Exception as _brain_err:
        logger.warning("Security brain router not registered: %s", _brain_err)

    # ── Security: SelfHealer (/api/security/heal/*) ───────────────────────────
    try:
        from security.self_healer import heal_router as _heal_router

        _include_router_deduped(app, _heal_router)
        logger.info("SelfHealer router registered (/api/security/heal/*)")
    except Exception as _heal_err:
        logger.warning("SelfHealer router not registered: %s", _heal_err)

    # ── Security: AntivirusScanner (/api/security/av/*) ───────────────────────
    try:
        from security.antivirus import av_router as _av_router

        _include_router_deduped(app, _av_router)
        logger.info("Antivirus router registered (/api/security/av/*)")
    except Exception as _av_err:
        logger.warning("Antivirus router not registered: %s", _av_err)

    # ── TCA (Transaction Cost Analysis) ──────────────────────────────────────
    try:
        from api.tca import router as tca_router

        _include_router_deduped(app, tca_router)
        logger.info("TCA router registered (/api/tca)")
    except Exception as _tca_err:
        logger.warning("TCA router not registered: %s", _tca_err)

    # ── P&L Dashboard ─────────────────────────────────────────────────────────
    try:
        from api.pnl_dashboard import router as pnl_router

        _include_router_deduped(app, pnl_router)
        logger.info("P&L dashboard router registered (/api/pnl)")
    except Exception as _pnl_err:
        logger.warning("P&L dashboard router not registered: %s", _pnl_err)

    # ── SuperAdmin ────────────────────────────────────────────────────────────
    try:
        from api.superadmin import router as superadmin_router

        _include_router_deduped(app, superadmin_router)
        logger.info("SuperAdmin router registered (/api/superadmin)")
    except Exception as _sa_err:
        logger.warning("SuperAdmin router not registered: %s", _sa_err)

    # ── Nuclear strategy ──────────────────────────────────────────────────────
    try:
        from api.nuclear import router as nuclear_router
        from api.nuclear_strategy import router as nuclear_strategy_router

        _include_router_deduped(app, nuclear_router)
        _include_router_deduped(app, nuclear_strategy_router)
        logger.info("Nuclear routers registered")
    except Exception as _nuc_err:
        logger.warning("Nuclear routers not registered: %s", _nuc_err)

    # ── KYC ───────────────────────────────────────────────────────────────────
    try:
        from api.kyc import router as kyc_router

        _include_router_deduped(app, kyc_router)
        logger.info("KYC router registered (/kyc)")
    except Exception as _kyc_err:
        logger.warning("KYC router not registered: %s", _kyc_err)

    # ── Chaos / mutation testing ──────────────────────────────────────────────
    try:
        from api.chaos import router as chaos_router

        _include_router_deduped(app, chaos_router)
        logger.info("Chaos router registered (/api/chaos)")
    except Exception as _chaos_err:
        logger.warning("Chaos router not registered: %s", _chaos_err)

    # ── Data layer (orchestrator) ─────────────────────────────────────────────
    try:
        from api.data_layer import router as data_layer_router

        _include_router_deduped(app, data_layer_router)
        logger.info("Data layer router registered (/api/data-layer)")
    except Exception as _dl_err:
        logger.warning("Data layer router not registered: %s", _dl_err)

    # ── Security fixes (LLM auto-heal queue + GitHub PR pipeline) ─────────────
    try:
        from api.security.fixes import router as fixes_router

        _include_router_deduped(app, fixes_router)
        logger.info("Security fixes router registered (/api/security/fixes)")
    except Exception as _fixes_err:
        logger.warning("Security fixes router not registered: %s", _fixes_err)

    # ── Security dashboard (attacks, lockdown, heal, AV) ──────────────────────
    try:
        from api.security_dashboard import router as sec_dashboard_router

        _include_router_deduped(app, sec_dashboard_router)
        logger.info("Security dashboard router registered (/api/security/*)")
    except Exception as _sec_err:
        logger.warning("Security dashboard router not registered: %s", _sec_err)

    # ── Market data streaming (/api/stream) ───────────────────────────────────
    if feature_flags.MARKET_DATA_STREAMING:
        try:
            from data.streaming import router as streaming_router

            _include_router_deduped(app, streaming_router)
            logger.info("Market data streaming router registered (/api/stream)")
        except Exception as _stream_err:
            logger.warning("Market data streaming router not registered: %s", _stream_err)
    else:
        logger.debug("MARKET_DATA_STREAMING disabled — set FEATURE_MARKET_DATA_STREAMING=true to enable")

    # ── Depth of Market (/api/dom) ────────────────────────────────────────────
    if feature_flags.DEPTH_OF_MARKET:
        try:
            from data.depth_of_market import router as dom_router

            _include_router_deduped(app, dom_router)
            logger.info("Depth of Market router registered (/api/dom)")
        except Exception as _dom_err:
            logger.warning("Depth of Market router not registered: %s", _dom_err)
    else:
        logger.debug("DEPTH_OF_MARKET disabled — set FEATURE_DEPTH_OF_MARKET=true to enable")

    # ── Time & Sales (/api/timesales) ─────────────────────────────────────────
    if feature_flags.TIME_AND_SALES:
        try:
            from data.time_and_sales import router as timesales_router

            _include_router_deduped(app, timesales_router)
            logger.info("Time & Sales router registered (/api/timesales)")
        except Exception as _ts_err:
            logger.warning("Time & Sales router not registered: %s", _ts_err)
    else:
        logger.debug("TIME_AND_SALES disabled — set FEATURE_TIME_AND_SALES=true to enable")

    # ── Order Flow Analysis (/api/orderflow) ──────────────────────────────────
    if feature_flags.ORDER_FLOW_ANALYSIS:
        try:
            from analysis.order_flow import router as orderflow_router

            _include_router_deduped(app, orderflow_router)
            logger.info("Order Flow router registered (/api/orderflow)")
        except Exception as _of_err:
            logger.warning("Order Flow router not registered: %s", _of_err)
    else:
        logger.debug("ORDER_FLOW_ANALYSIS disabled — set FEATURE_ORDER_FLOW_ANALYSIS=true to enable")

    # ── Order Flow Dashboard (/api/dashboard) ─────────────────────────────────
    if feature_flags.ORDER_FLOW_DASHBOARD:
        try:
            from analysis.order_flow_dashboard import router as of_dashboard_router

            _include_router_deduped(app, of_dashboard_router)
            logger.info("Order Flow Dashboard router registered (/api/dashboard)")
        except Exception as _ofd_err:
            logger.warning("Order Flow Dashboard router not registered: %s", _ofd_err)
    else:
        logger.debug("ORDER_FLOW_DASHBOARD disabled — set FEATURE_ORDER_FLOW_DASHBOARD=true to enable")

    # ── Market Scanner (/api/scanner) ─────────────────────────────────────────
    if feature_flags.MARKET_SCANNER:
        try:
            from analysis.market_scanner import router as scanner_router

            _include_router_deduped(app, scanner_router)
            logger.info("Market Scanner router registered (/api/scanner)")
        except Exception as _scan_err:
            logger.warning("Market Scanner router not registered: %s", _scan_err)
    else:
        logger.debug("MARKET_SCANNER disabled — set FEATURE_MARKET_SCANNER=true to enable")

    # ── Portfolio Strategy Allocator (/api/portfolio/allocator) ───────────────
    try:
        from portfolio.strategy_allocator import router as allocator_router

        _include_router_deduped(app, allocator_router)
        logger.info("Portfolio allocator router registered (/api/portfolio/allocator)")
    except Exception as _alloc_err:
        logger.warning("Portfolio allocator router not registered: %s", _alloc_err)

    # ── Research module (/api/research) ───────────────────────────────────────
    if feature_flags.RESEARCH_MODULE:
        try:
            from research import router as research_router

            _include_router_deduped(app, research_router)
            logger.info("Research router registered (/api/research)")
        except Exception as _res_err:
            logger.warning("Research router not registered: %s", _res_err)
    else:
        logger.debug("RESEARCH_MODULE disabled — set FEATURE_RESEARCH=true to enable")

    # ── No-Code Strategy Builder (/api/nocode) ────────────────────────────────
    if feature_flags.NOCODE_BUILDER:
        try:
            from nocode.router import router as nocode_router

            _include_router_deduped(app, nocode_router)
            logger.info("No-Code builder router registered (/api/nocode)")
        except Exception as _nc_err:
            logger.warning("No-Code builder router not registered: %s", _nc_err)
    else:
        logger.debug("NOCODE_BUILDER disabled — set FEATURE_NOCODE=true to enable")

    # ── Teams (/api/teams) ────────────────────────────────────────────────────
    if feature_flags.TEAMS_MODULE:
        try:
            from teams import router as teams_router

            _include_router_deduped(app, teams_router)
            logger.info("Teams router registered (/api/teams)")
        except Exception as _teams_err:
            logger.warning("Teams router not registered: %s", _teams_err)
    else:
        logger.debug("TEAMS_MODULE disabled — set FEATURE_TEAMS=true to enable")

    # ── Replay Engine (/api/replay) ───────────────────────────────────────────
    if feature_flags.REPLAY_ENGINE:
        try:
            from replay.router import router as replay_router

            _include_router_deduped(app, replay_router)
            logger.info("Replay engine router registered (/api/replay)")
        except Exception as _replay_err:
            logger.warning("Replay engine router not registered: %s", _replay_err)
    else:
        logger.debug("REPLAY_ENGINE disabled — set FEATURE_REPLAY=true to enable")

    # ── Notifications / Alert Engine (/api/alerts) ────────────────────────────
    if feature_flags.PUSH_NOTIFICATIONS:
        try:
            from notifications.alert_engine import router as notifications_router

            _include_router_deduped(app, notifications_router)
            logger.info("Notifications/alert engine router registered (/api/alerts)")
        except Exception as _notif_err:
            logger.warning("Notifications router not registered: %s", _notif_err)
    else:
        logger.debug("PUSH_NOTIFICATIONS disabled — set FEATURE_PUSH_NOTIFICATIONS=true to enable")

    # ── Transparency Reports (/api/transparency) ──────────────────────────────
    if feature_flags.TRANSPARENCY_REPORTS:
        try:
            from transparency.router import router as transparency_router

            _include_router_deduped(app, transparency_router)
            logger.info("Transparency router registered (/api/transparency)")
        except Exception as _trans_err:
            logger.warning("Transparency router not registered: %s", _trans_err)
    else:
        logger.debug("TRANSPARENCY_REPORTS disabled — set FEATURE_TRANSPARENCY=true to enable")

    # ── Explainability (/api/explainability) ──────────────────────────────────
    if feature_flags.EXPLAINABILITY:
        try:
            from explainability.router import router as explainability_router

            _include_router_deduped(app, explainability_router)
            logger.info("Explainability router registered (/api/explainability)")
        except Exception as _expl_err:
            logger.warning("Explainability router not registered: %s", _expl_err)
    else:
        logger.debug("EXPLAINABILITY disabled — set FEATURE_EXPLAINABILITY=true to enable")

    # ── Mobile API v2 (/mobile) ───────────────────────────────────────────────
    # Strategy: include_router for REST routes (visible in OpenAPI schema) +
    # app.mount for the full sub-app so WebSocket routes are also reachable.
    if feature_flags.MOBILE_API:
        try:
            from mobile.api_v2 import app as mobile_v2_app
            from mobile.api_v2 import router as mobile_v2_router

            # REST routes — included so they appear in the main OpenAPI schema
            # and pass through the main app's auth/rate-limit middleware.
            _include_router_deduped(app, mobile_v2_router)

            # Sub-app mount — required for WebSocket routes (/mobile/api/v2/ws/*)
            # which cannot be expressed as APIRoute objects on an APIRouter.
            # Mounted at /mobile so paths like /mobile/api/v2/ws/quotes work.
            app.mount("/mobile", mobile_v2_app)

            logger.info("Mobile API v2 registered: REST routes via include_router + WebSocket via mount(/mobile)")
        except Exception as _mob_err:
            logger.warning("Mobile API v2 router not registered: %s", _mob_err)
    else:
        logger.debug("MOBILE_API disabled — set FEATURE_MOBILE_API=true to enable")

    # ── News & Geopolitical Intelligence (/api/news) ─────────────────────────
    try:
        from news import create_news_router as _create_news_router

        _news_router = _create_news_router()
        if _news_router is not None:
            _include_router_deduped(app, _news_router)
            logger.info("News & Geopolitical router registered (/api/news)")
    except Exception as _news_err:
        logger.warning("News router not registered: %s", _news_err)

    # ── Public WebSocket (no auth — landing page ticker) ──────────────────────
    try:
        from api.ws_public import router as ws_public_router

        _include_router_deduped(app, ws_public_router)
        logger.info("Public WebSocket router registered (/ws/public)")
    except Exception as _ws_pub_err:
        logger.warning("Public WebSocket router not registered: %s", _ws_pub_err)

    # ── Live WebSocket ────────────────────────────────────────────────────────
    try:
        from api.ws_live import router as ws_live_router

        _include_router_deduped(app, ws_live_router)
        logger.info("Live WebSocket router registered (/ws/live)")
    except Exception as _ws_live_err:
        logger.warning("Live WebSocket router not registered: %s", _ws_live_err)

    # ── WebSocket server (legacy /ws endpoint) ────────────────────────────────
    try:
        from api.websocket_server import create_websocket_router, get_websocket_manager

        _ws_router = create_websocket_router(get_websocket_manager())
        _include_router_deduped(app, _ws_router)
        logger.info("WebSocket server router registered (/ws)")
    except Exception as _ws_err:
        logger.warning("WebSocket server router not registered: %s", _ws_err)

    # ── API v1 versioned prefix ────────────────────────────────────────────────
    # Mount a thin /api/v1/* prefix that re-exports the existing /api/* routes.
    # New clients should use /api/v1/; existing /api/* routes remain unchanged
    # for backward compatibility with current frontend and external integrations.
    #
    # Implementation: we mount a sub-application that strips the /api/v1 prefix
    # and re-dispatches to the main app, so every /api/v1/<path> automatically
    # resolves to the equivalent /api/<path> handler without duplicating routes.
    try:
        from fastapi import APIRouter
        from fastapi.routing import APIRoute

        _v1_router = APIRouter(prefix="/api/v1")

        # Collect all existing /api/* routes and re-register them under /v1.
        # We create lightweight forwarding entries rather than copying handlers,
        # keeping the route list in sync automatically via this loop.
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/api/"):
                _v1_path = "/api/v1" + route.path[len("/api") :]
                # Skip if already a v1 path (prevent infinite loop)
                if "/v1/" in route.path:
                    continue
                app.add_api_route(
                    _v1_path,
                    route.endpoint,
                    methods=list(route.methods) if route.methods else ["GET"],
                    response_model=route.response_model,
                    tags=list(route.tags) if route.tags else [],
                    summary=route.summary,
                    description=route.description,
                    include_in_schema=False,  # hide from OpenAPI to avoid duplicate docs
                )

        logger.info(
            "API v1 versioned routes registered (/api/v1/* aliases for /api/* — %d routes)",
            sum(1 for r in app.routes if isinstance(r, APIRoute) and "/api/v1/" in r.path),
        )
    except Exception as _v1_err:
        logger.warning("API v1 versioned routes not registered: %s", _v1_err)
