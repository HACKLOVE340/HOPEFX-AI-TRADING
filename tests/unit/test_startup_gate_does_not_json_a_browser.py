"""The startup gate must not answer a browser navigation with raw JSON.

`core/middleware.py`'s startup-gate comment states the intent plainly:

    Health, auth, CSRF, docs, and static assets are always allowed
    through so the frontend can render and users can log in while the
    trading engine is still warming up.

It did not do that. `/static` was allowed but the SPA *document* routes were
not, so a browser navigating to `/login` or `/dashboard` during startup was
handed `{"detail": "Server is starting up..."}` as its page and never reached
the HTML that would have loaded `/static/*`. Measured against the real server
on 2026-09-19: **50 seconds** of that, cold, because startup waits on three
FRED retries — while the message says "a few seconds".

The sibling `SubscriptionPaywallMiddleware` had already written down the rule
this violates: "Gating them would return raw JSON to a browser navigation."

The gate itself is not weakened. A path the server claims is still refused
while uninitialized, so no endpoint answers with uninitialized data; the SPA
shell carries no data, and its own `/api/...` calls stay gated.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from core.middleware import setup_startup_gate


class _State:
    def __init__(self, initialized: bool) -> None:
        self.initialized = initialized


def _app(initialized: bool = False, *, with_routes: bool = True) -> FastAPI:
    app = FastAPI()
    if with_routes:

        @app.get("/api/positions")
        async def positions():  # pragma: no cover - body never reached when gated
            return {"positions": []}

        @app.get("/ws/live")
        async def ws_live():  # pragma: no cover
            return {"ok": True}

        @app.get("/dashboard")
        async def dashboard():
            return HTMLResponse("<!doctype html><title>HOPEFX</title>")

        @app.get("/login")
        async def login():
            return HTMLResponse("<!doctype html><title>HOPEFX</title>")

    setup_startup_gate(app)
    app.state.app_state = _State(initialized)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ── positive controls: the gate is live and can fail ──────────────────────────


def test_the_gate_is_live_and_refuses_a_server_path_before_init(monkeypatch):
    """Without this, every assertion below passes against a gate that is off."""
    monkeypatch.delenv("STARTUP_GATE", raising=False)
    r = _client(_app(initialized=False)).get("/api/positions")
    assert r.status_code == 503, "the startup gate did not gate an API path"
    assert r.json()["status"] == "starting"


def test_an_initialized_app_serves_the_server_path(monkeypatch):
    monkeypatch.delenv("STARTUP_GATE", raising=False)
    r = _client(_app(initialized=True)).get("/api/positions")
    assert r.status_code == 200


# ── the defect ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/dashboard", "/login"])
def test_a_browser_navigation_gets_html_not_json_during_startup(monkeypatch, path):
    monkeypatch.delenv("STARTUP_GATE", raising=False)
    r = _client(_app(initialized=False)).get(path, headers={"Accept": "text/html"})

    assert r.status_code == 200, f"{path} was refused with {r.status_code} during startup"
    assert "text/html" in r.headers.get("content-type", "")
    assert "Server is starting up" not in r.text


# ── the gate is not weakened ──────────────────────────────────────────────────


def test_the_spa_own_api_calls_are_still_refused(monkeypatch):
    """The shell renders; the data it asks for is still withheld.

    Sent with `Accept: text/html` on purpose — the header is caller-controlled,
    so it must not be what decides whether data is served.
    """
    monkeypatch.delenv("STARTUP_GATE", raising=False)
    r = _client(_app(initialized=False)).get("/api/positions", headers={"Accept": "text/html"})
    assert r.status_code == 503, "/api/positions was served during startup"


def test_websockets_stay_allowed_through_by_decision(monkeypatch):
    """`/ws` is in the allowlist deliberately — not an oversight this fix closes.

    The allowlist's own comment states the reason: "WebSocket — auth is checked
    inside the handler". This test failed first as a floor assertion, and the
    honest answer was that the code was right and the assertion was invented.
    Recorded so the next reader does not re-litigate it. Whether a socket should
    also refuse to open before `initialized` is a separate question, untouched.
    """
    monkeypatch.delenv("STARTUP_GATE", raising=False)
    r = _client(_app(initialized=False)).get("/ws/live")
    assert r.status_code == 200, "/ws stopped being allowlisted"


def test_an_empty_route_table_still_refuses_api(monkeypatch):
    """The floor.

    Namespaces are DERIVED from the route table. A control that reads an empty
    table answers "nothing is claimed" and passes everything — it cannot fail.
    `/api/` is refused on its prefix alone, whatever the table says.
    """
    monkeypatch.delenv("STARTUP_GATE", raising=False)
    r = _client(_app(initialized=False, with_routes=False)).get("/api/anything")
    assert r.status_code == 503, "/api/anything passed the gate with no routes registered"
