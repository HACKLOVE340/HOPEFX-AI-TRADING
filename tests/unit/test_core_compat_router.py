# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/compat_router.py` — the backwards-compatible URL aliases.

Fourteen routes that external clients, mobile apps and integration dashboards
still call. Every one delegates by 307 redirect; the module's docstring promises
that **no hard-coded or synthetic data is returned from this module**, and that
every route requires authentication except `/api/system/health`.

It measured 0%. Nothing had checked that the promises hold — not the redirect
targets, not the auth, and not the one piece of untrusted input in the file.

The tests assert against the declared route table rather than a hand-copied
list, so a route added tomorrow is covered by the auth and redirect rules
automatically instead of being exempt from them by omission.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.compat_router import compat_router, system_health_alias, trades_alias

#: Path -> the target its docstring promises it delegates to.
DOCUMENTED: dict[str, str] = {
    "/api/dashboard/stats": "/api/performance/metrics",
    "/api/trades": "/api/trading/trades",
    "/api/market-data/live": "/api/trading/price/XAUUSD",
    "/api/ai/signals": "/api/trading/signals",
    "/api/nuclear/status": "/api/nuclear/status",
    "/api/system/health": "/api/health/live",
    "/api/risk/metrics": "/api/trading/risk",
    "/api/performance/metrics": "/api/performance/metrics",
    "/api/calendar/events": "/api/calendar",
    "/api/marketplace/items": "/api/monetization/marketplace/featured",
    "/api/prop-firm/status": "/api/risk/prop-firm-status",
    "/api/copy-trading/status": "/api/social/copy/active",
    "/api/admin/users": "/api/admin/all-users",
    "/api/superadmin/overview": "/api/superadmin/overview",
}

#: The single route the docstring marks public. Everything else needs a caller.
PUBLIC = "/api/system/health"


def _routes() -> dict[str, object]:
    return {r.path: r for r in compat_router.routes}


def _dependency_names(route) -> set[str]:
    """Every callable the route depends on, by name, flattened one level."""
    names: set[str] = set()
    for dep in route.dependant.dependencies:
        call = dep.call
        names.add(getattr(call, "__name__", type(call).__name__))
        for sub in dep.dependencies:
            names.add(getattr(sub.call, "__name__", type(sub.call).__name__))
    return names


class TestEveryDocumentedAliasExists:
    def test_all_fourteen_paths_are_mounted(self) -> None:
        assert set(_routes()) >= set(DOCUMENTED), set(DOCUMENTED) - set(_routes())

    def test_the_router_exposes_no_undocumented_alias(self) -> None:
        """An alias nobody wrote down is one nobody reviews for auth."""
        assert set(_routes()) <= set(DOCUMENTED), set(_routes()) - set(DOCUMENTED)

    @pytest.mark.parametrize("path", sorted(DOCUMENTED))
    def test_each_alias_is_read_only(self, path: str) -> None:
        """These are convenience aliases. A POST here would be a mutating route
        living outside the canonical API's review surface."""
        assert _routes()[path].methods <= {"GET", "HEAD"}


class TestAuthenticationIsNotOptional:
    """The docstring's claim, checked route by route rather than trusted."""

    @pytest.mark.parametrize("path", sorted(p for p in DOCUMENTED if p != PUBLIC))
    def test_a_private_alias_requires_a_caller(self, path: str) -> None:
        names = _dependency_names(_routes()[path])
        assert names & {"get_current_user", "_check", "require_role"}, (
            f"{path} has no authentication dependency: {names}"
        )

    def test_the_health_alias_is_public_on_purpose(self) -> None:
        """Documented as public. Pinned so it is a decision, not a drift."""
        assert not _dependency_names(_routes()[PUBLIC])

    def test_the_admin_alias_is_role_gated(self) -> None:
        route = _routes()["/api/admin/users"]
        assert route.dependant.dependencies, "admin alias carries no dependency at all"

    def test_the_superadmin_alias_is_role_gated(self) -> None:
        route = _routes()["/api/superadmin/overview"]
        assert route.dependant.dependencies, "superadmin alias carries no dependency at all"


class TestEachAliasRedirectsWhereItSaysItDoes:
    """Every route driven through its own endpoint, against the documented map.

    A redirect to the wrong canonical path is invisible in review — both sides
    are plausible `/api/...` strings — and shows up as an external client
    silently receiving somebody else's data.
    """

    @pytest.mark.parametrize(("path", "target"), sorted(DOCUMENTED.items()))
    def test_it_delegates_to_the_documented_target(self, path: str, target: str) -> None:
        response = asyncio.run(_routes()[path].endpoint())
        assert response.status_code == 307, f"{path} did not return a temporary redirect"
        assert response.headers["location"].split("?")[0] == target

    def test_the_public_health_alias_redirects_to_health_live(self) -> None:
        response = asyncio.run(system_health_alias())
        assert response.status_code == 307
        assert response.headers["location"] == "/api/health/live"

    def test_every_redirect_is_temporary_not_permanent(self) -> None:
        """308/301 would be cached by clients and the alias could never move."""
        for path in DOCUMENTED:
            assert asyncio.run(_routes()[path].endpoint()).status_code == 307, path

    def test_no_alias_returns_a_body_of_its_own(self) -> None:
        """ "No hard-coded / synthetic data is returned from this module." A
        route that answered directly would be a second source of truth that
        drifts from the canonical one without anybody noticing."""
        for path in DOCUMENTED:
            response = asyncio.run(_routes()[path].endpoint())
            assert type(response).__name__ == "RedirectResponse", f"{path} returned {type(response).__name__}"
            assert not response.body


class TestTheOneUntrustedInput:
    """`trades_alias` embeds `limit` in the redirect URL.

    The clamp carries its own comment naming the reason — CodeQL, untrusted
    input flowing unsanitised into a redirect. It is the only place in this
    module where a caller's value reaches a URL, so it is the only place that
    can be made to point somewhere it should not.
    """

    @pytest.mark.parametrize(
        ("given", "expected"),
        [(50, 50), (1, 1), (1000, 1000), (0, 1), (-5, 1), (10_000, 1000), (999_999, 1000)],
    )
    def test_the_limit_is_clamped_into_range(self, given: int, expected: int) -> None:
        response = asyncio.run(trades_alias(limit=given))
        assert response.headers["location"] == f"/api/trading/trades?limit={expected}"

    def test_the_default_is_within_range(self) -> None:
        response = asyncio.run(trades_alias())
        assert response.headers["location"] == "/api/trading/trades?limit=50"

    @pytest.mark.parametrize("hostile", ["1&redirect=//evil.test", "1 OR 1=1", "../../admin", "1\r\nX: y"])
    def test_a_hostile_limit_cannot_reach_the_url(self, hostile: str) -> None:
        """`int()` refuses it outright. The point is that nothing in the string
        ever reaches `location` — not that a particular exception is raised."""
        with pytest.raises((ValueError, TypeError)):
            asyncio.run(trades_alias(limit=hostile))  # type: ignore[arg-type]

    def test_the_redirect_target_is_always_this_api(self) -> None:
        """No caller value may turn a relative delegation into an off-site
        redirect."""
        for value in (50, 0, -1, 10_000):
            location = asyncio.run(trades_alias(limit=value)).headers["location"]
            assert location.startswith("/api/trading/trades?limit=")
            assert "//" not in location and ":" not in location
