from __future__ import annotations

"""Auditable, additive contracts for AI-generated trading candidates.

These contracts do not replace existing brains, strategies, or execution paths.
They provide a fail-closed boundary around research, paper, and live promotion.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class StrategyLifecycle(StrEnum):
    RESEARCH = "research"
    VALIDATED = "validated"
    PAPER_PENDING = "paper_pending"
    PAPER_ACTIVE = "paper_active"
    LIVE_PENDING_APPROVAL = "live_pending_approval"
    LIVE_APPROVED = "live_approved"
    RETIRED = "retired"


_ALLOWED_TRANSITIONS: dict[StrategyLifecycle, frozenset[StrategyLifecycle]] = {
    StrategyLifecycle.RESEARCH: frozenset({StrategyLifecycle.VALIDATED, StrategyLifecycle.RETIRED}),
    StrategyLifecycle.VALIDATED: frozenset(
        {StrategyLifecycle.PAPER_PENDING, StrategyLifecycle.RETIRED}
    ),
    StrategyLifecycle.PAPER_PENDING: frozenset(
        {StrategyLifecycle.PAPER_ACTIVE, StrategyLifecycle.RETIRED}
    ),
    StrategyLifecycle.PAPER_ACTIVE: frozenset(
        {StrategyLifecycle.LIVE_PENDING_APPROVAL, StrategyLifecycle.RETIRED}
    ),
    StrategyLifecycle.LIVE_PENDING_APPROVAL: frozenset(
        {StrategyLifecycle.LIVE_APPROVED, StrategyLifecycle.RETIRED}
    ),
    StrategyLifecycle.LIVE_APPROVED: frozenset({StrategyLifecycle.RETIRED}),
    StrategyLifecycle.RETIRED: frozenset(),
}


def _canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for audit records."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    checks: dict[str, bool]
    metrics: dict[str, float] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not self.checks:
            raise ValueError("validation report must include deterministic checks")
        if not self.passed and not self.errors:
            raise ValueError("failed validation reports require explicit errors")
        if not self.report_hash:
            payload = {
                "passed": self.passed,
                "checks": self.checks,
                "metrics": self.metrics,
                "errors": self.errors,
            }
            object.__setattr__(self, "report_hash", _canonical_hash(payload))


@dataclass(frozen=True)
class HumanApproval:
    approver_id: str
    scope: str
    approved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""
    approval_hash: str = ""

    def __post_init__(self) -> None:
        if not self.approver_id.strip():
            raise ValueError("approver_id is required")
        if self.scope not in {"paper", "live"}:
            raise ValueError("approval scope must be paper or live")
        if self.scope == "live" and not self.reason.strip():
            raise ValueError("live approval requires a reason")
        if not self.approval_hash:
            payload = {
                "approver_id": self.approver_id,
                "scope": self.scope,
                "approved_at": self.approved_at,
                "reason": self.reason,
            }
            object.__setattr__(self, "approval_hash", _canonical_hash(payload))


@dataclass(frozen=True)
class DecisionEvidence:
    decision_id: str
    model_version: str
    model_checksum: str
    feature_schema_hash: str
    data_snapshot_at: str
    regime: str
    calibration_state: str
    drift_state: str
    data_quality_state: str
    reason_codes: tuple[str, ...] = ()
    evidence_hash: str = ""

    def __post_init__(self) -> None:
        required = {
            "decision_id": self.decision_id,
            "model_version": self.model_version,
            "model_checksum": self.model_checksum,
            "feature_schema_hash": self.feature_schema_hash,
            "data_snapshot_at": self.data_snapshot_at,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"decision evidence missing: {', '.join(missing)}")
        if not self.evidence_hash:
            payload = asdict(self)
            payload.pop("evidence_hash")
            object.__setattr__(self, "evidence_hash", _canonical_hash(payload))


@dataclass(frozen=True)
class ResearchCandidate:
    candidate_id: str
    name: str
    source_hash: str
    skill_version: str
    prompt_hash: str
    data_scope: str
    lifecycle: StrategyLifecycle = StrategyLifecycle.RESEARCH
    validation: ValidationReport | None = None
    research_validation_hash: str = ""
    human_approval: HumanApproval | None = None

    def transition(self, target: StrategyLifecycle) -> ResearchCandidate:
        if target not in _ALLOWED_TRANSITIONS[self.lifecycle]:
            raise ValueError(f"invalid lifecycle transition: {self.lifecycle} -> {target}")
        if target in {
            StrategyLifecycle.PAPER_PENDING,
            StrategyLifecycle.LIVE_PENDING_APPROVAL,
        } and (self.validation is None or not self.validation.passed):
            raise ValueError("promotion requires a passing validation report")
        if target in {
            StrategyLifecycle.PAPER_PENDING,
            StrategyLifecycle.LIVE_PENDING_APPROVAL,
        } and not self.research_validation_hash.strip():
            raise ValueError("promotion requires replay and research validation evidence")
        if target == StrategyLifecycle.LIVE_APPROVED and (
            self.human_approval is None or self.human_approval.scope != "live"
        ):
            raise ValueError("live promotion requires explicit human approval")
        return ResearchCandidate(
            candidate_id=self.candidate_id,
            name=self.name,
            source_hash=self.source_hash,
            skill_version=self.skill_version,
            prompt_hash=self.prompt_hash,
            data_scope=self.data_scope,
            lifecycle=target,
            validation=self.validation,
            research_validation_hash=self.research_validation_hash,
            human_approval=self.human_approval,
        )


@dataclass(frozen=True)
class PromotionRequest:
    candidate_id: str
    target: StrategyLifecycle
    requested_by: str
    evidence_hash: str
    approval: HumanApproval | None = None

    def validate(self) -> None:
        if self.target not in {
            StrategyLifecycle.PAPER_PENDING,
            StrategyLifecycle.LIVE_PENDING_APPROVAL,
            StrategyLifecycle.LIVE_APPROVED,
        }:
            raise ValueError("promotion request target is not promotable")
        if not self.requested_by.strip() or not self.evidence_hash.strip():
            raise ValueError("promotion request requires requester and evidence")
        if self.target == StrategyLifecycle.LIVE_APPROVED and (
            self.approval is None or self.approval.scope != "live"
        ):
            raise ValueError("live approval requires a live-scoped human approval")


__all__ = [
    "DecisionEvidence",
    "HumanApproval",
    "PromotionRequest",
    "ResearchCandidate",
    "StrategyLifecycle",
    "ValidationReport",
]
