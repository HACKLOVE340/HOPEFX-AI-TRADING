# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_exception_info_exposure.py
==========================================
Handlers must not quote an arbitrary exception's message back to the caller.

Around forty endpoints caught a broad ``Exception`` and returned ``str(exc)`` —
``{"ok": False, "error": str(exc)}``, ``detail=str(exc)``. The message of an
exception nobody chose is not an explanation of what the caller did wrong; it
is whatever the failing library printed. Here that means DSNs with passwords in
them (psycopg2, redis), absolute filesystem paths, SQL text with bound row
values, and upstream broker responses.

``api.error_details.safe_error`` replaces those with the exception's class name
plus a reference, and writes the real thing to the log under that reference —
so the superadmin diagnostics pages keep their diagnosability, the detail just
moves to where it was already being written.

The one deliberate exception is ``api/nocode.py``'s ``except ValueError``: the
template compiler raises it to say *why* a strategy graph is invalid, and that
message is the response's entire purpose. It is our copy, not a library's.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[2]

# Every module that had a leak. If a new one appears in any of these, the sweep
# regressed.
_SWEPT = [
    "api/transparency.py",
    "api/settings_new_endpoints.py",
    "api/server.py",
    "api/mobile.py",
    "api/custom_indicators.py",
    "api/admin.py",
    "api/nocode.py",
    "ml/__init__.py",
    "health_check_service.py",
    "api/superadmin/users.py",
    "api/superadmin/diagnostics.py",
    "api/superadmin/health_engine_api.py",
    "api/superadmin/broker_management.py",
    "api/superadmin/auto_healing.py",
    "api/superadmin/compliance.py",
    "api/superadmin/reporting.py",
    "api/superadmin/reliability.py",
    "api/superadmin/risk_management.py",
    "api/superadmin/gdpr.py",
    "api/superadmin/platform.py",
    "api/superadmin/security_infra.py",
    "api/superadmin/infrastructure.py",
    "api/superadmin/system_health.py",
]

_LEAK_RE = re.compile(r"str\((exc|_exc)\)")


# ── The helper itself ─────────────────────────────────────────────────────────


def test_safe_error_keeps_the_message_off_the_wire():
    """A DSN in the exception text must not reach the caller."""
    from api.error_details import safe_error

    secret_dsn = "postgresql://hopefx:S3cretPw@db:5432/hopefx"  # pragma: allowlist secret
    try:
        raise ConnectionRefusedError(f"could not connect to {secret_dsn}")
    except ConnectionRefusedError as exc:
        out = safe_error(exc, "db ping")

    assert "S3cretPw" not in out
    assert "postgresql" not in out
    assert re.fullmatch(r"ConnectionRefusedError \[ref:[0-9a-f]{8}\]", out), out


def test_safe_error_logs_the_full_exception_under_the_same_ref(caplog):
    """The detail has to remain recoverable, or this trades a leak for a blind spot."""
    from api.error_details import safe_error

    with caplog.at_level(logging.ERROR, logger="api.error_details"):
        try:
            raise FileNotFoundError("/srv/hopefx/secrets/oanda.key")
        except FileNotFoundError as exc:
            out = safe_error(exc, "load broker key")

    ref = re.search(r"\[ref:([0-9a-f]{8})\]", out).group(1)
    record = caplog.text
    assert f"ref={ref}" in record, "client ref does not appear in the log"
    assert "/srv/hopefx/secrets/oanda.key" in record, "detail was lost, not relocated"
    assert "load broker key" in record


def test_safe_error_reference_is_unique_per_call():
    """Two failures must be distinguishable in the log."""
    from api.error_details import safe_error

    refs = set()
    for _ in range(10):
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            refs.add(safe_error(exc))
    assert len(refs) == 10


def test_the_class_name_survives_so_clients_can_still_branch():
    from api.error_details import safe_error

    for exc_type in (TimeoutError, PermissionError, ValueError):
        try:
            raise exc_type("detail that must not escape")
        except exc_type as exc:
            assert safe_error(exc).startswith(exc_type.__name__)


# ── The sweep ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rel", _SWEPT)
def test_no_module_returns_a_raw_exception_message(rel):
    src = (_REPO / rel).read_text(encoding="utf-8")
    leaks = [f"{rel}:{i}: {ln.strip()}" for i, ln in enumerate(src.split("\n"), 1) if _LEAK_RE.search(ln)]
    assert not leaks, "raw exception message returned to caller:\n" + "\n".join(leaks)


@pytest.mark.parametrize("rel", _SWEPT)
def test_every_swept_module_imports_the_helper_at_top_level(rel):
    """A function-local import would mean the sweep missed a path."""
    tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
    imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "api.error_details"
        and any(a.name == "safe_error" for a in node.names)
        for node in tree.body
    )
    assert imported, f"{rel} uses safe_error but does not import it at module level"


def test_nocode_still_passes_its_own_validation_message_through():
    """Product copy is not a leak — the 422 arm must keep its text."""
    src = (_REPO / "api" / "nocode.py").read_text(encoding="utf-8")

    assert "raise HTTPException(status_code=422, detail=str(e)) from e" in src, (
        "the deliberate ValueError passthrough was swept away with the leaks"
    )
    # ...but the catch-all next to it must not be.
    assert 'detail=f"Deployment failed: {e}"' not in src
