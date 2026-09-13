# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`/docs` must be able to load its own assets wherever it is mounted.

F200. FastAPI's Swagger UI fetches `swagger-ui-bundle.js` and `swagger-ui.css`
from `https://cdn.jsdelivr.net`. The Content-Security-Policy allows neither:

    script-src 'self'                       (production)
    script-src 'self' 'unsafe-inline'       (everywhere else)
    style-src  'self' 'unsafe-inline' https://fonts.googleapis.com

So the browser refuses both files and the page renders empty — the API
documentation is blank for everyone who opens it, and the failure appears only
in the browser console.

The finding said "blank in every deployment". Measured, that is not quite right
and the difference decides the fix: `app.py` and `api/server.py` both set

    docs_url=None if os.getenv("APP_ENV") == "production" else "/docs"

so in **production `/docs` does not exist at all** — a deliberate choice not to
publish the schema. It is blank in development, staging and local runs, which
is precisely where people open it.

## Why the CSP is widened rather than the assets vendored

Vendoring `swagger-ui-dist` is the usual answer and is wrong here. `static/` is
gitignored, so the files would need a new committed tree of roughly 1.5 MB, for
a page that does not exist in the environment the CSP is protecting.

Instead the CDN is allowed **exactly where `/docs` is mounted**, which is
everywhere except production. Production's `script-src 'self'` is untouched —
the control that matters is not weakened, and it is guarded below. Development
already permits `'unsafe-inline'`, so a pinned CDN is not the weakest link
there.

The invariant is the coupling, and it is what these tests pin: *the CSP admits
the documentation CDN exactly when the documentation is mounted.* Either half
changing alone is the bug — a CDN allowed in production, or a docs page that
still cannot load.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit

_CDN = "https://cdn.jsdelivr.net"


def _csp(monkeypatch, app_env: str | None) -> str:
    """The CSP header value this environment would send."""
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    import core.middleware as mw

    importlib.reload(mw)
    return mw._build_csp(["https://app.example.test"])


def _docs_are_mounted(app_env: str | None) -> bool:
    """The same expression app.py and api/server.py use for `docs_url`."""
    import os

    return (app_env or os.getenv("APP_ENV", "development")) != "production"


@pytest.mark.parametrize("app_env", ["development", "staging", None])
def test_the_docs_cdn_is_allowed_where_the_docs_are_mounted(monkeypatch, app_env):
    """Otherwise the page renders empty and only the console says why."""
    csp = _csp(monkeypatch, app_env)

    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    style_src = next(d for d in csp.split(";") if d.strip().startswith("style-src"))

    assert _CDN in script_src, f"Swagger's JS is blocked in {app_env!r}: {script_src.strip()}"
    assert _CDN in style_src, f"Swagger's CSS is blocked in {app_env!r}: {style_src.strip()}"


def test_production_does_not_allow_the_cdn(monkeypatch):
    """The half that must not move. /docs does not exist in production, so
    nothing there needs the CDN, and allowing it would widen the policy for no
    benefit at all."""
    csp = _csp(monkeypatch, "production")

    assert _CDN not in csp, f"production CSP admits an external CDN: {csp}"


def test_production_script_src_is_still_self_only(monkeypatch):
    """Regression guard on the control this change must not touch.

    If a later edit relaxes production's script-src while adding a CDN
    somewhere, this fails rather than the change passing as 'the F200 fix'.
    """
    csp = _csp(monkeypatch, "production")
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))

    assert script_src.strip() == "script-src 'self'", script_src
    assert "unsafe-inline" not in script_src


@pytest.mark.parametrize("app_env", ["production", "development", "staging", None])
def test_the_cdn_is_allowed_exactly_when_the_docs_are_mounted(monkeypatch, app_env):
    """The coupling itself. Either half drifting alone is the defect."""
    csp = _csp(monkeypatch, app_env)

    assert (_CDN in csp) is _docs_are_mounted(app_env), (
        f"APP_ENV={app_env!r}: docs mounted={_docs_are_mounted(app_env)} but CDN allowed={_CDN in csp}"
    )


def test_the_rest_of_the_policy_is_unchanged(monkeypatch):
    """A widened directive must not quietly become a widened policy."""
    csp = _csp(monkeypatch, "development")

    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp or "object-src" not in csp
    assert "frame-ancestors" in csp
    # connect-src must still be an allowlist, never a wildcard.
    connect = next(d for d in csp.split(";") if d.strip().startswith("connect-src"))
    assert "*" not in connect, connect
