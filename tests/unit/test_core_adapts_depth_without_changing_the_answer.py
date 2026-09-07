# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§5: the AI Core's own four behaviours.

    Maintain conversation context across active tasks. Adapt explanation depth
    without changing the intelligence. State uncertainty honestly. Challenge
    weak assumptions and present counterarguments.

## The sentence that shapes this file

**"Adapt explanation depth WITHOUT CHANGING THE INTELLIGENCE."** The failure
mode is not subtle and it is not rare: a "simpler" rendering that drops the
caveat, rounds the number, or leaves out the counter-thesis. That is not a
simpler argument, it is a different one — and the operator who asked for
simpler has no way to know they were handed it.

So three things survive every depth, and are asserted to: **every number, the
counter-thesis, and what would change the conclusion.** Depth may change how
much scaffolding goes round them. It may not remove them.

## And the one that shapes the calibration half

A confidence nobody has ever checked is not calibrated, and reporting it as
though it were is the fake-precision failure §22 exists to stop. So an
uncalibrated figure says so, and calibration annotates a confidence — it never
silently rewrites it.

These fail on the pre-fix tree: `ai.core` does not exist there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def _ev(claim: str, quality: str = "measured", *, minutes_old: float = 1.0):
    from ai.debate import Evidence, EvidenceQuality

    return Evidence(
        claim=claim,
        source=f"src.{quality}",
        quality=EvidenceQuality(quality),
        observed_at=NOW - timedelta(minutes=minutes_old),
    )


def _reasoning(**over):
    from ai.debate import Reasoning

    kwargs: dict = {
        "subject": "XAUUSD exposure",
        "thesis": "Daily loss is 4.10% against a 5.00% limit.",
        "counter_thesis": "Positions reconcile with the broker and nothing else is amiss.",
        "assumptions": ("The risk feed is current.",),
        "missing_information": ("No order-book depth reading today.",),
        "evidence": (_ev("Reconciled against the ledger"),),
        "counter_evidence": (_ev("Broker positions match", "reported"),),
        "confidence": 0.62,
        "confidence_basis": "Two of three departments reported.",
        "what_would_change_it": ("A fresh reading from research_intelligence.",),
        "risks": ("One more loss at this size ends the session.",),
        "alternatives": ("Take no action and request the missing reading first.",),
    }
    kwargs.update(over)
    return Reasoning(**kwargs)


# ── §5: depth changes the scaffolding, never the argument ─────────────────────


def test_every_depth_keeps_every_number():
    """The one that would cost money. "4.10%" softened to "a bit down" in the
    plain register is a different statement about the account."""
    from ai.core import DEPTHS, explain

    reasoning = _reasoning()
    for depth in DEPTHS:
        text = explain(reasoning, depth=depth)
        assert "4.10%" in text, f"{depth} lost the drawdown figure"
        assert "5.00%" in text, f"{depth} lost the limit it is measured against"


def test_every_depth_keeps_the_counter_thesis():
    """A simpler version that drops the other side is not simpler, it is
    one-sided — and the reader who asked for simpler cannot tell."""
    from ai.core import DEPTHS, explain

    for depth in DEPTHS:
        assert "reconcile" in explain(_reasoning(), depth=depth).lower(), f"{depth} dropped the counter-thesis"


def test_every_depth_keeps_what_would_change_the_conclusion():
    """An argument with no stated way to be wrong is an assertion, at any
    length."""
    from ai.core import DEPTHS, explain

    for depth in DEPTHS:
        assert "research_intelligence" in explain(_reasoning(), depth=depth), f"{depth} dropped the falsifier"


def test_the_depths_are_actually_different():
    """Otherwise this is one renderer with five names."""
    from ai.core import DEPTHS, explain

    rendered = [explain(_reasoning(), depth=d) for d in DEPTHS]
    assert len(set(rendered)) == len(DEPTHS)


def test_a_briefer_depth_is_shorter():
    from ai.core import explain

    assert len(explain(_reasoning(), depth="headline")) < len(explain(_reasoning(), depth="full"))


def test_depth_never_moves_the_confidence_figure():
    """Rounding 62% to "fairly sure" in one register and leaving it as a number
    in another gives two readers two different answers."""
    from ai.core import DEPTHS, explain

    for depth in DEPTHS:
        text = explain(_reasoning(), depth=depth)
        assert "62%" in text, f"{depth} changed or dropped the confidence"


