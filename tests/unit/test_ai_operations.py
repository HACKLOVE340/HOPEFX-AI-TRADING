from __future__ import annotations

import pytest

from core.ai_operations import (
    HealthObservation,
    RecoveryAction,
    RecoveryAuditEvent,
    RecoveryStatus,
    RepairProposal,
    decide_recovery,
    observe_health,
    should_rollback,
)


def _report(overall: str) -> dict:
    return {
        "overall": overall,
        "components": [{"name": "broker", "status": overall}],
    }


def test_observation_is_hashed_and_reproducible() -> None:
    first = HealthObservation(
        observation_id="obs-1",
        overall="ok",
        components=({"name": "broker", "status": "ok"},),
        observed_at="2026-09-05T00:00:00+00:00",
    )
    second = HealthObservation(
        observation_id="obs-1",
        overall="ok",
        components=({"name": "broker", "status": "ok"},),
        observed_at="2026-09-05T00:00:00+00:00",
    )

    assert first.observation_hash == second.observation_hash
    assert first.components[0]["name"] == "broker"


def test_healthy_observation_only_observes() -> None:
    observation = observe_health(_report("ok"), "obs-healthy")

    decision = decide_recovery(observation)

    assert decision.status is RecoveryStatus.HEALTHY
    assert decision.action is RecoveryAction.OBSERVE


def test_degraded_observation_requires_diagnosis() -> None:
    observation = observe_health(_report("degraded"), "obs-degraded")

    decision = decide_recovery(observation)

    assert decision.status is RecoveryStatus.DEGRADED
    assert decision.action is RecoveryAction.DIAGNOSE


def test_critical_observation_without_proposal_escalates() -> None:
    observation = observe_health(_report("critical"), "obs-critical")

    decision = decide_recovery(observation)

    assert decision.status is RecoveryStatus.ESCALATED
    assert decision.action is RecoveryAction.ESCALATE
    assert "critical_health_without_proposal" in decision.reason_codes


def test_critical_observation_with_proposal_requires_approval() -> None:
    observation = observe_health(_report("error"), "obs-error")
    proposal = RepairProposal(
        proposal_id="proposal-1",
        observation_hash=observation.observation_hash,
        diagnosis="broker circuit is open",
        target_paths=("brokers/oanda.py",),
    )

    decision = decide_recovery(observation, proposal)

    assert decision.status is RecoveryStatus.AWAITING_APPROVAL
    assert decision.action is RecoveryAction.REQUEST_APPROVAL
    assert decision.proposal_hash == proposal.proposal_hash


def test_audit_event_binds_observation_and_decision_evidence() -> None:
    observation = observe_health(_report("critical"), "obs-audit")
    decision = decide_recovery(observation)
    event = RecoveryAuditEvent(
        event_type="recovery_escalated",
        observation_hash=observation.observation_hash,
        decision_hash=decision.decision_hash,
        actor="ai-operations",
        details=(("component", "broker"),),
    )

    assert event.event_hash
    assert event.observation_hash == observation.observation_hash
    assert event.decision_hash == decision.decision_hash


def test_post_repair_regression_requires_rollback() -> None:
    baseline = observe_health(_report("ok"), "obs-baseline")
    post_repair = observe_health(_report("critical"), "obs-post")

    decision = should_rollback(baseline, post_repair)

    assert decision.status is RecoveryStatus.BLOCKED
    assert decision.action is RecoveryAction.ROLLBACK
    assert decision.reason_codes == ("post_repair_health_regressed",)


def test_contracts_fail_closed_on_missing_evidence() -> None:
    with pytest.raises(ValueError, match="components"):
        HealthObservation(observation_id="obs", overall="ok", components=())

    with pytest.raises(ValueError, match="target paths"):
        RepairProposal(
            proposal_id="proposal",
            observation_hash="hash",
            diagnosis="unknown",
            target_paths=(),
        )
