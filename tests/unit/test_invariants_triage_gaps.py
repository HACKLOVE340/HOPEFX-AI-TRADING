# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the new predicates closing top gaps from the Master Invariant Triage
(docs/MASTER_INVARIANT_TRIAGE.md): JWT algorithm allow-list (#42), money-column
precision (#66), enum-value constraint (#68), email format (#70)."""

import pytest

from invariants import platform_auth as auth
from invariants import platform_data as pdata

pytestmark = pytest.mark.unit


# ── #42 JWT algorithm allow-list ──────────────────────────────────────────────────
def test_token_algorithm():
    assert auth.verify_token_algorithm("HS256") == []
    assert auth.verify_token_algorithm("RS256") == []
    assert auth.verify_token_algorithm("none")            # unsigned forbidden
    assert auth.verify_token_algorithm("None")            # case-insensitive
    assert auth.verify_token_algorithm("")                # empty forbidden
    assert auth.verify_token_algorithm("HS384")           # not in default allow-list
    assert auth.verify_token_algorithm("HS384", allowed=("HS384",)) == []


# ── #66 monetary column precision ─────────────────────────────────────────────────
def test_money_precision():
    assert pdata.verify_money_precision("price", "NUMERIC(18,8)") == []
    assert pdata.verify_money_precision("balance", "DECIMAL(20,2)") == []
    assert pdata.verify_money_precision("price", "FLOAT")          # binary float
    assert pdata.verify_money_precision("price", "DOUBLE PRECISION")
    assert pdata.verify_money_precision("price", "REAL")


# ── #68 enum-value constraint ─────────────────────────────────────────────────────
def test_enum_value():
    allowed = {"NEW", "FILLED", "CANCELLED"}
    assert pdata.verify_enum_value("status", "FILLED", allowed) == []
    assert pdata.verify_enum_value("status", "BOGUS", allowed)
    assert pdata.verify_enum_value("status", "FILLED", set()) == []   # no enum declared → skip


# ── #70 email format ──────────────────────────────────────────────────────────────
def test_email_format():
    assert pdata.verify_email_format("a@b.com") == []
    assert pdata.verify_email_format("user.name@sub.domain.io") == []
    assert pdata.verify_email_format("not-an-email")
    assert pdata.verify_email_format("a@b")               # no TLD
    assert pdata.verify_email_format("")                  # empty
    assert pdata.verify_email_format("a b@c.com")         # space
