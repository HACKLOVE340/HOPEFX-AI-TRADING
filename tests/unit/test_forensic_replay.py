# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the forensic replay engine (decision + failure reconstruction) and
the Grafana invariant dashboard JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forensics import replay

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parent.parent.parent

_FULL_TRACE = {
    "decision_id": "d1",
    "model_version": "m",
    "prompt_hash": "p",
    "features_hash": "f",
    "data_snapshot": "s",
    "trade_id": "t",
}


# ── decision replay ───────────────────────────────────────────────────────────────
def test_decision_clean_is_reconstructable_and_passes():
    rec = {**_FULL_TRACE, "signal": {"confidence": 0.7, "probability": 0.6, "tick_mid": 2000.0, "tick_spread": 0.5}}
    out = replay.replay_decision(rec)
    assert out["reconstructable"] is True
    assert out["would_pass_today"] is True
    assert out["violations"] == []


def test_decision_incomplete_trace_not_reconstructable():
    out = replay.replay_decision({"decision_id": "d2"})
    assert out["reconstructable"] is False
    assert out["trace_gaps"]


def test_decision_bad_signal_would_not_pass():
    rec = {
        **_FULL_TRACE,
        "signal": {"confidence": float("nan"), "probability": 0.6, "tick_mid": 2000.0, "tick_spread": 0.5},
    }
    out = replay.replay_decision(rec)
    assert out["would_pass_today"] is False
    assert out["violations"]


def test_decision_risk_appetite_breach():
    policy = {"limits": {"max_daily_loss_pct": 0.05}, "prohibited": {}, "allowed_jurisdictions": []}
    rec = {**_FULL_TRACE, "risk_state": {"daily_loss_pct": 0.20}, "policy": policy}
    out = replay.replay_decision(rec)
    assert out["would_pass_today"] is False


# ── failure replay (regression checks) ──────────────────────────────────────────────
def test_failure_reconciliation_reproduces():
    rec = {
        "kind": "reconciliation",
        "inputs": {"internal_value": 10_000, "external_value": 8_000, "value_tol": 1.0},
        "expected_violation": True,
    }
    out = replay.replay_failure(rec)
    assert out["reproduced"] is True
    assert out["observed_violation"] is True


def test_failure_fixed_case_does_not_reproduce():
    rec = {
        "kind": "reconciliation",
        "inputs": {"internal_value": 10_000, "external_value": 10_000, "value_tol": 1.0},
        "expected_violation": False,
    }
    out = replay.replay_failure(rec)
    assert out["reproduced"] is True  # observed (no violation) matches expected (no violation)
    assert out["observed_violation"] is False


def test_failure_pre_trade_kind():
    rec = {
        "kind": "pre_trade",
        "inputs": {"signal": {"confidence": float("nan"), "probability": 0.6, "tick_mid": 2000.0, "tick_spread": 0.5}},
        "expected_violation": True,
    }
    assert replay.replay_failure(rec)["reproduced"] is True


def test_failure_unknown_kind_is_reported():
    out = replay.replay_failure({"kind": "bogus", "inputs": {}})
    assert out["reproduced"] is False
    assert "unknown failure kind" in out["error"]


# ── batch + loading ─────────────────────────────────────────────────────────────────
def test_replay_batch_summary():
    records = [
        {
            "kind": "reconciliation",
            "inputs": {"internal_value": 1, "external_value": 9, "value_tol": 0.01},
            "expected_violation": True,
        },
        {"kind": "var", "inputs": {"portfolio_var": 100, "approved_var": 50}, "expected_violation": True},
    ]
    report = replay.replay_batch(records, mode="failure")
    assert report["summary"]["total"] == 2
    assert report["summary"]["reproduced"] == 2


def test_load_records_jsonl(tmp_path):
    p = tmp_path / "recs.jsonl"
    p.write_text('{"kind":"var","inputs":{"portfolio_var":100,"approved_var":50},"expected_violation":true}\n\n')
    recs = replay.load_records(p)
    assert len(recs) == 1 and recs[0]["kind"] == "var"


# ── grafana dashboard ───────────────────────────────────────────────────────────────
def test_grafana_dashboard_valid_json():
    path = _REPO / "monitoring" / "grafana" / "invariant_dashboard.json"
    data = json.loads(path.read_text())
    assert data["uid"] == "hopefx-invariants"
    assert len(data["panels"]) >= 6
    exprs = " ".join(t["expr"] for p in data["panels"] for t in p.get("targets", []))
    for metric in ("hopefx_invariant_mode", "hopefx_invariant_violations_total", "hopefx_invariant_blocked_total"):
        assert metric in exprs
