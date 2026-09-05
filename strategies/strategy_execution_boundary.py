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
    ) -> StrategyExecutionDecision:
        if scope is ExecutionScope.RESEARCH:
            return StrategyExecutionDecision(True, scope, "RESEARCH_ALLOWED", "research execution is permitted")

        if candidate.validation is None or not candidate.validation.passed:
            return StrategyExecutionDecision(False, scope, "VALIDATION_REQUIRED", "a passing validation report is required")
        if not candidate.research_validation_hash.strip():
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
