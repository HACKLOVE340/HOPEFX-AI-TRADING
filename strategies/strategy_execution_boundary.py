from __future__ import annotations

"""Execution boundary for AI-generated strategies.

The existing dynamic registry remains available for compatibility. This guard
is an additive, explicit policy layer that callers can place before any paper
or live activation decision.
"""

from dataclasses import dataclass
from enum import StrEnum

from core.ai_contracts import HumanApproval, ResearchCandidate, StrategyLifecycle


class ExecutionScope(StrEnum):
    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class StrategyExecutionDecision:
    allowed: bool
    scope: ExecutionScope
    reason_code: str
    reason: str


class StrategyExecutionBoundary:
    """Fail-closed policy for strategy candidate execution."""

    def evaluate(
        self,
        candidate: ResearchCandidate,
        scope: ExecutionScope,
        approval: HumanApproval | None = None,
        *,
        research_only: bool = False,
    ) -> StrategyExecutionDecision:
        """Decide whether `candidate` may execute at `scope`.

        `ExecutionScope.RESEARCH` used to return allowed=True before any check,
        and every caller reached this method with that scope by default -- so a
        candidate with no validation, no evidence and no approval was waved
        through, and the caller then set `StrategyState.ACTIVE`. The scope
        argument described what the caller claimed, not what happened.

        Research scope now permits research and nothing else: the caller must
        affirm that no activation follows (`research_only=True`), and the
        candidate must still be in the research lifecycle. A candidate already
        promoted past research is not doing research.
        """
        if scope is ExecutionScope.RESEARCH:
            if not research_only:
                return StrategyExecutionDecision(
                    False,
                    scope,
                    "RESEARCH_LIFECYCLE_REQUIRED",
                    "research scope does not authorise activation; pass research_only=True "
                    "for a run that activates nothing",
                )
            if candidate.lifecycle is not StrategyLifecycle.RESEARCH:
                return StrategyExecutionDecision(
                    False,
                    scope,
                    "RESEARCH_LIFECYCLE_REQUIRED",
                    f"candidate is {candidate.lifecycle}, past research; it cannot run under research scope",
                )
            return StrategyExecutionDecision(True, scope, "RESEARCH_ALLOWED", "research-only execution is permitted")

        if candidate.validation is None or not candidate.validation.passed:
            return StrategyExecutionDecision(
                False, scope, "VALIDATION_REQUIRED", "a passing validation report is required"
            )
        if not candidate._research_evidence_is_verified():
            return StrategyExecutionDecision(
                False,
                scope,
                "RESEARCH_VALIDATION_REQUIRED",
                "replay, walk-forward, leakage, slippage, and model-quality evidence is required",
            )

        if scope is ExecutionScope.PAPER:
            allowed_states = {
                StrategyLifecycle.PAPER_PENDING,
                StrategyLifecycle.PAPER_ACTIVE,
            }
            if candidate.lifecycle not in allowed_states:
                return StrategyExecutionDecision(
                    False,
                    scope,
                    "PAPER_PROMOTION_REQUIRED",
                    "candidate must be explicitly promoted to paper",
                )
            return StrategyExecutionDecision(True, scope, "PAPER_ALLOWED", "paper execution gates passed")

        if candidate.lifecycle is not StrategyLifecycle.LIVE_APPROVED:
            return StrategyExecutionDecision(
                False,
                scope,
                "LIVE_APPROVAL_REQUIRED",
                "live execution requires explicit human approval",
            )
        if approval is None or approval.scope != "live":
            return StrategyExecutionDecision(
                False,
                scope,
                "LIVE_APPROVAL_REQUIRED",
                "live execution requires a live-scoped approval record",
            )
        return StrategyExecutionDecision(True, scope, "LIVE_ALLOWED", "live approval gate passed")


__all__ = ["ExecutionScope", "StrategyExecutionBoundary", "StrategyExecutionDecision"]
