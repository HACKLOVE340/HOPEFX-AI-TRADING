# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_news_keyword_matching.py
========================================
Three news scorers matched their keyword dictionaries with ``keyword in text``.

That is a substring test, and on these particular dictionaries it fires on
ordinary English rather than on rare edge cases. ``"war"`` is a HIGH-impact
geopolitical keyword, so *"Local bakery wins award"* was classified
GEOPOLITICAL at ImpactLevel.HIGH with a 1.3x volatility multiplier and a
``medium_term`` timeframe — reproduced directly, which is how this was found:
a test written to assert the boring case returned the alarming one.

The same shape appeared in all three:

* ``news/impact_predictor.py`` — ``war`` in *award*, *software*, *warehouse*
* ``news/sentiment.py`` — ``gain`` in *against* (scored **bullish**),
  ``miss`` in *mission*, ``fall`` in *fallout*, ``risk`` in *brisket*
* ``news/nuclear_wordmap_scorer.py`` — ``coup`` in *couple*, on the scorer
  whose severity ladder reaches ``nuclear_mode``

The fix is not a plain ``\\bword\\b``. Headlines are inflected — "stocks
*surges*", "*gains* on the day", "rate *cuts*" — and demanding an exact word
would drop the matches these dictionaries exist to catch. So a keyword matches
at a word boundary, optionally followed by one common inflection:
*falls* matches ``fall``; *fallout* does not.
"""

from __future__ import annotations

import pytest

from news.impact_predictor import EventCategory, ImpactLevel, ImpactPredictor
from news.keyword_match import contains_keyword, count_keyword, keyword_pattern
from news.sentiment import FinancialSentimentAnalyzer

pytestmark = pytest.mark.unit


@pytest.fixture
def predictor():
    return ImpactPredictor()


@pytest.fixture
def keyword_analyzer():
    analyzer = FinancialSentimentAnalyzer(use_vader=False, use_finbert=False)
    analyzer.vader = None
    analyzer._finbert = None
    return analyzer


# ── the matcher ───────────────────────────────────────────────────────────────


class TestWholeWordMatching:
    @pytest.mark.parametrize(
        ("text", "keyword"),
        [
            ("wins award", "war"),
            ("a software update", "war"),
            ("warehouse fire", "war"),
            ("a swarm of bees", "war"),
            ("went against expectations", "gain"),
            ("a mission to mars", "miss"),
            ("fallout shelter", "fall"),
            ("brisket recipe", "risk"),
            ("a couple of things", "coup"),
            ("the beaten path", "beat"),
        ],
    )
    def test_a_keyword_inside_a_longer_word_does_not_match(self, text, keyword):
        assert contains_keyword(text, keyword) is False

    @pytest.mark.parametrize(
        ("text", "keyword"),
        [
            ("the war began", "war"),
            ("two wars at once", "war"),
            ("a gain on the day", "gain"),
            ("gains on the day", "gain"),
            ("he misses the forecast", "miss"),
            ("the index falls", "fall"),
            ("the risks are rising", "risk"),
            ("a coup in the capital", "coup"),
            ("beats the forecast", "beat"),
            ("surged overnight", "surge"),
            ("strongly worded", "strong"),
        ],
    )
    def test_a_real_occurrence_still_matches(self, text, keyword):
        assert contains_keyword(text, keyword) is True

    def test_matching_is_case_insensitive(self):
        assert contains_keyword("The WAR Began", "war") is True

    def test_a_multi_word_phrase_matches_as_a_phrase(self):
        assert contains_keyword("raised the interest rate today", "interest rate") is True

    def test_a_multi_word_phrase_tolerates_odd_spacing(self):
        """Article bodies arrive with newlines and double spaces in them."""
        assert contains_keyword("the interest\n  rate decision", "interest rate") is True

    def test_a_phrase_whose_words_are_separated_does_not_match(self):
        assert contains_keyword("interest in the exchange rate", "interest rate") is False

    def test_an_empty_keyword_never_matches(self):
        """A bare pattern would match everywhere and score every article."""
        assert contains_keyword("any text at all", "") is False
        assert count_keyword("any text at all", "") == 0

    def test_a_keyword_absent_from_the_text_does_not_match(self):
        assert contains_keyword("a quiet day", "war") is False

    def test_counting_finds_every_occurrence(self):
        assert count_keyword("war and war and more war", "war") == 3

    def test_counting_ignores_substring_hits(self):
        assert count_keyword("award software warehouse", "war") == 0

    def test_counting_includes_inflected_forms(self):
        assert count_keyword("it falls and falls", "fall") == 2

    def test_patterns_are_cached_rather_than_recompiled(self):
        assert keyword_pattern("war") is keyword_pattern("war")

    def test_a_regex_metacharacter_in_a_keyword_is_literal(self):
        """WORDMAP.json is user-supplied; a stray '.' must not become 'any char'."""
        assert contains_keyword("the e.u economy", "e.u") is True
        assert contains_keyword("the exu economy", "e.u") is False

    def test_a_keyword_ending_in_punctuation_still_matches(self):
        """\b next to a '.' can never match, so such a keyword would never fire."""
        assert contains_keyword("the u.s. economy", "u.s.") is True

    def test_a_keyword_ending_in_punctuation_still_respects_word_edges(self):
        assert contains_keyword("u.s.a. today", "u.s.") is False


# ── the defect, at the level a caller sees it ─────────────────────────────────


class TestImpactPredictorNoLongerSeesWarEverywhere:
    @pytest.mark.parametrize(
        "headline",
        ["Local bakery wins award", "Software update released", "Warehouse opens in Ohio"],
    )
    def test_an_ordinary_headline_is_not_a_geopolitical_event(self, predictor, headline):
        impact = predictor.predict_impact(headline, "")

        assert impact.category is not EventCategory.GEOPOLITICAL

    def test_an_ordinary_headline_is_not_high_impact(self, predictor):
        impact = predictor.predict_impact("Local bakery wins award", "")

        assert impact.level in (ImpactLevel.VERY_LOW, ImpactLevel.LOW)

    def test_an_ordinary_headline_is_not_volatility_amplified(self, predictor):
        """The geopolitical multiplier was inflating the estimate by 1.3x."""
        award = predictor.predict_impact("Local bakery wins award", "")
        quiet = predictor.predict_impact("Quarterly report published", "")

        assert award.expected_volatility == pytest.approx(quiet.expected_volatility)

    def test_a_real_war_headline_is_still_geopolitical(self, predictor):
        """The fix must not disarm the keyword it was protecting."""
        impact = predictor.predict_impact("War breaks out on the border", "military conflict")

        assert impact.category is EventCategory.GEOPOLITICAL

    def test_the_high_impact_filter_no_longer_surfaces_a_bakery(self, predictor):
        articles = [
            {"title": "Local bakery wins award", "description": ""},
            {"title": "War breaks out, sanctions imposed", "description": "military conflict crisis"},
        ]

        kept = predictor.get_high_impact_events(articles, min_level=ImpactLevel.HIGH)

        assert all("bakery" not in a["title"] for a in kept)


class TestSentimentNoLongerMisreadsOrdinaryWords:
    def test_against_is_not_a_bullish_gain(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("the vote went against the motion").polarity == 0.0

    def test_a_mission_is_not_a_miss(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("a mission to mars").polarity == 0.0

    def test_fallout_is_not_a_fall(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("fallout shelter tours").polarity == 0.0

    def test_brisket_is_not_a_risk(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("a brisket recipe").confidence == 0.0

    def test_real_bullish_words_still_score(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("shares surge on strong profit growth").polarity == 1.0

    def test_real_bearish_words_still_score(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("shares plunge on a weak loss").polarity == -1.0

    def test_inflected_bullish_words_still_score(self, keyword_analyzer):
        """Headlines say 'gains', not 'gain'."""
        assert keyword_analyzer._keyword_analysis("the index gains and profits").polarity > 0


class TestNuclearScorerNoLongerSeesACoupInACouple:
    def _scorer(self, tmp_path, monkeypatch):
        from news.nuclear_wordmap_scorer import NuclearWordMapScorer

        monkeypatch.chdir(tmp_path)
        return NuclearWordMapScorer()

    def test_a_couple_of_things_is_not_a_coup(self, tmp_path, monkeypatch):
        scorer = self._scorer(tmp_path, monkeypatch)

        severity, action, _raw, meta = scorer.score_event("a couple of things happened today")

        assert severity == 0
        assert action == "normal"
        assert meta["matched_terms"] == []

    def test_a_real_coup_still_registers(self, tmp_path, monkeypatch):
        scorer = self._scorer(tmp_path, monkeypatch)

        assert scorer.score_event("a coup in the capital")[0] > 0

    def test_the_repetition_cap_still_applies_to_whole_word_hits(self, tmp_path, monkeypatch):
        scorer = self._scorer(tmp_path, monkeypatch)
        term = next(iter(next(iter(scorer._keywords.values()))))

        thrice = scorer.score_event(" ".join([term] * 3))[2]
        many = scorer.score_event(" ".join([term] * 30))[2]

        assert many == pytest.approx(thrice)
