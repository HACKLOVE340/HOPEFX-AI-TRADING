"""Task 11 — the evals gate: a scored suite that must pass before promotion.

Spec §12 makes this the promotion gate. The properties that matter are the ones
that stop a gate from being decorative:

* **Fail closed.** No report, or a stale one, refuses. A gate that permits when
  it has no evidence is not a gate -- that was D3's defect in another costume.
* **A required case cannot be averaged away.** A high aggregate score must not
  mask a failure on a case that matters, or the score becomes a way to buy past
  the thing the case was written to catch.
* **Live is a higher bar than paper.** Promotion targets are not
  interchangeable.
"""

from __future__ import annotations

import pytest

from ai.evals.gate import GateDecision, PromotionGate, PromotionRefused
from ai.evals.suite import EvalCase, SuiteReport, run_suite


def _report(score: float, *, failed: tuple[str, ...] = (), age_s: float = 0.0) -> SuiteReport:
    import time

    return SuiteReport(
        score=score,
        total=10,
        passed=10 - len(failed),
        failed_case_ids=failed,
        ran_at=time.time() - age_s,
    )


# ── the suite runs and scores ─────────────────────────────────────────────────


def test_a_suite_scores_what_it_ran() -> None:
    cases = [
        EvalCase(id="a", prompt="2+2", expect="4"),
        EvalCase(id="b", prompt="3+3", expect="6"),
    ]
    report = run_suite(cases, runner=lambda case: case.expect)
    assert report.score == 1.0
    assert report.passed == 2
    assert report.failed_case_ids == ()


def test_a_failing_case_is_named_not_just_counted() -> None:
    cases = [
        EvalCase(id="a", prompt="2+2", expect="4"),
        EvalCase(id="b", prompt="3+3", expect="6"),
    ]
    report = run_suite(cases, runner=lambda case: "4")
    assert report.score == 0.5
    assert report.failed_case_ids == ("b",)


def test_a_runner_that_raises_is_a_failed_case_not_a_crashed_suite() -> None:
    def _boom(case: EvalCase) -> str:
        raise RuntimeError("model unavailable")

    report = run_suite([EvalCase(id="a", prompt="x", expect="y")], runner=_boom)
    assert report.score == 0.0
    assert report.failed_case_ids == ("a",)


def test_an_empty_suite_scores_zero_not_one() -> None:
    """Nothing having failed is not the same as everything having passed."""
    report = run_suite([], runner=lambda case: "")
    assert report.score == 0.0


# ── the gate ──────────────────────────────────────────────────────────────────


def test_a_failing_score_refuses_promotion() -> None:
    gate = PromotionGate(minimum_score={"paper": 0.8, "live": 0.95})
    with pytest.raises(PromotionRefused):
        gate.check(_report(0.5), target="paper")


def test_a_passing_score_allows_promotion() -> None:
    gate = PromotionGate(minimum_score={"paper": 0.8, "live": 0.95})
    decision = gate.check(_report(0.9), target="paper")
    assert isinstance(decision, GateDecision)
    assert decision.allowed is True


def test_live_is_a_higher_bar_than_paper() -> None:
    gate = PromotionGate(minimum_score={"paper": 0.8, "live": 0.95})
    assert gate.check(_report(0.9), target="paper").allowed is True
    with pytest.raises(PromotionRefused):
        gate.check(_report(0.9), target="live")


def test_no_report_refuses() -> None:
    gate = PromotionGate(minimum_score={"paper": 0.8})
    with pytest.raises(PromotionRefused, match="no eval report"):
        gate.check(None, target="paper")


def test_a_stale_report_refuses() -> None:
    """Evidence that a model passed last month is not evidence about this one."""
    gate = PromotionGate(minimum_score={"paper": 0.8}, max_age_s=3600)
    with pytest.raises(PromotionRefused, match="stale"):
        gate.check(_report(0.99, age_s=7200), target="paper")


def test_a_required_case_cannot_be_averaged_away() -> None:
    """A high aggregate must not buy past the case that matters."""
    gate = PromotionGate(minimum_score={"live": 0.9}, required_case_ids=("no_live_order_without_approval",))
    with pytest.raises(PromotionRefused, match="no_live_order_without_approval"):
        gate.check(_report(0.98, failed=("no_live_order_without_approval",)), target="live")


def test_an_unknown_target_refuses_rather_than_defaulting() -> None:
    gate = PromotionGate(minimum_score={"paper": 0.8})
    with pytest.raises(PromotionRefused):
        gate.check(_report(1.0), target="production")


# ── wired into the promotion path ─────────────────────────────────────────────


def test_canary_validation_consults_the_eval_gate() -> None:
    """The gate is only a gate if the promotion path asks it."""
    import inspect

    import api.safe_agent_platform as sp

    source = inspect.getsource(sp.validate_proposal)
    assert "eval_gate_passed" in source


def test_canary_is_refused_without_an_eval_report() -> None:
    import api.safe_agent_platform as sp

    sp.set_eval_report(None)
    allowed, reason = sp._eval_gate_allows("canary")
    assert allowed is False
    assert "no_eval_report" in reason


def test_canary_is_allowed_with_a_passing_report() -> None:
    import time

    import api.safe_agent_platform as sp
    from ai.evals.suite import SuiteReport

    sp.set_eval_report(SuiteReport(score=0.97, total=10, passed=10, failed_case_ids=(), ran_at=time.time()))
    try:
        allowed, reason = sp._eval_gate_allows("canary")
        assert allowed is True
        assert reason == "eval_gate_passed"
    finally:
        sp.set_eval_report(None)


def test_sandbox_and_paper_do_not_require_a_score() -> None:
    """They are where a candidate runs to EARN a score; requiring one blocks that."""
    import api.safe_agent_platform as sp

    sp.set_eval_report(None)
    for environment in ("sandbox", "paper"):
        assert sp._eval_gate_allows(environment)[0] is True
