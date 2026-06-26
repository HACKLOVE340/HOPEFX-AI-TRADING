# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the domain invariant modules (portfolio, reconciliation, derivatives,
systems, compliance, operations, ai_governance).

Each invariant is proven to PASS on valid input and CATCH the violation.
"""

import pytest

from invariants import (
    ai_governance as g,
    compliance as comp,
    derivatives as d,
    operations as ops,
    portfolio as pf,
    reconciliation as rec,
    systems as sysm,
)

pytestmark = pytest.mark.unit


def test_portfolio():
    assert pf.verify_portfolio_state_transition("ACTIVE", "LIQUIDATING") == []
    assert pf.verify_portfolio_state_transition("ACTIVE", "CLOSED")  # must liquidate first
    assert pf.verify_portfolio_value(600, 300, 50, 50, 1000) == []
    assert pf.verify_portfolio_value(600, 300, 50, 50, 1200)
    assert pf.verify_position_sizing(10, 100, 25) == []
    assert pf.verify_position_sizing(40, 100, 25)
    assert pf.verify_diversification(10, 5) == []
    assert pf.verify_diversification(2, 5)
    assert pf.verify_correlation_budget(0.4, 0.8) == []
    assert pf.verify_correlation_budget(0.95, 0.8)
    assert pf.verify_hedging(1.0, 0.9) == []
    assert pf.verify_hedging(0.5, 0.9)
    assert pf.verify_currency_reconciled({"USD": 60, "EUR": 40}, 100) == []
    assert pf.verify_currency_reconciled({"USD": 60, "EUR": 40}, 200)
    assert pf.verify_synthetic_exposure_tracked(100, 100) == []
    assert pf.verify_synthetic_exposure_tracked(100, 80)
    assert pf.verify_capital_efficiency(0.7) == []
    assert pf.verify_capital_efficiency(1.5)


def test_reconciliation():
    assert rec.verify_reconciliation_chain({"broker": 100.0, "ledger": 100.0, "risk": 100.0}) == []
    assert rec.verify_reconciliation_chain({"broker": 100.0, "ledger": 95.0})
    assert rec.verify_custody_reconciled(50, 50) == []
    assert rec.verify_custody_reconciled(50, 49)
    assert rec.verify_double_entry(1000, 1000) == []
    assert rec.verify_double_entry(1000, 999)
    assert rec.verify_ledger_immutable("h", "h") == []
    assert rec.verify_ledger_immutable("h", "x")
    assert rec.verify_treasury_flow(1000, 200, 100, 50, 1150) == []
    assert rec.verify_treasury_flow(1000, 200, 100, 50, 9999)
    assert rec.verify_alpha_attribution(150, {"momentum": 100, "carry": 50}) == []
    assert rec.verify_alpha_attribution(150, {"momentum": 100})
    assert rec.verify_fee_integrity(10, 10) == []
    assert rec.verify_fee_integrity(10, 12)
    assert rec.verify_revenue_leakage(1000, 1000) == []
    assert rec.verify_revenue_leakage(1000, 900)


def test_derivatives():
    assert d.verify_greek_limits({"delta": 100, "vega": 50}, {"delta": 200, "vega": 100}) == []
    assert d.verify_greek_limits({"delta": 300}, {"delta": 200})
    assert d.verify_greek_limits({"delta": -300}, {"delta": 200})  # abs value
    assert d.verify_collateral_sufficient(1000, 1200) == []
    assert d.verify_collateral_sufficient(1000, 800)
    assert d.verify_expiry_handled(5, False) == []
    assert d.verify_expiry_handled(0.5, False)
    assert d.verify_expiry_handled(0.5, True) == []


def test_systems():
    assert sysm.verify_single_leader(1) == []
    assert sysm.verify_single_leader(2)  # split-brain
    assert sysm.verify_single_leader(0)  # leaderless
    assert sysm.verify_quorum(3, 5) == []
    assert sysm.verify_quorum(2, 5)
    assert sysm.verify_exactly_once(10, 10) == []
    assert sysm.verify_exactly_once(11, 10)
    assert sysm.verify_stream_lag(5, 100) == []
    assert sysm.verify_stream_lag(500, 100)
    assert sysm.verify_dead_letter_empty(0) == []
    assert sysm.verify_dead_letter_empty(3)
    assert sysm.verify_cache_fresh(100, 1000) == []
    assert sysm.verify_cache_fresh(5000, 1000)
    assert sysm.verify_cache_version("v1", "v1") == []
    assert sysm.verify_cache_version("v1", "v2")
    assert sysm.verify_acyclic({"a": ["b"], "b": ["c"], "c": []}) == []
    assert sysm.verify_acyclic({"a": ["b"], "b": ["a"]})  # cycle
    assert sysm.verify_no_zombies(0, "agent") == []
    assert sysm.verify_no_zombies(2, "capital")
    assert sysm.verify_blast_radius_contained(1, 10) == []
    assert sysm.verify_blast_radius_contained(8, 10)
    # single point of failure (No Critical Single Point Of Failure)
    assert sysm.verify_no_single_point_of_failure({"db": {"critical": True, "redundancy": 2}}) == []
    assert sysm.verify_no_single_point_of_failure({"db": {"critical": True, "redundancy": 1, "failover": True}}) == []
    assert sysm.verify_no_single_point_of_failure({"db": {"critical": True, "redundancy": 1, "failover": False}})
    assert sysm.verify_no_single_point_of_failure({"x": {"critical": False, "redundancy": 1}}) == []


def test_compliance():
    assert comp.verify_no_wash_trade("a", "b") == []
    assert comp.verify_no_wash_trade("a", "a")
    assert comp.verify_no_spoofing(100, 10, 5) == []
    assert comp.verify_no_spoofing(100, 99, 0)
    assert comp.verify_no_layering(3) == []
    assert comp.verify_no_layering(50)
    assert comp.verify_not_restricted("XAUUSD", {"INSIDERCO"}) == []
    assert comp.verify_not_restricted("INSIDERCO", {"INSIDERCO"})
    assert comp.verify_retention(100, 30, 365) == []
    assert comp.verify_retention(400, 30, 365)
    assert comp.verify_jurisdiction_allowed("US", {"US", "UK"}) == []
    assert comp.verify_jurisdiction_allowed("XX", {"US", "UK"})
    assert comp.verify_chain_of_custody(["a", "b", "c"]) == []
    assert comp.verify_chain_of_custody(["a", None, "c"])
    assert comp.verify_approval_workflow(["risk", "compliance"], ["risk", "compliance"]) == []
    assert comp.verify_approval_workflow(["risk", "compliance"], ["risk"])
    assert comp.verify_no_privilege_escalation(2, 3) == []
    assert comp.verify_no_privilege_escalation(5, 3)


def test_operations():
    assert ops.verify_critical_alert_delivered(True) == []
    assert ops.verify_critical_alert_delivered(False)
    assert ops.verify_critical_alert_acknowledged(10, 60) == []
    assert ops.verify_critical_alert_acknowledged(120, 60)
    assert ops.verify_monitoring_coverage(10, 10) == []
    assert ops.verify_monitoring_coverage(8, 10)
    assert ops.verify_incident_timeline_complete(True, True, True) == []
    assert ops.verify_incident_timeline_complete(True, False, True)
    assert ops.verify_operator_available(1) == []
    assert ops.verify_operator_available(0)
    assert ops.verify_operator_fatigue(8, 12) == []
    assert ops.verify_operator_fatigue(16, 12)
    assert ops.verify_emergency_reversible("liquidate", True) == []
    assert ops.verify_emergency_reversible("liquidate", False)
    assert ops.verify_alert_fatigue(0.1, 0.3) == []
    assert ops.verify_alert_fatigue(0.5, 0.3)
    assert ops.verify_monitors_healthy({"risk": True, "alerts": True}) == []
    assert ops.verify_monitors_healthy({"risk": True, "alerts": False})


def test_ai_governance():
    assert g.verify_determinism("buy", "buy") == []
    assert g.verify_determinism("buy", "sell")
    assert g.verify_reproducible({"x": 1}, {"x": 1}) == []
    assert g.verify_reproducible({"x": 1}, {"x": 2})
    full = dict.fromkeys(("data", "feature", "model", "signal", "decision", "risk_approval", "execution"), 1)
    assert g.verify_decision_lineage(full) == []
    assert g.verify_decision_lineage({"data": 1})
    assert g.verify_prompt_version("h", "h") == []
    assert g.verify_prompt_version("h", "x")
    assert g.verify_context_complete(True) == []
    assert g.verify_context_complete(False)
    assert g.verify_goal_alignment("profit", "profit") == []
    assert g.verify_goal_alignment("self", "profit")
    assert g.verify_optimization_target("sharpe", "sharpe") == []
    assert g.verify_optimization_target("volume", "sharpe")
    assert g.verify_no_shadow_objective({"a"}, {"a"}) == []
    assert g.verify_no_shadow_objective({"a"}, {"a", "b"})
    assert g.verify_alpha_decay(0.5, 0.1) == []
    assert g.verify_alpha_decay(0.05, 0.1)
    assert g.verify_belief_matches_reality(0.1, 0.3) == []
    assert g.verify_belief_matches_reality(0.9, 0.3)
    assert g.verify_calibration(0.7, 0.65) == []
    assert g.verify_calibration(0.95, 0.4)
    assert g.verify_strategy_approved("v1", {"v1"}, True) == []
    assert g.verify_strategy_approved("v9", {"v1"}, False)
    assert g.verify_strategy_identity(0.1, 0.5) == []
    assert g.verify_strategy_identity(0.9, 0.5)
    assert g.verify_no_self_replication(0, False) == []
    assert g.verify_no_self_replication(3, False)
    assert g.verify_autonomous_capital_limit(100, 200) == []
    assert g.verify_autonomous_capital_limit(300, 200)
    assert g.verify_autonomous_strategy_control(False, False) == []
    assert g.verify_autonomous_strategy_control(True, False)
