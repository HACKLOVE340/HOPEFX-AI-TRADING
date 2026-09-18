from __future__ import annotations

"""Fail-closed evidence gate for AI-generated research candidates."""

from dataclasses import dataclass

from core.ai_contracts import _canonical_hash


@dataclass(frozen=True)
class ResearchValidationEvidence:
    replay_ok: bool
    walk_forward_ok: bool
    leakage_check_ok: bool
    slippage_costs_ok: bool
    model_quality_ok: bool
    reason_codes: tuple[str, ...] = ()
    evidence_hash: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_hash:
            payload = {
                "replay_ok": self.replay_ok,
                "walk_forward_ok": self.walk_forward_ok,
                "leakage_check_ok": self.leakage_check_ok,
                "slippage_costs_ok": self.slippage_costs_ok,
                "model_quality_ok": self.model_quality_ok,
                "reason_codes": self.reason_codes,
            }
            object.__setattr__(self, "evidence_hash", _canonical_hash(payload))

    @property
    def passed(self) -> bool:
        return all(
            (
                self.replay_ok,
                self.walk_forward_ok,
                self.leakage_check_ok,
                self.slippage_costs_ok,
                self.model_quality_ok,
            )
        )

    def require_pass(self) -> None:
        if not self.passed:
            raise RuntimeError("research validation gate failed: " + ", ".join(self.reason_codes))


def evaluate_research_validation(
    *,
    replay_ok: bool,
    walk_forward_ok: bool,
    leakage_check_ok: bool,
    slippage_costs_ok: bool,
    model_quality_ok: bool,
) -> ResearchValidationEvidence:
    checks = {
        "replay": replay_ok,
        "walk_forward": walk_forward_ok,
        "leakage_check": leakage_check_ok,
        "slippage_costs": slippage_costs_ok,
        "model_quality": model_quality_ok,
    }
    reasons = tuple(f"{name}_failed" for name, passed in checks.items() if not passed)
    return ResearchValidationEvidence(
        replay_ok=replay_ok,
        walk_forward_ok=walk_forward_ok,
        leakage_check_ok=leakage_check_ok,
        slippage_costs_ok=slippage_costs_ok,
        model_quality_ok=model_quality_ok,
        reason_codes=reasons,
    )


__all__ = ["ResearchValidationEvidence", "evaluate_research_validation"]
