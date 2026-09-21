# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_auth_cookie_secure_flag.py
===========================================
Regression tests for finding S-07: token rotation dropped the ``Secure`` flag.

``auth/router.py`` sets five auth cookies, from four ``secure`` assignments —
and those four read two different environment variables::

    login:          os.getenv("APP_ENV",      "development")   # line ~691
    get_csrf_token: os.getenv("APP_ENV",      "development")   # line ~1101
    refresh:        os.getenv("ENVIRONMENT",  "development")   # lines ~768, ~784

``.env.example`` sets both, but not equally: ``APP_ENV=production`` is line 15,
while ``ENVIRONMENT=production`` sits at line 1008 annotated "controls uvicorn
reload". ``APP_ENV`` is what the other ~100 environment checks in this codebase
read. A deployment that sets only ``APP_ENV`` therefore got ``Secure`` cookies
at login — and then had both the access and the refresh cookie silently
re-issued **without** it on every rotation.

That is the wrong half to lose. ``/auth/refresh`` mints the freshest
credentials in the system, and the refresh cookie is the long-lived one
(``REFRESH_TOKEN_EXPIRE_DAYS``, default 30). Without ``Secure`` the browser
will attach both to any plain-HTTP request to the domain.

All four now go through ``_cookies_require_secure()``, which reads ``APP_ENV``
and falls back to ``ENVIRONMENT`` — the precedence ``api/admin.py`` and
``api/trading.py`` already use. (``login`` sets two cookies from one
assignment, which is why five cookies come from four call sites.)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROUTER = Path(__file__).resolve().parents[2] / "auth" / "router.py"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def _secure() -> bool:
    from auth.router import _cookies_require_secure

    return _cookies_require_secure()


@pytest.mark.unit
class TestEnvironmentResolution:
    @pytest.mark.parametrize("value", ["production", "staging", "PRODUCTION", " Staging "])
    def test_app_env_alone_is_enough(self, monkeypatch, value):
        monkeypatch.setenv("APP_ENV", value)
        assert _secure() is True, (
            "APP_ENV is the primary environment variable in this codebase and "
            "the first one .env.example sets; on its own it must produce Secure "
            "cookies everywhere, refresh included (S-07)."
        )

    def test_environment_alone_still_works(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert _secure() is True, "the older variable must keep working"

    def test_app_env_wins_when_they_disagree(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert _secure() is False

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ENVIRONMENT", "development")
        assert _secure() is True

    @pytest.mark.parametrize("value", ["development", "test", "local", ""])
    def test_non_production_does_not_force_secure(self, monkeypatch, value):
        monkeypatch.setenv("APP_ENV", value)
        assert _secure() is False, (
            "Secure cookies over plain HTTP would break local development — "
            "the flag must stay off outside production/staging."
        )

    def test_unset_defaults_to_insecure_not_to_a_crash(self):
        assert _secure() is False


@pytest.mark.unit
class TestEverySetCookieUsesTheOneHelper:
    """The defect was divergence, so pin that there is nothing left to diverge."""

    def _tree(self) -> ast.Module:
        return ast.parse(_ROUTER.read_text(encoding="utf-8"))

    def test_no_set_cookie_reads_an_env_var_directly(self):
        source = _ROUTER.read_text(encoding="utf-8")
        inline = re.findall(
            r'^\s*_?secure\s*=\s*os\.getenv\((?:"APP_ENV"|"ENVIRONMENT")',
            source,
            re.M,
        )
        assert not inline, (
            f"{len(inline)} cookie site(s) still resolve the environment inline. "
            "They must call _cookies_require_secure() so they cannot drift "
            "apart again (S-07)."
        )

    def test_every_cookie_is_still_set_and_all_pass_secure(self):
        calls = [
            node
            for node in ast.walk(self._tree())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_cookie"
        ]
        assert len(calls) == 5, (
            f"expected 5 set_cookie calls in auth/router.py, found {len(calls)} — a new one needs the same treatment."
        )
        for call in calls:
            names = {kw.arg for kw in call.keywords}
            assert "secure" in names, f"set_cookie at line {call.lineno} sets no secure flag"

    def test_every_secure_assignment_comes_from_the_helper(self):
        """Four assignments feed the five cookies — login sets two from one."""
        assignments = [
            node
            for node in ast.walk(self._tree())
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in ("secure", "_secure") for t in node.targets)
        ]
        assert assignments, "no `secure = ...` assignment found — file restructured?"
        for node in assignments:
            call = node.value
            assert (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_cookies_require_secure"
            ), (
                f"the secure flag at line {node.lineno} is computed inline instead "
                "of via _cookies_require_secure(); that divergence is exactly what "
                "dropped Secure on refresh (S-07)."
            )


@pytest.mark.unit
class TestRefreshSpecifically:
    """The endpoint that had it wrong, checked over a real response."""

    @staticmethod
    def _rotate_refresh_cookie():
        """Reproduce the refresh endpoint's cookie call on a real Response."""
        from fastapi import Response

        import auth.router as auth_router

        response = Response()
        response.set_cookie(
            key="hopefx_refresh_token",
            value="rotated",  # pragma: allowlist secret
            max_age=30 * 86400,
            httponly=True,
            samesite="strict",
            secure=auth_router._cookies_require_secure(),
            path="/api/auth/refresh",
        )
        return response.headers["set-cookie"]

    @pytest.mark.parametrize("var", ["APP_ENV", "ENVIRONMENT"])
    def test_rotated_cookie_is_secure_in_production(self, monkeypatch, var):
        monkeypatch.setenv(var, "production")

        header = self._rotate_refresh_cookie()

        assert "Secure" in header, (
            f"with {var}=production the rotated refresh cookie must carry Secure; "
            "it is the longest-lived credential the system issues (S-07)."
        )
        assert "HttpOnly" in header
        assert "samesite=strict" in header.lower()
        assert "Path=/api/auth/refresh" in header, "the refresh cookie stays scoped to the endpoint that consumes it"

    def test_rotated_cookie_is_not_secure_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        assert "Secure" not in self._rotate_refresh_cookie()
