# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§13 and §15: structured reasoning, opposing perspectives, and the rule that
shapes the whole package — **do not force artificial consensus.**

Every merging function wants to produce an answer. Averaging two confidences,
taking the higher-weighted side, counting heads: each is one line, each always
returns something, and each destroys the single most valuable output a
multi-agent system can produce — the finding that the agents do not agree and
that the evidence does not separate them.

These tests fail on the pre-fix tree: `ai.debate` does not exist there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def _ev(claim: str, quality: str = "measured", *, minutes_old: float | None = 1.0):
    from ai.debate import Evidence, EvidenceQuality

    return Evidence(
        claim=claim,
        source=f"src.{quality}",
        quality=EvidenceQuality(quality),
        observed_at=None if minutes_old is None else NOW - timedelta(minutes=minutes_old),
    )


# ── §15: the eight parts, and the two that get dropped first ──────────────────


def test_a_reasoning_without_a_counter_thesis_will_not_construct():
    """The part that gets dropped first, because it is the part that makes the
    author less persuasive. An omission has to be an error, not a shorter
    paragraph."""
    from ai.debate import Reasoning, ReasoningIncomplete

    with pytest.raises(ReasoningIncomplete) as caught:
        Reasoning(subject="s", thesis="buy", counter_thesis="", what_would_change_it=("x",))
    assert "counter_thesis" in caught.value.missing


def test_a_reasoning_that_cannot_be_changed_by_anything_will_not_construct():
    """The other one. An argument with no stated way to be wrong is not an
    argument, it is an assertion."""
    from ai.debate import Reasoning, ReasoningIncomplete

    with pytest.raises(ReasoningIncomplete) as caught:
        Reasoning(subject="s", thesis="buy", counter_thesis="sell", what_would_change_it=())
    assert "what_would_change_it" in caught.value.missing


def test_it_names_every_missing_part_rather_than_the_first():
    """So a caller can say what to add instead of reporting that something,
    somewhere, was wrong."""
    from ai.debate import Reasoning, ReasoningIncomplete

    with pytest.raises(ReasoningIncomplete) as caught:
        Reasoning(subject="", thesis="", counter_thesis="", what_would_change_it=())
    assert set(caught.value.missing) == {"subject", "thesis", "counter_thesis", "what_would_change_it"}


def test_whitespace_is_not_a_counter_thesis():
    from ai.debate import Reasoning, ReasoningIncomplete

    with pytest.raises(ReasoningIncomplete):
        Reasoning(subject="s", thesis="t", counter_thesis="   ", what_would_change_it=("x",))


def test_a_confidence_with_no_basis_is_refused():
    """A bare 0.8 is a mood. Somebody may size a position against it, and a mood
    formatted as a probability is worse than no figure at all."""
    from ai.debate import Reasoning, ReasoningIncomplete

    with pytest.raises(ReasoningIncomplete) as caught:
        Reasoning(subject="s", thesis="t", counter_thesis="c", what_would_change_it=("x",), confidence=0.8)
    assert "confidence_basis" in caught.value.missing


def test_no_confidence_at_all_is_allowed():
    """§15 says "calibrated confidence WHERE POSSIBLE". Absent is a legitimate
    answer; unfounded is not."""
    from ai.debate import Reasoning

    r = Reasoning(subject="s", thesis="t", counter_thesis="c", what_would_change_it=("x",))
    assert r.confidence is None
    assert r.is_calibrated is False


def test_an_absent_confidence_is_stated_in_words_not_omitted():
    """An omitted line reads as an oversight. The words say it was a decision."""
    from ai.debate import Reasoning

    prose = Reasoning(subject="s", thesis="t", counter_thesis="c", what_would_change_it=("x",)).as_prose()
    assert "not calibrated" in prose


def test_a_confidence_outside_zero_to_one_is_refused():
    from ai.debate import Reasoning

    with pytest.raises(ValueError, match="not a probability"):
        Reasoning(
            subject="s",
            thesis="t",
            counter_thesis="c",
            what_would_change_it=("x",),
            confidence=1.4,
            confidence_basis="because",
        )


