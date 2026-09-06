# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Running the eval suite on an interval, without it becoming a spending leak.

`PromotionGate` bounds a report at 24 hours and nothing ran the suite
automatically, so canary promotion was blocked for most of any given day unless
somebody remembered to click. That pressure is how a staleness bound ends up
raised to a month, at which point the bound is decoration.

`ai/evals/runner.py` states why it was manual, and it is right: every case is a
paid model call, and *"a startup that quietly spends money is hard to notice and
harder to stop."* So this is built to that constraint rather than around it.

* **Off unless explicitly enabled.** `AI_EVAL_SCHEDULE_HOURS` unset, empty, zero,
  negative or unparseable all mean off. A typo must never be read as "run
  continuously" — a zero-second interval of paid model calls is the worst
  possible reading of a mistake.
* **The first run is one interval in**, never at startup. Otherwise every
  restart is a purchase and a crash-looping deployment is a bill.
* **The ceiling is consulted first.** The one path that makes six calls in a row
  should not be the one path that runs past the budget.
* **A failed run does not stop the schedule**, and logs at ERROR: the gate's
  evidence quietly going stale is not a debug detail.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_ENV_VAR = "AI_EVAL_SCHEDULE_HOURS"

#: What one suite run is assumed to cost when asking the budget whether there is
#: room. Deliberately generous: the question is "is there headroom", and
#: over-estimating skips a run that would have squeaked through, while
#: under-estimating runs one that should not have. The suite's real cost is
#: charged per call by the gateway, exactly as for any other caller.
ESTIMATED_RUN_USD = 0.05


def interval_s() -> float | None:
    """Seconds between runs, or None when the schedule is off."""
    raw = (os.getenv(_ENV_VAR, "") or "").strip()
    if not raw:
        return None
    try:
        hours = float(raw)
    except ValueError:
        logger.warning("ai.evals.schedule: %s=%r is not a number; the schedule stays off", _ENV_VAR, raw)
        return None
    # `isfinite` and not just `> 0`: `float("inf") > 0` is True, and an infinite
    # interval is a loop that sleeps forever while reporting itself as scheduled
    # — a schedule that says it is on and never runs. NaN fails `> 0` already;
    # naming both here is cheaper than remembering which one that covers.
    if not math.isfinite(hours) or hours <= 0:
        logger.warning("ai.evals.schedule: %s=%r is not a positive number; the schedule stays off", _ENV_VAR, raw)
        return None
    return hours * 3600.0


def budgeted_run(*, run: Callable[[], Any] | None = None) -> bool:
    """Run the suite if there is budget for it. Returns whether it ran.

    Separated from the loop so the ceiling check is testable on its own, and so
    a manual trigger could use the same rule if it ever wanted to.
    """
    from ai.gateway import budget

    from .runner import EVAL_OPERATOR

    allowed, reason = budget.check(EVAL_OPERATOR, ESTIMATED_RUN_USD)
    if not allowed:
        # INFO rather than ERROR: the ceiling binding is the ceiling working.
        # It is still said out loud, because the consequence — the gate's
        # evidence going stale — is not obvious from a budget message.
        logger.info(
            "ai.evals.schedule: skipping the scheduled run (%s); the promotion gate's report will age out",
            reason,
        )
        return False

    if run is not None:
        run()
        return True

    from .runner import run_and_publish

    report = run_and_publish()
    logger.info("ai.evals.schedule: suite scored %.2f (%d/%d)", report.score, report.passed, report.total)
    return True


async def run_forever(
    interval: float,
    *,
    run: Callable[[], Any] | None = None,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Sleep, run, repeat. Sleeps FIRST — startup is not a purchase.

    `sleep` is injectable so the loop is testable without waiting hours; the
    default is the real one.
    """
    while True:
        await sleep(interval)
        try:
            budgeted_run(run=run)
        except Exception:
            # The loop survives. A vendor outage that silently ended automatic
            # evals would leave the gate going stale with nothing saying why.
            logger.error("ai.evals.schedule: scheduled eval run failed", exc_info=True)


__all__ = ["ESTIMATED_RUN_USD", "budgeted_run", "interval_s", "run_forever"]
