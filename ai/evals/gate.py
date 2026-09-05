# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The promotion gate: what an eval score permits.

Three properties keep this from becoming decorative, and each is the inverse of
a defect this audit already found:

* **Fail closed.** No report, an unknown target, or a stale report refuses. A
  gate that permits when it has no evidence is not a gate -- that is exactly
  what `validate_proposal` did before Task 3, deriving "passed" from the
  environment name.
* **A required case cannot be averaged away.** A 0.98 aggregate must not buy
  past a failure on "no live order without approval". Without this the score
  becomes a way to purchase exemption from the specific thing a case exists to
  catch.
* **Targets are not interchangeable.** Live carries a higher bar than paper,
  and a target with no configured bar is refused rather than defaulted.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ai.evals.suite import SuiteReport

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_S = 24 * 3600


class PromotionRefused(RuntimeError):
    """The gate refused. Carries the reason codes."""

    def __init__(self, reason_codes: tuple[str, ...], detail: str = "") -> None:
        super().__init__(detail or ", ".join(reason_codes))
        self.reason_codes = reason_codes


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    target: str
    score: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PromotionGate:
    minimum_score: dict[str, float]
    required_case_ids: tuple[str, ...] = ()
    max_age_s: float = DEFAULT_MAX_AGE_S

    def check(self, report: SuiteReport | None, *, target: str) -> GateDecision:
        """Permit or refuse promotion to `target`. Raises PromotionRefused."""
        if report is None:
            raise PromotionRefused(("no_eval_report",), f"no eval report for promotion to {target}")

        if target not in self.minimum_score:
            raise PromotionRefused(
                ("unknown_target",),
                f"no eval bar configured for target {target!r}; refusing rather than defaulting",
            )

        age_s = time.time() - report.ran_at
        if age_s > self.max_age_s:
            raise PromotionRefused(
                ("stale_report",),
                f"eval report is stale ({age_s / 3600:.1f}h old, limit {self.max_age_s / 3600:.1f}h); "
                "evidence about a previous model is not evidence about this one",
            )

        blocking = tuple(cid for cid in self.required_case_ids if cid in report.failed_case_ids)
        if blocking:
            raise PromotionRefused(
                blocking,
                f"required eval case(s) failed and cannot be averaged away: {', '.join(blocking)}",
            )

        bar = self.minimum_score[target]
        if report.score < bar:
            raise PromotionRefused(
                ("score_below_bar",),
                f"eval score {report.score:.2f} is below the {target} bar of {bar:.2f}",
            )

        return GateDecision(allowed=True, target=target, score=report.score, reason_codes=("eval_gate_passed",))


__all__ = ["DEFAULT_MAX_AGE_S", "GateDecision", "PromotionGate", "PromotionRefused"]
