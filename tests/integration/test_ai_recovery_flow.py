from __future__ import annotations

from core.ai_operations import (
    RecoveryAction,
    RecoveryStatus,
    RepairProposal,
    decide_recovery,
    observe_health,
    should_rollback,
)
from security.ai_repair_sandbox import validate_repair_source


def _report(overall: str) -> dict:
    return {"overall": overall, "components": [{"name": "broker", "status": overall}]}


def test_recovery_flow_escalates_without_mutating_or_approving() -> None:
    observation = observe_health(_report("critical"), "integration-critical")
    proposal = RepairProposal(
        proposal_id="integration-proposal",
        observation_hash=observation.observation_hash,
        diagnosis="broker health probe failed",
        target_paths=("brokers/paper.py",),
    )

    decision = decide_recovery(observation, proposal)
    validation = validate_repair_source("class CandidateRepair:\n    pass\n")

    assert decision.status is RecoveryStatus.AWAITING_APPROVAL
    assert decision.action is RecoveryAction.REQUEST_APPROVAL
    assert validation.accepted is True
    assert proposal.requires_human_approval is True


def test_recovery_flow_rolls_back_when_post_repair_health_regresses() -> None:
    baseline = observe_health(_report("ok"), "integration-baseline")
    post_repair = observe_health(_report("error"), "integration-post")

    decision = should_rollback(baseline, post_repair)

    assert decision.status is RecoveryStatus.BLOCKED
    assert decision.action is RecoveryAction.ROLLBACK
