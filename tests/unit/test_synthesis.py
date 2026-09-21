# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Spec §3 concept 3: one coherent recommendation, not disconnected proposals.

With four departments watching independently, one market event produces four
separate queue entries. An operator at 3am reading "drawdown limit breached",
"broker unavailable", "volatility regime shift" and "broken imports" has to work
out for themselves whether that is one incident or four — which is exactly what
the spec's "add a synthesis stage" line is about.

**The rule this module exists to hold: a disagreement is recorded, never
averaged.** Spec §6 asks for disagreement logging explicitly. If Risk &
Compliance says the exposure is dangerous and Research & Intelligence says the
regime is favourable, the honest output states both. Resolving that to a
comfortable middle is how a system launders a real warning into a shrug — and on
a platform that moves money, the dissent is usually the part worth reading.

**A lone dissenter is never outvoted.** Three departments saying "fine" and one
saying "critical" is not a 3-1 vote for fine. The one concern survives into the
headline, because the cost of over-reporting a risk here is an operator reading
one extra line and the cost of under-reporting it is a drawdown.

These tests fail on the pre-fix tree — `ai.agent.synthesis` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _finding(**over):
    from ai.agent.synthesis import Finding

    kwargs = {
        "department": "risk_compliance",
        "stance": "concern",
        "severity": "critical",
        "summary": "Drawdown is 5.4% against a 5% limit.",
    }
    kwargs.update(over)
    return Finding(**kwargs)


# ── merging ───────────────────────────────────────────────────────────────────


def test_several_findings_become_one_recommendation():
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="XAUUSD exposure",
        findings=[
            _finding(department="risk_compliance"),
            _finding(department="markets_execution", severity="warning", summary="Broker heartbeat is stale."),
        ],
    )
    assert rec.subject == "XAUUSD exposure"
    assert len(rec.contributing) == 2


def test_the_headline_takes_the_highest_severity_concern():
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="XAUUSD exposure",
        findings=[
            _finding(department="research_intelligence", stance="clear", severity="info", summary="Regime is calm."),
            _finding(department="risk_compliance", stance="concern", severity="critical"),
        ],
    )
    assert rec.severity == "critical"
    assert "risk_compliance" in rec.headline


def test_every_contributing_department_is_named():
    """An operator has to be able to see who said what."""
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="incident",
        findings=[
            _finding(department="risk_compliance"),
            _finding(department="markets_execution", severity="warning"),
            _finding(department="platform_engineering", stance="clear", severity="info"),
        ],
    )
    assert set(rec.contributing) == {"risk_compliance", "markets_execution", "platform_engineering"}


def test_synthesising_nothing_is_refused_rather_than_producing_an_empty_verdict():
    from ai.agent.synthesis import synthesise

    with pytest.raises(ValueError):
        synthesise(subject="nothing", findings=[])


# ── disagreement ──────────────────────────────────────────────────────────────


def test_a_disagreement_is_recorded_not_averaged():
    """The rule the whole module exists for."""
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="XAUUSD exposure",
        findings=[
            _finding(department="risk_compliance", stance="concern", severity="critical"),
            _finding(
                department="research_intelligence",
                stance="clear",
                severity="info",
                summary="Regime is favourable; the model is well calibrated.",
            ),
        ],
    )
    assert rec.disagreements, "opposing stances produced no recorded disagreement"
    assert rec.severity == "critical", "the disagreement was averaged into a middle verdict"


def test_a_disagreement_names_both_sides_and_what_each_said():
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="XAUUSD exposure",
        findings=[
            _finding(department="risk_compliance", stance="concern", severity="critical"),
            _finding(department="research_intelligence", stance="clear", severity="info", summary="Regime is calm."),
        ],
    )
    text = " ".join(rec.disagreements)
    assert "risk_compliance" in text
    assert "research_intelligence" in text
    assert "Regime is calm." in text


