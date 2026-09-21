# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Outcome and failure memory — Group 3 Chapter 8.

    decision ──► prediction ──► action ──► observed outcome ──► accuracy ──► lesson

Chapter 8's purpose is to make the platform *experienced* rather than merely
knowledgeable, and the field it makes load-bearing is the **prediction**. The
ledger already refuses a decision without one; this is the half that uses it.

## What is actually being defended

**An outcome cannot be attached twice.** A record whose outcome can be revised
is a record that eventually agrees with whoever looked last. Learning from it
would be learning from a retelling.

**An outcome cannot be attached to a refusal.** Nothing was done, so there is
nothing to observe. Allowing it would let a refusal be scored as a wrong call —
which is exactly backwards, and would teach a system to refuse less.

**Accuracy is stated, never inferred from prose.** Comparing a free-text
prediction to a free-text observation is not a measurement, so the caller says
whether the prediction held. What the ledger guarantees is that it was asked.

**Failure memory answers five questions, and the third is required.** "How was
it detected?" is the one usually skipped and the most valuable: a failure found
by a customer and one found by a test are the same failure with very different
lessons.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from ai.ledger import decisions, outcomes


@pytest.fixture(autouse=True)
def _clean():
    decisions.reset_for_testing()
    outcomes.reset_for_testing()
    yield
    decisions.reset_for_testing()
    outcomes.reset_for_testing()


def a_decision(**overrides):
    payload = {
        "actor": "router",
        "actor_kind": "system",
        "authority_tier": "propose",
        "context": "which model answers this prompt",
        "options": ("local-7b", "gateway-opus"),
        "chosen": "gateway-opus",
        "prediction": "the answer passes validation first time",
    }
    payload.update(overrides)
    return decisions.record(**payload)


class TestClosingTheLoop:
    def test_an_outcome_is_attached_to_the_decision(self) -> None:
        entry = a_decision()
        outcomes.observe(entry.id, observed="validation passed", held=True)
        stored = decisions.get(entry.id)
        assert stored is not None and stored.outcome is not None
        assert stored.outcome["observed"] == "validation passed"
        assert stored.outcome["held"] is True

    def test_the_decision_itself_is_unchanged(self) -> None:
        """Append-only: attaching an outcome adds, it does not revise."""
        entry = a_decision()
        outcomes.observe(entry.id, observed="validation passed", held=True)
        stored = decisions.get(entry.id)
        assert stored is not None
        assert (stored.context, stored.chosen, stored.prediction) == (
            entry.context,
            entry.chosen,
            entry.prediction,
        )

    def test_the_prediction_is_carried_into_the_outcome(self) -> None:
        # So the pair can be read without a second lookup, which is what makes
        # "what did we expect, and what happened" answerable from one row.
        entry = a_decision(prediction="latency under 900ms")
        outcomes.observe(entry.id, observed="1400ms", held=False)
        stored = decisions.get(entry.id)
        assert stored is not None and stored.outcome["predicted"] == "latency under 900ms"

    def test_a_lesson_can_be_attached(self) -> None:
        entry = a_decision()
        outcomes.observe(entry.id, observed="1400ms", held=False, lesson="the gateway is slower under load")
        stored = decisions.get(entry.id)
        assert stored is not None and "slower under load" in stored.outcome["lesson"]

    def test_coverage_moves(self) -> None:
        first = a_decision()
        a_decision()
        assert decisions.summary()["outcome_coverage"] == 0.0
        outcomes.observe(first.id, observed="ok", held=True)
        assert decisions.summary()["outcome_coverage"] == pytest.approx(0.5)


class TestWhatCannotBeObserved:
    def test_an_outcome_cannot_be_attached_twice(self) -> None:
        entry = a_decision()
        outcomes.observe(entry.id, observed="ok", held=True)
        with pytest.raises(ValueError, match="already"):
            outcomes.observe(entry.id, observed="actually not ok", held=False)

    def test_a_refusal_cannot_be_scored(self) -> None:
        refusal = decisions.refuse(
            actor="risk-manager",
            actor_kind="system",
            authority_tier="execute",
            context="size a position",
            options=("size it", "refuse"),
            by="data_quality:unmeasured",
        )
        with pytest.raises(ValueError, match="refus"):
            outcomes.observe(refusal.id, observed="nothing happened", held=True)

    def test_an_unknown_decision_is_refused(self) -> None:
        with pytest.raises(KeyError):
            outcomes.observe("not-a-real-id", observed="ok", held=True)

    def test_held_must_be_stated(self) -> None:
        # Accuracy is stated, never inferred from prose: comparing free text to
        # free text is not a measurement.
        entry = a_decision()
        with pytest.raises(TypeError):
            outcomes.observe(entry.id, observed="ok")  # type: ignore[call-arg]


class TestCalibrationIsFedFromRealOutcomes:
    def test_a_stated_confidence_is_resolved_when_the_outcome_lands(self) -> None:
        """The loop the calibration module was built for and never given.

        `ai/core/calibration.py` has `record` and `resolve`; without an outcome
        linkage nothing ever called `resolve`, so every stated confidence stayed
        unscored and `assess` had nothing to assess.
        """
        from ai.core import calibration

        calibration.reset_for_testing()
        entry = a_decision(confidence=0.9)
        outcomes.observe(entry.id, observed="validation passed", held=True)
        # `summary()` is keyed per agent, so read the router's own row.
        assert calibration.summary()["router"]["resolved"] == 1

    def test_a_decision_with_no_confidence_resolves_nothing(self) -> None:
        from ai.core import calibration

        calibration.reset_for_testing()
        entry = a_decision()
        outcomes.observe(entry.id, observed="ok", held=True)
        assert calibration.summary() == {}, "nothing was stated, so nothing should be scored"


class TestFailureMemoryAnswersFiveQuestions:
    FIVE = {
        "what": "the risk gate sized a position on unmeasured data quality",
        "why": "an absent measurement defaulted to a perfect 1.0",
        "detected": "found by reading the code, not by a test or an alert",
        "fixed": "size_order refuses when data quality is unmeasured",
        "prevented": "tests/unit/test_risk_data_quality_is_measured.py, red on the pre-fix tree",
    }

    def test_a_complete_entry_is_recorded(self) -> None:
        entry = outcomes.record_failure(**self.FIVE)
        assert entry.detected.startswith("found by reading")
        assert len(outcomes.failures()) == 1

    @pytest.mark.parametrize("missing", sorted(FIVE))
    def test_every_question_is_required(self, missing: str) -> None:
        payload = dict(self.FIVE)
        payload[missing] = "  "
        with pytest.raises(ValueError, match=missing):
            outcomes.record_failure(**payload)

    def test_how_it_was_detected_is_called_out_by_name(self) -> None:
        """The question usually skipped, and the most valuable.

        A failure found by a customer and one found by a test are the same
        failure with very different lessons, so the refusal says so rather than
        listing a field name.
        """
        payload = dict(self.FIVE)
        payload["detected"] = ""
        with pytest.raises(ValueError) as caught:
            outcomes.record_failure(**payload)
        assert "luck" in str(caught.value) or "detect" in str(caught.value).lower()

    def test_a_failure_can_cite_the_decision_it_came_from(self) -> None:
        entry = a_decision()
        failure = outcomes.record_failure(**self.FIVE, decision_id=entry.id)
        assert failure.decision_id == entry.id

    def test_citing_a_decision_that_does_not_exist_is_refused(self) -> None:
        with pytest.raises(KeyError):
            outcomes.record_failure(**self.FIVE, decision_id="nope")
