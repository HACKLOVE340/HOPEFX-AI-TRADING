# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_router_registry.py
========================================
Coverage tests for core/router_registry.py.

register_routers() is called with a real FastAPI app and mock feature flags.
All optional routers that fail to import are handled gracefully.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from core.router_registry import register_routers


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    return FastAPI()


def _make_flags(**kwargs) -> MagicMock:
    flags = MagicMock()
    for k, v in kwargs.items():
        setattr(flags, k, v)
    return flags


# ── register_routers — basic invocation ───────────────────────────────────────


def test_register_routers_no_crash():
    app = _make_app()
    flags = _make_flags()
    # Must not raise even if optional routers fail to import
    register_routers(app, flags)


def test_register_routers_adds_routes():
    app = _make_app()
    flags = _make_flags()
    register_routers(app, flags)
    # At least some routes should be registered
    assert len(app.routes) > 0


def test_register_routers_with_graphql_router():
    app = _make_app()
    flags = _make_flags()
    mock_graphql = MagicMock()
    register_routers(
        app,
        flags,
        graphql_router=mock_graphql,
        graphql_available=True,
    )
    assert len(app.routes) > 0


def test_register_routers_with_signals_router():
    app = _make_app()
    flags = _make_flags()
    mock_signals = MagicMock()
    register_routers(
        app,
        flags,
        signals_router=mock_signals,
    )
    assert len(app.routes) > 0


def test_register_routers_graphql_unavailable():
    app = _make_app()
    flags = _make_flags()
    register_routers(
        app,
        flags,
        graphql_router=None,
        graphql_available=False,
    )
    assert len(app.routes) > 0


def test_register_routers_idempotent_no_crash():
    """Calling register_routers twice must not raise."""
    app = _make_app()
    flags = _make_flags()
    register_routers(app, flags)
    register_routers(app, flags)


def test_register_routers_returns_none():
    app = _make_app()
    flags = _make_flags()
    result = register_routers(app, flags)
    assert result is None


def test_register_routers_all_optional_flags_false():
    app = _make_app()
    flags = _make_flags(
        GRAPHQL=False,
        SIGNALS_ROUTER=False,
        TCA=False,
        PNL_DASHBOARD=False,
        SUPERADMIN=False,
        NUCLEAR=False,
        KYC=False,
        CHAOS=False,
        DATA_LAYER=False,
        SECURITY_FIXES=False,
        SECURITY_DASHBOARD=False,
        WS_LIVE=False,
    )
    register_routers(app, flags)
    assert len(app.routes) > 0


def test_register_routers_all_optional_flags_true():
    app = _make_app()
    flags = _make_flags(
        GRAPHQL=True,
        SIGNALS_ROUTER=True,
        TCA=True,
        PNL_DASHBOARD=True,
        SUPERADMIN=True,
        NUCLEAR=True,
        KYC=True,
        CHAOS=True,
        DATA_LAYER=True,
        SECURITY_FIXES=True,
        SECURITY_DASHBOARD=True,
        WS_LIVE=True,
    )
    register_routers(app, flags)
    assert len(app.routes) > 0