def test_the_prose_carries_all_eight_parts():
    from ai.debate import Reasoning

    prose = Reasoning(
        subject="XAUUSD",
        thesis="holds",
        counter_thesis="breaks",
        assumptions=("the feed is honest",),
        missing_information=("no order book depth",),
        evidence=(_ev("held for six hours"),),
        counter_evidence=(_ev("CPI in forty minutes", "reported"),),
        confidence=0.6,
        confidence_basis="evidence weight",
        what_would_change_it=("a hawkish print",),
        risks=("a gap through the stop",),
        alternatives=("wait",),
    ).as_prose()
    for fragment in (
        "Thesis:",
        "Counter-thesis:",
        "Evidence:",
        "Against:",
        "Assuming:",
        "Not known:",
        "Confidence:",
        "Would change it:",
        "Risks:",
        "Alternatives:",
    ):
        assert fragment in prose, f"{fragment} is missing from the prose"


# ── §13: evidence weighted by quality and freshness ───────────────────────────


def test_a_measured_number_outweighs_a_recalled_claim():
    """Treating a model's recollection as equal to a reconciliation is how a
    hallucinated figure ends up outranking the books."""
    from ai.debate import weigh

    measured = weigh(_ev("x", "measured"), now=NOW).weight
    recalled = weigh(_ev("x", "recalled"), now=NOW).weight
    assert measured > recalled * 4


def test_three_recalled_claims_cannot_outvote_one_measured_one():
    """The spread is wide on purpose. A gentle slope makes repetition a
    substitute for sourcing."""
    from ai.debate import weigh

    assert weigh(_ev("x", "measured"), now=NOW).weight > 3 * weigh(_ev("y", "recalled"), now=NOW).weight


def test_old_evidence_is_downweighted_and_marked_not_dropped():
    """Dropping it silently produces a conclusion that looks better supported
    than it is: three strong points on screen, and no sign that the fourth —
    which contradicted them — was merely old."""
    from ai.debate import weigh

    fresh = weigh(_ev("x", minutes_old=1), now=NOW)
    old = weigh(_ev("x", minutes_old=120), now=NOW)
    assert old.weight < fresh.weight
    assert old.weight > 0, "old evidence was deleted rather than downweighted"
    assert old.stale is True
    assert fresh.stale is False


def test_evidence_with_no_timestamp_is_unmeasured_not_fresh():
    """Treating an absent timestamp as "now" makes the least verifiable evidence
    the heaviest, which is exactly backwards."""
    from ai.debate import weigh

    undated = weigh(_ev("x", minutes_old=None), now=NOW)
    fresh = weigh(_ev("x", minutes_old=1), now=NOW)
    assert undated.unmeasured_age is True
    assert undated.stale is True
    assert undated.weight < fresh.weight
    assert undated.age_s is None


def test_evidence_needs_a_source():
    """ "Somebody said" is not attributable, and an unattributable claim cannot be
    weighed at all."""
    from ai.debate import Evidence, EvidenceQuality

    with pytest.raises(ValueError, match="source"):
        Evidence(claim="gold is up", source="  ", quality=EvidenceQuality.MEASURED)


def test_a_naive_timestamp_is_refused_at_construction():
    """Rather than raising a TypeError inside a risk decision, hours later."""
    from ai.debate import Evidence, EvidenceQuality

    with pytest.raises(ValueError, match="timezone-aware"):
        Evidence(
            claim="x",
            source="s",
            quality=EvidenceQuality.MEASURED,
            observed_at=datetime(2026, 3, 10, 12, 0),
        )


# ── §13: no forced consensus ──────────────────────────────────────────────────


def test_a_close_debate_is_unresolved_rather_than_narrowly_won():
    """The rule the whole package is arranged around. Two sides within a few
    percent have not been separated by the evidence, and calling that a
    resolution is artificial consensus wearing a decimal point."""
    from ai.debate import Position, debate

    result = debate(
        subject="hold gold overnight",
        positions=[
            Position(agent="a", stance="for", argument="holds", evidence=(_ev("held all day"),)),
            Position(agent="b", stance="against", argument="breaks", evidence=(_ev("print due"),)),
        ],
        now=NOW,
    )
    assert result.resolved is False
    assert result.leading is None
    assert "does not separate" in result.unresolved_reason


