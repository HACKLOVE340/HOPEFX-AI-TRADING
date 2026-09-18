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

from fastapi import APIRouter, FastAPI

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
    # A bare MagicMock can no longer stand in for a router here: FastAPI's
    # include_router() validates its argument and rejects anything that
    # isn't a real APIRouter, so a real (empty) one is used instead.
    app = _make_app()
    flags = _make_flags()
    fake_graphql = APIRouter()
    register_routers(
        app,
        flags,
        graphql_router=fake_graphql,
        graphql_available=True,
    )
    assert len(app.routes) > 0


def test_register_routers_with_signals_router():
    app = _make_app()
    flags = _make_flags()
    fake_signals = APIRouter()
    register_routers(
        app,
        flags,
        signals_router=fake_signals,
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


# ── An optional router that cannot import must not take the app down ──────────
#
# `register_routers` wraps roughly sixty optional routers in
# `try: import … except Exception: logger.warning(…)`. Every one of those
# `except` branches was unmeasured — they are 25% of this module — and they are
# the branches that decide what happens when part of the API cannot load.
#
# That matters here for the reason S6-01 records: a router that disappears
# quietly is indistinguishable from one that was never meant to exist. The app
# comes up, the endpoint 404s, and nothing says why. So the property under test
# is not only "does not crash" — it is **the failure is logged, by name**.
#
# The module was also excluded from coverage entirely by `.coveragerc`, with the
# justification "requires full app context; covered by integration/e2e tests".
# These nine unit tests already existed when that was written.


class _FailingImporter:
    """Make selected top-level packages unimportable, and nothing else.

    Scoped rather than blanket: failing *every* import would take out pydantic,
    FastAPI and the standard library, and the resulting run would prove that a
    broken interpreter raises rather than that this module degrades.
    """

    def __init__(self, prefixes: tuple[str, ...]) -> None:
        self._prefixes = prefixes
        self._real = __import__

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):
        # `level == 0` only: a relative import carries the bare submodule name,
        # so `from .security import router` inside `api/superadmin/__init__.py`
        # arrives here as name="security", level=1. Matching it broke an
        # unrelated package and the ImportError escaped `register_routers`
        # entirely — the test failed for a reason that had nothing to do with
        # the branch under test.
        if level == 0 and any(name == p or name.startswith(p + ".") for p in self._prefixes):
            raise ImportError(f"simulated: {name} is unavailable")
        return self._real(name, globals, locals, fromlist, level)


def _register_with_broken_imports(prefixes, caplog):
    import builtins
    import logging
    import sys

    from unittest.mock import patch

    app = _make_app()
    flags = _make_flags()

    # Drop anything already imported under those prefixes, or the cached module
    # is handed back without `__import__` ever being consulted and the test
    # passes while proving nothing. Snapshot first: leaving these out of
    # sys.modules would hand every later test in the session a second, distinct
    # copy of each package, and the resulting failures would look like anything
    # except this test.
    evicted = {
        name: mod for name, mod in sys.modules.items() if any(name == p or name.startswith(p + ".") for p in prefixes)
    }
    for name in evicted:
        del sys.modules[name]

    try:
        with caplog.at_level(logging.WARNING, logger="core.router_registry"):
            with patch.object(builtins, "__import__", _FailingImporter(prefixes)):
                register_routers(app, flags)
    finally:
        for name in [n for n in sys.modules if any(n == p or n.startswith(p + ".") for p in prefixes)]:
            del sys.modules[name]
        sys.modules.update(evicted)

    return app, [r.getMessage() for r in caplog.records]


#: Optional-router packages that can be made to fail without taking out a
#: mandatory import. `api` is deliberately absent: the core routers at the top
#: of `register_routers` are not wrapped, so failing that package raises rather
#: than degrading, which is the correct behaviour and a different test.
_OPTIONAL_PACKAGES = (
    "security",
    "social",
    "monetization",
    "analysis",
    "explainability",
    "news",
    "nocode",
    "portfolio",
    "replay",
    "research",
    "teams",
    "transparency",
    "mobile",
    "data.streaming",
    "data.depth_of_market",
    "data.time_and_sales",
    # Named individually rather than as the whole `api` package: the core
    # routers at the top of `register_routers` are not wrapped in try/except,
    # so failing all of `api` raises instead of degrading. These are the
    # optional ones.
    "api.custom_indicators",
    "api.tca",
    "api.pnl_dashboard",
    "api.risk_calculator",
    "api.kyc",
    "api.chaos",
    "api.data_layer",
    "api.security_dashboard",
    "api.ws_public",
    "api.ws_live",
    "api.dynamic_strategies",
    "api.advanced_orders",
    "api.ml_ops",
    "api.transparency",
    "api.news_feed",
    "api.observability",
    "api.copy_trading",
    "api.nocode",
)


def test_a_router_that_cannot_import_is_logged_not_swallowed(caplog):
    """The app still boots, and says which routers it lost."""
    app, warnings = _register_with_broken_imports(("security",), caplog)

    assert any("not registered" in w for w in warnings), (
        "a router failed to import and nothing said so — an endpoint that 404s "
        "for an unexplained reason is the worst version of this failure"
    )
    assert len(app.routes) > 0, "one failed optional router took the whole app down"


def test_the_whole_optional_surface_can_fail_and_the_app_still_serves(caplog):
    """Twelve packages unimportable at once. The core API is still mounted."""
    app, warnings = _register_with_broken_imports(_OPTIONAL_PACKAGES, caplog)

    assert len(app.routes) > 0, "the app served nothing once the optional routers failed"
    assert len(warnings) >= 10, f"only {len(warnings)} routers reported a failure"


def test_the_warning_names_the_router_and_the_reason(caplog):
    """ "Something failed" is not actionable at 3am."""
    _app, warnings = _register_with_broken_imports(("security",), caplog)

    assert any("simulated" in w for w in warnings), "the log records that a router failed but not why"
