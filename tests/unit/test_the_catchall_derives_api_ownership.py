# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The SPA catch-all must read the route table, not a list someone maintains.

F198, the shape rather than the symptom.

`/kyc` returned `{"detail":"No route for GET /kyc"}` to a user following a
verification email. The symptom was fixed by editing one string in
`core/page_routes.py::_passthrough_prefixes` — a hand-maintained tuple of path
prefixes that the catch-all consulted to decide whether a path belongs to the
API or to the React router. A list like that is wrong in both directions the
moment anything is added on either side of it, and both were reproduced against
the pre-fix tree:

    /replay/session-123     -> 404 application/json   (a declared SPA page,
                               refused because the string "replay/" is listed
                               while nothing at all is mounted under /replay)
    /webhooks/stripe/nope   -> 200 text/html          (a live API namespace
                               nobody added to the list, so an API client is
                               answered with the SPA shell)

The second is the dangerous one on a money-moving system: a JSON client gets
HTML and a 200, so a missing endpoint reads as a parsing bug rather than a
missing endpoint.

So these tests assert the property the list was standing in for: **a path is
the server's when something is actually registered there, and the React
router's when nothing is** — measured from `app.routes` at request time, with
the routers registered in the order production registers them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _build(extra: APIRouter | None = None, *, with_api: bool = True) -> TestClient:
    """The production wiring: API routers first, page routes last.

    Registering the pages first would pass every test below for the wrong
    reason — nothing would be ahead of the catch-all to claim anything.
    """
    from config.feature_flags import flags
    from core.page_routes import register_page_routes
    from core.router_registry import register_routers

    app = FastAPI()
    if with_api:
        register_routers(app, flags)
    if extra is not None:
        app.include_router(extra)
    register_page_routes(app)
    return TestClient(app)


def _webhooks_router() -> APIRouter:
    """An API namespace invented here, so it cannot be in any list.

    This is the whole point: the next router somebody adds is not in the
    catch-all's vocabulary, and must not need to be.
    """
    router = APIRouter(prefix="/webhooks", tags=["test-only"])

    @router.get("/stripe/events")
    async def _events() -> dict[str, bool]:
        return {"ok": True}

    return router


@pytest.fixture(scope="module")
def client() -> TestClient:
    if not (ROOT / "static" / "index.html").is_file():
        pytest.skip("frontend build (static/) absent")
    return _build(_webhooks_router())


def _is_html(response) -> bool:
    return "text/html" in response.headers.get("content-type", "")


# ── The harness has to be live before anything it reports means something ────


def test_the_derivation_can_see_routes_that_live_inside_included_routers(client: TestClient):
    """Guard the measurement, not just the result.

    This FastAPI records each `include_router` as an opaque `_IncludedRouter`
    on `app.routes`, so a naive `for route in app.routes: route.path` walk sees
    almost nothing — the registry documents that trap at length, and the
    catch-all's previous `_claimed_by_a_real_route` fell into it: it could only
    ever see app-level routes and mounts, so its "does anything claim /kyc?"
    question answered "no" while six /kyc/* routes were registered.

    If a FastAPI upgrade changes those internals, this fails loudly instead of
    the catch-all quietly falling back to serving the SPA everywhere.
    """
    from core.page_routes import server_namespaces

    namespaces = server_namespaces(client.app)

    assert "/api" in namespaces, "no /api/* route was seen — the route walk is dead, and everything below is vacuous"
    assert "/kyc" in namespaces, "the /kyc/* routes live inside an included router and were not seen"
    assert "/webhooks" in namespaces, "the router this test registered was not seen"
    assert len(namespaces) > 100, f"only {len(namespaces)} namespaces derived — the walk is probably truncated"


def test_the_route_walk_agrees_with_iter_api_routes(client: TestClient):
    """The walk generalises the registry's; it must not have diverged from it.

    `core.router_registry.iter_api_routes` is this repository's tested answer
    to the same problem for APIRoutes alone. `_iter_route_paths` accumulates
    prefixes the same way and additionally yields Mounts and WebSocket routes,
    so every path the registry's walk finds must appear in this one — a
    difference means one of the two stopped descending.
    """
    from core.page_routes import _iter_route_paths, _serves_the_spa
    from core.router_registry import iter_api_routes

    derived = set(_iter_route_paths(client.app.routes))
    registry = {r.path for r in iter_api_routes(client.app.routes) if not _serves_the_spa(r)}

    assert registry, "iter_api_routes found nothing — the comparison would be vacuous"
    assert not (registry - derived), (
        f"paths the registry walk sees and this one does not: {sorted(registry - derived)[:10]}"
    )
    assert "/mobile" in derived, "the mobile Mount is not an APIRoute and must still be seen"