def test_an_uncalibrated_reasoning_says_so_at_every_depth():
    """Absence of a confidence is a fact about the answer, not a line to omit
    when space is short."""
    from ai.core import DEPTHS, explain

    bare = _reasoning(confidence=None, confidence_basis="")
    for depth in DEPTHS:
        assert "not calibrated" in explain(bare, depth=depth).lower(), f"{depth} hid an absent confidence"


def test_an_unknown_depth_is_refused_rather_than_silently_defaulted():
    """Defaulting would hand somebody the standard register while they believe
    they asked for the plain one."""
    from ai.core import explain

    with pytest.raises(ValueError, match="depth"):
        explain(_reasoning(), depth="eli5-but-shorter")


# ── §5: challenge weak assumptions ────────────────────────────────────────────


def test_an_assumption_with_no_supporting_evidence_is_challenged():
    # `now=NOW` on every call below is load-bearing, not tidiness. Without it the
    # fixture's timestamps sit relative to a fixed NOW while the checker measures
    # against real time, so the stale rule fires on everything and the other
    # assertions in this section pass by accident. The "well-supported argument"
    # test is the one that caught it.
    from ai.core import challenge

    found = challenge(_reasoning(assumptions=("Liquidity will hold into the close.",)), now=NOW)
    assert any("liquidity" in c.about.lower() for c in found)


def test_each_challenge_states_the_counterargument_not_only_the_flaw():
    """ "This is unsupported" tells the reader nothing they can act on."""
    from ai.core import challenge

    for c in challenge(_reasoning(assumptions=("Liquidity will hold into the close.",)), now=NOW):
        assert len(c.counterargument) > 30, c.counterargument


def test_a_thesis_resting_only_on_recollection_is_challenged():
    """A model's recollection is the weakest thing that is still evidence. A
    conclusion built entirely on it should say so before somebody trades it."""
    from ai.core import challenge

    weak = _reasoning(evidence=(_ev("I recall the ledger balanced", "recalled"),))
    assert any("recall" in c.about.lower() or "sourced" in c.about.lower() for c in challenge(weak, now=NOW))


def test_a_thesis_resting_only_on_stale_readings_is_challenged():
    from ai.core import challenge

    stale = _reasoning(evidence=(_ev("Balanced four hours ago", minutes_old=600),))
    assert any(
        "stale" in c.counterargument.lower() or "old" in c.counterargument.lower() for c in challenge(stale, now=NOW)
    )


def test_a_confidence_that_outruns_its_evidence_is_challenged():
    """0.95 on one recalled claim is a number describing a feeling."""
    from ai.core import challenge

    overconfident = _reasoning(
        confidence=0.95,
        confidence_basis="It feels right.",
        evidence=(_ev("something", "recalled"),),
        counter_evidence=(),
    )
    assert any("confidence" in c.about.lower() for c in challenge(overconfident, now=NOW))


def test_an_argument_with_no_evidence_against_it_is_challenged():
    """Not because it is wrong, but because nobody looked."""
    from ai.core import challenge

    onesided = _reasoning(counter_evidence=())
    assert any("against" in c.about.lower() or "counter" in c.about.lower() for c in challenge(onesided, now=NOW))


def test_a_well_supported_argument_is_not_given_invented_weaknesses():
    """A challenger that always finds something is a challenger nobody reads."""
    from ai.core import challenge

    strong = _reasoning(
        assumptions=(),
        evidence=(_ev("a"), _ev("b"), _ev("c")),
        counter_evidence=(_ev("d"), _ev("e")),
        confidence=0.55,
        confidence_basis="Evidence weight, both sides.",
    )
    assert challenge(strong, now=NOW) == []


def test_challenges_are_ordered_worst_first():
    """A list an operator reads top-down has to put the thing that matters at
    the top."""
    from ai.core import challenge

    found = challenge(
        _reasoning(
            assumptions=("Liquidity holds.", "The clock is right."),
            evidence=(_ev("hearsay", "recalled"),),
            counter_evidence=(),
            confidence=0.97,
            confidence_basis="strong feeling",
        ),
        now=NOW,
    )
    assert len(found) >= 2
    severities = [c.severity for c in found]
    assert severities == sorted(severities, key=lambda s: -{"high": 2, "medium": 1, "low": 0}[s])


# ── §5: uncertainty stated honestly, and actually calibrated ──────────────────


def test_a_confidence_nobody_has_checked_is_reported_as_uncalibrated():
    """Reporting 62% as calibrated when no prediction has ever been resolved is
    the fake-precision failure, wearing a decimal point."""
    from ai.core import calibration

    calibration.reset_for_testing()
    report = calibration.assess("risk_compliance", stated=0.62)
    assert report.calibrated is False
    assert report.resolved == 0
    assert "not been checked" in report.note.lower()


