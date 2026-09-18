# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Every route the SPA declares must answer with the SPA, not with JSON.

F199, and the class F198 belongs to.

`core/page_routes.py` registers a hand-maintained `_SPA_ROUTES` list — 60 paths
— ahead of a `/{full_path:path}` catch-all, and `frontend/src/App.tsx` declares
88. The gap sounds like the defect and is not: an unlisted path still reaches
the catch-all and still gets `index.html`. The list is an optimisation.

The defect is what F198 actually was. `api/kyc.py` mounts a router at the bare
prefix `/kyc`, which claims that path **before** the catch-all ever sees it, so
a user following a verification email got:

    {"detail":"No route for GET /kyc"}

on a regulatory gate. Nothing about the route list would have caught that, and
syncing 60 to 88 would not catch the next one either — any router mounted at a
bare prefix that collides with a page shadows it silently, and in-app
navigation keeps working because React Router never asks the server.

So this file tests the property rather than the list: **for every path
`App.tsx` declares, a direct GET returns HTML.** That is the thing a user does
when they follow a link from an email, and it is the thing no other test does.

The route table is read out of `App.tsx` rather than duplicated here. A test
that hard-codes the paths it checks goes stale exactly like the list it is
meant to be protecting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
APP_TSX = ROOT / "frontend" / "src" / "App.tsx"

#: Paths React Router owns but a direct GET is not expected to serve as a page.
#: Keep this empty unless there is a reason a user could never arrive here from
#: outside the app — every entry is a route somebody's bookmark or email link
#: will eventually hit.
_NOT_DIRECTLY_REACHABLE: frozenset[str] = frozenset(
    {
        # A genuine collision, not an oversight, and it needs an owner decision.
        # `App.tsx` declares a `/mobile` page AND `core/router_registry.py`
        # mounts the mobile API sub-application at `/mobile` — measured: one
        # exact route, one Mount. Unlike `/kyc`, which nothing claimed, this
        # path really is a server-side handler, so serving the SPA there would
        # shadow a live API. Resolving it means renaming the page or moving the
        # mount to `/api/mobile`; both are product choices. Tracked as F198.
        "/mobile",
    }
)


def _declared_routes() -> list[str]:
    """Concrete paths declared in App.tsx, minus parameterised and wildcard ones.

    `:param` and `*` routes cannot be fetched without inventing a value, and a
    made-up id would exercise the API's 404 rather than the SPA's shell.
    """
    text = APP_TSX.read_text(encoding="utf-8")
    paths = {m.group(1) for m in re.finditer(r'path="(/[^"]*)"', text)}
    return sorted(p for p in paths if ":" not in p and "*" not in p and p not in _NOT_DIRECTLY_REACHABLE)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The page routes plus every API router, which is where shadowing happens.

    Registering only the page routes would pass unconditionally: nothing would
    be mounted that could claim a path ahead of them, and the whole point is
    that something is.
    """
    if not (ROOT / "static" / "index.html").is_file():
        pytest.skip("frontend build (static/) absent")

    from config.feature_flags import flags as feature_flags
    from core.page_routes import register_page_routes
    from core.router_registry import register_routers

    app = FastAPI()
    # API routers first, exactly as production does — the ordering is the whole
    # subject. Feature flags come from the real resolver so a router disabled in
    # this configuration is absent here too, rather than being conjured by a
    # stub and shadowing a page that production would have served.
    register_routers(app, feature_flags)
    register_page_routes(app)
    return TestClient(app)


def test_app_tsx_declares_the_routes_this_file_checks():
    """Guard the harness before trusting what it reports.

    If the regex stops matching — a refactor to a route array, say — every test
    below passes vacuously over an empty list.
    """
    routes = _declared_routes()
    assert len(routes) >= 50, (
        f"only {len(routes)} routes parsed out of App.tsx — the extraction has probably "
        "broken, and the checks below would be passing over nothing"
    )
    assert "/dashboard" in routes


def test_every_declared_route_serves_the_spa_on_a_direct_get(client: TestClient):
    """The user typed the URL, or followed a link from an email.

    In-app navigation never asks the server, which is why this class of defect
    survives manual testing.
    """
    json_instead: dict[str, str] = {}
    for path in _declared_routes():
        r = client.get(path)
        content_type = r.headers.get("content-type", "")
        if "text/html" not in content_type:
            json_instead[path] = f"{r.status_code} {content_type} {r.text[:80]}"

    assert not json_instead, (
        "these declared SPA routes do not serve the app on a direct GET — an API "
        f"router is claiming the path ahead of the page: {json_instead}"
    )


def test_a_declared_route_is_not_answered_with_a_404(client: TestClient):
    """Stated separately from the content type so the failure names the cause.

    A 404 means the path was claimed and refused. A 200 of the wrong type means
    it was claimed and answered. They need different fixes.
    """
    refused = [p for p in _declared_routes() if client.get(p).status_code == 404]

    assert not refused, f"declared SPA routes answering 404 on a direct GET: {refused}"


def test_an_undeclared_path_still_reaches_the_spa(client: TestClient):
    """The catch-all is why the hand-maintained list is an optimisation.

    Without this, the tests above could be satisfied by adding all 88 paths to
    `_SPA_ROUTES` — restoring the hand-maintenance this finding is about.
    """
    r = client.get("/some-route-nobody-has-added-to-the-list")

    assert "text/html" in r.headers.get("content-type", ""), (
        "an unlisted SPA path did not reach the catch-all, so the route list is load-bearing and will go stale again"
    )


def test_the_api_is_not_shadowed_by_the_spa_catchall(client: TestClient):
    """The converse, and the reason the catch-all must stay last.

    A page route or catch-all that swallowed /api/* would serve HTML to every
    API client — the same defect pointed the other way.
    """
    r = client.get("/api/health")

    assert "text/html" not in r.headers.get("content-type", ""), "an /api/ path was answered with the SPA shell"


def test_the_mobile_collision_is_still_a_collision(client: TestClient):
    """Pin the exemption above so it cannot quietly become permanent.

    If `/mobile` starts serving the SPA — because the mount moved, or the page
    was renamed — this fails and says to delete the exemption. An exclusion list
    nobody revisits is how a known defect becomes invisible.
    """
    r = client.get("/mobile")

    assert "text/html" not in r.headers.get("content-type", ""), (
        "/mobile now serves the SPA — the collision is resolved, so remove it from "
        "_NOT_DIRECTLY_REACHABLE and close that half of F198"
    )