# ── Direction 1: a frontend route reaches the SPA ────────────────────────────


def test_a_page_sub_path_nothing_is_mounted_under_serves_the_app(client: TestClient):
    """Red on the pre-fix tree: 404 application/json.

    `/replay` is a declared SPA page. Nothing is registered under `/replay/` in
    any configuration — the string "replay/" in `_passthrough_prefixes` was the
    only thing refusing it, exactly as "kyc" was for F198.
    """
    r = client.get("/replay/session-123")

    assert _is_html(r), f"a page sub-path with nothing mounted under it was refused: {r.status_code} {r.text[:120]}"


def test_a_bare_page_path_nothing_claims_serves_the_app(client: TestClient):
    """F198's original symptom, kept pinned once the list is gone."""
    r = client.get("/kyc")

    assert _is_html(r), f"/kyc did not serve the SPA: {r.status_code} {r.text[:120]}"


def test_an_invented_page_path_still_serves_the_app(client: TestClient):
    """The catch-all's actual job, and the control for the tests above."""
    assert _is_html(client.get("/a-page-nobody-has-registered-anything-for"))


# ── Direction 2: an API path still reaches the API ───────────────────────────


def test_a_registered_route_in_a_brand_new_namespace_still_answers(client: TestClient):
    """The positive control: the catch-all did not swallow the real route."""
    r = client.get("/webhooks/stripe/events")

    assert r.status_code == 200 and r.json() == {"ok": True}


def test_a_missing_path_in_a_brand_new_api_namespace_is_a_json_404(client: TestClient):
    """Red on the pre-fix tree: 200 text/html.

    The namespace is live, so a path inside it that has no route is a missing
    endpoint — and an API client must be told so, with a body naming the route.
    Answering HTML turns a missing endpoint into a parse error three layers
    away from the cause.
    """
    r = client.get("/webhooks/stripe/nope")

    assert not _is_html(r), "an unlisted API namespace was answered with the SPA shell"
    assert r.status_code == 404
    assert r.json()["path"] == "/webhooks/stripe/nope"


def test_a_sibling_path_in_a_brand_new_api_namespace_is_a_json_404(client: TestClient):
    """Red on the pre-fix tree: 200 text/html. One segment deep, not two."""
    r = client.get("/webhooks/paypal")

    assert not _is_html(r), "an unlisted API namespace was answered with the SPA shell"
    assert r.status_code == 404


def test_an_api_path_that_does_not_exist_is_still_a_json_404(client: TestClient):
    """Green before and after — the behaviour the change must not lose."""
    r = client.get("/api/definitely-not-a-route")

    assert not _is_html(r)
    assert r.status_code == 404
    assert r.json()["detail"] == "No route for GET /api/definitely-not-a-route"


def test_a_webhook_path_under_a_registered_namespace_is_not_the_spa(client: TestClient):
    """`/kyc` is a page; `/kyc/webhooks/sumsub` is Sumsub's.

    Both halves of the same derivation: the bare path is claimed by nothing, a
    path inside it is claimed by the KYC router. Answering a provider webhook
    with the SPA shell is worse than 404ing it.
    """
    r = client.get("/kyc/webhooks/sumsub")

    assert not _is_html(r), "a registered API sub-path was answered with the SPA shell"


def test_the_mobile_mount_is_still_reached(client: TestClient):
    """A Mount is not an APIRoute, and the derivation has to see it too."""
    r = client.get("/mobile/api/v2/quotes/XAUUSD")

    assert not _is_html(r), "the mobile API mount was shadowed by the SPA"


# ── The floor: /api/ and /ws/ are never the SPA, registered or not ───────────


def test_api_paths_are_never_the_spa_even_with_no_routers_registered():
    """A registration failure must not become a silent HTML 200 for every API path.

    Derivation alone would serve the SPA here, because with no routers there is
    no /api namespace to derive. That is the one case where reading the route
    table gives the wrong answer, so the floor is stated rather than derived —
    and it is two prefixes the React router never owns, not a list of every
    namespace.
    """
    if not (ROOT / "static" / "index.html").is_file():
        pytest.skip("frontend build (static/) absent")

    client = _build(with_api=False)

    for path in ("/api/health", "/api/v1/auth/login", "/ws/live"):
        r = client.get(path)
        assert not _is_html(r), f"{path} was answered with the SPA shell after the API routers failed to register"
        assert r.status_code == 404
