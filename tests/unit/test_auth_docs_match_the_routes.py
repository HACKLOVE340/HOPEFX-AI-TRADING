# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_auth_docs_match_the_routes.py
==============================================
Regression test for finding S-09: the auth documentation described endpoints
that do not exist.

``docs/API.md``'s "Authentication Endpoints" table listed five paths with no
implementation behind them::

    /api/auth/2fa/enable
    /api/auth/2fa/verify
    /api/auth/password/change
    /api/auth/password/reset
    (and docs/SECURITY.md added /api/auth/2fa/complete)

Two of the real ones exist under a *different* prefix: TOTP verification and
backup codes live on ``/api/2fa`` (``api/two_factor.py``), a separate
implementation from ``/api/auth/2fa`` (``auth/router.py``). Password change is
``/api/auth/change-password`` in ``api/settings_extended.py``; reset is
``forgot-password`` + ``reset-password``.

This test checks the direction that matters: **every path the table documents
must exist**. The reverse is not asserted — a table is allowed to be a summary
and omit routes — so adding an endpoint never breaks this, while documenting a
fictional one does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_DOC = _REPO_ROOT / "docs" / "API.md"

# Routers that register the paths this table documents.
_ROUTER_SOURCES = (
    Path("auth") / "router.py",
    Path("api") / "settings_extended.py",
    Path("api") / "two_factor.py",
)

_PREFIX_RE = re.compile(r'APIRouter\(\s*prefix="([^"]+)"')
_ROUTE_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"')
# | POST | `/api/auth/login` | None | Get JWT token |
_TABLE_ROW_RE = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|")


def _registered_routes() -> set[tuple[str, str]]:
    """(method, full path) for every route in the auth-related routers."""
    routes: set[tuple[str, str]] = set()
    for relative in _ROUTER_SOURCES:
        source = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        prefix_match = _PREFIX_RE.search(source)
        prefix = prefix_match.group(1) if prefix_match else ""
        for method, path in _ROUTE_RE.findall(source):
            routes.add((method.upper(), prefix + path))
    return routes


def _documented_auth_rows() -> list[tuple[str, str]]:
    """(method, path) from the Authentication Endpoints table in docs/API.md."""
    lines = _API_DOC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "## Authentication Endpoints")

    rows: list[tuple[str, str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):  # next section
            break
        match = _TABLE_ROW_RE.match(line)
        if match:
            rows.append((match.group(1), match.group(2)))
    return rows


def _normalise(path: str) -> str:
    """Collapse path parameters so `{session_id}` and `{id}` compare equal."""
    return re.sub(r"\{[^}]*\}", "{}", path.rstrip("/")) or "/"


@pytest.mark.unit
class TestAuthEndpointTable:
    def test_the_table_was_found_and_is_not_empty(self):
        rows = _documented_auth_rows()
        assert len(rows) >= 10, (
            f"only parsed {len(rows)} rows from the Authentication Endpoints "
            "table — the heading or table format changed and this test is no "
            "longer checking anything."
        )

    def test_the_routers_were_parsed(self):
        routes = _registered_routes()
        assert ("POST", "/api/auth/login") in routes, (
            "route extraction is broken — /api/auth/login should always be there"
        )

    def test_every_documented_path_exists(self):
        registered = {(method, _normalise(path)) for method, path in _registered_routes()}

        missing = [
            f"{method} {path}"
            for method, path in _documented_auth_rows()
            if (method, _normalise(path)) not in registered
        ]

        assert not missing, (
            "docs/API.md documents endpoints with no implementation: "
            f"{missing}. Five such rows shipped for some time, including "
            "`/api/auth/2fa/verify` (the real one is `/api/2fa/verify`, a "
            "different module) and `/api/auth/password/change` (really "
            "`/api/auth/change-password`) — see S-09."
        )


@pytest.mark.unit
class TestTheFictionalPathsAreGoneEverywhere:
    """They appeared in three documents, so check all three."""

    _FICTIONAL = (
        "/api/auth/2fa/enable",
        "/api/auth/2fa/verify",
        "/api/auth/2fa/complete",
        "/api/auth/password/change",
        "/api/auth/password/reset",
    )

    # Phrases that mark a mention as "this does not exist" rather than a
    # reference. Both documents keep the fictional paths on purpose, to record
    # that the endpoints — and in one case the whole 2FA-at-login flow — are
    # absent. Deleting the mention would remove the claim without recording the
    # gap, so the test looks for the disclaimer instead of banning the string.
    _DISCLAIMERS = ("not exist", "not implemented", "no implementation", "used to document")

    _CONTEXT_LINES = 6

    @pytest.mark.parametrize("doc", ["API.md", "SECURITY.md", "FAQ.md"])
    def test_no_doc_presents_a_fictional_path_as_real(self, doc):
        lines = (_REPO_ROOT / "docs" / doc).read_text(encoding="utf-8").splitlines()

        for path in self._FICTIONAL:
            for index, line in enumerate(lines):
                if path not in line:
                    continue
                start = max(0, index - self._CONTEXT_LINES)
                paragraph = " ".join(lines[start : index + self._CONTEXT_LINES + 1]).lower()
                assert any(phrase in paragraph for phrase in self._DISCLAIMERS), (
                    f"{doc}:{index + 1} presents {path} as a real endpoint, with "
                    f"nothing within {self._CONTEXT_LINES} lines saying it does "
                    f"not exist:\n  {line.strip()}"
                )
