# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The AI staying awake to improve itself, bounded four ways.

Owner request, 2026-09-07: the AI should always be awake to improve itself.

An autonomous loop that reads all the code, asks a model to write patches, and
files them for review is a useful thing and a dangerous one. What makes it
safe is not the intention behind it; it is what it cannot do.

## Off by default

`AI_IMPROVE_CYCLE_HOURS` unset, empty, zero, negative, infinite or unparseable
all mean off. `ai/evals/schedule.py` reached the same conclusion for the same
reason and this mirrors it deliberately: a typo must never be read as "run
continuously", because a zero-second interval of paid model calls is the worst
available reading of a mistake. A self-improvement loop that starts itself on
first deployment is also a change nobody chose.

## A kill switch that needs no deploy

A Redis key, read at the top of every cycle. `redis-cli set
hopefx:ai:improve:halted 1` stops it; no restart, no release.

**And if the switch cannot be read, the cycle does not run.** That is the one
place in this module where unavailable means refuse rather than report, and it
is the opposite of the rule everywhere else in this codebase — because the
question here is not "what is true" but "have I been told to stop". A loop that
spends money and answers "no halt found" to a connection error has turned its
kill switch into a suggestion.

## The ceiling, before the work

The walk is free — `ai/improve/walker.py` is a parser. Asking a model to write
a patch is not. `ai/gateway/budget.check` is consulted first, against this
cycle's own operator so the spend is attributable and does not come out of a
person's share. A cycle without headroom is skipped and says it was skipped.

## A cap, spent on the worst first

Three proposals per cycle. The walker finds around thirteen hundred things in
this repository; filing them all would turn two people's review queue into
noise, and a queue nobody reads is a queue nobody approves from. Findings are
ordered by severity so the cap is spent where it matters, and a finding on a
vault-protected path never reaches the generator at all — paying a model to
write a patch that cannot be applied is money for nothing.

## The report is the deliverable

A cycle that proposed nothing says so, with the reason. Silence from a
self-improving system reads as "nothing is wrong", which is the same defect as
a gauge showing zero because its probe failed. Every refusal is named with the
evidence it belongs to, never dropped.

## It cannot apply anything

Like the rest of `ai/improve/`, this module never signs and never writes to the
queue the healer drains. It calls `ai/improve/proposal.py`, which puts a
`pending` record in front of two humans, one of whom must be a superadmin.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

_ENV_VAR: Final[str] = "AI_IMPROVE_CYCLE_HOURS"

#: `redis-cli set hopefx:ai:improve:halted 1` — stop, without a deploy.
HALT_KEY: Final[str] = "hopefx:ai:improve:halted"

#: The cycle's own budget identity, so its spend is attributable and is not
#: taken out of an operator's monthly share.
CYCLE_OPERATOR: Final[str] = "ai-improvement-cycle"

#: What one cycle is assumed to cost when asking whether there is headroom.
#: Deliberately generous, like `ai/evals/schedule.py`'s: over-estimating skips a
#: cycle that would have squeaked through, under-estimating runs one that should
#: not have. The real cost is charged per call by the gateway.
ESTIMATED_CYCLE_USD: Final[float] = 0.25

#: Proposals filed per cycle. Small on purpose — see the module docstring.
MAX_PROPOSALS_PER_CYCLE: Final[int] = 3

_SEVERITY_ORDER: Final[dict[str, int]] = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class CycleReport:
    """What one cycle walked, found, proposed, and refused to propose.

    `reason` is always populated, whether or not the cycle ran. A report that
    says nothing is indistinguishable from a cycle that did nothing, and from
    one that never started.
    """

    ran: bool
    reason: str
    files_walked: int = 0
    findings: int = 0
    #: Findings actually handed to the generator. Bounded by the cap.
    considered: int = 0
    proposed: int = 0
    #: `(evidence, why)` for everything considered and not filed.
    refused: tuple[tuple[str, str], ...] = ()
    #: Evidence locators of the proposals that reached the queue.
    queued: tuple[str, ...] = ()
    checks_run: tuple[str, ...] = ()
    checks_skipped: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "reason": self.reason,
            "files_walked": self.files_walked,
            "findings": self.findings,
            "considered": self.considered,
            "proposed": self.proposed,
            "refused": [{"evidence": e, "why": w} for e, w in self.refused],
            "queued": list(self.queued),
            "checks_run": list(self.checks_run),
            "checks_skipped": [{"check": c, "reason": r} for c, r in self.checks_skipped],
            "cap": MAX_PROPOSALS_PER_CYCLE,
        }


def interval_s() -> float | None:
    """Seconds between cycles, or None when the schedule is off."""
    raw = (os.getenv(_ENV_VAR, "") or "").strip()
    if not raw:
        return None
    try:
        hours = float(raw)
    except ValueError:
        logger.warning("ai.improve.cycle: %s=%r is not a number; the cycle stays off", _ENV_VAR, raw)
        return None
    # `isfinite` as well as `> 0`: `float("inf") > 0` is True, and an infinite
    # interval is a loop that sleeps for ever while reporting itself scheduled.
    if not math.isfinite(hours) or hours <= 0:
        logger.warning("ai.improve.cycle: %s=%r is not a positive number; the cycle stays off", _ENV_VAR, raw)
        return None
    return hours * 3600.0


async def halted(redis: Any) -> tuple[bool, str]:
    """Whether the cycle has been told to stop. Fail closed.

    Returns `(stop, reason)`. No Redis, or a Redis that raises, both mean stop:
    the question is "have I been told to halt", and a loop that cannot read the
    answer must not assume it is free to run.
    """
    if redis is None:
        return True, "stopped: the halt switch could not be read (no Redis), and an unreadable switch means stop"
    try:
        value = await redis.get(HALT_KEY)
    except Exception as exc:
        return True, (
            f"stopped: the halt switch could not be read ({type(exc).__name__}), and an unreadable switch means stop"
        )
    if value in (None, "", b"", "0", b"0"):
        return False, ""
    return True, f"halted: {HALT_KEY} is set; clear it to resume"