def test_a_decisive_margin_is_called():
    """Unresolved must not be the answer to everything, or it is not a finding."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            Position(
                agent="a",
                stance="for",
                argument="strong",
                evidence=(_ev("a"), _ev("b"), _ev("c")),
            ),
            Position(agent="b", stance="against", argument="weak", evidence=(_ev("d", "recalled"),)),
        ],
        now=NOW,
    )
    assert result.resolved is True
    assert result.leading == "for"


def test_one_stance_is_not_a_debate():
    """Dressing a single position as a debate implies an opposing view was
    sought and found wanting."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            Position(agent="a", stance="for", argument="x", evidence=(_ev("a"),)),
            Position(agent="b", stance="for", argument="y", evidence=(_ev("b"),)),
        ],
        now=NOW,
    )
    assert result.resolved is False
    assert "No opposing perspective" in result.unresolved_reason


def test_a_side_resting_on_nothing_cannot_win():
    """A position with no evidence has not made an argument."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            Position(agent="a", stance="for", argument="I think so"),
            Position(agent="b", stance="against", argument="measured", evidence=(_ev("x"),)),
        ],
        now=NOW,
    )
    assert result.leading != "for"


def test_an_unsupported_position_is_recorded_rather_than_dropped():
    """An unsupported dissent is still a fact about what the workforce believes."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            Position(agent="a", stance="for", argument="I think so"),
            Position(agent="b", stance="against", argument="measured", evidence=(_ev("x"), _ev("y"))),
        ],
        now=NOW,
    )
    unsupported = [p for p in result.positions if p.unsupported]
    assert len(unsupported) == 1
    assert unsupported[0].position.agent == "a"
    assert "no evidence offered" in result.as_prose()


def test_headcount_does_not_beat_evidence():
    """Four agents recalling the same unsourced claim must not outrank one agent
    with a measured number, and a majority vote makes that inevitable."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            *[
                Position(
                    agent=f"crowd{i}", stance="against", argument="I recall", evidence=(_ev("hearsay", "recalled"),)
                )
                for i in range(4)
            ],
            Position(
                agent="measurer",
                stance="for",
                argument="the books say",
                evidence=(_ev("reconciled"), _ev("also reconciled")),
            ),
        ],
        now=NOW,
    )
    assert result.leading == "for"


def test_a_debate_resting_only_on_stale_evidence_is_not_called():
    """A correct reading of the order book from four hours ago is a wrong
    reading of the order book now."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            Position(agent="a", stance="for", argument="x", evidence=(_ev("old", "recalled", minutes_old=600),)),
            Position(agent="b", stance="against", argument="y", evidence=(_ev("older", "recalled", minutes_old=900),)),
        ],
        now=NOW,
    )
    assert result.resolved is False
    assert "solid or fresh enough" in result.unresolved_reason


def test_every_competing_claim_is_recorded_with_its_evidence():
    """§13: "record competing claims and evidence". The conclusion alone is not
    auditable."""
    from ai.debate import Position, debate

    result = debate(
        subject="s",
        positions=[
            Position(agent="a", stance="for", argument="x", evidence=(_ev("first"),)),
            Position(agent="b", stance="against", argument="y", evidence=(_ev("second", "reported"),)),
        ],
        now=NOW,
    )
    body = result.as_dict()
    claims = [e["claim"] for p in body["positions"] for e in p["evidence"]]
    assert claims == ["first", "second"]
    assert all("weight" in e and "stale" in e for p in body["positions"] for e in p["evidence"])


def test_a_debate_with_no_positions_is_refused():
    from ai.debate import debate

    with pytest.raises(ValueError, match="no positions"):
        debate(subject="s", positions=[])


# ── §20: a trade thesis is a document, not an instruction ─────────────────────


def test_a_trade_analysis_is_never_actionable():
    """An analysis is not a permission. A structure carrying something an order
    router would accept is one refactor away from an AI trading because its own
    argument convinced it."""
    from ai.debate import Evidence, EvidenceQuality, analyse_trade

    analysis = analyse_trade(
        symbol="XAUUSD",
        thesis="holds above 2400",
        counter_thesis="a hawkish print takes it through 2380",
        supporting=[_ev("held six hours")],
        opposing=[Evidence("CPI in forty minutes", "feeds.macro", EvidenceQuality.REPORTED, NOW)],
        now=NOW,
    )
    assert analysis.actionable is False
    body = analysis.as_dict()
    assert body["actionable"] is False
    for forbidden in ("side", "quantity", "size", "lots", "order", "price"):
        assert forbidden not in body, f"a trade analysis carries {forbidden!r}, which an order router could read"


