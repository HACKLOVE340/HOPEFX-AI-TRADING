from __future__ import annotations

from core.ai_contracts import HumanApproval, ResearchCandidate, StrategyLifecycle, ValidationReport
from strategies.strategy_execution_boundary import ExecutionScope, StrategyExecutionBoundary


def make_candidate() -> ResearchCandidate:
    return ResearchCandidate(
        candidate_id="candidate-1",
        name="research_strategy",
        source_hash="source",
        skill_version="skill-v1",
        prompt_hash="prompt",
        data_scope="fixture",
        lifecycle=StrategyLifecycle.PAPER_ACTIVE,
        validation=ValidationReport(passed=True, checks={"walk_forward": True}),
        research_validation_hash="research-evidence-sha",
    )


def test_research_is_allowed_without_promotion() -> None:
    candidate = make_candidate()
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.RESEARCH)
    assert decision.allowed is True
    assert decision.reason_code == "RESEARCH_ALLOWED"


def test_paper_requires_explicit_paper_state() -> None:
    candidate = make_candidate()
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.PAPER)
    assert decision.allowed is True


def test_live_fails_closed_without_approval() -> None:
    candidate = make_candidate()
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.LIVE)
    assert decision.allowed is False
    assert decision.reason_code == "LIVE_APPROVAL_REQUIRED"


def test_live_requires_live_scoped_approval() -> None:
    candidate = ResearchCandidate(
        **{**make_candidate().__dict__, "lifecycle": StrategyLifecycle.LIVE_APPROVED}
    )
    paper_approval = HumanApproval("operator-1", "paper")
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.LIVE, paper_approval)
    assert decision.allowed is False
    assert decision.reason_code == "LIVE_APPROVAL_REQUIRED"

    live_approval = HumanApproval("operator-1", "live", reason="reviewed")
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.LIVE, live_approval)
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_ALLOWED"


def test_invalid_candidate_fails_closed_for_paper() -> None:
    candidate = ResearchCandidate(
        **{
            **make_candidate().__dict__,
            "validation": ValidationReport(
                passed=False,
                checks={"walk_forward": False},
                errors=("leakage detected",),
            ),
        }
    )
    decision = StrategyExecutionBoundary().evaluate(candidate, ExecutionScope.PAPER)
    assert decision.allowed is False
    assert decision.reason_code == "VALIDATION_REQUIRED"
