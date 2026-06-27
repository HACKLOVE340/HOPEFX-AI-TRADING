# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the meta layer: the invariant registry (auto-discovery), the
meta-coverage invariants, and the coverage report."""

from __future__ import annotations

import pytest

from invariants import meta, registry

pytestmark = pytest.mark.unit


# ── registry (single source of truth) ────────────────────────────────────────────
def test_registry_discovers_predicates():
    s = registry.registry_summary()
    assert s["modules"] >= 30
    assert s["predicates"] >= 300  # the whole library is inventoried
    assert s["predicates"] == registry.predicate_count()


def test_registry_includes_known_modules():
    by_module = registry.discover_predicates()
    for mod in ("risk", "execution", "meta", "systems", "ai_governance"):
        assert mod in by_module and by_module[mod]
    # infrastructure modules are NOT counted as predicate libraries
    assert "registry" not in by_module
    assert "enforcement" not in by_module


def test_coverage_counts_shape():
    counts = registry.coverage_counts()
    for dim in ("protected", "monitored", "alerted", "recoverable"):
        cov, total = counts[dim]
        assert 0 <= cov <= total == len(registry.CRITICAL_COMPONENTS)


# ── meta-coverage invariants ──────────────────────────────────────────────────────
def test_invariant_alert_recovery_coverage():
    assert meta.verify_invariant_coverage(10, 10) == []
    assert meta.verify_invariant_coverage(9, 10)
    assert meta.verify_alert_coverage(5, 5) == []
    assert meta.verify_alert_coverage(4, 5)
    assert meta.verify_recovery_coverage(3, 3) == []
    assert meta.verify_recovery_coverage(2, 3)
    assert meta.verify_ai_explainability_coverage(100, 100) == []
    assert meta.verify_ai_explainability_coverage(99, 100)


def test_decision_trace_reconstructable():
    full = {
        "decision_id": "d",
        "model_version": "m",
        "prompt_hash": "p",
        "features_hash": "f",
        "data_snapshot": "s",
        "trade_id": "t",
    }
    assert meta.verify_decision_trace(full) == []
    assert meta.verify_decision_trace({"decision_id": "d"})  # missing links
    assert meta.verify_decision_trace({**full, "data_snapshot": ""})  # broken link


# ── coverage report ────────────────────────────────────────────────────────────────
def test_coverage_report_no_invariant_or_alert_gaps():
    from scripts.invariant_coverage import build_report

    report = build_report()
    errors = [g for g in report["gaps"] if g["severity"] == "ERROR"]
    assert errors == [], f"unexpected coverage ERRORs: {errors}"
    assert report["registry"]["predicates"] >= 300
