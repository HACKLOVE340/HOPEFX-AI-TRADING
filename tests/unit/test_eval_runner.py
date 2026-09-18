# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The eval runner — the seam that made canary promotion impossible.

`ai/evals/` had a suite runner and a promotion gate, both correct and both
tested. `api/safe_agent_platform.set_eval_report` had **zero callers**, so
`_EVAL_REPORT` was always None and the gate always refused `no_eval_report`.
Fail-closed, which is the right direction — and it meant canary promotion was
not gated, it was *impossible*. A gate that can only ever say no is not
governing anything; it is a wall.

This adds the two missing pieces: a committed suite of cases, and a runner that
executes them through the gateway and files the report.

**Running evals spends money.** Every case is a model call, so the runner is
never automatic — nothing calls it at startup. It is triggered explicitly, and
the budget ceiling and the velocity brake bound it like any other model call.

**The scoring is exact-match**, so the cases are written to have exactly one
correct answer. Two of them are risk arithmetic and are marked `required`: a
model that gets "is 15% drawdown above a 10% limit" wrong should not be
promoted no matter how well it does on the others, and `required` is what stops
that being averaged away.
"""

from __future__ import annotations

import pytest

from ai.evals import cases as eval_cases
from ai.evals import runner as eval_runner
from ai.evals.gate import PromotionGate, PromotionRefused

pytestmark = pytest.mark.unit


# ── the committed suite ──────────────────────────────────────────────────────


def test_the_suite_is_not_empty():
    """An empty suite scores 0.0 by design; committing one would be pointless."""
    assert eval_cases.DEFAULT_CASES


def test_every_case_has_an_id_a_prompt_and_an_expected_answer():
    for case in eval_cases.DEFAULT_CASES:
        assert case.id.strip()
        assert case.prompt.strip()
        assert case.expect.strip()


def test_case_ids_are_unique():
    """Duplicate ids make failed_case_ids ambiguous, and the gate reads those."""
    ids = [c.id for c in eval_cases.DEFAULT_CASES]
    assert len(ids) == len(set(ids))


def test_at_least_one_case_is_required():
    """Without a required case, a bad answer on a safety question averages away."""
    assert any(c.required for c in eval_cases.DEFAULT_CASES)


def test_the_required_cases_are_the_risk_ones():
    required = {c.id for c in eval_cases.DEFAULT_CASES if c.required}
    assert required <= set(eval_cases.REQUIRED_CASE_IDS)
    assert required, "REQUIRED_CASE_IDS and the cases themselves must agree"


def test_expected_answers_are_single_tokens():
    """Exact-match scoring punishes prose. A case whose answer is a sentence
    measures formatting, not knowledge."""
    for case in eval_cases.DEFAULT_CASES:
        assert len(case.expect.split()) == 1, case.id


# ── the runner ───────────────────────────────────────────────────────────────


def test_a_perfect_run_scores_one():
    answers = {c.id: c.expect for c in eval_cases.DEFAULT_CASES}
    report = eval_runner.run_default_suite(ask=lambda case: answers[case.id])
    assert report.score == pytest.approx(1.0)
    assert report.failed_case_ids == ()


def test_a_model_that_answers_nothing_scores_zero():
    report = eval_runner.run_default_suite(ask=lambda case: "")
    assert report.score == pytest.approx(0.0)
    assert report.total == len(eval_cases.DEFAULT_CASES)


def test_a_model_that_raises_fails_that_case_without_killing_the_run():
    def ask(case):
        if case.required:
            raise RuntimeError("provider down")
        return case.expect

    report = eval_runner.run_default_suite(ask=ask)
    assert report.total == len(eval_cases.DEFAULT_CASES)
    assert report.failed_case_ids, "the raising case must be recorded as failed"
    assert report.passed > 0, "the other cases still ran"


def test_answers_are_compared_case_insensitively_and_trimmed():
    """A model replying " gold\\n" got the answer right."""
    report = eval_runner.run_default_suite(ask=lambda case: f"  {case.expect.lower()}  \n")
    assert report.score == pytest.approx(1.0)


# ── publishing: the seam that had no filler ──────────────────────────────────


def test_publishing_fills_the_gate_seam():
    from api import safe_agent_platform

    safe_agent_platform.set_eval_report(None)
    assert safe_agent_platform._EVAL_REPORT is None

    answers = {c.id: c.expect for c in eval_cases.DEFAULT_CASES}
    report = eval_runner.run_and_publish(ask=lambda case: answers[case.id])

    assert safe_agent_platform._EVAL_REPORT is report
    safe_agent_platform.set_eval_report(None)


def test_a_passing_run_makes_canary_promotion_possible():
    """The whole point: the gate can now say yes, not only no."""
    from api import safe_agent_platform

    try:
        answers = {c.id: c.expect for c in eval_cases.DEFAULT_CASES}
        eval_runner.run_and_publish(ask=lambda case: answers[case.id])
        allowed, reason = safe_agent_platform._eval_gate_allows("canary")
        assert allowed is True, reason
    finally:
        safe_agent_platform.set_eval_report(None)


def test_with_no_report_the_gate_still_refuses():
    """Fail-closed is preserved. The runner adds a yes; it removes no no."""
    from api import safe_agent_platform

    safe_agent_platform.set_eval_report(None)
    allowed, reason = safe_agent_platform._eval_gate_allows("canary")
    assert allowed is False
    assert "no_eval_report" in reason


def test_a_failing_run_is_published_and_refused_not_hidden():
    """A bad score must reach the gate. Withholding it would be fail-open."""
    from api import safe_agent_platform

    try:
        eval_runner.run_and_publish(ask=lambda case: "wrong")
        allowed, reason = safe_agent_platform._eval_gate_allows("canary")
        assert allowed is False
        assert "score_below_bar" in reason or "required" in reason.lower() or reason
    finally:
        safe_agent_platform.set_eval_report(None)


def test_a_required_case_failing_blocks_even_a_high_score():
    """Required cases exist so a safety answer cannot be averaged away."""
    required_id = eval_cases.REQUIRED_CASE_IDS[0]
    answers = {c.id: ("wrong" if c.id == required_id else c.expect) for c in eval_cases.DEFAULT_CASES}
    report = eval_runner.run_default_suite(ask=lambda case: answers[case.id])

    gate = PromotionGate(
        minimum_score={"canary": 0.5},
        required_case_ids=eval_cases.REQUIRED_CASE_IDS,
    )
    with pytest.raises(PromotionRefused) as excinfo:
        gate.check(report, target="canary")
    assert required_id in excinfo.value.reason_codes


# ── it is not automatic ──────────────────────────────────────────────────────


def test_nothing_runs_the_suite_at_startup():
    """Every case is a paid model call. Automatic evals are a recurring bill
    nobody asked for, and a startup that spends money is hard to notice."""
    import subprocess

    hits = subprocess.run(
        ["git", "grep", "-l", "run_and_publish", "--", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    offenders = [h for h in hits if h.startswith("core/startup") or h == "app.py"]
    assert not offenders, f"the eval runner is wired into startup: {offenders}"


# ── the production gate, not one built in a test ─────────────────────────────


def test_the_production_gate_refuses_a_failed_required_case_at_any_score():
    """Measured before the fix: a 0.95 report whose single failure was the
    drawdown safety case was PERMITTED, because the aggregate cleared the bar.

    `EvalCase.required` existed and `PromotionGate` supported required_case_ids;
    `_eval_gate_allows` never passed them. The flag was decorative — a control
    that exists and is never wired, which is this audit's signature defect.

    This asserts the REAL gate, not one constructed here. A test that builds its
    own gate proves the dataclass works and nothing about the deployment.
    """
    from api import safe_agent_platform
    from ai.evals.suite import SuiteReport

    try:
        safe_agent_platform.set_eval_report(
            SuiteReport(
                score=0.95,
                total=20,
                passed=19,
                failed_case_ids=(eval_cases.REQUIRED_CASE_IDS[0],),
            )
        )
        allowed, reason = safe_agent_platform._eval_gate_allows("canary")
        assert allowed is False, "a failed safety case must not be averaged away"
        assert eval_cases.REQUIRED_CASE_IDS[0] in reason
    finally:
        safe_agent_platform.set_eval_report(None)


def test_the_production_gate_still_permits_a_clean_high_score():
    """The gate must not now refuse everything."""
    from api import safe_agent_platform
    from ai.evals.suite import SuiteReport

    try:
        safe_agent_platform.set_eval_report(
            SuiteReport(score=0.95, total=20, passed=19, failed_case_ids=("follow.no_prose",))
        )
        allowed, reason = safe_agent_platform._eval_gate_allows("canary")
        assert allowed is True, reason
    finally:
        safe_agent_platform.set_eval_report(None)
