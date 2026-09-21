# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""Tests for the runtime TrustScorer (elite-architecture #7) and its integration
with the trust-allocation invariant."""

from __future__ import annotations

import pytest

from invariants import enforcement as enf
from ml.trust_scorer import TrustScorer

pytestmark = pytest.mark.unit


def test_prior_and_validation():
    s = TrustScorer(prior=0.5)
    assert s.score("ml_model") == 0.5  # unseen → prior
    with pytest.raises(ValueError):
        TrustScorer(alpha=0)
    with pytest.raises(ValueError):
        TrustScorer(prior=1.5)


def test_record_moves_toward_outcome():
    s = TrustScorer(alpha=0.5, prior=0.5)
    after_good = s.record("m", correct=True)
    assert after_good > 0.5  # good call raises trust
    s2 = TrustScorer(alpha=0.5, prior=0.5)
    after_bad = s2.record("m", correct=False)
    assert after_bad < 0.5  # bad call lowers trust


def test_scores_stay_in_unit_interval():
    s = TrustScorer(alpha=0.9)
    for _ in range(50):
        s.record("good", correct=True)
        s.record("bad", correct=False)
    assert 0.0 <= s.score("bad") <= s.score("good") <= 1.0
    assert s.score("good") > 0.9 and s.score("bad") < 0.1


def test_signal_path_and_garbage_ignored():
    s = TrustScorer(alpha=0.5, prior=0.5)
    s.record("m", signal=1.0)
    assert s.score("m") > 0.5
    before = s.score("m")
    s.record("m", signal=float("nan"))  # garbage ignored
    assert s.score("m") == before


def test_allocation_is_trust_weighted_and_floored():
    s = TrustScorer(prior=0.5, floor=0.4)
    s._scores.update({"trusted": 0.9, "ok": 0.6, "distrusted": 0.2})
    alloc = s.allocate(capital=10_000, subsystems=["trusted", "ok", "distrusted"])
    assert alloc["distrusted"]["capital"] == 0.0  # below floor → nothing
    assert alloc["trusted"]["capital"] > alloc["ok"]["capital"] > 0  # more trust → more capital
    assert abs(sum(a["capital"] for a in alloc.values()) - 10_000) < 1e-6  # fully allocated


def test_allocation_passes_the_trust_invariant(monkeypatch):
    """The allocation the scorer produces must satisfy enforce_trust_allocation."""
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    s = TrustScorer(prior=0.5, floor=0.5)
    s._scores.update({"ml": 0.9, "rules": 0.7})
    alloc = s.allocate(capital=50_000, subsystems=["ml", "rules"])
    r = enf.enforce_trust_allocation(alloc, floor=0.5)
    assert r.violations == []  # no trust/capital inversion, no distrusted funded