def test_calibration_needs_a_real_sample_before_it_claims_anything():
    """Three resolved predictions is a coincidence, not a track record."""
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(3):
        calibration.record("risk_compliance", key=f"k{i}", stated=0.6)
        calibration.resolve("risk_compliance", key=f"k{i}", correct=True)
    assert calibration.assess("risk_compliance", stated=0.6).calibrated is False


def test_overconfidence_is_named_once_there_is_a_record():
    """Said 90%, right half the time. That is the single most useful thing a
    calibration record can tell an operator."""
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(20):
        calibration.record("risk_compliance", key=f"k{i}", stated=0.9)
        calibration.resolve("risk_compliance", key=f"k{i}", correct=i % 2 == 0)

    report = calibration.assess("risk_compliance", stated=0.9)
    assert report.calibrated is True
    assert report.observed == pytest.approx(0.5, abs=0.01)
    assert "overconfident" in report.note.lower()


def test_underconfidence_is_named_too():
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(20):
        calibration.record("research", key=f"k{i}", stated=0.3)
        calibration.resolve("research", key=f"k{i}", correct=True)
    assert "underconfident" in calibration.assess("research", stated=0.3).note.lower()


def test_a_well_calibrated_agent_is_said_to_be_well_calibrated():
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(20):
        calibration.record("risk_compliance", key=f"k{i}", stated=0.7)
        calibration.resolve("risk_compliance", key=f"k{i}", correct=i % 10 < 7)
    report = calibration.assess("risk_compliance", stated=0.7)
    assert report.calibrated is True
    assert abs(report.observed - 0.7) < 0.05


def test_calibration_never_rewrites_the_stated_confidence():
    """Silently adjusting a figure the author put their name to is worse than
    reporting that the author is usually optimistic."""
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(20):
        calibration.record("a", key=f"k{i}", stated=0.9)
        calibration.resolve("a", key=f"k{i}", correct=False)
    report = calibration.assess("a", stated=0.9)
    assert report.stated == 0.9


def test_an_unresolved_prediction_does_not_count():
    """Otherwise every open question reads as a wrong answer."""
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(20):
        calibration.record("a", key=f"k{i}", stated=0.8)
    assert calibration.assess("a", stated=0.8).resolved == 0


def test_one_agents_record_does_not_taint_another():
    from ai.core import calibration

    calibration.reset_for_testing()
    for i in range(20):
        calibration.record("careless", key=f"k{i}", stated=0.9)
        calibration.resolve("careless", key=f"k{i}", correct=False)
    assert calibration.assess("careful", stated=0.9).resolved == 0


def test_resolving_something_never_recorded_is_refused_rather_than_invented():
    from ai.core import calibration

    calibration.reset_for_testing()
    assert calibration.resolve("a", key="never-seen", correct=True) is False


def test_the_same_prediction_cannot_be_resolved_twice():
    """Otherwise a resolved-twice win doubles an agent's apparent accuracy."""
    from ai.core import calibration

    calibration.reset_for_testing()
    calibration.record("a", key="k", stated=0.8)
    assert calibration.resolve("a", key="k", correct=True) is True
    assert calibration.resolve("a", key="k", correct=True) is False


# ── §5: conversation context across active tasks ──────────────────────────────


def test_the_conversation_knows_what_is_still_running():
    """ "Is the backtest done?" is unanswerable if the conversation has no idea a
    backtest was started."""
    from ai.core import context

    context.reset_for_testing()
    context.note_task("owner", task_id="j1", summary="Backtest of the mean-reversion strategy")
    assert "Backtest" in context.describe("owner")


def test_a_finished_task_leaves_the_active_list_but_stays_referable():
    """ "How did it go?" arrives after the job ends, not during it."""
    from ai.core import context

    context.reset_for_testing()
    context.note_task("owner", task_id="j1", summary="Backtest")
    context.finish_task("owner", task_id="j1", outcome="Sharpe 1.2 over 3 years")
    described = context.describe("owner")
    assert "nothing running" in described.lower()
    assert "Sharpe 1.2" in described


def test_one_operators_tasks_are_not_in_anothers_context():
    """The cross-operator leak this repository shipped once already, rebuilt on
    the channel that answers questions."""
    from ai.core import context

    context.reset_for_testing()
    context.note_task("alice", task_id="j1", summary="Alice's backtest")
    assert "Alice" not in context.describe("bob")


def test_the_context_says_so_when_there_is_nothing_to_say():
    """An empty string would read as a missing feature rather than a quiet
    system."""
    from ai.core import context

    context.reset_for_testing()
    assert context.describe("owner").strip() != ""


