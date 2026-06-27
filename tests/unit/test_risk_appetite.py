# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the Risk Appetite Framework (policy-as-code) and its enforcement.

Covers the loader/defaults, governance-hygiene validation (unsigned / placeholder
/ overdue), and the enforce_risk_appetite / enforce_policy_governance facades.
"""

from __future__ import annotations

import json

import pytest

from invariants import enforcement as enf
from risk import risk_appetite as ra

pytestmark = pytest.mark.unit


_GOOD_POLICY = {
    "version": "1.2.0",
    "approved_by": "Risk Committee",
    "effective_date": "2026-01-01",
    "review_due": "2026-12-31",
    "limits": {
        "max_daily_loss_pct": 0.05,
        "max_drawdown_pct": 0.10,
        "max_position_pct": 0.05,
        "max_symbol_exposure_usd": 1_000_000,
        "max_leverage": 10,
        "approved_var_usd": 50_000,
    },
    "prohibited": {"symbols": ["MEME"], "jurisdictions_blocked": ["XX"]},
    "allowed_jurisdictions": ["US", "UK"],
}


# ── loader ────────────────────────────────────────────────────────────────────────
def test_load_from_path(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(_GOOD_POLICY))
    loaded = ra.load_risk_appetite(p)
    assert loaded["version"] == "1.2.0"
    assert ra.get_limits(loaded)["max_leverage"] == 10


def test_load_missing_falls_back_to_default(tmp_path):
    loaded = ra.load_risk_appetite(tmp_path / "nope.json")
    assert loaded["version"].endswith("-default")  # safe conservative default


# ── governance hygiene ─────────────────────────────────────────────────────────────
def test_validate_good_policy_clean():
    assert ra.validate_policy(_GOOD_POLICY, today="2026-06-26") == []


def test_validate_flags_unsigned():
    pol = {**_GOOD_POLICY, "approved_by": ""}
    issues = ra.validate_policy(pol, today="2026-06-26")
    assert any("UNSIGNED" in i for i in issues)


def test_validate_flags_placeholder_and_overdue():
    pol = {**_GOOD_POLICY, "approved_by": "CHANGE_ME_x", "review_due": "2025-01-01"}
    issues = ra.validate_policy(pol, today="2026-06-26")
    assert any("placeholder" in i for i in issues)
    assert any("OVERDUE" in i for i in issues)


def test_validate_flags_bad_limits():
    pol = {**_GOOD_POLICY, "limits": {**_GOOD_POLICY["limits"], "max_daily_loss_pct": 5}}
    issues = ra.validate_policy(pol, today="2026-06-26")
    assert any("max_daily_loss_pct" in i for i in issues)


# ── enforcement facade ──────────────────────────────────────────────────────────────
def test_enforce_risk_appetite_within_limits(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    state = {
        "daily_loss_pct": 0.01,
        "drawdown_pct": 0.03,
        "leverage": 5,
        "portfolio_var": 10_000,
        "symbol_exposures": {"XAUUSD": 500_000},
        "traded_symbol": "XAUUSD",
        "jurisdiction": "US",
    }
    assert enf.enforce_risk_appetite(state, _GOOD_POLICY).violations == []


def test_enforce_risk_appetite_catches_breaches(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    state = {"daily_loss_pct": 0.20, "leverage": 50, "traded_symbol": "MEME", "jurisdiction": "XX"}
    r = enf.enforce_risk_appetite(state, _GOOD_POLICY)
    msgs = " ".join(v.message for v in r.violations)
    assert "daily loss" in msgs
    assert "leverage" in msgs
    assert "MEME" in msgs  # prohibited symbol
    assert "XX" in msgs  # blocked jurisdiction


def test_enforce_risk_appetite_jurisdiction_not_allowed(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    r = enf.enforce_risk_appetite({"jurisdiction": "CN"}, _GOOD_POLICY)  # not blocked, but not allowed
    assert r.violations


def test_enforce_policy_governance(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
    assert enf.enforce_policy_governance(_GOOD_POLICY, today="2026-06-26").violations == []
    bad = enf.enforce_policy_governance({**_GOOD_POLICY, "approved_by": ""}, today="2026-06-26")
    assert bad.violations