def test_its_confidence_says_where_it_came_from():
    """Not the model's feeling about the trade — a function of what was measured
    and how fresh it was, which a reader can disagree with by disagreeing with
    the inputs."""
    from ai.debate import analyse_trade

    analysis = analyse_trade(
        symbol="XAUUSD",
        thesis="up",
        counter_thesis="down",
        supporting=[_ev("a")],
        opposing=[_ev("b", "recalled")],
        now=NOW,
    )
    assert analysis.reasoning.confidence is not None
    assert "evidence weight" in analysis.reasoning.confidence_basis
    assert "not a probability of the trade working" in analysis.reasoning.confidence_basis


def test_with_no_evidence_at_all_there_is_no_confidence():
    """A number describing nothing is worse than no number."""
    from ai.debate import analyse_trade

    analysis = analyse_trade(
        symbol="XAUUSD",
        thesis="up",
        counter_thesis="down",
        supporting=[],
        opposing=[],
        now=NOW,
    )
    assert analysis.reasoning.confidence is None
    assert "none on either side" in analysis.reasoning.what_would_change_it[0].lower()


def test_an_unresolved_debate_reaches_the_reasoning_not_only_the_debate():
    """Otherwise a reader of the conclusion never learns the sides were tied."""
    from ai.debate import analyse_trade

    analysis = analyse_trade(
        symbol="XAUUSD",
        thesis="up",
        counter_thesis="down",
        supporting=[_ev("a")],
        opposing=[_ev("b")],
        now=NOW,
    )
    assert analysis.debate.resolved is False
    assert any("does not separate" in item for item in analysis.reasoning.missing_information)


def test_the_explanation_carries_both_the_argument_and_how_it_was_reached():
    """§20 explainability. A conclusion with no working is not explainable."""
    from ai.debate import analyse_trade

    text = analyse_trade(
        symbol="XAUUSD",
        thesis="up",
        counter_thesis="down",
        supporting=[_ev("a"), _ev("b"), _ev("c")],
        opposing=[_ev("d", "recalled")],
        now=NOW,
    ).explain()
    assert "Counter-thesis:" in text
    assert "how this was reached" in text
    assert "weight" in text


def test_a_trade_analysis_without_a_counter_thesis_will_not_build():
    """A trade thesis without one is a pitch."""
    from ai.debate import ReasoningIncomplete, analyse_trade

    with pytest.raises(ReasoningIncomplete):
        analyse_trade(
            symbol="XAUUSD",
            thesis="up",
            counter_thesis="",
            supporting=[_ev("a")],
            opposing=[],
            now=NOW,
        )


# ── it reaches the one place consequential recommendations are produced ───────


def test_the_synthesis_renders_itself_as_the_eight_part_structure():
    """`ai.debate.Reasoning` with nothing in the platform producing one would be
    a structure nobody runs. The synthesis already knew every part §15 asks for
    — it spelled them as prose."""
    from ai.agent.synthesis import Finding, synthesise

    reasoning = synthesise(
        subject="XAUUSD exposure",
        findings=[
            Finding("risk_compliance", "concern", "critical", "Daily loss is 4.10% against a 5.00% limit."),
            Finding("markets_execution", "clear", "info", "Positions reconcile with the broker."),
            Finding("research_intelligence", "unknown", "info", "The regime model has not scored today."),
        ],
    ).reasoning()

    assert "4.10%" in reasoning.thesis
    assert "markets_execution" in reasoning.counter_thesis
    assert reasoning.is_calibrated


def test_a_department_with_no_reading_becomes_stated_missing_information():
    """Silence about a blind spot reads as an all-clear."""
    from ai.agent.synthesis import Finding, synthesise

    reasoning = synthesise(
        subject="s",
        findings=[
            Finding("a", "concern", "warning", "something"),
            Finding("b", "unknown", "info", "no reading"),
        ],
    ).reasoning()

    assert any("b could not get a reading" in item for item in reasoning.missing_information)
    assert any("reading from b" in item for item in reasoning.what_would_change_it)


def test_unanimous_agreement_is_not_dressed_up_as_confirmation():
    """ "No department disagreed" and "nobody independent checked" are different
    facts, and an empty counter-thesis cannot tell them apart."""
    from ai.agent.synthesis import Finding, synthesise

    reasoning = synthesise(
        subject="s",
        findings=[
            Finding("a", "concern", "warning", "x"),
            Finding("b", "concern", "warning", "y"),
        ],
    ).reasoning()

    assert "not independent confirmation" in reasoning.counter_thesis


