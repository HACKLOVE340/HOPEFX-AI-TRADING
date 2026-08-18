# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_godmode_mount_reachable.py
===========================================
Regression tests for finding S-02: the GodMode dashboard was unreachable in the
one deployment that matters.

``core/page_routes.py`` mounted ``dashboard/dist`` at ``/godmode`` *after*
registering the ``/{full_path:path}`` SPA catch-all. Starlette matches routes in
registration order, so the catch-all claimed every ``/godmode/*`` request first.
It does list ``"godmode/"`` among its passthrough prefixes — but as the comment
beside that list already explains for the ``/api`` case, returning 404 from a
route that has **matched** does not hand the request onward; the response ends
it. ``GET /godmode/`` answered::

    {"detail": "No route for GET /godmode/", ...}

Only in the branch where ``static/`` exists, i.e. the Docker/production build.
The fallback branch (dashboard only, no main app) mounted it before any
catch-all existed and worked, which is why this survived.

Behind that sat a second break. ``dashboard/vite.config.ts`` set no ``base``, so
the bundle emitted absolute ``/assets/…`` URLs. Served from ``/godmode/`` those
resolve against the **root** mount — the main app's build, with different
content hashes — so they fell through to the catch-all and came back as
``index.html``. HTML delivered for a ``<script src>``. And ``BrowserRouter`` had
no ``basename``, so routes declared ``/checkout``, ``/dashboard`` were matched
against ``/godmode/...`` and matched nothing.

Three independent faults, each sufficient on its own to leave the page blank.
The source-level tests below hold for all of them without needing a build; the
functional test runs when both builds are present.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _REPO_ROOT / "dashboard"
_PAGE_ROUTES = _REPO_ROOT / "core" / "page_routes.py"
_CATCHALL_PATH = "/{full_path:path}"


@pytest.mark.unit
class TestMountIsRegisteredBeforeTheCatchAll:
    """The ordering invariant, checked on the source so it holds without a build."""

    @staticmethod
    def _arm_map(tree: ast.AST) -> dict[int, list[tuple[int, str]]]:
        """For every node, the ``(if-node-id, "body"|"orelse")`` arms enclosing it.

        Two statements can only both execute if they agree on every ``if`` they
        share. This is what keeps the fallback branch — dashboard built, main
        app not — from being read as a defect: it mounts /godmode at a line
        after the other branch's catch-all, but the two arms are mutually
        exclusive and never run together.
        """
        arms: dict[int, list[tuple[int, str]]] = {id(tree): []}
        for parent in ast.walk(tree):
            inherited = arms.get(id(parent), [])
            for field, value in ast.iter_fields(parent):
                children = value if isinstance(value, list) else [value]
                for child in children:
                    if not isinstance(child, ast.AST):
                        continue
                    path = list(inherited)
                    if isinstance(parent, ast.If) and field in ("body", "orelse"):
                        path.append((id(parent), field))
                    arms[id(child)] = path
        return arms

    @staticmethod
    def _calls(tree: ast.AST, attr: str, first_arg: str) -> list[ast.Call]:
        """Every ``<x>.<attr>(first_arg, ...)`` call in the tree."""
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == first_arg
        ]

    @staticmethod
    def _mutually_exclusive(a: list[tuple[int, str]], b: list[tuple[int, str]]) -> bool:
        b_arms = dict(b)
        return any(node_id in b_arms and b_arms[node_id] != arm for node_id, arm in a)

    def test_every_godmode_mount_precedes_the_catchall_that_could_shadow_it(self):
        tree = ast.parse(_PAGE_ROUTES.read_text(encoding="utf-8"))
        arms = self._arm_map(tree)

        mounts = self._calls(tree, "mount", "/godmode")
        catchalls = self._calls(tree, "get", _CATCHALL_PATH)
        assert mounts, "no /godmode mount found in core/page_routes.py"
        assert catchalls, "no SPA catch-all found — has the file been restructured?"

        compared = 0
        for mount in mounts:
            for catchall in catchalls:
                if self._mutually_exclusive(arms[id(mount)], arms[id(catchall)]):
                    continue  # never registered on the same request path
                compared += 1
                assert mount.lineno < catchall.lineno, (
                    f"the /godmode mount at line {mount.lineno} is registered "
                    f"after the catch-all at line {catchall.lineno}, on the same "
                    "execution path. Starlette matches in registration order, so "
                    "the catch-all wins and /godmode/ 404s (S-02)."
                )

        assert compared, (
            "no mount and catch-all share an execution path — the file has been "
            "restructured and this test no longer checks anything."
        )


@pytest.mark.unit
class TestBundleIsBuiltForItsMountPoint:
    def test_vite_config_declares_the_godmode_base(self):
        config = (_DASHBOARD / "vite.config.ts").read_text(encoding="utf-8")
        assert re.search(r"^\s*base:\s*'/godmode/'", config, re.M), (
            "dashboard/vite.config.ts must set base: '/godmode/' — without it the "
            "bundle asks the root mount for its own JavaScript (S-02)."
        )

    def test_router_carries_a_basename(self):
        main = (_DASHBOARD / "src" / "main.tsx").read_text(encoding="utf-8")
        assert "basename=" in main, (
            "BrowserRouter needs a basename, or every route is matched against /godmode/... and nothing renders (S-02)."
        )

    def test_built_index_references_only_prefixed_paths(self):
        index = _DASHBOARD / "dist" / "index.html"
        assert index.is_file(), "dashboard/dist/index.html is committed — it must exist"

        html = index.read_text(encoding="utf-8")
        absolute = re.findall(r'(?:src|href)="(/[^"]*)"', html)
        assert absolute, "expected the built index to reference its assets absolutely"

        unprefixed = [p for p in absolute if not p.startswith("/godmode/")]
        assert not unprefixed, (
            f"{unprefixed} are served from the root mount, not from this bundle. "
            "Rebuild with `cd dashboard && npm run build` (S-02)."
        )

    def test_no_second_competing_manifest(self):
        html = (_DASHBOARD / "dist" / "index.html").read_text(encoding="utf-8")
        assert '"/manifest.json"' not in html, (
            "the hand-written manifest declared scope '/' and listed icons that "
            "were never shipped; the generated manifest.webmanifest is the one."
        )


@pytest.mark.unit
class TestGodModeAnswersOverHttp:
    """Functional check — only meaningful when the main app is also built."""

    def _app(self) -> FastAPI:
        from core.page_routes import register_page_routes

        app = FastAPI()
        register_page_routes(app)
        return app

    @pytest.fixture(autouse=True)
    def _needs_both_builds(self):
        if not (_REPO_ROOT / "static" / "index.html").is_file():
            pytest.skip("frontend build (static/) absent — the conflicting branch")
        if not (_DASHBOARD / "dist" / "index.html").is_file():
            pytest.skip("dashboard/dist absent")

    def test_mount_wins_over_the_catchall_in_the_built_app(self):
        routes = self._app().routes
        mount_at = next(i for i, r in enumerate(routes) if isinstance(r, Mount) and r.path == "/godmode")
        catchall_at = next(i for i, r in enumerate(routes) if isinstance(r, APIRoute) and r.path == _CATCHALL_PATH)
        assert mount_at < catchall_at

    def test_godmode_index_and_all_its_assets_resolve(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(), raise_server_exceptions=False)

        index = client.get("/godmode/")
        assert index.status_code == 200, index.text[:200]
        assert index.headers["content-type"].startswith("text/html")

        for ref in re.findall(r'(?:src|href)="(/[^"]*)"', index.text):
            asset = client.get(ref)
            content_type = (asset.headers.get("content-type") or "").split(";")[0]
            assert asset.status_code == 200, f"{ref} -> {asset.status_code}"
            assert content_type != "text/html", (
                f"{ref} came back as HTML — it resolved against the root mount instead of the dashboard bundle (S-02)."
            )

    def test_the_main_app_and_api_404s_are_unaffected(self):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(), raise_server_exceptions=False)

        for path in ("/", "/dashboard", "/login"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/html")

        missing = client.get("/api/definitely-not-a-route")
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/json"), (
            "the catch-all must still answer unknown /api paths with JSON rather than handing back the SPA shell."
        )
