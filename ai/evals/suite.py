# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A scored eval suite: test inputs, a response, an evaluation, a score.

Spec §3 concept 6 asks for exactly that chain, and §12 makes the resulting score
a promotion gate. This module produces the score; `ai.evals.gate` decides what
it permits.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvalCase:
    """One test input and what a correct answer looks like."""

    id: str
    prompt: str
    expect: str
    #: When True, this case must pass for promotion regardless of the aggregate.
    required: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("an eval case needs an id")


@dataclass(frozen=True)
class SuiteReport:
    score: float
    total: int
    passed: int
    failed_case_ids: tuple[str, ...] = field(default_factory=tuple)
    ran_at: float = field(default_factory=time.time)


def run_suite(cases: list[EvalCase], *, runner: Callable[[EvalCase], str]) -> SuiteReport:
    """Run every case and score the result.

    A runner that raises marks its case FAILED rather than aborting the suite: a
    model being unavailable is a result about that model, and a suite that dies
    on the first error produces no score at all -- which the gate would then
    have to treat as "no evidence", losing the information that the other cases
    passed.

    An empty suite scores 0.0, not 1.0. Nothing having failed is not the same as
    everything having passed, and a vacuous 1.0 would let an unpopulated suite
    authorise a promotion.
    """
    if not cases:
        logger.warning("ai.evals: suite is empty; scoring 0.0 rather than a vacuous 1.0")
        return SuiteReport(score=0.0, total=0, passed=0)

    failed: list[str] = []
    for case in cases:
        try:
            answer = runner(case)
        except Exception as exc:  # a dead model is a result, not a crash
            logger.warning("ai.evals: case %s raised: %s", case.id, exc)
            failed.append(case.id)
            continue
        if str(answer).strip() != case.expect.strip():
            failed.append(case.id)

    passed = len(cases) - len(failed)
    return SuiteReport(
        score=passed / len(cases),
        total=len(cases),
        passed=passed,
        failed_case_ids=tuple(failed),
    )


__all__ = ["EvalCase", "SuiteReport", "run_suite"]