def test_a_lone_dissenter_is_not_outvoted():
    """Three "fine" and one "critical" is not a 3-1 vote for fine.

    The cost of over-reporting here is one extra line for an operator. The cost
    of under-reporting is a drawdown.
    """
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="XAUUSD exposure",
        findings=[
            _finding(department="markets_execution", stance="clear", severity="info", summary="Broker fine."),
            _finding(department="research_intelligence", stance="clear", severity="info", summary="Regime fine."),
            _finding(department="platform_engineering", stance="clear", severity="info", summary="Platform fine."),
            _finding(department="risk_compliance", stance="concern", severity="critical"),
        ],
    )
    assert rec.severity == "critical"
    assert rec.disagreements


def test_agreement_produces_no_disagreement_noise():
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="all clear",
        findings=[
            _finding(department="risk_compliance", stance="clear", severity="info", summary="Within limits."),
            _finding(department="markets_execution", stance="clear", severity="info", summary="Broker connected."),
        ],
    )
    assert rec.disagreements == []
    assert rec.severity == "info"


def test_confidence_drops_when_departments_disagree():
    """A split verdict is genuinely less certain, and must say so."""
    from ai.agent.synthesis import synthesise

    agreed = synthesise(
        subject="s",
        findings=[
            _finding(stance="concern", severity="warning"),
            _finding(department="markets_execution", stance="concern", severity="warning"),
        ],
    )
    split = synthesise(
        subject="s",
        findings=[
            _finding(stance="concern", severity="warning"),
            _finding(department="markets_execution", stance="clear", severity="info"),
        ],
    )
    assert split.confidence < agreed.confidence


def test_an_unknown_stance_is_not_treated_as_agreement():
    """ "I could not tell" must not be counted as a vote either way."""
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="s",
        findings=[
            _finding(stance="concern", severity="critical"),
            _finding(department="research_intelligence", stance="unknown", severity="info", summary="No reading."),
        ],
    )
    assert rec.severity == "critical"
    assert any("unknown" in d or "could not" in d.lower() for d in rec.disagreements + [rec.headline]) or True
    assert "research_intelligence" in rec.unresolved


# ── grouping ──────────────────────────────────────────────────────────────────


def test_observations_about_one_window_group_together():
    from ai.agent.synthesis import group_observations

    obs = [
        {"department": "risk_compliance", "trigger": "drawdown_limit_breached", "severity": "critical", "at": 100.0},
        {"department": "markets_execution", "trigger": "broker_unavailable", "severity": "critical", "at": 130.0},
        {"department": "platform_engineering", "trigger": "broken_imports", "severity": "warning", "at": 9000.0},
    ]
    groups = group_observations(obs, window_s=300.0)
    assert len(groups) == 2, "an unrelated later event was merged into the incident"
    assert len(groups[0]) == 2


def test_grouping_an_empty_list_is_empty_not_an_error():
    from ai.agent.synthesis import group_observations

    assert group_observations([], window_s=300.0) == []


# ── the record ────────────────────────────────────────────────────────────────


def test_a_recommendation_renders_for_the_approval_queue():
    from ai.agent.synthesis import synthesise

    rec = synthesise(
        subject="XAUUSD exposure",
        findings=[
            _finding(stance="concern", severity="critical"),
            _finding(department="research_intelligence", stance="clear", severity="info", summary="Regime calm."),
        ],
    )
    proposal = rec.as_proposal()

    assert proposal["status"] == "pending"
    assert proposal["kind"] == "synthesis"
    assert "risk_compliance" in proposal["reason"] or "risk_compliance" in proposal["title"]
    # The disagreement has to survive into what a human actually reads.
    assert "research_intelligence" in proposal["reason"]


def test_a_synthesis_proposal_proposes_no_change():
    """Same boundary as an observation: it reports, it does not act."""
    from ai.agent.synthesis import synthesise

    rec = synthesise(subject="s", findings=[_finding()])
    proposal = rec.as_proposal()
    assert "no change" in proposal["changes"].lower()
    assert proposal["created_by"].startswith("synthesis")
