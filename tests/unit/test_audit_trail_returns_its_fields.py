# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_audit_trail_returns_its_fields.py
=================================================
The Audit Trail page reported "15 total admin actions" over 15 empty rows.

Every column except the user UUID was blank: no action, no resource, no IP, no
status, no timestamp. It looked like an audit log that had recorded nothing —
on a money-moving platform, where the audit log is the compliance record.

**The records were complete the whole time.** ``AuditLogEntry`` carries
``actor``, ``action``, ``category`` and ``level``, all ``nullable=False``, plus
``event_type``, ``detail``, ``ip_address`` and ``created_at``. Two independent
mistakes hid all of it:

1. ``GET /api/superadmin/audit`` returned only six fields and **omitted
   ``action``, ``category``, ``level`` and ``actor``** — the four that say what
   happened and how serious it was.

2. The React component read a completely different set of names —
   ``e.username``, ``e.action``, ``e.resource``, ``e.resource_id``, ``e.ip``,
   ``e.status``, ``e.timestamp`` — against an API that sends ``event_type``,
   ``ip_address`` and ``created_at``. Its ``SystemAuditEntry`` interface
   described an endpoint that has never existed, and TypeScript accepted it
   because the response is read off ``res.data`` untyped. Every field resolved
   to ``undefined`` at runtime, including the React ``key``.

``resource_id`` and ``status`` were removed rather than renamed: the table has
no column for either, so any cell bound to them can only ever be empty. A
column that is structurally incapable of holding data is not a degraded
feature, it is a false promise.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SECTION = _ROOT / "frontend/src/pages/superadmin/AuditTrailSection.tsx"


# ── The model carries the data ───────────────────────────────────────────────


@pytest.mark.parametrize("column", ["actor", "action", "category", "level"])
def test_the_audit_model_has_the_fields_that_were_missing(column):
    """If these ever become nullable or disappear, the endpoint below is
    returning something it cannot guarantee."""
    from database.models import AuditLogEntry

    col = AuditLogEntry.__table__.columns.get(column)
    assert col is not None, f"AuditLogEntry lost its {column} column"
    assert col.nullable is False, f"{column} became nullable — the page can no longer rely on it"


@pytest.mark.parametrize("column", ["resource_id", "status", "username", "resource"])
def test_the_model_has_no_column_for_the_invented_fields(column):
    """Pins why those table columns were deleted rather than remapped."""
    from database.models import AuditLogEntry

    assert AuditLogEntry.__table__.columns.get(column) is None, (
        f"AuditLogEntry gained a {column} column — the Audit Trail table can show it now"
    )


# ── The endpoint returns them ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "field",
    ["event_id", "created_at", "actor", "user_id", "action", "event_type", "category", "level", "ip_address", "detail"],
)
def test_the_endpoint_emits_every_field_the_table_renders(field):
    import inspect

    from api.superadmin.audit import get_audit_log

    src = inspect.getsource(get_audit_log)
    assert f'"{field}"' in src, f"the audit endpoint stopped returning {field}"


def test_action_falls_back_to_event_type_not_to_blank():
    """`action` is NOT NULL, but older rows written before the event_type
    migration are worth rendering rather than dropping."""
    import inspect

    from api.superadmin.audit import get_audit_log

    assert "r.action or r.event_type" in inspect.getsource(get_audit_log)


def test_the_csv_export_carries_the_same_fields():
    """An export that omits the action is not an audit export."""
    import inspect

    from api.superadmin.audit import export_audit_log

    src = inspect.getsource(export_audit_log)
    for field in ("action", "category", "level", "actor"):
        assert f'"{field}"' in src, f"CSV export omits {field}"


# ── The page reads them ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expr",
    ["e.actor", "e.action", "e.category", "e.ip_address", "e.level", "e.created_at", "e.event_id"],
)
def test_the_table_reads_the_names_the_api_sends(expr):
    assert expr in _SECTION.read_text(), f"the audit table stopped reading {expr}"


@pytest.mark.parametrize("expr", ["e.username", "e.resource_id", "e.status", "e.ip}", "e.timestamp}"])
def test_the_table_no_longer_reads_names_the_api_never_sent(expr):
    """Each of these resolved to undefined on every row."""
    assert expr not in _SECTION.read_text(), f"{expr} is back — it will render blank"


def test_the_react_key_is_a_field_that_exists():
    """`key={e.id}` was undefined for every row, so React had no stable key."""
    src = _SECTION.read_text()
    assert "key={e.event_id}" in src
    assert "key={e.id}" not in src


def test_the_interface_describes_the_real_response():
    """The old interface documented an endpoint that never existed, which is
    how this survived typechecking."""
    src = _SECTION.read_text()
    start = src.index("interface SystemAuditEntry")
    body = src[start : src.index("}", start)]
    for field in ("event_id", "created_at", "actor", "action", "category", "level", "ip_address"):
        assert field in body, f"SystemAuditEntry is missing {field}"
    for ghost in ("username", "resource_id", "status"):
        assert f"{ghost}:" not in body, f"SystemAuditEntry still declares {ghost}, which the API never sends"


def _tsx_code_only(path: pathlib.Path) -> str:
    """Source with JSX block comments and // line comments stripped.

    Needed because this file documents the defect it fixes, so a plain
    substring search matches the explanation instead of the code. That mistake
    has been made three times in this codebase's history — twice in Python
    tests, once here — which is why it is now a helper rather than a habit.
    """
    import re

    src = path.read_text()
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)  # JSX comments
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # block comments
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)  # line comments
    src = re.sub(r"^\s*\*.*$", "", src, flags=re.M)  # jsdoc continuation lines
    return src


def test_the_dead_column_is_gone_from_the_header():
    """'Resource ID' could only ever render '—'."""
    assert "'Resource ID'" not in _tsx_code_only(_SECTION)


def test_the_comment_stripper_does_not_hide_real_code():
    """Guards the helper above: over-stripping would make the assertion vacuous."""
    code = _tsx_code_only(_SECTION)
    assert "'Category'" in code, "the stripper removed live JSX"
    assert "e.created_at" in code
    # ...and it must actually remove the prose that caused the false failure.
    assert "rendered '—' on every row forever" not in code


def test_the_headers_match_what_the_rows_render():
    """The header list and the cell order must not drift apart again."""
    src = _SECTION.read_text()
    assert "['User', 'Action', 'Category', 'IP', 'Level', 'Timestamp']" in src
