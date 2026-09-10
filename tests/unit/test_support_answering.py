# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The support AI answers from facts it was given, or says it cannot.

`support.triage` picks a department; `support.tickets` records the conversation.
Neither produces a reply. This is the layer that does — and the whole of its
design is what it refuses to do.

Three refusals, each with a failure it prevents:

1. **It never answers an escalated ticket.** No model call at all. The floor
   sent that ticket to a person; drafting a reply for it puts a plausible
   answer in front of an operator who is about to paste it.
2. **No reachable model means no answer.** Not a canned fallback, not a
   templated "we are looking into it". A deployment with no gateway leg gets
   `available=False` and the ticket goes to a person. A support desk that
   invents a reply when the AI is down is worse than one that admits it is
   down, because the customer cannot tell the difference.
3. **A fact the department could not measure is stated as unavailable**, and
   never dropped. Dropping it hands the model a gap to fill.

The "different AI in different aspects" the owner asked for is
`DEPARTMENT_BRIEFS`: each department gets its own instructions and its own
limits, and every brief is checked here for the sentence that stops it
inventing numbers.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def answered():
    """A gateway that returns a fixed reply, so the surrounding rules are what
    is under test rather than a model's wording."""
    from ai.gateway.client import ModelResponse

    response = ModelResponse(
        text="You can enable two-factor authentication in Settings → Security.",
        provider="anthropic",
        model="test-model",
        latency_ms=12.0,
    )
    with patch("support.answering._call_gateway", return_value=response) as call:
        yield call


@pytest.fixture
def no_gateway():
    from ai.gateway.client import NoProviderAvailable

    with patch(
        "support.answering._call_gateway",
        side_effect=NoProviderAvailable("no credentialed leg and no local runtime"),
    ):
        yield


class TestItNeverAnswersAnEscalatedTicket:
    def test_an_escalated_question_gets_no_answer(self, answered):
        from support.answering import answer_question

        result = answer_question("withdraw my balance to my bank account")

        assert result.available is False
        assert result.text is None
        assert result.needs_human is True

    def test_and_the_model_is_not_even_called(self, answered):
        """Cheapest possible refusal, and the one that matters most.

        A drafted reply on an escalated ticket is a plausible answer sitting in
        front of an operator who is about to paste it.
        """
        from support.answering import answer_question

        answer_question("should I buy gold right now?")

        assert answered.call_count == 0, "the gateway was asked about an escalated ticket"

    def test_an_escalation_that_names_a_department_is_still_refused(self, answered):
        """The test that the first version of this class did not have.

        Deleting the escalation branch entirely left all sixteen tests green:
        an escalated `TriageResult` carries `department=None`, so execution fell
        into the unroutable branch and returned a refusal that satisfied every
        assertion — for a completely different reason.

        Triage returning a department alongside an escalation is a plausible
        change (an operator wants to know whose queue it belongs in), and it
        would have turned that accident into a model call on a ticket the floor
        had already sent to a person. So this pins the escalation branch
        directly, with a decision the fallthrough cannot rescue.
        """
        from unittest.mock import patch

        from support.triage import TriageResult

        escalated_with_department = TriageResult(
            category="account_or_money",
            department="platform_engineering",
            needs_human=True,
            escalation_reason="Anything that moves money is a human action here.",
            confidence=1.0,
            matched_on="refund",
        )

        from support.answering import answer_question

        with patch("support.answering.triage", return_value=escalated_with_department):
            result = answer_question("I want a refund")

        assert answered.call_count == 0, (
            "the gateway was asked about an escalated ticket — the refusal is coming from "
            "the unroutable branch by accident, not from the floor"
        )
        assert result.available is False
        assert result.needs_human is True
        assert "human action" in (result.unavailable_reason or ""), (
            "the refusal did not carry the escalation's own reason"
        )

    def test_the_refusal_carries_the_escalation_reason(self, answered):
        """The floor's own words, not a generic "a person will look at this".

        Asserted against the reason `triage` produced rather than merely that
        the field is non-empty: the unroutable branch also fills it, and a test
        that cannot tell them apart cannot tell which control fired.
        """
        from support.answering import answer_question
        from support.triage import triage

        question = "someone else logged into my account"
        result = answer_question(question)

        assert result.needs_human is True
        assert result.unavailable_reason == triage(question).escalation_reason


