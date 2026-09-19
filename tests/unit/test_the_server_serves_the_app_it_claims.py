# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What the server hands a browser must be the app, not merely HTML.

This file exists because a careful test already covered this ground and still
let four defects reach a laptop.

`test_every_spa_route_serves_the_app.py` asserts, for every route `App.tsx`
declares, that a direct GET answers with `text/html`. That is the right
question asked in a way that cannot fail. Three separate wrong answers are all
`text/html`:

* the legacy dashboard committed under `dashboard/dist/`, two weeks stale,
* a server-rendered Jinja page shadowing the React page of the same name,
* a meta-refresh whose destination is the Swagger UI.

It also opens with a skip when `static/index.html` is absent -- which is the
state every one of those defects needs in order to appear. A guard that stands
down in the failure condition is not a guard.

So this file asserts identity rather than shape: the bytes returned are the
bytes of the built shell. And it exercises the unbuilt case on purpose instead
of skipping it, because a deployment whose frontend build failed is a real
deployment and is the one a new machine produces.

Reproduced 2026-09-19 against a live server on this branch, by moving
`static/` aside and issuing the requests a browser issues:

    GET /          -> 302 to /godmode/, then "HOPEFX GodMode v9.5"
    GET /login     -> 200, a meta-refresh to /docs
    GET /register  -> 200, a meta-refresh to /docs
    GET /dashboard -> 404 application/json

and with `static/` present:

    GET /pricing   -> 200, 22,572 bytes of templates/pricing.html,
                      not the 8,574-byte React shell
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
SPA_INDEX = ROOT / "static" / "index.html"
START_SH = ROOT / "start.sh"

#: Paths React Router declares that a server-side handler claims first.
#:
#: Every entry is a live collision: the React page is built, shipped and
#: unreachable, because a handler registered earlier answers the path. None is
#: a convenience exemption, and each needs an owner decision rather than a
#: unilateral fix, because resolving it changes which page a user sees.
#:
#:   /mobile   - `core/router_registry.py` mounts the mobile API sub-app here
#:               and `App.tsx` declares a page. Serving the SPA would shadow a
#:               live API. Tracked as F198; also pinned by the sibling file.
#:   /docs     - FastAPI's own Swagger UI. `App.tsx` declares a DocsPage, which
#:               is therefore dead. Resolving it means moving Swagger (it is a
#:               published API surface, so moving it is not free) or renaming
#:               the page.
#:   /pricing  - `core/page_routes.py::pricing_page` renders templates/pricing.html
#:               (22,572 bytes). The React PricingPage is built and dead. This
#:               is a billing surface, so which one is authoritative is a
#:               product call.
#:   /status   - same shape as /pricing, via templates/status.html.
#:
#: `test_a_pinned_collision_is_still_a_collision` fails if any of these starts
#: serving the shell, so a resolved one cannot sit here unnoticed.
_SERVER_OWNED: frozenset[str] = frozenset({"/mobile", "/docs", "/pricing", "/status"})


def _declared_routes() -> list[str]:
    """Concrete page paths declared in App.tsx.

    Parameterised and wildcard routes are excluded: a made-up id exercises a
    404 rather than the shell.
    """
    text = APP_TSX.read_text(encoding="utf-8")
    paths = {m.group(1) for m in re.finditer(r'path="(/[^"]*)"', text)}
    return sorted(p for p in paths if ":" not in p and "*" not in p and p not in _SERVER_OWNED)


def _built_app() -> TestClient:
    """The full production registration order: API routers, then page routes."""
    from config.feature_flags import flags as feature_flags
    from core.page_routes import register_page_routes
    from core.router_registry import register_routers

    app = FastAPI()
    register_routers(app, feature_flags)
    register_page_routes(app)
    return TestClient(app)


# ── Harness guards ───────────────────────────────────────────────────────────
# Assert the harness observed something before trusting what it reports.


def test_the_route_table_was_actually_parsed():
    routes = _declared_routes()
    assert len(routes) >= 50, (
        f"only {len(routes)} routes parsed out of App.tsx -- the extraction has broken "
        "and every check below would pass over an empty list"
    )
    assert "/dashboard" in routes


# ── The built case: identity, not shape ──────────────────────────────────────


@pytest.mark.skipif(not SPA_INDEX.is_file(), reason="frontend build (static/) absent")
def test_declared_routes_return_the_shell_itself_not_just_some_html():
    """A direct GET must return the bytes of the built shell.

    Asserting the content type instead lets a Jinja page, a stale bundle and a
    redirect to the API docs all pass, because each is HTML.
    """
    client = _built_app()
    expected = SPA_INDEX.read_bytes()

    wrong: dict[str, str] = {}
    for path in _declared_routes():
        r = client.get(path)
        if r.content != expected:
            wrong[path] = f"{r.status_code} {r.headers.get('content-type', '')} {len(r.content)}B"

    assert not wrong, (
        "these declared SPA routes answered with something other than the built shell -- "
        f"a server-side handler is claiming the path ahead of the page: {wrong}"
    )


# ── The unbuilt case: exercised, not skipped ─────────────────────────────────


