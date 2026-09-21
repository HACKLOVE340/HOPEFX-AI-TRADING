# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What a support answer is allowed to know, and what it must never be told.

`support.answering` composes a FACTS block and instructs the model to state no
figure that is not in it. Nothing filled that block: every reply came from the
department brief alone, so the strictest half of the design was carrying the
whole thing.

This is the gatherer. Its entire design is a refusal list.

## READ_ONLY is not the same as "safe to put in a prompt"

The obvious implementation is "call every implemented READ_ONLY action with no
required arguments". Measured against the real registry, that would have called:

    platform_engineering.scan_secrets      -> secret-scanner findings
    platform_engineering.walk_code         -> source
    platform_engineering.run_tests         -> the test suite, per support ticket
    research_intelligence.run_backtest     -> a backtest, per support ticket
    markets_execution.shadow_place_order   -> a simulated order

The first two are the serious ones. Their output would be pasted into a prompt
sent to a **third-party model**, so a rule that looks like a safety tier
(READ_ONLY) would have been a credential-disclosure path. The risk tier
describes what an action does to the *platform*; it says nothing about what its
OUTPUT is, and the output is what travels.

So `SUPPORT_FACTS` is an allowlist, per department, of facts a customer answer
may use — and a test asserts the excluded ones stay excluded by name.

## Rule 2, at the fact boundary

A handler that raises, times out, or returns something unserialisable
contributes `None`, never a plausible substitute. `_render_facts` prints `None`
as `not measured`, so the model is told the gap exists rather than left to fill
it. That is the same rule `ai/departments/` already follows by returning
`available: False`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestTheAllowlistIsTheDesign:
    def test_every_allowlisted_action_exists_and_is_implemented(self):
        """An allowlisted action nobody built is a fact that is always absent."""
        from ai.departments import DEPARTMENTS
        from support.facts import SUPPORT_FACTS

        for dept, actions in SUPPORT_FACTS.items():
            assert dept in DEPARTMENTS, f"{dept!r} is not a department"
            implemented = {a.name.split(".", 1)[1] for a in DEPARTMENTS[dept].actions if a.handler is not None}
            for action in actions:
                assert action in implemented, f"{dept}.{action} is allowlisted but not implemented"

    def test_every_allowlisted_action_is_read_only_and_needs_no_approval(self):
        from ai.departments import DEPARTMENTS
        from support.facts import SUPPORT_FACTS

        for dept, actions in SUPPORT_FACTS.items():
            by_name = {a.name.split(".", 1)[1]: a for a in DEPARTMENTS[dept].actions}
            for action in actions:
                a = by_name[action]
                assert str(a.risk) == "read_only", f"{dept}.{action} is {a.risk}"
                assert a.requires_approval is False

    @pytest.mark.parametrize(
        ("dept", "action"),
        [
            ("platform_engineering", "scan_secrets"),
            ("platform_engineering", "walk_code"),
            ("platform_engineering", "run_tests"),
            ("research_intelligence", "run_backtest"),
            ("research_intelligence", "walk_forward_validate"),
            ("markets_execution", "shadow_place_order"),
            ("markets_execution", "shadow_cancel_order"),
        ],
    )
    def test_the_dangerous_read_only_actions_stay_out(self, dept: str, action: str):
        """Named individually so removing one is a deliberate act, not a diff.

        `scan_secrets` and `walk_code` are the reason this list exists: their
        output would reach a third-party model.
        """
        from support.facts import SUPPORT_FACTS

        assert action not in SUPPORT_FACTS.get(dept, ()), (
            f"{dept}.{action} would put its output into a prompt sent to a hosted model"
        )

    def test_no_allowlisted_fact_is_structurally_unmeasurable(self):
        """Found by running the gatherer against the real registry, not by reading.

        `news_intelligence.score_geopolitical_risk` was allowlisted and answered
        `nothing to score: 'text' was empty` — for every ticket, forever, because
        the text to score is an argument this desk will not invent. A fact that
        can never be measured is noise in a billed prompt and a control that can
        never fire.
        """
        from support.facts import SUPPORT_FACTS

        assert "score_geopolitical_risk" not in SUPPORT_FACTS.get("news_intelligence", ())

    def test_a_department_with_nothing_useful_declares_nothing(self):
        """Better an empty fact block than a fact nobody needed.

        `platform_engineering` answers "how do I enable 2FA". No measurement
        helps, and the only actions it has are the ones that must not travel.
        """
        from support.facts import SUPPORT_FACTS

        assert SUPPORT_FACTS.get("platform_engineering", ()) == ()


