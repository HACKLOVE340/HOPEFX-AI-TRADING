# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Decision Ledger — Group 3 Chapter 7.

Where an ADR records a *design* decision by a human, this records an
*operational* decision by the system: which model was chosen, which agent was
trusted, which recommendation was accepted, which action was refused.

The spec's own diagnosis of why it is needed: the components already record
their own decisions in their own shapes, and that is precisely why nobody can
answer "what did the platform decide today?" `ai/gateway/audit.py` has model
calls, `ai/improve/proposal.py` has AI-proposed changes, approvals live in pull
requests. One schema across all actors is what turns per-component logging into
a ledger.

## The three properties worth testing, and what each prevents

**Refusals are entries, not absences.** A ledger of actions taken cannot
distinguish a system that was never asked from one that refused — and on a
governed platform the refusals are the evidence that governance worked. A
refusal must also name the control that produced it; "something said no" is not
evidence.

**A prediction is required.** Chapter 8 makes it load-bearing: without a stated
expectation an observed outcome has nothing to be compared against, and
"learning" degrades into narrative. So a decision that can have an outcome
cannot be recorded without saying what it expects.

**Unmeasured stays unmeasured.** Confidence is `None` when nobody stated one,
never 0.5, and its calibration class is `None` with it. This is the defect this
repository has spent the most time removing, and a governance record is the
worst place to reintroduce it.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from ai.ledger import decisions


@pytest.fixture(autouse=True)
def _clean():
    decisions.reset_for_testing()
    yield
    decisions.reset_for_testing()


def a_decision(**overrides):
    payload = {
        "actor": "router",
        "actor_kind": "system",
        "authority_tier": "propose",
        "context": "which model answers this prompt",
        "options": ("local-7b", "gateway-opus"),
        "chosen": "gateway-opus",
        "prediction": "the answer will pass validation on the first attempt",
    }
    payload.update(overrides)
    return decisions.record(**payload)


class TestARefusalIsAnEntry:
    def test_a_refusal_is_recorded(self) -> None:
        entry = decisions.refuse(
            actor="risk-manager",
            actor_kind="system",
            authority_tier="execute",
            context="size a XAU_USD position",
            options=("size 0.4 lots", "refuse"),
            by="data_quality:unmeasured",
        )
        assert entry.refused is True
        assert entry.refused_by == "data_quality:unmeasured"
        assert entry.chosen is None
        assert len(decisions.entries()) == 1

    def test_a_refusal_must_name_the_control(self) -> None:
        # "Something said no" is not evidence that governance worked.
        with pytest.raises(ValueError, match="control"):
            decisions.refuse(
                actor="risk-manager",
                actor_kind="system",
                authority_tier="execute",
                context="size a position",
                options=("size it", "refuse"),
                by="   ",
            )

    def test_refusals_are_counted_apart_from_decisions(self) -> None:
        a_decision()
        decisions.refuse(
            actor="gate",
            actor_kind="system",
            authority_tier="execute",
            context="c",
            options=("a", "b"),
            by="kill_switch",
        )
        summary = decisions.summary()
        assert summary["total"] == 2
        assert summary["refused"] == 1
        assert summary["decided"] == 1

    def test_a_refusal_needs_no_prediction(self) -> None:
        """Nothing happened, so there is no outcome to compare against."""
        entry = decisions.refuse(
            actor="gate",
            actor_kind="system",
            authority_tier="execute",
            context="c",
            options=("a", "b"),
            by="kill_switch",
        )
        assert entry.prediction is None


class TestAPredictionIsRequired:
    def test_a_decision_without_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match="prediction"):
            a_decision(prediction="")

    def test_the_prediction_is_kept_verbatim(self) -> None:
        entry = a_decision(prediction="latency under 900ms")
        assert entry.prediction == "latency under 900ms"


class TestTheChosenOptionMustHaveBeenAnOption:
    def test_choosing_something_unlisted_is_refused(self) -> None:
        # A record saying the system picked something it never considered is
        # worse than no record: it is a false account of how it decided.
        with pytest.raises(ValueError, match="not among the options"):
            a_decision(chosen="a-third-model")

    def test_no_options_at_all_is_refused(self) -> None:
        with pytest.raises(ValueError, match="option"):
            a_decision(options=())

    def test_one_option_is_allowed_and_is_not_the_adr_rule(self) -> None:
        """Deliberately unlike `scripts/adr.py`, which demands two.

        An ADR records a human weighing paths; one option there means the record
        is justification written afterwards. An automated router legitimately has
        one candidate when the others are unavailable, and forcing a second would
        make the ledger record a choice nobody had.
        """
        entry = a_decision(options=("local-7b",), chosen="local-7b")
        assert entry.options == ("local-7b",)


class TestUnmeasuredStaysUnmeasured:
    def test_confidence_defaults_to_none_not_a_half(self) -> None:
        entry = a_decision()
        assert entry.confidence is None
        assert entry.calibration_class is None

    def test_a_stated_confidence_carries_a_calibration_class(self) -> None:
        entry = a_decision(confidence=0.82)
        assert entry.confidence == pytest.approx(0.82)
        assert entry.calibration_class, "a stated confidence with no calibration class is half a record"

    @pytest.mark.parametrize("bad", [-0.1, 1.4, float("nan")])
    def test_an_impossible_confidence_is_refused(self, bad: float) -> None:
        with pytest.raises(ValueError):
            a_decision(confidence=bad)


class TestAuthorityTiersAreTheRealOnes:
    @pytest.mark.parametrize("tier", ["view", "propose", "approve", "execute"])
    def test_every_real_tier_is_accepted(self, tier: str) -> None:
        assert a_decision(authority_tier=tier).authority_tier == tier

    def test_an_invented_tier_is_refused(self) -> None:
        # A typo must not create a tier nobody enforces.
        with pytest.raises(ValueError, match="authority tier"):
            a_decision(authority_tier="superuser")

    def test_the_tiers_come_from_the_policy_module(self) -> None:
        from ai.policy import roles

        assert set(decisions.AUTHORITY_TIERS) == {roles.VIEW, roles.PROPOSE, roles.APPROVE, roles.EXECUTE}


class TestAppendOnly:
    def test_entries_returns_copies(self) -> None:
        a_decision()
        first = decisions.entries()
        first.clear()
        assert len(decisions.entries()) == 1

    def test_a_recorded_entry_cannot_be_mutated(self) -> None:
        import dataclasses

        entry = a_decision()
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.context = "something else"  # type: ignore[misc]

    def test_ids_are_unique(self) -> None:
        ids = {a_decision().id for _ in range(20)}
        assert len(ids) == 20


class TestCredentialsNeverReachADurableRecord:
    def test_a_credential_in_the_context_is_refused(self, monkeypatch) -> None:
        from ai.guardrails import output as guardrails

        monkeypatch.setattr(guardrails, "_KNOWN", {"broker_token": "sk-live-abc123"}, raising=False)
        with pytest.raises(guardrails.GuardrailViolation):
            a_decision(context="retry with token sk-live-abc123")
