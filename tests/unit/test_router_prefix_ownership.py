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


# ── S-32: two routers owned /api/indicators, and /api/security/fixes ─────────


def _by_normalised_path(app) -> dict[str, set[str]]:
    """{path with params collapsed: {serving module}} for the whole app.

    Params are collapsed so `/{ind_id}` and `/{indicator_id}` — the same URL,
    named differently by two routers — compare equal. A trailing slash is
    stripped for the same reason: Starlette treats `/x` and `/x/` as distinct
    routes when both are registered, so a one-character difference is enough
    to publish two subsystems on what a caller reads as one endpoint.
    """
    import re

    from core.router_registry import iter_api_routes

    found: dict[str, set[str]] = collections.defaultdict(set)
    for route in iter_api_routes(app.routes):
        if route.path.startswith("/api/v1/"):  # documented alias layer
            continue
        key = re.sub(r"\{[^}]*\}", "{}", route.path.rstrip("/")) or "/"
        found[key].add(getattr(route.endpoint, "__module__", "?"))
    return dict(found)


@pytest.mark.unit
class TestNoPathIsServedByTwoModules:
    """The general form of S-21, S-32 and the `/api/security/fixes` overlap.

    Sharing a *prefix* is normal and expected here — `/api/superadmin` alone is
    served by 27 modules, and `/api/settings` by three. What is never right is
    two modules answering the **same path**, because then which one runs is
    decided by registration order rather than by anyone's intent.
    """

    def test_every_path_has_exactly_one_owner(self):
        collisions = {
            path: sorted(modules) for path, modules in _by_normalised_path(_build_app()).items() if len(modules) > 1
        }

        assert not collisions, (
            "these paths are served by more than one module, so which handler "
            f"answers depends on registration order: {collisions}. Four existed "
            "before S-32 — three on /api/indicators (api.advanced_trading vs "
            "api.custom_indicators) and one on /api/security/fixes."
        )


@pytest.mark.unit
class TestTheIndicatorApisAreSeparate:
    """S-32: `/api/indicators` and `/api/custom-indicators` are two products.

    `api/advanced_trading.py` serves formula-based chart overlays
    (`{"formula": "close - close", "color": ...}`) from `advanced:indicator:*`.
    `api/custom_indicators.py` serves parameterised built-ins
    (`{"type": "ema", "params": {"period": 20}}`) from its own store. Both were
    mounted on `/api/indicators`, advanced_trading first, so:

      * `DELETE`, `PATCH` and `/{id}/apply` from custom_indicators were
        shadowed outright;
      * `GET /{id}`, `PUT`, `/{id}/test` and `/{id}/deploy` — which
        advanced_trading does not define — stayed reachable but answered 404
        for every indicator the app actually creates, because they read the
        other store;
      * `GET /api/indicators` and `GET /api/indicators/` returned different
        users' data from different subsystems.

    Merging them would have meant picking one schema and orphaning the other's
    data. Splitting the prefix fixes both halves.
    """

    @staticmethod
    def _owners(app, prefix: str) -> set[str]:
        from core.router_registry import iter_api_routes

        return {
            getattr(route.endpoint, "__module__", "?")
            for route in iter_api_routes(app.routes)
            if route.path == prefix or route.path.startswith(prefix + "/")
        }

    def test_api_indicators_belongs_to_advanced_trading(self):
        """It is what frontend/src/hooks/useApi.ts calls, so it must not move."""
        assert self._owners(_build_app(), "/api/indicators") == {"api.advanced_trading"}

    def test_custom_indicators_has_its_own_prefix(self):
        assert self._owners(_build_app(), "/api/custom-indicators") == {"api.custom_indicators"}

    def test_the_full_custom_indicator_surface_is_reachable(self):
        """The four endpoints that used to 404 on real data included."""
        from core.router_registry import iter_api_routes

        paths = {
            route.path
            for route in iter_api_routes(_build_app().routes)
            if route.path.startswith("/api/custom-indicators")
        }

        for suffix in ("", "/builtin", "/calculate", "/preview", "/{indicator_id}", "/{indicator_id}/test"):
            assert f"/api/custom-indicators{suffix}" in paths, f"{suffix or '(root)'} is missing"