def test_the_context_does_not_grow_without_limit():
    """A session running for a week must not accumulate a thousand finished
    jobs in every answer."""
    from ai.core import context

    context.reset_for_testing()
    for i in range(200):
        context.note_task("owner", task_id=f"j{i}", summary=f"Task {i}")
        context.finish_task("owner", task_id=f"j{i}", outcome="done")
    assert len(context.describe("owner")) < 2000


# ── it has to run, or it is four modules nobody calls ─────────────────────────


def test_a_submitted_job_reaches_the_conversation_context():
    """`ai/core/context.py` could be perfect and never be written to. The job
    runner is where tasks actually start, and this asserts the bridge fires."""
    import time

    from ai.core import context
    from ai.jobs.runner import JobRunner

    context.reset_for_testing()
    runner = JobRunner(max_concurrent=1)
    try:
        runner.submit(prompt="Backtest the mean-reversion strategy", work=lambda report: "done", operator="owner")
        assert "Backtest" in context.describe("owner")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and context.active("owner"):
            time.sleep(0.02)
        described = context.describe("owner")
        assert "nothing running" in described.lower()
        assert "Backtest" in described, "the finished job stopped being referable"
    finally:
        runner.shutdown()
        context.reset_for_testing()


def test_a_broken_context_store_cannot_stop_work_being_queued():
    """ "Is the backtest done?" being answerable is worth less than the backtest
    running."""
    from ai.core import context as context_module
    from ai.jobs.runner import JobRunner

    original = context_module.note_task
    context_module.note_task = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("context is down"))
    runner = JobRunner(max_concurrent=1)
    try:
        job_id = runner.submit(prompt="still works", work=lambda report: "done", operator="owner")
        assert job_id
    finally:
        context_module.note_task = original
        runner.shutdown()


def test_the_weak_points_are_in_the_proposal_body_a_human_reads():
    """A weakness behind a link is a weakness read after the decision, which is
    the wrong order."""
    from ai.agent.synthesis import Finding, synthesise

    proposal = synthesise(
        subject="XAUUSD exposure",
        findings=[
            Finding("risk_compliance", "concern", "critical", "Daily loss is 4.10% against a 5.00% limit."),
            Finding("markets_execution", "clear", "info", "Positions reconcile with the broker."),
        ],
    ).as_proposal()
    assert "Weak point" in proposal["reason"]


def test_a_broken_challenger_cannot_stop_a_recommendation_reaching_a_human():
    from ai.core import challenger as challenge_module
    from ai.agent.synthesis import Finding, synthesise

    original = challenge_module.challenge
    challenge_module.challenge = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    try:
        proposal = synthesise(subject="s", findings=[Finding("a", "concern", "warning", "something")]).as_proposal()
        assert proposal["reason"]
    finally:
        challenge_module.challenge = original


@pytest.mark.asyncio
async def test_the_endpoints_report_the_rule_they_enforce():
    """An operator reading a calibration figure deserves to see, on the same
    screen, what the figure does and does not mean."""
    from api.ai_core import ai_core_calibration, ai_core_depths
    from api.auth import TokenPayload

    user = TokenPayload(sub="owner", role="superadmin")
    depths = await ai_core_depths(user)
    assert "counter-thesis" in depths["invariant"]
    assert "different argument" in depths["invariant"]

    calib = await ai_core_calibration(user)
    assert "never rewrites" in calib["note"]


@pytest.mark.asyncio
async def test_one_operator_cannot_read_anothers_conversation_through_the_api():
    from ai.core import context
    from api.ai_core import ai_core_conversation_context
    from api.auth import TokenPayload

    context.reset_for_testing()
    context.note_task("alice", task_id="j1", summary="Alice's backtest")
    body = await ai_core_conversation_context(TokenPayload(sub="bob", role="superadmin"))
    assert body["active"] == []
    assert "Alice" not in body["description"]
    context.reset_for_testing()


def test_the_package_does_not_shadow_its_own_submodule():
    """`import ai.core.challenge` used to resolve to the FUNCTION, because
    `from ai.core.challenge import challenge` rebinds the module attribute on
    the package with the callable of the same name. Anyone reaching for the
    module got a function and an AttributeError three lines later. The module is
    `challenger` now, so the collision cannot happen."""
    import importlib

    for name in ("ai.core.challenger", "ai.core.depth", "ai.core.calibration", "ai.core.context"):
        module = importlib.import_module(name)
        assert not callable(module) or hasattr(module, "__file__"), name
        assert module.__name__ == name