class TestNoModelMeansNoAnswer:
    def test_an_unreachable_gateway_does_not_produce_a_reply(self, no_gateway):
        from support.answering import answer_question

        result = answer_question("how do I enable two factor authentication")

        assert result.available is False
        assert result.text is None

    def test_it_says_the_ai_is_unavailable_rather_than_inventing_one(self, no_gateway):
        """A desk that invents a reply when the AI is down is worse than one
        that admits it: the customer cannot tell the difference."""
        from support.answering import answer_question

        result = answer_question("how do I enable two factor authentication")

        assert result.unavailable_reason
        assert result.needs_human is True, "an unanswerable ticket must reach a person"

    def test_a_provider_error_is_not_an_answer_either(self):
        from ai.gateway.client import ProviderError
        from support.answering import answer_question

        with patch("support.answering._call_gateway", side_effect=ProviderError("timeout")):
            result = answer_question("how do I enable two factor authentication")

        assert result.available is False
        assert result.text is None

    def test_an_empty_model_reply_is_not_an_answer(self, answered):
        """A blank completion is a failure that looks like a success."""
        from ai.gateway.client import ModelResponse
        from support.answering import answer_question

        answered.return_value = ModelResponse(text="   ", provider="p", model="m", latency_ms=1.0)
        result = answer_question("how do I enable two factor authentication")

        assert result.available is False


class TestAnAnswerSaysWhereItCameFrom:
    def test_it_records_the_department_provider_and_model(self, answered):
        from support.answering import answer_question

        result = answer_question("what timeframes does the backtester support")

        assert result.available is True
        assert result.department == "research_intelligence"
        assert result.provider == "anthropic"
        assert result.model == "test-model"

    def test_an_unroutable_question_reaches_a_person_not_a_generalist(self, answered):
        from support.answering import answer_question

        result = answer_question("zzzz qqqq")

        assert result.available is False
        assert result.needs_human is True
        assert answered.call_count == 0


class TestTheDepartmentBriefs:
    def test_every_routed_department_has_a_brief(self):
        """A department with no brief would be answered by a generic assistant
        with no limits — the opposite of what was asked for."""
        from support.answering import DEPARTMENT_BRIEFS
        from support.triage import DEPARTMENT_ROUTES

        for category, dept in DEPARTMENT_ROUTES.items():
            assert dept in DEPARTMENT_BRIEFS, f"{category!r} routes to {dept!r}, which has no brief"

    def test_every_brief_exists_as_a_real_department(self):
        from ai.departments import DEPARTMENTS
        from support.answering import DEPARTMENT_BRIEFS

        for dept in DEPARTMENT_BRIEFS:
            assert dept in DEPARTMENTS, f"brief for {dept!r}, which is not a department"

    def test_the_briefs_differ_from_one_another(self):
        """ "Different AI in different aspects" is not one prompt with a name
        substituted into it."""
        from support.answering import DEPARTMENT_BRIEFS

        assert len(set(DEPARTMENT_BRIEFS.values())) == len(DEPARTMENT_BRIEFS)


