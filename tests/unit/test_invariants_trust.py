# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for AI subsystem trust scoring (Elite Architecture requirement #7):
trust score validity, distrust floor, no trust/capital inversion, and the
enforce_trust_allocation façade."""

import pytest

from invariants import ai
from invariants import enforcement as enf

pytestmark = pytest.mark.unit


def test_trust_score_range():
    assert ai.verify_trust_score(0.0) == []
    assert ai.verify_trust_score(1.0) == []
    assert ai.verify_trust_score(0.73) == []
    assert ai.verify_trust_score(1.5)            # >1
    assert ai.verify_trust_score(-0.1)           # <0
    assert ai.verify_trust_score(float("nan"))   # NaN


def test_trust_floor():
    assert ai.verify_trust_floor(0.8, 1000, floor=0.5) == []   # trusted → ok
    assert ai.verify_trust_floor(0.2, 0, floor=0.5) == []      # distrusted but no capital → ok
    assert ai.verify_trust_floor(0.2, 1000, floor=0.5)         # distrusted + capital → breach


def test_no_trust_capital_inversion():
    ok = {"signal": {"trust": 0.9, "capital": 1000}, "risk": {"trust": 0.6, "capital": 400}}
    assert ai.verify_trust_weighted_allocation(ok) == []
    bad = {"signal": {"trust": 0.9, "capital": 100}, "exec": {"trust": 0.4, "capital": 900}}
    assert ai.verify_trust_weighted_allocation(bad)            # lower trust got more capital


def test_enforce_trust_allocation(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    ok = {"signal": {"trust": 0.9, "capital": 1000}, "risk": {"trust": 0.7, "capital": 500}}
    assert enf.enforce_trust_allocation(ok).violations == []
    bad = {"signal": {"trust": 0.9, "capital": 100}, "exec": {"trust": 0.3, "capital": 900}}
    r = enf.enforce_trust_allocation(bad, floor=0.5)
    assert r.violations                                        # floor breach + inversion
