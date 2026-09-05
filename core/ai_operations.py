from __future__ import annotations

"""Additive AI operations control plane for diagnosis and safe repair planning.

This module deliberately plans and validates recovery actions without mutating
code, broker state, credentials, or live trading. Existing health, self-healing,
and rollback systems remain the execution owners.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from core.ai_contracts import _canonical_hash


class RecoveryAction(StrEnum):
    OBSERVE = "observe"
    DIAGNOSE = "diagnose"
    PROPOSE_REPAIR = "propose_repair"
    VALIDATE_REPAIR = "validate_repair"
    REQUEST_APPROVAL = "request_approval"
    ROLLBACK = "rollback"
    ESCALATE = "escalate"


class RecoveryStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class HealthObservation:
    observation_id: str
    overall: str
    components: tuple[dict[str, Any], ...]
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observation_hash: str = ""

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id is required")
        if not self.components:
            raise ValueError("health observation requires components")
        if not self.observation_hash:
            payload = {
                "observation_id": self.observation_id,
                "overall": self.overall,
                "components": self.components,
                "observed_at": self.observed_at,
            }
            object.__setattr__(self, "observation_hash", _canonical_hash(payload))


@dataclass(frozen=True)
class RepairProposal:
    proposal_id: str
    observation_hash: str
    diagnosis: str
    target_paths: tuple[str, ...]
    action: RecoveryAction = RecoveryAction.PROPOSE_REPAIR
    requires_human_approval: bool = True
    proposed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    proposal_hash: str = ""

    def __post_init__(self) -> None:
        if not self.proposal_id.strip() or not self.observation_hash.strip():
            raise ValueError("repair proposal requires identifiers and observation evidence")
        if self.action not in {
            RecoveryAction.PROPOSE_REPAIR,
            RecoveryAction.VALIDATE_REPAIR,
            RecoveryAction.ROLLBACK,
            RecoveryAction.ESCALATE,
        }:
            raise ValueError("invalid repair proposal action")
        if not self.target_paths:
            raise ValueError("repair proposal requires target paths")
        if not self.proposal_hash:
            payload = {
                "proposal_id": self.proposal_id,
                "observation_hash": self.observation_hash,
                "diagnosis": self.diagnosis,
                "target_paths": self.target_paths,
                "action": self.action,
                "requires_human_approval": self.requires_human_approval,
                "proposed_at": self.proposed_at,
            }
            object.__setattr__(self, "proposal_hash", _canonical_hash(payload))


@dataclass(frozen=True)
class RecoveryDecision:
    status: RecoveryStatus
    action: RecoveryAction
    reason_codes: tuple[str, ...]
    observation_hash: str
    proposal_hash: str | None = None
    decision_hash: str = ""

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("recovery decision requires reason codes")
        if not self.observation_hash.strip():
            raise ValueError("recovery decision requires observation evidence")
        if not self.decision_hash:
            payload = {
                "status": self.status,
                "action": self.action,
                "reason_codes": self.reason_codes,
                "observation_hash": self.observation_hash,
                "proposal_hash": self.proposal_hash,
            }
            object.__setattr__(self, "decision_hash", _canonical_hash(payload))


def should_rollback(baseline: HealthObservation, post_repair: HealthObservation) -> RecoveryDecision:
    """Fail closed when a candidate repair worsens health or loses evidence."""
    if baseline.overall not in {"ok", "healthy"}:
        raise ValueError("rollback comparison requires a healthy baseline")
    if post_repair.overall in {"critical", "error"}:
        return RecoveryDecision(
            status=RecoveryStatus.BLOCKED,
            action=RecoveryAction.ROLLBACK,
            reason_codes=("post_repair_health_regressed",),
            observation_hash=post_repair.observation_hash,
        )
    return RecoveryDecision(
        status=RecoveryStatus.HEALTHY,
        action=RecoveryAction.OBSERVE,
        reason_codes=("post_repair_health_not_regressed",),
        observation_hash=post_repair.observation_hash,
    )


def observe_health(report: Any, observation_id: str) -> HealthObservation:
    """Convert the existing HealthReport into immutable AI evidence."""
    if hasattr(report, "to_dict"):
        report = report.to_dict()
    components = tuple(report.get("components", ()))
    return HealthObservation(
        observation_id=observation_id,
        overall=str(report.get("overall", "unknown")),
        components=components,
    )


@dataclass(frozen=True)
class RecoveryAuditEvent:
    event_type: str
    observation_hash: str
    decision_hash: str
    actor: str
    details: tuple[tuple[str, str], ...] = ()
    event_hash: str = ""

    def __post_init__(self) -> None:
        if not self.event_type.strip() or not self.actor.strip():
            raise ValueError("audit event requires event type and actor")
        if not self.observation_hash.strip() or not self.decision_hash.strip():
            raise ValueError("audit event requires evidence hashes")
        if not self.event_hash:
            payload = {
                "event_type": self.event_type,
                "observation_hash": self.observation_hash,
                "decision_hash": self.decision_hash,
                "actor": self.actor,
                "details": self.details,
            }
            object.__setattr__(self, "event_hash", _canonical_hash(payload))


def decide_recovery(observation: HealthObservation, proposal: RepairProposal | None = None) -> RecoveryDecision:
    """Return a fail-closed recovery decision; never applies a repair."""
    if observation.overall in {"critical", "error"}:
        if proposal is None:
            return RecoveryDecision(
                status=RecoveryStatus.ESCALATED,
                action=RecoveryAction.ESCALATE,
                reason_codes=("critical_health_without_proposal",),
                observation_hash=observation.observation_hash,
            )
        return RecoveryDecision(
            status=RecoveryStatus.AWAITING_APPROVAL,
            action=RecoveryAction.REQUEST_APPROVAL,
            reason_codes=("critical_health_requires_review",),
            observation_hash=observation.observation_hash,
            proposal_hash=proposal.proposal_hash,
        )
    if observation.overall in {"degraded", "warning"}:
        return RecoveryDecision(
            status=RecoveryStatus.DEGRADED,
            action=RecoveryAction.DIAGNOSE,
            reason_codes=("degraded_health_requires_diagnosis",),
            observation_hash=observation.observation_hash,
        )
    return RecoveryDecision(
        status=RecoveryStatus.HEALTHY,
        action=RecoveryAction.OBSERVE,
        reason_codes=("health_within_bounds",),
        observation_hash=observation.observation_hash,
    )


__all__ = [
    "HealthObservation",
    "RecoveryAction",
    "RecoveryAuditEvent",
    "RecoveryDecision",
    "RecoveryStatus",
    "RepairProposal",
    "decide_recovery",
    "observe_health",
    "should_rollback",
]
