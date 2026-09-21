# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_audit_payload_decoding.py
==========================================
Five compliance views showed no database rows, and said nothing about it.

AML alerts, sanctions hits, GDPR requests, the consent log and prop-firm risk
breaches all read their payload out of ``AuditLogEntry`` like this::

    meta = json.loads(r.metadata or "{}") if r.metadata else {}

``AuditLogEntry`` has no ``metadata`` column — the payload column is
``data_json``, which is what both writers use. And ``r.metadata`` on a
declarative model is not ``None``: it is SQLAlchemy's ``MetaData`` object, so
the ``if r.metadata`` guard never fires and ``json.loads`` receives it anyway::

    TypeError: the JSON object must be str, bytes or bytearray

Each of the five caught that and returned whatever list it had already built —
usually the Redis-backed one, often empty. So an operator opening the AML queue
saw "no alerts" when the alerts existed in the audit table, on pages whose whole
purpose is regulatory review.

The ``.metadata`` trap is worth stating on its own: it is not a missing-attribute
error, which would be loud. Every declarative model has a truthy ``.metadata``,
so the usual ``or {}`` and ``if x`` defences pass straight through it and the
failure surfaces one call later as a type error about JSON.
"""

from __future__ import annotations

import json

import pytest

from api.superadmin._shared import _audit_payload
from database.models import AuditLogEntry

pytestmark = pytest.mark.unit


def _row(**kw) -> AuditLogEntry:
    base = {
        "sequence_number": 1,
        "level": "COMPLIANCE",
        "category": "SUPERADMIN",
        "actor": "admin",
        "action": "review",
        "hash_chain": "0" * 64,
    }
    base.update(kw)
    return AuditLogEntry(**base)


def test_audit_log_has_no_metadata_column_but_metadata_is_truthy():
    """The premise, and the reason the guards did not catch it."""
    assert "metadata" not in AuditLogEntry.__table__.columns
    assert "data_json" in AuditLogEntry.__table__.columns

    row = _row()
    assert row.metadata, "if this is falsy the original guard would have worked"
    with pytest.raises(TypeError):
        json.loads(row.metadata)


def test_the_payload_is_read_from_data_json():
    row = _row(data_json=json.dumps({"username": "ada", "list_name": "OFAC"}))
    meta = _audit_payload(row)
    assert meta["username"] == "ada"
    assert meta["list_name"] == "OFAC"


def test_a_row_with_no_payload_gives_an_empty_dict():
    assert _audit_payload(_row(data_json=None)) == {}
    assert _audit_payload(_row(data_json="")) == {}


def test_malformed_payloads_do_not_raise():
    """One unreadable row must not empty a compliance queue — which is exactly
    what the old code did, for every row."""
    assert _audit_payload(_row(data_json="{not json")) == {}
    assert _audit_payload(_row(data_json='"a string"')) == {}
    assert _audit_payload(_row(data_json="[1, 2, 3]")) == {}


def test_the_superadmin_writers_envelope_round_trips():
    """``_log_superadmin_action`` stores ``{"detail": ...}`` in data_json."""
    row = _row(data_json=json.dumps({"detail": "halted trading"}))
    assert _audit_payload(row)["detail"] == "halted trading"


@pytest.mark.parametrize(
    "module",
    [
        "api.superadmin.compliance",
        "api.superadmin.gdpr",
        "api.superadmin.risk_management",
    ],
)
def test_no_compliance_reader_still_decodes_metadata(module):
    """Regression guard on the pattern itself, not just this one helper."""
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(module))
    assert ".metadata" not in src, (
        f"{module} still reads .metadata off a model row — that is the MetaData object, not a column"
    )