@pytest.mark.unit
class TestSecurityFixesHaveOneOwner:
    """S-32: the same collision, on the endpoint that approves code changes.

    `security/global_fortress.py` and `api/security/fixes.py` both declared
    `/api/security/fixes`, `/fixes/approve` and `/fixes/decline`, and the
    global_fortress copies won on registration order. Both carry
    `require_role("admin")`, so this was never an auth hole — but the winner
    was worse in three ways: the listing took no `limit` and 500'd on a single
    malformed queue record, decline accepted an untyped dict with no reason
    field, and **approve answered 503 "Security brain not started"** unless the
    brain was running, while the shadowed implementation publishes the GitHub
    PR without it.

    Fixed by registering the dedicated router first.
    """

    def test_all_of_them_come_from_the_dedicated_module(self):
        from core.router_registry import iter_api_routes

        owners = {
            route.path: getattr(route.endpoint, "__module__", "?")
            for route in iter_api_routes(_build_app().routes)
            if route.path.startswith("/api/security/fixes")
        }

        assert owners, "no /api/security/fixes routes found — the check is not checking anything"
        assert set(owners.values()) == {"api.security.fixes"}, (
            f"a global_fortress copy is winning again: {owners}. Approving a fix "
            "then needs the security brain running or answers 503 (S-32)."
        )

    def test_approving_a_fix_does_not_depend_on_the_brain(self):
        """The behavioural difference, asserted on the handler that is mounted."""
        import inspect

        from core.router_registry import iter_api_routes

        approve = next(
            route
            for route in iter_api_routes(_build_app().routes)
            if route.path == "/api/security/fixes/approve" and "POST" in route.methods
        )
        source = inspect.getsource(approve.endpoint)

        assert "Security brain not started" not in source
        assert "get_pr_publisher" in source, "the mounted approve handler no longer publishes the PR"


@pytest.mark.unit
class TestARouteAtTheBarePrefixKeepsItsPath:
    """S-32's mechanism: `@router.get("")` was remounted one character off.

    `_include_router_deduped` rebuilds a router when it has to drop a duplicate
    route. `_relative_path` returned `"/"` for a route sitting exactly at the
    router's prefix, so the rebuild re-added it at `/api/indicators/` — a
    second, distinct path answered by a different subsystem than
    `/api/indicators`. Starlette only redirects a trailing slash when no exact
    match exists, so nothing collapsed them.
    """

    def test_the_helper_returns_an_empty_relative_path(self):
        import core.router_registry as registry
        from fastapi import APIRouter, FastAPI

        source = APIRouter(prefix="/api/thing")

        @source.get("")
        async def _root():
            return {}

        @source.get("/leaf")
        async def _leaf():
            return {}

        app = FastAPI()
        # Pre-claim /leaf so the dedup rebuild path is exercised, which is the
        # only path on which the bug appeared.
        registry._registered_routes.clear()
        registry._registered_routes.add(("GET", "/api/thing/leaf"))
        registry._include_router_deduped(app, source)

        paths = {route.path for route in registry.iter_api_routes(app.routes)}
        registry._registered_routes.clear()

        assert "/api/thing" in paths, f"the bare-prefix route moved: {paths}"
        assert "/api/thing/" not in paths


# ── S-34: a literal path declared after a parameterised one never runs ───────


@pytest.mark.unit
class TestNoLiteralPathIsShadowedByAParameterisedOne:
    """Starlette matches in registration order, first match wins.

    So `@router.get("/stats")` declared *after* `@router.get("/{symbol}")`
    never runs — the request is handed to the parameterised handler with
    `symbol="stats"`. Three endpoints were dead this way (S-34), confirmed by
    calling them on the fully registered app:

        GET  /api/dom/stats                    404 "No order book for stats"
        POST /api/superadmin/users/bulk/ban    404 "User not found"   (user_id="bulk")
        POST /api/superadmin/users/bulk/unban  404 "User not found"

    `/users/bulk/export` was fine only because no `/users/{user_id}/export`
    exists — which is the point: this is a property of declaration order, not
    something a reader can see from one route.
    """

    @staticmethod
    def _pattern(path: str):
        import re

        out = ""
        for part in re.split(r"(\{[^}]*\})", path):
            if part.startswith("{") and part.endswith("}"):
                out += ".*" if ":path" in part else "[^/]+"
            else:
                out += re.escape(part)
        return re.compile("^" + out + "$")

    def test_every_literal_route_is_reachable(self):
        from core.router_registry import iter_api_routes

        routes = [r for r in iter_api_routes(_build_app().routes) if not r.path.startswith("/api/v1/")]
        compiled = [(r, self._pattern(r.path)) for r in routes]

        shadowed = []
        for index, (later, _) in enumerate(compiled):
            if "{" in later.path:
                continue
            for earlier, pattern in compiled[:index]:
                if "{" not in earlier.path:
                    continue
                overlap = earlier.methods & later.methods
                if overlap and pattern.match(later.path):
                    shadowed.append(f"{sorted(overlap)} {later.path} is swallowed by {earlier.path}")
                    break

        assert not shadowed, (
            "these routes can never be reached — a parameterised route declared "
            f"earlier matches them first: {shadowed}. Move the literal path above "
            "the parameterised one in its module (S-34)."
        )
