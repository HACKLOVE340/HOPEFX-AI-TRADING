# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""Tests for the client audit-statement endpoint (api/transparency.py).

The statement bundles governance posture + active-model honest metrics + decision
stats + audit-trail availability, and must ALWAYS render (every section is
best-effort, never 500s)."""

from __future__ import annotations

import asyncio

import pytest

from api import transparency as tp

pytestmark = pytest.mark.unit


def test_statement_always_renders_all_sections():
    s = asyncio.run(tp.client_statement())
    for key in ("generated_at", "disclaimer", "governance", "model", "decisions", "audit_trail"):
        assert key in s, f"statement missing section {key}"


def test_statement_reports_governance_posture(monkeypatch):
    monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "monitor")
    monkeypatch.setenv("HOPEFX_INVARIANT_ENFORCE_KINDS", "order_authorization,pre_trade")
    s = asyncio.run(tp.client_statement())
    g = s["governance"]
    assert g["invariant_mode"] == "monitor"
    assert "order_authorization" in g["enforced_checks"]
    assert g["blocking_enabled"] is True


def test_statement_includes_active_model_metrics():
    s = asyncio.run(tp.client_statement())
    m = s["model"]
    # Either the registry resolved (active_version present) or it self-describes an error.
    assert "active_version" in m or "error" in m
    if "active_version" in m:
        assert m["active_version"]  # non-empty


def test_statement_decisions_section_is_safe():
    # With no decision store wired, the section degrades to stats-of-zero, not a crash.
    s = asyncio.run(tp.client_statement())
    d = s["decisions"]
    assert isinstance(d, dict)
    assert "total_decisions" in d or "available" in d


def test_compute_stats_empty_and_nonempty():
    assert tp._compute_stats([])["total_decisions"] == 0
    decisions = [
        {"outcome": "win", "confidence": 0.7, "execution_ms": 10},
        {"outcome": "loss", "confidence": 0.5, "execution_ms": 20},
        {"direction": "skip"},
    ]
    st = tp._compute_stats(decisions)
    assert st["total_decisions"] == 3
    assert st["wins"] == 1 and st["losses"] == 1 and st["skipped"] == 1
    assert st["win_rate"] == 50.0
