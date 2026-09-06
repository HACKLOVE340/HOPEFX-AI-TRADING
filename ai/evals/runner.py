# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Run the eval suite and file the report the promotion gate reads.

This is the seam that had no filler. `api/safe_agent_platform.set_eval_report`
had zero callers, so `_EVAL_REPORT` was always None and the gate always refused
`no_eval_report`. Fail-closed is the right direction, and it meant canary
promotion was not gated but impossible — a gate that can only say no is a wall.

**Nothing calls this automatically.** Every case is a paid model call through
the gateway, so an eval run is triggered explicitly by an operator and bounded
by the same budget ceiling and velocity brake as any other call. A startup that
quietly spends money is hard to notice and harder to stop.

Answers are compared case-insensitively after trimming. Exact-match scoring is
what makes the cases unambiguous, but punishing a model for replying " Gold\\n"
would measure whitespace.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .cases import DEFAULT_CASES, REQUIRED_CASE_IDS
from .suite import EvalCase, SuiteReport, run_suite

logger = logging.getLogger(__name__)

#: Eval prompts are short and the answers are one word.
EVAL_ROLE = "fast"
EVAL_OPERATOR = "eval-runner"


def _build_client() -> Any:
    """One gateway client, wired to whatever vendors this deployment can reach.

    `GatewayClient()` with no arguments has an EMPTY provider map — it does not
    discover anything — so it can reach no vendor at all. The endpoint that
    submits a generation builds providers explicitly, and so must this.
    """
    from ai.gateway.adapters import build_providers
    from ai.gateway.client import GatewayClient

    return GatewayClient(build_providers())


def _gateway_ask(case: EvalCase, *, client: Any = None) -> str:
    """Ask the model chain, through the gateway like every other model call.

    This function had never been executed. Every test in `test_eval_runner.py`
    injects `ask=`, so the production path was covered by nothing, and it did
    not work: it called `GatewayClient.complete`, which does not exist — the
    class exposes `call_sync` — and passed `operator=` to `ModelRequest`, which
    has no such field. `run_suite` marks a raising case FAILED rather than
    aborting, which is right, and which meant six exceptions presented
    themselves as a 0.00 score about the MODEL. The promotion gate then refused
    `score_below_bar` for a reason that had nothing to do with any model.

    A budget refusal or an unreachable vendor still raises here, and is still
    scored as a failed case. That is deliberate: a model this deployment cannot
    afford to ask is not a model it can promote on.
    """
    from ai.gateway.client import ModelRequest

    gateway = client if client is not None else _build_client()
    response = gateway.call_sync(
        ModelRequest(prompt=case.prompt, role=EVAL_ROLE),
        # Eval spend is a system cost with its own line in the audit trail, not
        # a charge against whichever operator happened to click Run.
        operator=EVAL_OPERATOR,
    )
    return str(getattr(response, "text", "") or "")


def _normalise(answer: str) -> str:
    return str(answer).strip().strip(".").lower()


def run_default_suite(*, ask: Callable[[EvalCase], str] | None = None) -> SuiteReport:
    """Run the committed suite. Returns the report; files nothing."""
    if ask is not None:
        asker = ask
    else:
        # One client for the whole suite rather than one per case: building it
        # reads the environment for every vendor, and six identical rebuilds
        # per run is work for nothing.
        gateway = _build_client()

        def asker(case: EvalCase) -> str:
            return _gateway_ask(case, client=gateway)

    def runner(case: EvalCase) -> str:
        # Normalise both sides here rather than in the suite: `run_suite`
        # compares exactly, which is what makes it usable for suites where
        # case matters. This suite's answers are single words.
        return _normalise(asker(case))

    normalised = [
        EvalCase(id=c.id, prompt=c.prompt, expect=_normalise(c.expect), required=c.required) for c in DEFAULT_CASES
    ]
    report = run_suite(normalised, runner=runner)
    logger.info(
        "ai.evals: suite scored %.2f (%d/%d), failed=%s",
        report.score,
        report.passed,
        report.total,
        list(report.failed_case_ids) or "none",
    )
    return report


def run_and_publish(*, ask: Callable[[EvalCase], str] | None = None) -> SuiteReport:
    """Run the suite and file the report for the promotion gate.

    A failing report is published too. Withholding a bad score would leave the
    gate reading a stale passing one, which is fail-OPEN wearing fail-closed's
    clothes — the gate is meant to see the evidence, not only the good news.
    """
    report = run_default_suite(ask=ask)
    from api.safe_agent_platform import set_eval_report

    set_eval_report(report)
    return report


def required_case_ids() -> tuple[str, ...]:
    return REQUIRED_CASE_IDS


__all__ = ["EVAL_OPERATOR", "EVAL_ROLE", "required_case_ids", "run_and_publish", "run_default_suite"]