async def run_cycle(
    *,
    redis: Any,
    patcher: Callable[[Any], str] | None = None,
    walk: Callable[..., Any] | None = None,
) -> CycleReport:
    """One pass: check, walk, consider, propose, report.

    `patcher` turns a finding into candidate source. None means the cycle walks
    and reports and proposes nothing — which is a useful cycle, and the report
    says that is what happened rather than looking like a clean bill.
    """
    stop, why = await halted(redis)
    if stop:
        logger.info("ai.improve.cycle: %s", why)
        return CycleReport(ran=False, reason=why)

    from ai.gateway import budget

    allowed, budget_reason = budget.check(CYCLE_OPERATOR, ESTIMATED_CYCLE_USD)
    if not allowed:
        # INFO, not ERROR: the ceiling binding is the ceiling working. Said out
        # loud anyway, because "the AI stopped improving itself" is not obvious
        # from a budget message.
        logger.info("ai.improve.cycle: skipping this cycle (%s)", budget_reason)
        return CycleReport(ran=False, reason=budget_reason)

    walker_fn = walk
    if walker_fn is None:
        from ai.improve import walker as _walker

        walker_fn = _walker.walk

    report = walker_fn()
    findings = tuple(report.findings)

    proposable = [f for f in findings if f.proposable]
    refused: list[tuple[str, str]] = [
        (f.evidence, "protected path: no AI-originated change may modify it, so no patch was generated")
        for f in findings
        if not f.proposable
    ]

    if not findings:
        return CycleReport(
            ran=True,
            reason=f"walked {report.files_walked} files and found nothing to propose",
            files_walked=report.files_walked,
            checks_run=tuple(report.checks_run),
            checks_skipped=tuple(report.checks_skipped),
        )

    if patcher is None:
        return CycleReport(
            ran=True,
            reason=(
                f"walked {report.files_walked} files and reported {len(findings)} findings; "
                "proposed nothing because no patch generator is installed"
            ),
            files_walked=report.files_walked,
            findings=len(findings),
            refused=tuple(refused),
            checks_run=tuple(report.checks_run),
            checks_skipped=tuple(report.checks_skipped),
        )

    ordered = sorted(proposable, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 3), f.path, f.line))
    selected = ordered[:MAX_PROPOSALS_PER_CYCLE]

    queued: list[str] = []
    for finding in selected:
        outcome = await _propose_one(finding, patcher=patcher, redis=redis)
        if outcome[0]:
            queued.append(finding.evidence)
        else:
            refused.append((finding.evidence, outcome[1]))

    reason = (
        f"walked {report.files_walked} files, reported {len(findings)} findings, "
        f"considered {len(selected)} (cap {MAX_PROPOSALS_PER_CYCLE}), filed {len(queued)}"
    )
    if not queued:
        reason += " — proposed nothing; every candidate was refused by a gate, listed in `refused`"

    return CycleReport(
        ran=True,
        reason=reason,
        files_walked=report.files_walked,
        findings=len(findings),
        considered=len(selected),
        proposed=len(queued),
        refused=tuple(refused),
        queued=tuple(queued),
        checks_run=tuple(report.checks_run),
        checks_skipped=tuple(report.checks_skipped),
    )


async def _propose_one(finding: Any, *, patcher: Callable[[Any], str], redis: Any) -> tuple[bool, str]:
    """Generate, gate, queue. Returns `(filed, why not)`.

    A generator that raises costs this finding and not the cycle: one model
    refusal must not end the only thing keeping the review queue supplied.
    """
    from ai.improve import proposal

    try:
        candidate = patcher(finding)
    except Exception as exc:
        logger.warning("ai.improve.cycle: the patch generator raised on %s: %s", finding.evidence, exc)
        return False, f"the patch generator raised {type(exc).__name__}: {exc}"

    if not candidate or not candidate.strip():
        return False, "the patch generator returned nothing for this finding"

    prepared = proposal.prepare(finding, new_source=candidate, proposer="improvement-cycle")
    if not prepared.accepted:
        return False, prepared.refused_because

    result = await proposal.queue(prepared, redis=redis)
    if not result.get("queued"):
        return False, str(result.get("reason", "the queue write did not report success"))
    return True, ""


async def run_forever(
    interval: float,
    *,
    redis: Any,
    patcher: Callable[[Any], str] | None = None,
    sleep: Callable[[float], Any] = asyncio.sleep,
    run: Callable[..., Any] | None = None,
) -> None:
    """Sleep, cycle, repeat. Sleeps FIRST — a restart is not a purchase.

    A crash-looping deployment that ran a cycle at startup would be a bill.
    """
    cycle = run or run_cycle
    while True:
        await sleep(interval)
        try:
            report = await cycle(redis=redis, patcher=patcher)
            logger.info("ai.improve.cycle: %s", getattr(report, "reason", report))
        except Exception:
            # The loop survives. A vendor outage that silently ended the cycle
            # would leave the AI reporting nothing and looking healthy.
            logger.error("ai.improve.cycle: a cycle failed", exc_info=True)


__all__ = [
    "CYCLE_OPERATOR",
    "ESTIMATED_CYCLE_USD",
    "HALT_KEY",
    "MAX_PROPOSALS_PER_CYCLE",
    "CycleReport",
    "halted",
    "interval_s",
    "run_cycle",
    "run_forever",
]
