# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Who answers a customer, and when a human must.

Owner requirement, 2026-09-10: a support surface where the AI engages, issues
reach a human, and the operator can watch in real time and take over — with
"different AI in different aspects of any question".

The second half already exists. `ai/departments/` holds eleven specialists
(research, markets_execution, risk_compliance, data_ops, news_intelligence,
system_ops, platform_engineering, memory_ops, notification_ops, vision_ops,
voice_interface), each delegating to code that already exists and returning
`available: False` rather than a number it did not get. What was missing is the
customer-facing flow around them: nothing routed a question to a specialist,
and nothing decided when a person had to be involved.

## The floor, and why it is a floor

This is a money-moving platform, so the dangerous failure is not a wrong answer
— it is a *confident* one on a question the AI should never have answered.

    **Some categories always reach a human, whatever the AI's confidence.**

Financial advice, anything touching an account or a withdrawal, a complaint, a
legal or regulatory question, a suspected security incident. Not "escalate when
unsure" — *always*, because an AI that is wrong and confident is exactly the
case a confidence threshold cannot catch.

Modelled on `ai/notify/policy.py`, which enforces its critical floor
structurally rather than by a check somewhere in the middle: the escalation
decision returns before any auto-answer path is reachable, and `TriageResult`
carries no field that could turn it off. These tests enumerate the categories
and assert the floor holds for every one of them, including when the classifier
is maximally confident.
"""

from __future__ import annotations

import pytest


class TestTheEscalationFloor:
    """The rule that makes an AI support desk safe on a trading platform.

    These assertions name the *category* the floor matched, not merely that
    `needs_human` came back True — and that difference was found by running the
    counterfactual rather than by reading the code.

    The first version of this class asserted only `needs_human is True`. Turning
    the floor into a threshold (`if hit is not None and confidence <
    MIN_CONFIDENCE`) left twenty of those assertions green: with the floor
    disabled, "withdraw my balance" matches no *category* either, falls through
    to the unroutable branch, and escalates for an entirely different reason. A
    test that passes against the defect it was written to catch is the F176
    shape — a measurement that cannot fail — and it is no better in a test file
    than in `invariant_coverage.py`.

    So each case now carries the category the floor must attribute it to, and
    `MIXED` below holds the questions that *do* match a routable category: with
    the floor off, those would have been answered by an AI.
    """

    ALWAYS_HUMAN = [
        ("should I buy gold right now?", "financial_advice"),
        ("what should I invest in this week", "financial_advice"),
        ("is XAUUSD going up tomorrow", "financial_advice"),
        ("please close my position for me", "account_or_money"),
        ("withdraw my balance to my bank account", "account_or_money"),
        ("I want to close my account and get a refund", "account_or_money"),
        ("my money is missing and I am reporting you", "legal_or_complaint"),
        ("I am going to take legal action over this loss", "legal_or_complaint"),
        ("someone else has logged into my account", "security_incident"),
        ("I think my API key was stolen", "security_incident"),
    ]

    #: Questions that ALSO match a routable category. Without the floor these
    #: reach a department and get answered — they are the cases that prove the
    #: floor runs, rather than the unroutable fallback standing in for it.
    MIXED = [
        ("should I close my position, my drawdown is nearly at the limit", "account_or_money"),
        ("my order was rejected and I want a refund", "account_or_money"),
        ("the price feed was frozen so I am reporting you to the regulator", "legal_or_complaint"),
        ("someone logged into my dashboard and changed my password", "security_incident"),
        ("should I buy gold based on your sentiment score", "financial_advice"),
    ]

    @pytest.mark.parametrize(("question", "category"), ALWAYS_HUMAN + MIXED)
    def test_these_always_reach_a_human(self, question: str, category: str):
        from support.triage import triage

        result = triage(question)
        assert result.needs_human is True, (
            f"the AI would have answered this on its own: {question!r} "
            f"(category={result.category}, reason={result.escalation_reason})"
        )
        assert result.category == category, (
            f"{question!r} escalated, but as {result.category!r} rather than {category!r} — "
            f"the floor did not catch it; something downstream did"
        )
        assert result.escalation_reason, "an escalation must say why"

    @pytest.mark.parametrize(("question", "category"), ALWAYS_HUMAN + MIXED)
    def test_confidence_cannot_override_the_floor(self, question: str, category: str):
        """A confident classifier must not be able to answer these.

        "Escalate when unsure" is the design that fails here: the dangerous
        case is an AI that is wrong AND certain.
        """
        from support.triage import triage

        result = triage(question, confidence=1.0)
        assert result.needs_human is True
        assert result.category == category

    @pytest.mark.parametrize(("question", "category"), MIXED)
    def test_a_floor_question_is_never_routed_to_a_department(self, question: str, category: str):
        """The floor wins over routing, not the other way round.

        Every question here matches a department rule too. If routing ran first,
        a specialist would answer a refund request or a security incident.
        """
        from support.triage import triage

        result = triage(question)
        assert result.department is None, (
            f"{question!r} was handed to {result.department!r}; the floor must claim it first"
        )

    def test_the_result_cannot_express_an_auto_answer_for_an_escalated_ticket(self):
        """Structural, not a check in the middle of a function."""
        from support.triage import triage

        result = triage("should I buy gold right now?")
        assert result.needs_human is True
        assert result.suggested_reply is None, "an escalated ticket must carry no draft the UI could send by accident"


class TestQuestionsTheAICanTake:
    ANSWERABLE = [
        "how do I enable two factor authentication",
        "what timeframes does the backtester support",
        "where do I find my trade journal",
        "how do I change my email address",
        "what does the drift warning on the dashboard mean",
    ]

    @pytest.mark.parametrize("question", ANSWERABLE)
    def test_a_how_to_question_is_not_escalated_by_default(self, question: str):
        from support.triage import triage

        result = triage(question)
        assert result.needs_human is False, (
            f"{question!r} escalated unnecessarily — a desk that escalates everything is a desk with no AI in it"
        )

    def test_low_confidence_still_escalates(self):
        """The floor is a floor, not a ceiling. Uncertainty escalates too."""
        from support.triage import triage

        assert triage("how do I enable two factor authentication", confidence=0.1).needs_human is True


class TestRoutingToTheRightSpecialist:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("what timeframes does the backtester support", "research_intelligence"),
            ("why was my order rejected by the broker", "markets_execution"),
            ("what is my current drawdown limit", "risk_compliance"),
            ("the price feed looks frozen", "data_ops"),
            ("why is the dashboard slow to load", "system_ops"),
        ],
    )
    def test_a_question_reaches_the_department_that_owns_it(self, question: str, expected: str):
        from support.triage import triage

        assert triage(question).department == expected

    def test_every_routed_department_actually_exists(self):
        """A route to a department nobody built is a dead end at 3am."""
        from ai.departments import DEPARTMENTS
        from support.triage import DEPARTMENT_ROUTES

        for category, dept in DEPARTMENT_ROUTES.items():
            assert dept in DEPARTMENTS, f"category {category!r} routes to unknown department {dept!r}"

    def test_an_unroutable_question_goes_to_a_human_not_a_guess(self):
        """Rule 2 for routing: unknown is not "probably research"."""
        from support.triage import triage

        result = triage("zzzz qqqq")
        assert result.needs_human is True
        assert result.department is None


class TestTheTicketIsAuditable:
    def test_the_result_records_what_it_decided_and_why(self):
        from support.triage import triage

        result = triage("please close my position for me")
        payload = result.as_dict()
        assert set(payload) >= {
            "category",
            "department",
            "needs_human",
            "escalation_reason",
            "confidence",
            "matched_on",
        }

    def test_it_says_what_it_matched_on(self):
        """An operator taking over must see why it was routed here."""
        from support.triage import triage

        result = triage("withdraw my balance to my bank account")
        assert result.matched_on, "the decision gives no evidence for itself"


class TestTriageCannotAct:
    def test_it_has_no_send_or_execute_surface(self):
        """Triage decides who answers. It does not answer, and it cannot trade."""
        import support.triage as mod

        forbidden = {"send", "reply", "execute", "place_order", "close_position", "refund"}
        surface = {n for n in dir(mod) if not n.startswith("_")}
        assert not (surface & forbidden), f"triage can act: {surface & forbidden}"


class TestTheTwoSafetyPathsThatNothingElseExercises:
    """Both branches escalate. Both were unmeasured until this class existed."""

    @pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
    def test_an_empty_message_goes_to_a_person(self, empty: str):
        """A blank ticket is not a routing problem to solve by guessing."""
        from support.triage import triage

        result = triage(empty)
        assert result.needs_human is True
        assert result.category is None
        assert result.department is None

    def test_a_category_with_no_department_escalates_rather_than_improvising(self):
        """A configuration error must surface, not get papered over.

        `DEPARTMENT_ROUTES` losing an entry — a rename, a merge, a department
        retired — must not silently send the ticket to a plausible neighbour.
        """
        from unittest.mock import patch

        import support.triage as mod  # the module, not the re-exported function

        broken = dict(mod.DEPARTMENT_ROUTES)
        del broken["market_data"]

        with patch.object(mod, "DEPARTMENT_ROUTES", broken):
            result = mod.triage("the price feed looks frozen")

        assert result.needs_human is True
        assert result.department is None
        assert result.category == "market_data"
        assert "no department" in (result.escalation_reason or "")


def test_the_package_does_not_shadow_its_own_submodule():
    """`support.triage` must mean the module, whatever `__init__` re-exports.

    It did not, briefly: `__init__` exported the `triage` *function* under the
    same name as the `triage` *module*, and `import support.triage as mod`
    handed back the function. Any caller wanting `DEPARTMENT_ROUTES`,
    `ALWAYS_HUMAN_RULES` or `MIN_CONFIDENCE` off the module hit an
    `AttributeError` that reads like a typo.
    """
    import types

    import support
    import support.triage as mod

    assert isinstance(mod, types.ModuleType), f"support.triage is {type(mod).__name__}, not a module"
    assert isinstance(support.triage, types.ModuleType)
