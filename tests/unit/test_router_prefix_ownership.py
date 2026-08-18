# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_router_prefix_ownership.py
===========================================
Regression tests for findings S-20 and S-21.

**S-21 — two routers owned /api/alerts, and the safe one was not always the
winner.** ``PRICE_ALERTS`` mounts ``api/alerts.py``; ``PUSH_NOTIFICATIONS``
mounted ``notifications.alert_engine.router``, which declares the *same*
``/api/alerts`` prefix. ``_include_router_deduped`` silently skips paths that
are already registered, so the outcome depended on registration order.

Built under each flag combination, the result was:

    both on            8 of 9 paths from api.alerts, but
                       GET /api/alerts/stats from notifications.alert_engine
    PRICE_ALERTS off   all 9 paths from notifications.alert_engine
    both off           none

That middle row is the defect. ``FEATURE_PRICE_ALERTS=false`` is the documented
way to switch price alerts off; instead of disabling them it swapped in an
implementation with **no ownership checks at all** —
``GET``/``DELETE``/``pause``/``resume`` act on any alert id, ``GET /`` lists
every user's alerts with no user filter, and ``POST /`` stores alerts with no
``user_id``. It also skips the ``require_plan("starter")`` gate. ``api/alerts.py``
does all of this correctly through ``_get_owned_alert``, which returns 404
rather than 403 so it does not leak which ids exist.

Nothing was lost by removing the duplicate mount: ``api/notifications.py``
(``/api/notifications``) is mounted unconditionally with the core routers — the
collision between the two ``notifications_router`` imports is the likely origin
— and no client calls ``/api/alerts/stats``.

**S-20 — the flag docstring contradicted the flag definitions.** It said
"EXPERIMENTAL … off by default" while 7 of the 11 experimental flags default to
True, GRAPHQL_API among them.
"""

from __future__ import annotations

import ast
import collections
import importlib
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "core" / "router_registry.py"


def _build_app(**flag_env: str):
    """Register every router on a bare app under the given flag environment."""
    from fastapi import FastAPI

    from config import feature_flags

    previous = {k: os.environ.get(k) for k in flag_env}
    os.environ.update(flag_env)
    try:
        flags = importlib.reload(feature_flags).flags
        app = FastAPI()
        from core.router_registry import register_routers

        register_routers(app, flags)
        return app
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(feature_flags)


def _alert_routes(app) -> dict[str, set[str]]:
    """{path: {serving module}} for the /api/alerts surface."""
    from core.router_registry import iter_api_routes

    found: dict[str, set[str]] = collections.defaultdict(set)
    for route in iter_api_routes(app.routes):
        if "/v1/" in route.path or not route.path.startswith("/api/alerts"):
            continue
        found[route.path].add(getattr(route.endpoint, "__module__", "?"))
    return dict(found)


@pytest.mark.unit
class TestAlertsHaveExactlyOneOwner:
    def test_with_default_flags_only_api_alerts_serves_them(self):
        modules = {m for mods in _alert_routes(_build_app()).values() for m in mods}

        assert modules == {"api.alerts"}, (
            f"/api/alerts is served by {sorted(modules)}. Exactly one module "
            "must own the prefix — a blend means which implementation answers "
            "depends on registration order (S-21)."
        )

    def test_turning_the_flag_off_disables_the_feature(self):
        routes = _alert_routes(_build_app(FEATURE_PRICE_ALERTS="false"))

        assert not routes, (
            f"FEATURE_PRICE_ALERTS=false left {sorted(routes)} mounted. Turning "
            "the flag off must disable price alerts, not hand them to a second "
            "implementation with no ownership checks (S-21)."
        )

    def test_push_notifications_does_not_resurrect_them(self):
        routes = _alert_routes(_build_app(FEATURE_PRICE_ALERTS="false", FEATURE_PUSH_NOTIFICATIONS="true"))

        assert not routes, (
            "PUSH_NOTIFICATIONS is for iOS/Android delivery; it must not mount an alerts CRUD router (S-21)."
        )

    def test_the_unscoped_router_is_no_longer_registered_anywhere(self):
        source = _REGISTRY.read_text(encoding="utf-8")
        live = [
            line
            for line in source.splitlines()
            if "notifications.alert_engine import router" in line and not line.lstrip().startswith("#")
        ]
        assert not live, (
            f"core/router_registry.py imports the alert_engine router again: {live}. It has no per-user scoping (S-21)."
        )


@pytest.mark.unit
class TestTheUnscopedRouterReallyLacksOwnershipChecks:
    """Pins *why* the mount was removed, so it is not restored as harmless."""

    _MODULE = _REPO_ROOT / "notifications" / "alert_engine.py"

    def test_its_handlers_never_consult_a_user(self):
        tree = ast.parse(self._MODULE.read_text(encoding="utf-8"))

        handlers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router"
                for d in node.decorator_list
            )
        ]
        assert handlers, "no @router handlers found — has the module been restructured?"

        scoped = [h.name for h in handlers if "user" in ast.unparse(h).lower()]
        assert not scoped, (
            f"{scoped} now reference a user — if this router has grown proper "
            "scoping, revisit whether it should own /api/alerts (S-21)."
        )

    def test_api_alerts_by_contrast_checks_ownership(self):
        source = (_REPO_ROOT / "api" / "alerts.py").read_text(encoding="utf-8")
        assert "_get_owned_alert" in source
        assert "user_id=user.sub" in source, "list/create must be scoped to the caller"


@pytest.mark.unit
class TestFlagStatusIsALabelNotADefault:
    """S-20: the docstring claimed experimental flags were off by default."""

    def test_the_docstring_no_longer_claims_experimental_means_off(self):
        source = (_REPO_ROOT / "config" / "feature_flags.py").read_text(encoding="utf-8")
        docstring = ast.get_docstring(ast.parse(source)) or ""

        # Line-anchored on purpose. The rewritten docstring quotes the old
        # wording while explaining that it was wrong, so a loose search over the
        # whole string matches the explanation rather than the claim — the same
        # docstring trap that has caught assertions in this suite before.
        claims = [
            line
            for line in docstring.splitlines()
            if line.strip().startswith("EXPERIMENTAL") and "off by default" in line
        ]
        assert not claims, (
            f"the status table still says experimental features are off by "
            f"default ({claims}); 7 of the 11 are on (S-20)."
        )

    def test_the_experimental_flags_that_are_on_are_named(self):
        """So the next reader sees the real state, not a rule that is not kept."""
        from config.feature_flags import flags

        registry = flags.registry()
        on = sorted(n for n, i in registry.items() if i["status"] == "experimental" and i["default"])
        assert on, "no experimental flag defaults to True any more — update the docstring"

        source = (_REPO_ROOT / "config" / "feature_flags.py").read_text(encoding="utf-8")
        docstring = ast.get_docstring(ast.parse(source)) or ""
        missing = [name for name in on if name not in docstring]
        assert not missing, f"{missing} default to True but the docstring does not name them (S-20)."

    def test_live_trading_is_still_off_by_default(self):
        """The deliberate stable-but-off case, which the same text must allow."""
        from config.feature_flags import flags

        live = flags.registry()["LIVE_TRADING"]
        assert live["status"] == "stable"
        assert live["default"] is False, (
            "LIVE_TRADING must stay off by default — it is the flag that lets real orders reach a broker."
        )
