# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for phase 1-10 invariant modules (market_structure, replay, drift,
knowledge, ml_pipeline, resilience, multi_agent, economic, security, meta).

Each invariant is proven to PASS on valid input and CATCH the violation.
"""

import pytest

from invariants import (
    drift,
    economic as eco,
    knowledge as kn,
    market_structure as ms,
    meta,
    ml_pipeline as mlp,
    multi_agent as ma,
    replay,
    resilience as res,
    security as sec,
)

pytestmark = pytest.mark.unit


def test_market_structure():
    assert ms.verify_not_halted(False) == []
    assert ms.verify_not_halted(True)
    assert ms.verify_not_halted(False, market_wide_halt=True)
    assert ms.verify_circuit_breaker(3, 7, 13, 20) == []
    assert ms.verify_circuit_breaker(21, 7, 13, 20)
    assert ms.verify_luld_band(100.5, 100, 1) == []
    assert ms.verify_luld_band(110, 100, 1)
    assert ms.verify_auction_state("limit", "opening_auction") == []
    assert ms.verify_auction_state("market_on_continuous", "opening_auction")
    assert ms.verify_venue_eligible("XAUUSD", "lit", {"XAUUSD": {"lit"}}) == []
    assert ms.verify_venue_eligible("XAUUSD", "dark", {"XAUUSD": {"lit"}})
    assert ms.verify_cross_venue_price({"a": 100, "b": 100.5}) == []
    assert ms.verify_cross_venue_price({"a": 100, "b": 110})


def test_replay():
    assert replay.verify_replay_matches({"x": 1}, {"x": 1}) == []
    assert replay.verify_replay_matches({"x": 1}, {"x": 2})
    assert replay.verify_replay_within_tolerance(100.0, 100.0001, 0.01) == []
    assert replay.verify_replay_within_tolerance(100.0, 105.0, 0.01)
    assert replay.verify_historical_recoverable(True) == []
    assert replay.verify_historical_recoverable(False)
    assert replay.verify_deleted_stays_deleted([1, 2], [3, 4]) == []
    assert replay.verify_deleted_stays_deleted([1, 2], [2, 3])
    assert replay.verify_event_replay_idempotent("s", "s") == []
    assert replay.verify_event_replay_idempotent("s1", "s2")
    assert replay.verify_snapshot_consistent(1000, 1000) == []
    assert replay.verify_snapshot_consistent(1000, 900)


def test_drift():
    assert drift.verify_no_value_drift(10, 10, 0.1, "x") == []
    assert drift.verify_no_value_drift(12, 10, 0.1, "x")
    assert drift.verify_risk_appetite_stable("moderate", "moderate") == []
    assert drift.verify_risk_appetite_stable("aggressive", "moderate")
    assert drift.verify_allocation_policy_stable({"a": 1}, {"a": 1}) == []
    assert drift.verify_allocation_policy_stable({"a": 2}, {"a": 1})
    assert drift.verify_governance_consistent("v1", "v1") == []
    assert drift.verify_governance_consistent("v2", "v1")
    assert drift.verify_compliance_current("2026Q2", "2026Q2") == []
    assert drift.verify_compliance_current("2025Q1", "2026Q2")
    assert drift.verify_constitution_version("c1", "c1") == []
    assert drift.verify_constitution_version("c2", "c1")
    assert drift.verify_incentive_alignment(True) == []
    assert drift.verify_incentive_alignment(False)


def test_knowledge():
    assert kn.verify_retrieval([1], {1, 2}, {"sec"}, ["sec"]) == []
    assert kn.verify_retrieval([9], {1, 2}, {"sec"}, ["sec"])  # missing doc
    assert kn.verify_retrieval([1], {1}, {"sec"}, ["evil"])  # untrusted source
    assert kn.verify_context_freshness(10, 60) == []
    assert kn.verify_context_freshness(120, 60)
    assert kn.verify_no_orphan_entities({1, 2}, {1}) == []
    assert kn.verify_no_orphan_entities({1, 2}, {3})
    assert kn.verify_no_contradictory_facts(0) == []
    assert kn.verify_no_contradictory_facts(2)
    assert kn.verify_memory_age(10, 100) == []
    assert kn.verify_memory_age(200, 100)
    assert kn.verify_no_memory_conflict(False) == []
    assert kn.verify_no_memory_conflict(True)


def test_ml_pipeline():
    assert mlp.verify_feature_schema({"a": 1, "b": 2}, {"a", "b"}) == []
    assert mlp.verify_feature_schema({"a": 1}, {"a", "b"})  # missing col
    assert mlp.verify_online_offline_parity(1.0, 1.0) == []
    assert mlp.verify_online_offline_parity(1.0, 2.0)
    assert mlp.verify_dataset_complete(1000, 500, 0.01) == []
    assert mlp.verify_dataset_complete(100, 500, 0.01)
    assert mlp.verify_training_reproducible(True, True) == []
    assert mlp.verify_training_reproducible(False, True)
    full = {"owner": "u", "training_record": "t", "validation_record": "v", "approved": True}
    assert mlp.verify_model_lineage(full) == []
    assert mlp.verify_model_lineage({"owner": "u"})
    assert mlp.verify_model_signed("sig") == []
    assert mlp.verify_model_signed("")
    assert mlp.verify_inference_cost(5, 10) == []
    assert mlp.verify_inference_cost(20, 10)
    assert mlp.verify_gpu_allocation(2, 4) == []
    assert mlp.verify_gpu_allocation(8, 4)


def test_resilience():
    assert res.verify_backup_recent(5, 24) == []
    assert res.verify_backup_recent(48, 24)
    assert res.verify_backup_integrity(True) == []
    assert res.verify_backup_integrity(False)
    assert res.verify_restore_tested(True, 5, 30) == []
    assert res.verify_restore_tested(False, 5, 30)
    assert res.verify_failover_ready(2, 1) == []
    assert res.verify_failover_ready(0, 1)
    assert res.verify_multi_region(2, 2) == []
    assert res.verify_multi_region(1, 2)
    assert res.verify_recovery_path_exists("db", True, True) == []
    assert res.verify_recovery_path_exists("db", False, True)
    assert res.verify_chaos_survival({"broker_offline": True, "db_offline": True}) == []
    assert res.verify_chaos_survival({"broker_offline": True, "db_offline": False})
    assert res.verify_recovery_sla(30, 60) == []
    assert res.verify_recovery_sla(120, 60)


def test_multi_agent():
    assert ma.verify_no_deadlock({"a": "b", "b": "c"}) == []
    assert ma.verify_no_deadlock({"a": "b", "b": "a"})
    assert ma.verify_no_collusion(0) == []
    assert ma.verify_no_collusion(3)
    assert ma.verify_conflict_rate(0.1, 0.3) == []
    assert ma.verify_conflict_rate(0.5, 0.3)
    assert ma.verify_resource_fairness([10, 10, 10]) == []
    assert ma.verify_resource_fairness([90, 5, 5])
    assert ma.verify_no_circular_delegation({"a": "b"}) == []
    assert ma.verify_no_circular_delegation({"a": "b", "b": "a"})
    assert ma.verify_emergent_behavior(0.1, 0.8) == []
    assert ma.verify_emergent_behavior(0.95, 0.8)
    assert ma.verify_agent_count_bounded(5, 10) == []
    assert ma.verify_agent_count_bounded(50, 10)


def test_economic():
    assert eco.verify_economic_equilibrium(100, 50, 30, 10, 70) == []  # 100-50+30-10=70
    assert eco.verify_economic_equilibrium(100, 50, 30, 10, 999)
    assert eco.verify_report_accurate(100, 100) == []
    assert eco.verify_report_accurate(100, 80)
    assert eco.verify_fund_segregation({"c1": 100.0}, commingled=False) == []
    assert eco.verify_fund_segregation({"c1": 100.0}, commingled=True)
    assert eco.verify_fund_segregation({"c1": -1.0}, commingled=False)
    assert eco.verify_redemption_fairness(100, 100, 200) == []
    assert eco.verify_redemption_fairness(100, 50, 200)  # short-paid despite funds
    assert eco.verify_within_contract_limits(50, 100, "drawdown") == []
    assert eco.verify_within_contract_limits(150, 100, "drawdown")
    assert eco.verify_cost_growth(5, 20) == []
    assert eco.verify_cost_growth(50, 20)


def test_security():
    assert sec.verify_no_exposed_secret("realsecretvalue") == []
    assert sec.verify_no_exposed_secret("")
    assert sec.verify_no_exposed_secret("CHANGE_ME_now")
    assert sec.verify_no_exposed_secret("your_api_key_here")
    assert sec.verify_secret_rotation(10, 90) == []
    assert sec.verify_secret_rotation(200, 90)
    assert sec.verify_secret_usage("svc-a", {"svc-a"}) == []
    assert sec.verify_secret_usage("attacker", {"svc-a"})
    assert sec.verify_artifact_signed(["sig1", "sig2"]) == []
    assert sec.verify_artifact_signed(["sig1", ""])
    assert sec.verify_data_provenance(True) == []
    assert sec.verify_data_provenance(False)
    assert sec.verify_trust_boundary("agent->tool", True) == []
    assert sec.verify_trust_boundary("agent->tool", False)
    assert sec.verify_prompt_not_injected(False) == []
    assert sec.verify_prompt_not_injected(True)
    assert sec.verify_input_not_poisoned(0.1, 0.8) == []
    assert sec.verify_input_not_poisoned(0.95, 0.8)


def test_meta():
    assert meta.verify_observed_matches_actual(5, 5) == []
    assert meta.verify_observed_matches_actual(5, 7)
    assert meta.verify_platform_identity(["trade", "report"], {"trade", "report"}) == []
    assert meta.verify_platform_identity(["trade", "self_modify"], {"trade"})
    assert meta.verify_anomaly_detection_operational(True) == []
    assert meta.verify_anomaly_detection_operational(False)
    assert meta.verify_human_can_stop({"trading": True, "agents": True}) == []
    assert meta.verify_human_can_stop({"trading": True, "agents": False})
    assert meta.verify_invariant_engine_healthy(True) == []
    assert meta.verify_invariant_engine_healthy(False)
    assert meta.verify_constitution([]) == []
    from invariants import constitution as c

    assert meta.verify_constitution(c.verify_pnl_reconciliation(1, 1, 999))
    ok = meta.verify_five_master_guarantees(
        nothing_unnoticed=True,
        nothing_unbounded=True,
        nothing_unrecoverable=True,
        nothing_unaccounted=True,
        human_in_control=True,
    )
    assert ok == []
    bad = meta.verify_five_master_guarantees(
        nothing_unnoticed=True,
        nothing_unbounded=True,
        nothing_unrecoverable=True,
        nothing_unaccounted=True,
        human_in_control=False,
    )
    assert bad
