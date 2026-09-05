from __future__ import annotations

import pytest

from core.ai_contracts import (
    DecisionEvidence,
    HumanApproval,
    PromotionRequest,
    ResearchCandidate,
    StrategyLifecycle,
    ValidationReport,
)


def candidate(validation: ValidationReport | None = None) -> ResearchCandidate:
    return ResearchCandidate(
        candidate_id="candidate-1",
        name="test_strategy",
        source_hash="source-hash",
        skill_version="skills-v1",
        prompt_hash="prompt-hash",
        data_scope="research-fixture",
        validation=validation,
        research_validation_hash="research-evidence-sha" if validation is not None else "",
    )


def passing_report() -> ValidationReport:
    return ValidationReport(passed=True, checks={"walk_forward": True})


def test_lifecycle_rejects_unvalidated_paper_promotion() -> None:
    research = candidate()
    validated = research.transition(StrategyLifecycle.VALIDATED)
    with pytest.raises(ValueError, match="passing validation"):
        validated.transition(StrategyLifecycle.PAPER_PENDING)


def test_lifecycle_requires_human_approval_for_live_promotion() -> None:
    validated = candidate(passing_report()).transition(StrategyLifecycle.VALIDATED)
    paper = validated.transition(StrategyLifecycle.PAPER_PENDING)
    active = paper.transition(StrategyLifecycle.PAPER_ACTIVE)
    pending = active.transition(StrategyLifecycle.LIVE_PENDING_APPROVAL)

    with pytest.raises(ValueError, match="human approval"):
        pending.transition(StrategyLifecycle.LIVE_APPROVED)


def test_lifecycle_allows_live_promotion_only_with_live_approval() -> None:
    validated = candidate(passing_report()).transition(StrategyLifecycle.VALIDATED)
    paper = validated.transition(StrategyLifecycle.PAPER_PENDING)
    active = paper.transition(StrategyLifecycle.PAPER_ACTIVE)
    pending = active.transition(StrategyLifecycle.LIVE_PENDING_APPROVAL)
    approved = ResearchCandidate(
        **{**pending.__dict__, "human_approval": HumanApproval("operator-1", "live", reason="reviewed")}
    )

    assert approved.transition(StrategyLifecycle.LIVE_APPROVED).lifecycle == StrategyLifecycle.LIVE_APPROVED


def test_validation_and_evidence_hashes_are_reproducible() -> None:
    first = passing_report()
    second = passing_report()
    assert first.report_hash == second.report_hash

    evidence = DecisionEvidence(
        decision_id="decision-1",
        model_version="model-v1",
        model_checksum="model-sha",
        feature_schema_hash="features-sha",
        data_snapshot_at="2026-09-05T00:00:00+00:00",
        regime="ranging",
        calibration_state="calibrated",
        drift_state="clear",
        data_quality_state="valid",
    )
    assert evidence.evidence_hash == DecisionEvidence(**evidence.__dict__).evidence_hash


def test_live_promotion_request_fails_closed_without_approval() -> None:
    request = PromotionRequest(
        candidate_id="candidate-1",
        target=StrategyLifecycle.LIVE_APPROVED,
        requested_by="operator-1",
        evidence_hash="evidence-sha",
    )

    with pytest.raises(ValueError, match="live approval"):
        request.validate()


def test_promotion_request_requires_evidence_and_supported_target() -> None:
    missing_evidence = PromotionRequest(
        candidate_id="candidate-1",
        target=StrategyLifecycle.PAPER_PENDING,
        requested_by="operator-1",
        evidence_hash="",
    )
    with pytest.raises(ValueError, match="requester and evidence"):
        missing_evidence.validate()

    unsupported = PromotionRequest(
        candidate_id="candidate-1",
        target=StrategyLifecycle.RESEARCH,
        requested_by="operator-1",
        evidence_hash="evidence-sha",
    )
    with pytest.raises(ValueError, match="not promotable"):
        unsupported.validate()


def test_lifecycle_cannot_skip_paper_validation_stage() -> None:
    validated = candidate(passing_report()).transition(StrategyLifecycle.VALIDATED)
    with pytest.raises(ValueError, match="invalid lifecycle transition"):
        validated.transition(StrategyLifecycle.PAPER_ACTIVE)