def test_the_auth_pages_do_not_send_an_unbuilt_frontend_to_the_api_docs():
    """A person clicking Login gets a login page or an honest error.

    Sending them to the Swagger UI reads, to the person, as the product being
    broken in a way they cannot describe. It was reported as "it takes me to
    documents".
    """
    from api import pages

    absent = pages._STATIC / "index-this-file-does-not-exist.html"
    original = pages._SPA_INDEX
    pages._SPA_INDEX = absent
    try:
        response = pages._spa()
        body = getattr(response, "body", b"") or b""
        text = body.decode("utf-8", "replace")
    finally:
        pages._SPA_INDEX = original

    assert "/docs" not in text, "the unbuilt frontend fallback points a person at the API documentation: " + text[:200]
    assert "npm run build" in text, (
        "the unbuilt frontend fallback does not tell the operator how to build it: " + text[:200]
    )


def test_the_root_path_does_not_serve_the_legacy_dashboard_when_the_app_is_unbuilt(tmp_path):
    """A failed build must not silently promote a stale committed bundle.

    `dashboard/dist/` is committed on purpose and is reachable at /godmode/.
    Serving it at / when the real build is missing is the shape this repository
    names elsewhere: success reported for work that did not happen.
    """
    from core.page_routes import register_page_routes

    # A root where the build failed: no static/, but the committed legacy
    # bundle is present exactly as it is in a real checkout.
    (tmp_path / "dashboard" / "dist").mkdir(parents=True)
    (tmp_path / "dashboard" / "dist" / "index.html").write_text(
        "<html><title>HOPEFX GodMode v9.5</title><body>legacy</body></html>", encoding="utf-8"
    )
    assert not (tmp_path / "static").exists(), "harness did not produce an unbuilt root"

    app = FastAPI()
    register_page_routes(app, root=tmp_path)
    r = TestClient(app).get("/", follow_redirects=False)

    assert not (r.status_code == 302 and "/godmode" in r.headers.get("location", "")), (
        "/ redirects to the legacy dashboard when the main app is unbuilt, so an operator "
        "whose build failed is shown a stale committed UI instead of being told the build failed"
    )
    assert r.status_code == 503, (
        f"/ answered {r.status_code} with the frontend unbuilt -- the server cannot serve the "
        "application, and any 2xx tells probes and uptime checks that it can"
    )
    assert "npm run build" in r.text, "the build-required page does not name the command that fixes it"

    # The legacy bundle is committed deliberately; it must stay reachable, just
    # not at the application's own address.
    assert TestClient(app).get("/godmode/").status_code == 200, (
        "/godmode/ stopped serving the legacy dashboard -- it is committed on purpose"
    )


# ── The script that starts it ────────────────────────────────────────────────


def test_start_sh_does_not_stamp_the_commit_after_a_failed_build():
    """The stamp is what makes a failed build permanent.

    start.sh rebuilds when static/.build-commit differs from HEAD. Writing the
    stamp on a failure path means the next run reports the build as up to date
    and never retries, so one transient failure pins the machine to whatever
    bundle happened to be on disk.
    """
    text = START_SH.read_text(encoding="utf-8")
    # The failure branch runs from the `elif`/`else` after the build attempt up
    # to the end of that if-block. Read the block rather than the whole file so
    # the success-path stamp is not mistaken for a failure-path one.
    marker = "npm run build"
    idx = text.find(marker)
    assert idx != -1, "start.sh no longer invokes the frontend build -- this guard is checking nothing"

    after = text[idx:]
    end = after.find("\n# ")
    block = after[: end if end != -1 else len(after)]

    # Split on the first branch boundary: everything after it is a failure path.
    branch = re.search(r"\n\s*(elif|else)\b", block)
    assert branch is not None, (
        "start.sh no longer has a failure branch after the frontend build -- if the build "
        "can no longer fail, delete this guard deliberately rather than letting it pass"
    )
    failure_paths = block[branch.start() :]

    # A *write* is the defect. `rm -f static/.build-commit` on the failure path
    # is the opposite and must stay allowed, so match the redirection rather
    # than the filename -- the crude version of this check failed the fix.
    writes = re.findall(r">\s*static/\.build-commit", failure_paths)

    assert not writes, (
        "start.sh writes static/.build-commit on a path where the build did not succeed. "
        "Every later run then reports the frontend as up to date and skips the rebuild, "
        "so one failed build pins the machine to a stale bundle permanently."
    )

    assert re.search(r"rm\s+-f\s+static/\.build-commit", failure_paths), (
        "start.sh does not clear static/.build-commit when the build fails. Without that, a "
        "stamp left by an earlier successful build at this commit still suppresses the rebuild."
    )


@pytest.mark.skipif(not SPA_INDEX.is_file(), reason="frontend build (static/) absent")
def test_a_pinned_collision_is_still_a_collision():
    """An exemption nobody revisits is how a known defect becomes invisible.

    If one of these starts serving the shell -- the mount moved, the template
    route was deleted, the page was renamed -- this fails and says to take it
    out of the set. That is the only thing standing between a documented,
    decided exemption and a permanent one.
    """
    client = _built_app()
    shell = SPA_INDEX.read_bytes()

    resolved = [p for p in sorted(_SERVER_OWNED) if client.get(p).content == shell]

    assert not resolved, (
        f"these paths now serve the SPA shell: {resolved}. The collision is resolved -- "
        "remove them from _SERVER_OWNED so the identity check above starts covering them."
    )
