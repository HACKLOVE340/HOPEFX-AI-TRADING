# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A headline containing "coupon" must not open a short on gold.

`NuclearWordMapScorer._score` matched with a bare substring test:

    news/nuclear_wordmap_scorer.py:284    if term in text_lower:

so "coup" (weight 7.0) fires inside "coupon", "nuclear war" (10.0) inside
"nuclear warning", "depression" (7.5) inside "tropical depression",
"gold standard" (6.0) inside "the gold standard of liquidity". Verified by
running the real scorer (F80):

    "Treasury coupon auction results beat expectations"  -> sev  7  hedge_mode
    "IAEA issues nuclear warning over inspections"       -> sev 10  nuclear_mode
    "Tropical depression forms off the Florida coast"    -> sev  8  hedge_mode
    "ETF seen as the gold standard of liquidity"         -> sev  6  pause
    "Markets in risk off mode ahead of data"             -> sev  5  pause

`hedge_mode` places a real market order: nuclear_supervisor.py:462-467 →
risk/orchestrator.py place_order(units=-hedge_units) — a short on XAU_USD.
`nuclear_mode` trips the kill switch. The text arrives from public news feeds,
so this is attacker-influenceable, not merely accident-prone.

The substring path is the default *and* the fallback: `news/geopolitical_llm.py`
gates the LLM replacement behind a flag that is "default OFF" and falls back to
the wordmap on any failure. There is no configuration in which it is bypassed.

These tests pin word-boundary matching. No weight changes — the weights are a
deliberate risk policy.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def scorer():
    from news.nuclear_wordmap_scorer import NuclearWordMapScorer

    return NuclearWordMapScorer()


def _score(scorer, text):
    result = scorer.score_event(text) if hasattr(scorer, "score_event") else scorer._score(text)
    if isinstance(result, tuple):
        severity, action = result[0], result[1]
        meta = result[3] if len(result) > 3 else {}
    else:
        severity = result.get("severity")
        action = result.get("action")
        meta = result.get("meta", result)
    return severity, action, meta


# ── The five verified false positives ────────────────────────────────────────


@pytest.mark.parametrize(
    "headline, collides_with",
    [
        ("Treasury coupon auction results beat expectations", "coup"),
        ("IAEA issues nuclear warning over inspections", "nuclear war"),
        ("Tropical depression forms off the Florida coast", "depression"),
        ("ETF seen as the gold standard of liquidity", "gold standard"),
        ("Recoupment of costs expected next quarter", "coup"),
    ],
)
def test_an_ordinary_headline_does_not_trigger(scorer, headline, collides_with):
    severity, action, meta = _score(scorer, headline)

    matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
    assert collides_with not in matched, (
        f"{headline!r} matched {collides_with!r} as a substring — severity {severity}, action {action}"
    )
    assert action == "normal", f"{headline!r} produced action {action!r} at severity {severity}"


def test_the_coupon_headline_does_not_place_a_hedge(scorer):
    """The headline finding, stated as its consequence."""
    severity, action, _ = _score(scorer, "Treasury coupon auction results beat expectations")
    assert action != "hedge_mode", "a fixed-income headline opened a short on gold"
    assert severity == 0


# ── The true positives must still fire ───────────────────────────────────────


@pytest.mark.parametrize(
    "headline, term, min_severity",
    [
        ("Reports of a coup in the capital", "coup", 7),
        ("Fears of nuclear war grow after the summit", "nuclear war", 10),
        ("Economists warn of a depression", "depression", 7),
        ("Markets in risk off mode ahead of data", "risk off", 5),
    ],
)
def test_a_real_signal_still_matches(scorer, headline, term, min_severity):
    severity, action, meta = _score(scorer, headline)

    matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
    assert term in matched, f"{headline!r} no longer matches {term!r} — the fix suppressed a real signal"
    assert severity >= min_severity
    assert action != "normal"


def test_a_term_next_to_punctuation_still_matches(scorer):
    """Punctuation is normalised to spaces before matching, so a boundary
    must not depend on the term being surrounded by literal spaces."""
    _, action, meta = _score(scorer, "Breaking: coup, capital seized.")
    matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
    assert "coup" in matched
    assert action != "normal"


def test_matching_is_still_case_insensitive(scorer):
    _, action, meta = _score(scorer, "REPORTS OF A COUP IN THE CAPITAL")
    matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
    assert "coup" in matched
    assert action != "normal"


def test_a_multi_word_term_matches_across_a_space(scorer):
    _, _, meta = _score(scorer, "analysts fear nuclear war within months")
    matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
    assert "nuclear war" in matched


def test_repeat_counting_still_caps_at_three(scorer):
    """The count cap is anti-spam policy, not a defect — it must survive."""
    _, _, meta = _score(scorer, "coup coup coup coup coup coup")
    matched = [m for m in (meta.get("matched_terms") or []) if isinstance(m, dict) and m["term"] == "coup"]
    assert matched and matched[0]["count"] == 3


def test_a_quiet_headline_is_still_quiet(scorer):
    severity, action, _ = _score(scorer, "Quiet session, gold drifts sideways")
    assert severity == 0
    assert action == "normal"


# ── The narrow context guard must stay narrow ────────────────────────────────


def test_the_context_guard_does_not_swallow_a_real_signal(scorer):
    """`AMBIGUOUS_TERM_CONTEXTS` suppresses a term only inside a named phrase.
    An economic depression and a return to the gold standard are exactly the
    events the wordmap exists for and must still fire at full weight."""
    for headline, term in [
        ("Economists warn of a depression as output collapses", "depression"),
        ("Central bank floats a return to the gold standard", "gold standard"),
    ]:
        severity, action, meta = _score(scorer, headline)
        matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
        assert term in matched, f"the context guard suppressed a real signal: {headline!r}"
        assert action != "normal"


def test_a_text_using_a_term_both_ways_still_scores(scorer):
    """Suppression is per-occurrence, not per-text: one idiomatic use must not
    mask a real one in the same headline."""
    _, action, meta = _score(
        scorer,
        "Tropical depression nears Florida as economists warn of a depression",
    )
    matched = [m["term"] if isinstance(m, dict) else m for m in (meta.get("matched_terms") or [])]
    assert "depression" in matched
    assert action != "normal"
