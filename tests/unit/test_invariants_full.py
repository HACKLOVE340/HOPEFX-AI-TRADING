# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for the extended invariant library (market/risk/ai/execution/governance).

Each invariant is proven to PASS on valid input and CATCH the violation.
"""

import pytest

from invariants import ai, execution, governance, market
from invariants import risk as r

pytestmark = pytest.mark.unit
NAN = float("nan")


# ── market ──────────────────────────────────────────────────────────────────────
def test_market_invariants():
    assert market.verify_orderbook_integrity([(100, 5)], [(101, 5)]) == []
    assert market.verify_orderbook_integrity([(102, 5)], [(101, 5)])  # crossed
    assert market.verify_orderbook_integrity([], [(101, 5)])  # empty side
    assert market.verify_feed_agreement({"a": 100.0, "b": 100.5}) == []
    assert market.verify_feed_agreement({"a": 100.0, "b": 130.0})  # 30% divergence
    assert market.verify_data_freshness(5, 60) == []
    assert market.verify_data_freshness(120, 60)
    assert market.verify_clock_drift(10) == []
    assert market.verify_clock_drift(500)
    assert market.verify_no_future_event(10, 1000) == []
    assert market.verify_no_future_event(2000, 1000)
    assert market.verify_event_sequence(5, 6) == []
    assert market.verify_event_sequence(5, 5)  # replay/gap
    assert market.verify_causal_order(1, 2) == []
    assert market.verify_causal_order(5, 2)
    assert market.verify_market_open(True, halted=False) == []
    assert market.verify_market_open(True, halted=True)
    assert market.verify_symbol_tradeable("XAUUSD", tradeable={"XAUUSD"}) == []
    assert market.verify_symbol_tradeable("DEAD", delisted={"DEAD"})


# ── risk ─────────────────────────────────────────────────────────────────────────
def test_risk_invariants():
    assert r.verify_daily_loss(50, 100) == []
    assert r.verify_daily_loss(150, 100)
    assert r.verify_drawdown(2, 5) == []
    assert r.verify_drawdown(9, 5)
    assert r.verify_var(100, 200) == []
    assert r.verify_var(300, 200)
    assert r.verify_leverage(2, 3) == []
    assert r.verify_leverage(5, 3)
    assert r.verify_margin_buffer(1000, 500) == []
    assert r.verify_margin_buffer(100, 500)
    assert r.verify_liquidation_distance(20, 10) == []
    assert r.verify_liquidation_distance(5, 10)
    assert r.verify_order_liquidity(10, 100) == []
    assert r.verify_order_liquidity(80, 100)  # >25%
    assert r.verify_exposure_limits({"tech": 30}, {"tech": 50}) == []
    assert r.verify_exposure_limits({"tech": 70}, {"tech": 50})
    assert r.verify_concentration(20, 30) == []
    assert r.verify_concentration(40, 30)
    assert r.verify_dependency_concentration(40, 60, "broker") == []
    assert r.verify_dependency_concentration(80, 60, "broker")
    assert r.catastrophic_loss_triggers(2, 50, False, 10, 100) == []
    assert r.catastrophic_loss_triggers(15, 50, False, 10, 100)  # dd kill


# ── ai ───────────────────────────────────────────────────────────────────────────
def test_ai_invariants():
    assert ai.verify_model_approved("abc", "abc", approved=True) == []
    assert ai.verify_model_approved("abc", "xyz", approved=True)  # hash mismatch
    assert ai.verify_model_approved("abc", "abc", approved=False)  # not approved
    assert ai.verify_drift(0.1, 0.3) == []
    assert ai.verify_drift(0.5, 0.3)
    assert ai.verify_confidence(0.8, 0.6) == []
    assert ai.verify_confidence(0.3, 0.6)
    assert ai.verify_confidence(1.5, 0.6)  # out of [0,1]
    assert ai.verify_prediction_entropy(0.9, 0.2) == []
    assert ai.verify_prediction_entropy(0.05, 0.2)
    assert ai.verify_ensemble_diversity([0.3, 0.3, 0.4]) == []
    assert ai.verify_ensemble_diversity([0.8, 0.1, 0.1])
    assert ai.verify_consensus(0.8, 0.6) == []
    assert ai.verify_consensus(0.4, 0.6)
    assert ai.verify_features_finite({"a": 1.0, "b": 2.0}) == []
    assert ai.verify_features_finite({"a": NAN, "b": None})
    assert ai.verify_embedding(384, 384, 1.0) == []
    assert ai.verify_embedding(128, 384, 1.0)
    assert ai.verify_hallucination_guard(True, 1, 5, 0.8, 0.6) == []
    assert ai.verify_hallucination_guard(False, 1, 5, 0.8, 0.6)  # no real data
    assert ai.verify_hallucination_guard(True, 99, 5, 0.8, 0.6)  # stale data
    assert ai.verify_explainable("bought on momentum breakout") == []
    assert ai.verify_explainable(None)
    assert ai.verify_agent_action_authorized("buy", {"buy", "sell"}) == []
    assert ai.verify_agent_action_authorized("wire_funds", {"buy", "sell"})
    assert ai.verify_tool_allowed("market_data", {"market_data"}) == []
    assert ai.verify_tool_allowed("shell", {"market_data"})
    assert ai.verify_reasoning_depth(5, 10) == []
    assert ai.verify_reasoning_depth(50, 10)
    assert ai.verify_agent_authority(2, 5) == []
    assert ai.verify_agent_authority(8, 5)
    assert ai.verify_agent_no_self_escalation(False) == []
    assert ai.verify_agent_no_self_escalation(True)
    assert ai.verify_memory_ownership("pod-1", "pod-1") == []
    assert ai.verify_memory_ownership("pod-2", "pod-1")


# ── execution ────────────────────────────────────────────────────────────────────
def test_execution_invariants():
    assert execution.verify_slippage(100, 100.05, 0.5) == []
    assert execution.verify_slippage(100, 102, 0.5)
    assert execution.verify_latency_budget({"data": 10, "infer": 20}, 100) == []
    assert execution.verify_latency_budget({"data": 200}, 100)
    assert execution.verify_broker_reconciliation(10, 10) == []
    assert execution.verify_broker_reconciliation(10, 9)
    assert execution.verify_reported_matches_actual({"qty": 5}, {"qty": 5}) == []
    assert execution.verify_reported_matches_actual({"qty": 5}, {"qty": 3})
    assert execution.verify_settlement_balanced(1000, 1000) == []
    assert execution.verify_settlement_balanced(1000, 900)
    ok = execution.verify_pre_trade_gate(
        prediction_exists=True,
        confidence_ok=True,
        risk_approved=True,
        capital_available=True,
        market_open=True,
        broker_reachable=True,
        kill_switch_active=False,
    )
    assert ok == []
    blocked = execution.verify_pre_trade_gate(
        prediction_exists=True,
        confidence_ok=True,
        risk_approved=True,
        capital_available=True,
        market_open=True,
        broker_reachable=True,
        kill_switch_active=True,
    )
    assert blocked  # kill switch blocks
    failed = execution.verify_pre_trade_gate(
        prediction_exists=True,
        confidence_ok=True,
        risk_approved=False,
        capital_available=True,
        market_open=True,
        broker_reachable=True,
        kill_switch_active=False,
    )
    assert failed and failed[0].severity == "CONSTITUTIONAL"


# ── governance ──────────────────────────────────────────────────────────────────
def test_governance_invariants():
    assert governance.verify_no_lookahead(1, 2) == []
    assert governance.verify_no_lookahead(2, 1)
    assert governance.verify_no_lookahead(5, 5)  # signal == trade time
    assert governance.verify_no_data_leakage([1, 2], [3, 4]) == []
    assert governance.verify_no_data_leakage([1, 2, 3], [3, 4])
    assert governance.verify_strategy_viable_after_costs(100, 10, 5, 5) == []
    assert governance.verify_strategy_viable_after_costs(10, 5, 5, 5)  # net <= 0
    assert governance.verify_pod_isolation({"positions": [1]}, {"positions": [2]}) == []
    assert governance.verify_pod_isolation({"memory": "x"}, {"memory": "x"})
    assert governance.verify_audit_immutable("h1", "h1") == []
    assert governance.verify_audit_immutable("h1", "h2")
    assert governance.verify_audit_complete({"who": "u", "when": "t", "what": "x", "result": "ok"}) == []
    assert governance.verify_audit_complete({"who": "u"})
    # hash-chain: intact chain passes; a broken link / missing hash is caught
    g = "0" * 64
    chain = [{"prev_hash": g, "hash": "a"}, {"prev_hash": "a", "hash": "b"}, {"prev_hash": "b", "hash": "c"}]
    assert governance.verify_hash_chain(chain) == []
    tampered = [{"prev_hash": g, "hash": "a"}, {"prev_hash": "X", "hash": "b"}]
    assert governance.verify_hash_chain(tampered)
    assert governance.verify_hash_chain([{"prev_hash": g, "hash": ""}])  # missing hash
    # per-AI-action audit completeness (No Hidden AI Action)
    assert governance.verify_action_audited("d1", ["d1", "d2"]) == []
    assert governance.verify_action_audited("d9", ["d1"])
    assert governance.verify_action_audited(None, [])
    assert governance.verify_segregation_of_duties("alice", "bob") == []
    assert governance.verify_segregation_of_duties("alice", "alice")
    assert governance.verify_dual_control(["alice", "bob"]) == []
    assert governance.verify_dual_control(["alice"])
    assert governance.verify_config_unchanged({"a": 1}, {"a": 1}) == []
    assert governance.verify_config_unchanged({"a": 2}, {"a": 1})
    assert governance.verify_deployment_gates({"tests": True, "security": True}) == []
    assert governance.verify_deployment_gates({"tests": True, "security": False})
    assert governance.verify_human_supremacy(10, 5) == []
    assert governance.verify_human_supremacy(5, 10)