class TestThePromptCannotInviteAGuess:
    def test_the_prompt_carries_the_no_invented_figures_rule(self, answered):
        from support.answering import NO_INVENTED_FIGURES, answer_question

        answer_question("what timeframes does the backtester support")

        prompt = answered.call_args.kwargs["prompt"]
        assert NO_INVENTED_FIGURES in prompt

    def test_a_fact_the_department_could_not_measure_is_stated_not_dropped(self, answered):
        """Dropping it hands the model a gap to fill.

        This is the same rule as `ai/departments/`' `available: False`: an
        unmeasured value is absent, never best-case.
        """
        from support.answering import answer_question

        answer_question(
            "why was my order rejected",
            facts={"broker_connected": True, "last_heartbeat": None},
        )

        prompt = answered.call_args.kwargs["prompt"]
        assert "last_heartbeat" in prompt
        assert "not measured" in prompt

    def test_the_customer_question_is_not_the_whole_prompt(self, answered):
        """A bare question with no brief is a generic assistant."""
        from support.answering import answer_question

        answer_question("what timeframes does the backtester support")

        prompt = answered.call_args.kwargs["prompt"]
        assert "what timeframes does the backtester support" in prompt
        assert len(prompt) > 200


class TestAnsweringCannotAct:
    def test_it_has_no_send_or_execute_surface(self):
        import support.answering as mod

        forbidden = {"send", "execute", "place_order", "close_position", "refund", "resolve"}
        assert not ({n for n in dir(mod) if not n.startswith("_")} & forbidden)


class TestTheGuardAgainstAGeneralistAnswer:
    """A branch today's `triage` cannot reach, proven able to fire anyway.

    `triage` sets `needs_human` whenever it has no department, so the
    "routable but unowned" branch is unreachable through the real function —
    coverage showed it as a never-executed line, which is the shape
    `hopefx-dead-controls` catalogues as a guard that can never open.

    Deleting it is the wrong fix. It is the last thing standing between a
    future triage change and `_build_prompt(department=None)`, which composes
    the fallback brief and lets a generalist answer a question nobody owns. So
    it stays, and this test puts the system in the state that opens it.
    """

    def test_a_question_with_no_department_is_never_answered_by_a_generalist(self, answered):
        from unittest.mock import patch

        from support.answering import answer_question
        from support.triage import TriageResult

        unowned = TriageResult(
            category="something_new",
            department=None,
            needs_human=False,
            escalation_reason=None,
            confidence=1.0,
            matched_on="something",
        )

        with patch("support.answering.triage", return_value=unowned):
            result = answer_question("a question about something new")

        assert answered.call_count == 0, "a generalist answered a question no department owns"
        assert result.available is False
        assert result.needs_human is True


class TestTheGatewaySeamIsRealWiring:
    def test_it_reaches_the_gateway_with_the_fast_role_and_the_prompt(self):
        """The seam every other test patches, exercised once against the real
        construction — otherwise nothing here proves a model is ever reached."""
        from unittest.mock import patch

        from support.answering import _call_gateway

        with patch("ai.gateway.client.GatewayClient") as client:
            _call_gateway(prompt="hello", operator="support_desk", timeout_s=5.0)

        request = client.return_value.call_sync.call_args.args[0]
        assert request.role == "fast"
        assert request.prompt == "hello"
        assert request.timeout_s == 5.0
        assert client.return_value.call_sync.call_args.kwargs["operator"] == "support_desk"


class TestTheAnswerIsSerialisable:
    def test_an_answer_renders_for_an_api(self, answered):
        from support.answering import answer_question

        payload = answer_question("what timeframes does the backtester support").as_dict()

        assert payload["available"] is True
        assert payload["department"] == "research_intelligence"
        assert payload["text"]

    def test_a_refusal_renders_with_no_text_at_all(self, answered):
        from support.answering import answer_question

        payload = answer_question("I want a refund").as_dict()

        assert payload["available"] is False
        assert payload["text"] is None, "a refusal must not carry a body a UI could render"

    def test_facts_with_no_entries_are_stated_as_such(self, answered):
        """The model is told it has no platform data, rather than shown an
        empty block it can read as 'nothing is wrong'."""
        from support.answering import answer_question

        answer_question("why is the dashboard slow to load", facts={})

        assert "none supplied" in answered.call_args.kwargs["prompt"]
