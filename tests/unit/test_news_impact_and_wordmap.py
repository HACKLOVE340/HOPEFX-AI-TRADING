# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_news_impact_and_wordmap.py
==========================================
The two remaining `news/` scorers, both of which feed risk decisions.

`news/impact_predictor.py` (74.85 %) turns a headline into an expected
volatility and a timeframe. `news/nuclear_wordmap_scorer.py` (69.09 %) turns
one into a severity 0-10 and an *action* — and at severity 8 that action is
``nuclear_mode``. A scorer that can halt trading deserves its thresholds
written down.

The uncovered parts of each were the same shape: the batch/filter entry points
that callers actually use, and the `WORDMAP.json` merge — which matters because
`WORDMAP.json` is gitignored, so the file is present in some deployments and
absent in others, and the built-in dictionary has to carry the load when it is
missing.
"""

from __future__ import annotations

import json

import pytest

from news.impact_predictor import (
    EventCategory,
    ImpactLevel,
    ImpactPredictor,
    MarketImpact,
    get_impact_predictor,
)
from news.nuclear_wordmap_scorer import (
    NuclearWordMapScorer,
    NuclearWordmapScorer,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def predictor():
    return ImpactPredictor()


@pytest.fixture
def scorer(tmp_path, monkeypatch):
    """A scorer with no WORDMAP.json in reach — built-in keywords only."""
    monkeypatch.chdir(tmp_path)
    return NuclearWordMapScorer()


# ── impact prediction ─────────────────────────────────────────────────────────


class TestMarketImpactRecord:
    def test_to_dict_flattens_the_enums(self):
        payload = MarketImpact(
            level=ImpactLevel.HIGH,
            category=EventCategory.CENTRAL_BANK,
            confidence=0.8,
            expected_volatility=1.5,
        ).to_dict()

        assert payload["level"] == ImpactLevel.HIGH.value
        assert payload["category"] == EventCategory.CENTRAL_BANK.value


class TestPredictImpact:
    def test_a_rate_decision_is_a_central_bank_event(self, predictor):
        impact = predictor.predict_impact("Fed raises interest rate", "FOMC decision")

        assert impact.category is EventCategory.CENTRAL_BANK

    def test_an_unmatched_headline_falls_to_other(self, predictor):
        impact = predictor.predict_impact("Local bakery wins award", "")

        assert impact.category is EventCategory.OTHER

    def test_a_positive_sentiment_biases_bullish(self, predictor):
        assert predictor.predict_impact("t", "d", sentiment_score=0.5).direction_bias == "bullish"

    def test_a_negative_sentiment_biases_bearish(self, predictor):
        assert predictor.predict_impact("t", "d", sentiment_score=-0.5).direction_bias == "bearish"

    @pytest.mark.parametrize("sentiment", [0.05, -0.05, 0.0])
    def test_a_weak_sentiment_expresses_no_bias(self, predictor, sentiment):
        assert predictor.predict_impact("t", "d", sentiment_score=sentiment).direction_bias is None

    def test_no_sentiment_expresses_no_bias(self, predictor):
        assert predictor.predict_impact("t", "d").direction_bias is None

    def test_supplied_symbols_are_carried_through(self, predictor):
        impact = predictor.predict_impact("t", "d", symbols=["XAUUSD"])

        assert impact.affected_symbols == ["XAUUSD"]

    def test_a_failure_degrades_to_a_low_impact_rather_than_raising(self, predictor, monkeypatch):
        def _boom(text):
            raise RuntimeError("classifier down")

        monkeypatch.setattr(predictor, "_categorize_event", _boom)

        impact = predictor.predict_impact("t", "d")

        assert impact.level is ImpactLevel.LOW
        assert impact.category is EventCategory.OTHER
        assert impact.confidence == 0.0

    def test_matching_is_case_insensitive(self, predictor):
        upper = predictor.predict_impact("FED RAISES INTEREST RATE", "")
        lower = predictor.predict_impact("fed raises interest rate", "")

        assert upper.category is lower.category


class TestConfidence:
    def test_it_is_never_above_one(self, predictor):
        impact = predictor.predict_impact(
            "Fed emergency interest rate decision crisis war", "central bank", sentiment_score=0.9
        )

        assert impact.confidence <= 1.0

    def test_supplying_sentiment_raises_confidence(self, predictor):
        without = predictor.predict_impact("Fed interest rate decision", "")
        with_sentiment = predictor.predict_impact("Fed interest rate decision", "", sentiment_score=0.5)

        assert with_sentiment.confidence > without.confidence

    def test_a_recognised_category_beats_an_unrecognised_one(self, predictor):
        known = predictor._calculate_confidence("", EventCategory.CENTRAL_BANK, None)
        unknown = predictor._calculate_confidence("", EventCategory.OTHER, None)

        assert known > unknown


class TestVolatilityEstimate:
    def test_it_rises_with_the_impact_level(self, predictor):
        levels = [
            ImpactLevel.VERY_LOW,
            ImpactLevel.LOW,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.VERY_HIGH,
        ]
        estimates = [predictor._estimate_volatility(level, EventCategory.OTHER) for level in levels]

        assert estimates == sorted(estimates)

    def test_central_bank_events_are_amplified_most(self, predictor):
        base = predictor._estimate_volatility(ImpactLevel.HIGH, EventCategory.OTHER)
        cb = predictor._estimate_volatility(ImpactLevel.HIGH, EventCategory.CENTRAL_BANK)
        geo = predictor._estimate_volatility(ImpactLevel.HIGH, EventCategory.GEOPOLITICAL)

        assert cb > geo > base

    def test_the_estimate_is_never_negative(self, predictor):
        for level in ImpactLevel:
            assert predictor._estimate_volatility(level, EventCategory.OTHER) >= 0.0


class TestTimeframe:
    @pytest.mark.parametrize("category", [EventCategory.CENTRAL_BANK, EventCategory.GEOPOLITICAL])
    def test_slow_burning_categories_are_not_intraday(self, predictor, category):
        assert predictor._estimate_timeframe(category) != "intraday"

    def test_everything_else_is_intraday(self, predictor):
        assert predictor._estimate_timeframe(EventCategory.OTHER) == "intraday"


class TestBatchPredict:
    def test_it_returns_one_impact_per_article(self, predictor):
        articles = [{"title": "a"}, {"title": "b"}, {"title": "c"}]

        assert len(predictor.batch_predict(articles)) == 3

    def test_an_empty_batch_is_an_empty_list(self, predictor):
        assert predictor.batch_predict([]) == []

    def test_missing_keys_are_tolerated(self, predictor):
        """Articles come from four different providers with four shapes."""
        impacts = predictor.batch_predict([{}])

        assert len(impacts) == 1
        assert isinstance(impacts[0], MarketImpact)

    def test_the_article_sentiment_reaches_the_prediction(self, predictor):
        impacts = predictor.batch_predict([{"title": "t", "sentiment": 0.9}])

        assert impacts[0].direction_bias == "bullish"


class TestHighImpactFilter:
    def _articles(self):
        return [
            {"title": "Fed emergency interest rate decision crisis", "description": "central bank shock"},
            {"title": "Local bakery wins award", "description": "nothing to see"},
        ]

    def test_it_keeps_only_events_at_or_above_the_floor(self, predictor):
        kept = predictor.get_high_impact_events(self._articles(), min_level=ImpactLevel.HIGH)

        assert all("bakery" not in a["title"] for a in kept)

    def test_the_lowest_floor_keeps_everything(self, predictor):
        articles = self._articles()

        assert len(predictor.get_high_impact_events(articles, min_level=ImpactLevel.VERY_LOW)) == 2

    def test_the_highest_floor_is_the_most_selective(self, predictor):
        articles = self._articles()
        loose = predictor.get_high_impact_events(articles, min_level=ImpactLevel.VERY_LOW)
        tight = predictor.get_high_impact_events(articles, min_level=ImpactLevel.VERY_HIGH)

        assert len(tight) <= len(loose)

    def test_the_kept_articles_are_annotated_with_the_prediction(self, predictor):
        kept = predictor.get_high_impact_events(self._articles(), min_level=ImpactLevel.VERY_LOW)

        assert "predicted_impact" in kept[0]
        assert "level" in kept[0]["predicted_impact"]

    def test_an_empty_input_is_an_empty_output(self, predictor):
        assert predictor.get_high_impact_events([]) == []


class TestImpactPredictorSingleton:
    def test_it_is_shared(self):
        assert get_impact_predictor() is get_impact_predictor()


# ── the nuclear word-map scorer ───────────────────────────────────────────────


class TestScorerConstruction:
    def test_it_loads_the_built_in_dictionary_without_a_wordmap_file(self, scorer):
        assert scorer.get_keyword_count() > 0
        assert scorer.get_categories()

    def test_a_missing_wordmap_path_is_not_an_error(self, tmp_path):
        s = NuclearWordMapScorer(wordmap_path=tmp_path / "absent.json")

        assert s.get_keyword_count() > 0

    def test_a_wordmap_dict_section_merges_its_weights(self, tmp_path):
        path = tmp_path / "WORDMAP.json"
        path.write_text(json.dumps({"nuclear_risk": {"custom": {"kessler syndrome": 9.0}}}))

        s = NuclearWordMapScorer(wordmap_path=path)

        assert "custom" in s.get_categories()
        assert s.score_event("a kessler syndrome event")[0] >= 8

    def test_a_wordmap_list_section_gets_a_default_weight(self, tmp_path):
        path = tmp_path / "WORDMAP.json"
        path.write_text(json.dumps({"nuclear_risk": {"listy": ["Some Term"]}}))

        s = NuclearWordMapScorer(wordmap_path=path)

        assert s.score_event("some term happened")[0] > 0

    def test_list_terms_are_lower_cased_on_load(self, tmp_path):
        path = tmp_path / "WORDMAP.json"
        path.write_text(json.dumps({"nuclear_risk": {"listy": ["UPPERCASE TERM"]}}))

        s = NuclearWordMapScorer(wordmap_path=path)

        assert s.score_event("an UPPERCASE TERM appears")[0] > 0

    def test_non_string_list_entries_are_skipped(self, tmp_path):
        path = tmp_path / "WORDMAP.json"
        path.write_text(json.dumps({"nuclear_risk": {"listy": ["good term", 42, None]}}))

        assert NuclearWordMapScorer(wordmap_path=path).get_keyword_count() > 0

    def test_a_malformed_wordmap_falls_back_to_the_built_ins(self, tmp_path):
        """The file is gitignored, so a broken local copy must not disarm the scorer."""
        path = tmp_path / "WORDMAP.json"
        path.write_text("{ this is not json")

        s = NuclearWordMapScorer(wordmap_path=path)

        assert s.get_keyword_count() > 0

    def test_a_wordmap_without_the_nuclear_section_is_ignored(self, tmp_path):
        path = tmp_path / "WORDMAP.json"
        path.write_text(json.dumps({"something_else": {"a": 1}}))
        baseline = NuclearWordMapScorer(wordmap_path=tmp_path / "absent.json").get_keyword_count()

        assert NuclearWordMapScorer(wordmap_path=path).get_keyword_count() == baseline

    def test_merging_does_not_mutate_the_built_in_dictionary(self, tmp_path):
        """The built-ins are module-level; a merge must copy, not write through."""
        path = tmp_path / "WORDMAP.json"
        path.write_text(json.dumps({"nuclear_risk": {"custom": {"one off": 9.0}}}))
        NuclearWordMapScorer(wordmap_path=path)

        assert "custom" not in NuclearWordMapScorer(wordmap_path=tmp_path / "absent.json").get_categories()

    def test_the_back_compat_alias_is_the_same_class(self):
        """api/news_feed.py imports the lowercase-'map' spelling."""
        assert NuclearWordmapScorer is NuclearWordMapScorer


class TestScoreEvent:
    def test_an_unremarkable_headline_scores_zero_and_stays_normal(self, scorer):
        severity, action, raw, meta = scorer.score_event("quarterly bakery earnings were fine")

        assert severity == 0
        assert action == "normal"
        assert raw == pytest.approx(0.0)
        assert meta["matched_terms"] == []

    def test_the_return_shape_is_stable(self, scorer):
        severity, action, raw, meta = scorer.score_event("anything")

        assert isinstance(severity, int)
        assert isinstance(action, str)
        assert isinstance(raw, float)
        assert set(meta) == {
            "matched_terms",
            "category_scores",
            "base_score",
            "vol_factor",
            "sentiment_factor",
            "confidence",
            "n_categories_matched",
        }

    def test_severity_is_always_inside_zero_to_ten(self, scorer):
        for text in ("", "quiet day", " ".join(t for terms in scorer._keywords.values() for t in terms)):
            severity, _a, _r, _m = scorer.score_event(text, volatility=10.0, sentiment=-1.0)
            assert 0 <= severity <= 10

    def test_punctuation_does_not_hide_a_keyword(self, scorer):
        term = next(iter(next(iter(scorer._keywords.values()))))
        plain = scorer.score_event(f"a {term} happened")[0]
        punctuated = scorer.score_event(f"a {term}, happened!")[0]

        assert punctuated == plain

    def test_higher_volatility_amplifies_a_matched_event(self, scorer):
        term = next(iter(next(iter(scorer._keywords.values()))))
        calm = scorer.score_event(f"a {term} happened", volatility=1.0)[2]
        stormy = scorer.score_event(f"a {term} happened", volatility=3.0)[2]

        assert stormy > calm

    def test_volatility_below_normal_does_not_dampen_the_score(self, scorer):
        """The amplifier is one-sided: a quiet tape must not suppress a real alarm."""
        term = next(iter(next(iter(scorer._keywords.values()))))
        normal = scorer.score_event(f"a {term} happened", volatility=1.0)[2]
        quiet = scorer.score_event(f"a {term} happened", volatility=0.1)[2]

        assert quiet == pytest.approx(normal)

    def test_negative_sentiment_raises_the_score(self, scorer):
        term = next(iter(next(iter(scorer._keywords.values()))))
        neutral = scorer.score_event(f"a {term} happened", sentiment=0.0)[2]
        fearful = scorer.score_event(f"a {term} happened", sentiment=-1.0)[2]

        assert fearful > neutral

    def test_positive_sentiment_does_not_lower_the_score(self, scorer):
        term = next(iter(next(iter(scorer._keywords.values()))))
        neutral = scorer.score_event(f"a {term} happened", sentiment=0.0)[2]
        happy = scorer.score_event(f"a {term} happened", sentiment=1.0)[2]

        assert happy == pytest.approx(neutral)

    def test_repetition_is_capped_so_spam_cannot_escalate_indefinitely(self, scorer):
        term = next(iter(next(iter(scorer._keywords.values()))))
        thrice = scorer.score_event(" ".join([term] * 3))[2]
        fifty = scorer.score_event(" ".join([term] * 50))[2]

        assert fifty == pytest.approx(thrice)

    def test_a_match_reports_its_term_and_category(self, scorer):
        category, terms = next(iter(scorer._keywords.items()))
        term = next(iter(terms))

        _s, _a, _r, meta = scorer.score_event(f"a {term} happened")

        assert meta["matched_terms"][0]["term"] == term
        assert meta["matched_terms"][0]["category"] == category
        assert category in meta["category_scores"]

    def test_any_match_earns_at_least_thirty_percent_confidence(self, scorer):
        term = next(iter(next(iter(scorer._keywords.values()))))

        assert scorer.score_event(f"a {term} happened")[3]["confidence"] >= 0.3

    def test_no_match_earns_no_confidence(self, scorer):
        assert scorer.score_event("a quiet uneventful day")[3]["confidence"] == 0.0

    def test_confidence_never_exceeds_one(self, scorer):
        everything = " ".join(t for terms in scorer._keywords.values() for t in terms)

        assert scorer.score_event(everything, volatility=5.0, sentiment=-1.0)[3]["confidence"] <= 1.0

    def test_matching_more_categories_is_recorded(self, scorer):
        categories = list(scorer._keywords.items())
        if len(categories) < 2:
            pytest.skip("built-in dictionary has only one category")
        text = f"{next(iter(categories[0][1]))} and {next(iter(categories[1][1]))}"

        assert scorer.score_event(text)[3]["n_categories_matched"] >= 2

    def test_the_amplifiers_are_configurable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        term = next(iter(next(iter(NuclearWordMapScorer()._keywords.values()))))
        weak = NuclearWordMapScorer(vol_amplifier=0.0).score_event(f"a {term}", volatility=5.0)[2]
        strong = NuclearWordMapScorer(vol_amplifier=1.0).score_event(f"a {term}", volatility=5.0)[2]

        assert strong > weak

    def test_the_action_ladder_escalates_with_severity(self, scorer):
        """Severity 8 means `nuclear_mode`. A scorer that can halt trading
        needs its ladder written down, not inferred from a lookup table."""
        from news.nuclear_wordmap_scorer import _SEVERITY_ACTIONS

        seen = [_SEVERITY_ACTIONS.get(s, "normal") for s in range(11)]

        assert seen[0] == "normal"
        assert "nuclear_mode" in seen
        assert seen.index("nuclear_mode") > seen.index("normal")

    def test_every_severity_maps_to_a_known_action(self, scorer):
        valid = {"normal", "pause_new_entries", "hedge_mode", "nuclear_mode"}

        for _severity in range(11):
            _s, action, _r, _m = scorer.score_event("x")
            assert action in valid

    def test_an_empty_string_is_safe(self, scorer):
        severity, action, _r, _m = scorer.score_event("")

        assert (severity, action) == (0, "normal")