class TestGathering:
    def test_it_returns_a_value_per_allowlisted_action(self):
        from support.facts import gather_facts

        with patch("support.facts._call_action", return_value={"connected": True}):
            facts = gather_facts("data_ops")

        assert set(facts) == {"feed_health", "stale_sources"}
        assert facts["feed_health"] == {"connected": True}

    def test_an_unknown_department_gathers_nothing(self):
        from support.facts import gather_facts

        assert gather_facts("no_such_department") == {}

    def test_none_department_gathers_nothing(self):
        from support.facts import gather_facts

        assert gather_facts(None) == {}


class TestAFailedMeasurementIsAbsentNotGuessed:
    def test_a_handler_that_raises_contributes_none(self):
        from support.facts import gather_facts

        with patch("support.facts._call_action", side_effect=RuntimeError("broker down")):
            facts = gather_facts("markets_execution")

        assert facts == {"query_broker_status": None}, (
            "a failed measurement produced something other than 'not measured'"
        )

    def test_the_failure_is_logged_at_error(self, caplog):
        """A fact gatherer that silently returns nothing looks like a system
        with nothing to report — F248's shape."""
        import logging

        from support.facts import gather_facts

        with caplog.at_level(logging.DEBUG, logger="support.facts"):
            with patch("support.facts._call_action", side_effect=RuntimeError("broker down")):
                gather_facts("markets_execution")

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors and "broker down" in errors[0].getMessage()

    def test_a_partial_failure_keeps_the_facts_that_worked(self):
        """One dead department action must not blank the whole block."""
        from support.facts import gather_facts

        def flaky(dept: str, action: str):
            if action == "stale_sources":
                raise RuntimeError("nope")
            return {"ok": True}

        with patch("support.facts._call_action", side_effect=flaky):
            facts = gather_facts("data_ops")

        assert facts["feed_health"] == {"ok": True}
        assert facts["stale_sources"] is None

    def test_an_unserialisable_value_becomes_absent(self):
        """A value that cannot be rendered is not a value."""
        from support.facts import gather_facts

        with patch("support.facts._call_action", return_value=object()):
            facts = gather_facts("markets_execution")

        assert facts["query_broker_status"] is None

    def test_a_huge_value_is_not_pasted_into_the_prompt(self):
        """Prompt cost is billed, and a 200KB fact is not a fact anyone reads."""
        from support.facts import gather_facts

        with patch("support.facts._call_action", return_value={"blob": "x" * 200_000}):
            facts = gather_facts("markets_execution")

        assert len(repr(facts["query_broker_status"])) < 4_000


class TestTheAnswerUsesThem:
    def test_answer_question_gathers_when_no_facts_are_passed(self):
        from support.answering import answer_question

        with (
            patch("support.answering._gather", return_value={"broker_connected": True}) as g,
            patch("support.answering._call_gateway") as gw,
        ):
            gw.return_value = type("R", (), {"text": "ok", "provider": "p", "model": "m"})()
            answer_question("why was my order rejected by the broker")

        assert g.call_count == 1
        assert "broker_connected" in gw.call_args.kwargs["prompt"]

    def test_explicit_facts_are_not_overwritten_by_gathering(self):
        """A caller that measured something itself is the authority."""
        from support.answering import answer_question

        with (
            patch("support.answering._gather") as g,
            patch("support.answering._call_gateway") as gw,
        ):
            gw.return_value = type("R", (), {"text": "ok", "provider": "p", "model": "m"})()
            answer_question("why was my order rejected", facts={"mine": 1})

        assert g.call_count == 0
        assert "mine" in gw.call_args.kwargs["prompt"]

    def test_an_empty_dict_means_deliberately_no_facts(self):
        """`{}` is a decision; `None` is "go and find out"."""
        from support.answering import answer_question

        with (
            patch("support.answering._gather") as g,
            patch("support.answering._call_gateway") as gw,
        ):
            gw.return_value = type("R", (), {"text": "ok", "provider": "p", "model": "m"})()
            answer_question("why was my order rejected", facts={})

        assert g.call_count == 0

    def test_an_escalated_question_gathers_nothing(self):
        """No measurement, no spend, no model call — the floor returns first."""
        from support.answering import answer_question

        with patch("support.answering._gather") as g:
            result = answer_question("I want a refund")

        assert g.call_count == 0
        assert result.available is False

    def test_a_gatherer_that_explodes_does_not_take_the_answer_down(self):
        """The facts are an improvement to the answer, not a precondition."""
        from support.answering import answer_question

        with (
            patch("support.answering._gather", side_effect=RuntimeError("registry broken")),
            patch("support.answering._call_gateway") as gw,
        ):
            gw.return_value = type("R", (), {"text": "ok", "provider": "p", "model": "m"})()
            result = answer_question("why was my order rejected by the broker")

        assert result.available is True
        assert "not measured" in gw.call_args.kwargs["prompt"] or "none supplied" in gw.call_args.kwargs["prompt"]