def test_its_confidence_says_it_is_about_agreement_not_correctness():
    """The number measures how much the departments agree. A reader who took it
    for a probability that the conclusion is right would size against it."""
    from ai.agent.synthesis import Finding, synthesise

    reasoning = synthesise(
        subject="s", findings=[Finding("a", "concern", "warning", "x"), Finding("b", "clear", "info", "y")]
    ).reasoning()

    assert "not a probability that the" in reasoning.confidence_basis


# ── §20: correlation, and the sentence it must never let you forget ───────────


def _sig(domain: str, label: str, *, minutes: float = 1.0, direction: int | None = 1):
    from ai.debate.correlation import Signal

    return Signal(domain=domain, label=label, at=NOW - timedelta(minutes=minutes), direction=direction)


def _move(change: float = 4.5):
    from ai.debate.correlation import PriceMove

    return PriceMove(symbol="XAUUSD", at=NOW, change=change)


def test_signals_moving_with_the_price_are_separated_from_those_against():
    from ai.debate.correlation import correlate

    result = correlate(
        move=_move(4.5),
        signals=[
            _sig("news", "dovish headline", direction=1),
            _sig("macro", "hot CPI", direction=-1),
        ],
    )
    assert [s.label for s in result.aligned] == ["dovish headline"]
    assert [s.label for s in result.opposing] == ["hot CPI"]


def test_an_unknown_direction_is_not_counted_as_neutral_agreement():
    """ "This does not push either way" and "nobody worked out which way this
    pushes" are different, and merging them fabricates a neutral."""
    from ai.debate.correlation import correlate

    result = correlate(move=_move(), signals=[_sig("news", "unclear headline", direction=None)])
    assert result.aligned == []
    assert result.opposing == []
    assert [s.label for s in result.unaligned] == ["unclear headline"]


def test_a_signal_outside_the_window_is_counted_not_silently_dropped():
    """Dropping it makes the surviving evidence look denser than it is."""
    from ai.debate.correlation import correlate

    result = correlate(move=_move(), signals=[_sig("news", "yesterday", minutes=600)], window_s=900)
    assert result.out_of_window == 1
    assert result.aligned == []


def test_a_domain_with_no_signal_is_named_as_a_blind_spot():
    """ "No news moved it" and "the news feed did not answer" render identically
    as an empty list."""
    from ai.debate.correlation import correlate

    result = correlate(move=_move(), signals=[_sig("technical", "broke the range")])
    assert set(result.domains_missing) == {"news", "macro", "microstructure"}
    assert "blind spot" in result.as_prose()


def test_the_caveat_is_part_of_the_output_not_a_footnote():
    """Every correlation engine ever built has been read as a causal claim by
    somebody under time pressure."""
    from ai.debate.correlation import correlate

    result = correlate(move=_move(), signals=[_sig("news", "headline")])
    assert "not a cause" in result.caveat
    assert result.caveat in result.as_prose()
    assert result.as_dict()["caveat"] == result.caveat


def test_correlation_never_produces_measured_evidence():
    """What was measured is the price and the signal. The link between them is
    this module's inference, and evidence quality has to describe the weakest
    link rather than the strongest."""
    from ai.debate.correlation import correlate

    evidence = correlate(
        move=_move(),
        signals=[_sig("technical", "broke the range"), _sig("news", "dovish headline")],
    ).as_evidence()
    assert evidence
    assert all(e.quality.value != "measured" for e in evidence)


def test_a_flat_move_correlates_with_nothing_either_way():
    """A zero move has no direction to agree with."""
    from ai.debate.correlation import correlate

    result = correlate(move=_move(0.0), signals=[_sig("news", "headline", direction=1)])
    assert result.aligned == []
    assert result.opposing == []
    assert len(result.unaligned) == 1


def test_a_naive_signal_timestamp_is_refused():
    from ai.debate.correlation import Signal

    with pytest.raises(ValueError, match="timezone-aware"):
        Signal(domain="news", label="x", at=datetime(2026, 3, 10))


def test_an_unknown_domain_is_refused():
    """Four domains are what §20 names. A fifth would silently never be reported
    as missing."""
    from ai.debate.correlation import Signal

    with pytest.raises(ValueError, match="domain"):
        Signal(domain="astrology", label="x", at=NOW)  # type: ignore[arg-type]