class TestWhatCountsAsAValue:
    """`default=str` makes everything serialisable, which is the bug.

    The first `_renderable` used `json.dumps(value, default=str)`, so a bare
    `object()` became `"<object object at 0x7f...>"`: the check passed and a
    memory address was on its way to a hosted model as a measurement.
    """

    def test_a_timestamp_survives_because_it_is_a_fact(self):
        import datetime as dt

        from support.facts import _renderable

        stamp = dt.datetime(2026, 9, 10, 4, 0, 0)
        assert _renderable({"last_tick": stamp}) == {"last_tick": stamp}

    def test_a_decimal_survives(self):
        from decimal import Decimal

        from support.facts import _renderable

        assert _renderable({"drawdown_pct": Decimal("5.40")}) is not None

    def test_an_arbitrary_object_does_not(self):
        from support.facts import _renderable

        assert _renderable({"thing": object()}) is None

    def test_a_repr_is_never_substituted_for_a_measurement(self):
        """The failure mode in one line: no memory address may reach a prompt."""
        from support.facts import _renderable

        assert "object at 0x" not in repr(_renderable(object()))


class TestTheSeamAndTheBudgetAreRealWiring:
    """The two paths the mocked tests above step over."""

    def test_it_calls_the_real_handler_the_registry_declares(self):
        """`_call_action` is patched everywhere else; exercised once for real,
        or nothing here proves a department is ever reached."""
        from support.facts import _call_action

        result = _call_action("markets_execution", "query_broker_status")

        assert isinstance(result, dict)
        # The department's own honesty flows straight through: it reports
        # `available` rather than inventing a broker state.
        assert "available" in result

    def test_an_action_with_no_handler_raises_rather_than_returning_a_blank(self):
        from support.facts import _call_action

        with pytest.raises(LookupError):
            _call_action("markets_execution", "place_order")

    def test_an_operator_argument_is_supplied_and_nothing_else_is(self):
        """`operator` is this caller's real identity. Every other argument
        would have to be invented, so those actions are not allowlisted."""
        from support.facts import FACT_OPERATOR, _call_action

        seen: dict[str, object] = {}

        def handler(*, operator):
            seen["operator"] = operator
            return {"ok": True}

        class _A:
            name = "system_ops.service_health"

        _A.handler = staticmethod(handler)

        with patch("ai.departments.DEPARTMENTS", {"system_ops": type("D", (), {"actions": (_A,)})}):
            _call_action("system_ops", "service_health")

        assert seen["operator"] == FACT_OPERATOR

    def test_a_spent_budget_records_absence_rather_than_omitting_the_key(self):
        """A key that simply vanishes lets the model assume the department had
        nothing to say. Absent is a value; missing is not."""
        from support.facts import gather_facts

        with patch("support.facts._call_action", return_value={"ok": True}):
            facts = gather_facts("data_ops", budget_s=-1.0)

        assert facts == {"feed_health": None, "stale_sources": None}

    def test_the_spent_budget_is_logged_at_error(self, caplog):
        import logging

        from support.facts import gather_facts

        with caplog.at_level(logging.DEBUG, logger="support.facts"):
            with patch("support.facts._call_action", return_value={"ok": True}):
                gather_facts("data_ops", budget_s=-1.0)

        assert [r for r in caplog.records if r.levelno >= logging.ERROR]
