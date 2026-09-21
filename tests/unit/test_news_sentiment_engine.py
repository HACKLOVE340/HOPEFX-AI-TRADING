# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_news_sentiment_engine.py
========================================
`news/sentiment.py` was 162 statements at 58 %.

The module has a three-tier fallback — FinBERT, then VADER, then a keyword
count — chosen at runtime by which dependencies happen to be installed. That
means a deployment can silently be running a *different scorer* than the one
its author tested, so all three tiers need to produce a sane score and the
selection between them needs to be deliberate. `tests/unit/test_news_sentiment_finbert.py`
covers the FinBERT preference; the VADER and keyword tiers, the aggregation
used by `/api/news/sentiment/{symbol}`, and the entity extractor were not
covered.

Two label ladders live in this file and they **disagree on purpose**:
`SentimentAnalyzer._get_label` turns positive at 0.1, `FinancialSentimentAnalyzer._get_label`
at 0.05 — VADER compounds cluster nearer zero than TextBlob polarities. That
divergence is invisible and easy to "tidy" into a bug, so both are pinned here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import news.sentiment as sentiment_mod
from news.sentiment import (
    FinancialSentimentAnalyzer,
    SentimentAnalyzer,
    SentimentLabel,
    SentimentScore,
    get_financial_analyzer,
    get_sentiment_analyzer,
)

pytestmark = pytest.mark.unit


def _score(polarity=0.0, subjectivity=0.5, confidence=0.5, label=SentimentLabel.NEUTRAL, compound=None):
    return SentimentScore(
        polarity=polarity,
        subjectivity=subjectivity,
        confidence=confidence,
        label=label,
        compound_score=compound,
    )


@pytest.fixture
def keyword_analyzer():
    """An analyzer forced down to the keyword tier."""
    analyzer = FinancialSentimentAnalyzer(use_vader=False, use_finbert=False)
    analyzer.vader = None
    analyzer._finbert = None
    return analyzer


# ── the score record ──────────────────────────────────────────────────────────


class TestSentimentScore:
    def test_to_dict_flattens_the_label(self):
        payload = _score(polarity=0.4, label=SentimentLabel.POSITIVE).to_dict()

        assert payload["label"] == "positive"
        assert payload["polarity"] == 0.4

    def test_the_compound_score_is_optional(self):
        assert _score().to_dict()["compound_score"] is None

    @pytest.mark.parametrize(("polarity", "bullish"), [(0.5, True), (0.11, True), (0.1, False), (-0.5, False)])
    def test_bullish_is_strictly_above_the_threshold(self, polarity, bullish):
        assert _score(polarity=polarity).is_bullish() is bullish

    @pytest.mark.parametrize(("polarity", "bearish"), [(-0.5, True), (-0.11, True), (-0.1, False), (0.5, False)])
    def test_bearish_is_strictly_below_the_threshold(self, polarity, bearish):
        assert _score(polarity=polarity).is_bearish() is bearish

    @pytest.mark.parametrize(("polarity", "neutral"), [(0.0, True), (0.1, True), (-0.1, True), (0.2, False)])
    def test_neutral_is_the_inclusive_band(self, polarity, neutral):
        assert _score(polarity=polarity).is_neutral() is neutral

    def test_the_thresholds_are_configurable(self):
        score = _score(polarity=0.3)

        assert score.is_bullish(threshold=0.5) is False
        assert score.is_neutral(threshold=0.5) is True

    def test_a_score_is_never_both_bullish_and_bearish(self):
        for polarity in (-1.0, -0.3, 0.0, 0.3, 1.0):
            score = _score(polarity=polarity)
            assert not (score.is_bullish() and score.is_bearish())


# ── the TextBlob tier ─────────────────────────────────────────────────────────


class TestSentimentAnalyzer:
    def test_it_refuses_to_construct_without_textblob(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", False)

        with pytest.raises(ImportError, match="TextBlob is required"):
            SentimentAnalyzer()

    @pytest.mark.parametrize(
        ("polarity", "expected"),
        [
            (0.9, SentimentLabel.VERY_POSITIVE),
            (0.5, SentimentLabel.VERY_POSITIVE),
            (0.2, SentimentLabel.POSITIVE),
            (0.1, SentimentLabel.POSITIVE),
            (0.0, SentimentLabel.NEUTRAL),
            (-0.05, SentimentLabel.NEUTRAL),
            (-0.1, SentimentLabel.NEGATIVE),
            (-0.5, SentimentLabel.VERY_NEGATIVE),
            (-0.9, SentimentLabel.VERY_NEGATIVE),
        ],
    )
    def test_the_textblob_label_ladder_turns_at_a_tenth(self, monkeypatch, polarity, expected):
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)

        assert SentimentAnalyzer()._get_label(polarity) is expected

    def test_analyze_reads_polarity_and_derives_confidence(self, monkeypatch):
        """Confidence is the inverse of subjectivity: an opinion is weaker evidence."""
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)
        monkeypatch.setattr(
            sentiment_mod,
            "TextBlob",
            lambda text: MagicMock(sentiment=MagicMock(polarity=0.6, subjectivity=0.25)),
            raising=False,
        )

        score = SentimentAnalyzer().analyze("gold surges")

        assert score.polarity == pytest.approx(0.6)
        assert score.confidence == pytest.approx(0.75)
        assert score.label is SentimentLabel.VERY_POSITIVE

    def test_a_failing_backend_degrades_to_neutral(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)

        def _boom(text):
            raise RuntimeError("corpus missing")

        monkeypatch.setattr(sentiment_mod, "TextBlob", _boom, raising=False)

        score = SentimentAnalyzer().analyze("anything")

        assert score.polarity == 0.0
        assert score.confidence == 0.0
        assert score.label is SentimentLabel.NEUTRAL

    def test_analyze_multiple_returns_one_score_per_text(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)
        monkeypatch.setattr(
            sentiment_mod,
            "TextBlob",
            lambda text: MagicMock(sentiment=MagicMock(polarity=0.2, subjectivity=0.5)),
            raising=False,
        )

        assert len(SentimentAnalyzer().analyze_multiple(["a", "b", "c"])) == 3

    def test_the_average_is_the_mean_of_the_parts(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)
        polarities = iter([0.8, 0.0, -0.2])
        monkeypatch.setattr(
            sentiment_mod,
            "TextBlob",
            lambda text: MagicMock(sentiment=MagicMock(polarity=next(polarities), subjectivity=0.5)),
            raising=False,
        )

        score = SentimentAnalyzer().get_average_sentiment(["a", "b", "c"])

        assert score.polarity == pytest.approx(0.2)
        assert score.label is SentimentLabel.POSITIVE


# ── tier selection ────────────────────────────────────────────────────────────


class TestTierSelection:
    def test_vader_is_used_when_available(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", True)
        monkeypatch.setattr(sentiment_mod, "SentimentIntensityAnalyzer", MagicMock, raising=False)

        assert FinancialSentimentAnalyzer(use_finbert=False).use_vader is True

    def test_an_unavailable_vader_is_not_pretended_to_be_present(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", False)

        analyzer = FinancialSentimentAnalyzer(use_vader=True, use_finbert=False)

        assert analyzer.use_vader is False
        assert analyzer.vader is None

    def test_vader_can_be_declined_explicitly(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", True)

        assert FinancialSentimentAnalyzer(use_vader=False, use_finbert=False).vader is None

    def test_finbert_defaults_on_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("NEWS_FINBERT_SENTIMENT", "true")
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", False)

        # Construction must succeed whether or not the transformer deps exist.
        FinancialSentimentAnalyzer(use_vader=False)

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_finbert_can_be_disabled_by_the_environment(self, monkeypatch, value):
        monkeypatch.setenv("NEWS_FINBERT_SENTIMENT", value)
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", False)

        assert FinancialSentimentAnalyzer(use_vader=False)._finbert is None

    def test_the_kwarg_overrides_the_environment(self, monkeypatch):
        monkeypatch.setenv("NEWS_FINBERT_SENTIMENT", "true")
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", False)

        assert FinancialSentimentAnalyzer(use_vader=False, use_finbert=False)._finbert is None


# ── the VADER tier ────────────────────────────────────────────────────────────


class TestVaderTier:
    def _analyzer(self, monkeypatch, scores):
        monkeypatch.setattr(sentiment_mod, "VADER_AVAILABLE", True)
        vader = MagicMock()
        vader.polarity_scores.return_value = scores
        monkeypatch.setattr(sentiment_mod, "SentimentIntensityAnalyzer", lambda: vader, raising=False)
        analyzer = FinancialSentimentAnalyzer(use_finbert=False)
        analyzer._finbert = None
        return analyzer, vader

    def test_the_compound_score_becomes_the_polarity(self, monkeypatch):
        analyzer, _ = self._analyzer(monkeypatch, {"compound": 0.72, "pos": 0.6, "neg": 0.0, "neu": 0.4})

        score = analyzer.analyze("gold rallies")

        assert score.polarity == pytest.approx(0.72)
        assert score.compound_score == pytest.approx(0.72)

    def test_subjectivity_is_one_minus_the_neutral_share(self, monkeypatch):
        analyzer, _ = self._analyzer(monkeypatch, {"compound": 0.5, "pos": 0.5, "neg": 0.1, "neu": 0.4})

        assert analyzer.analyze("x").subjectivity == pytest.approx(0.6)

    def test_confidence_is_the_strongest_of_the_three_shares(self, monkeypatch):
        analyzer, _ = self._analyzer(monkeypatch, {"compound": 0.5, "pos": 0.3, "neg": 0.1, "neu": 0.6})

        assert analyzer.analyze("x").confidence == pytest.approx(0.6)

    def test_the_title_is_weighted_by_repetition(self, monkeypatch):
        """The title counts twice — it is the part a trader actually reads."""
        analyzer, vader = self._analyzer(monkeypatch, {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0})

        analyzer.analyze("body text", title="HEADLINE")

        assert vader.polarity_scores.call_args.args[0] == "HEADLINE HEADLINE body text"

    def test_a_failing_vader_degrades_to_neutral(self, monkeypatch):
        analyzer, vader = self._analyzer(monkeypatch, {})
        vader.polarity_scores.side_effect = RuntimeError("lexicon missing")

        score = analyzer.analyze("x")

        assert score.polarity == 0.0
        assert score.label is SentimentLabel.NEUTRAL


# ── the keyword tier ──────────────────────────────────────────────────────────


class TestKeywordTier:
    def test_it_is_reached_when_no_model_is_available(self, keyword_analyzer):
        assert keyword_analyzer.analyze("gold surges to a record").polarity > 0

    def test_bullish_words_score_positive(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("shares surge and rally on strong growth").polarity == 1.0

    def test_bearish_words_score_negative(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("shares plunge on weak results and loss").polarity == -1.0

    def test_a_balanced_mix_is_neutral(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("a rally then a plunge").polarity == pytest.approx(0.0)

    def test_no_keywords_means_no_signal_and_no_confidence(self, keyword_analyzer):
        score = keyword_analyzer._keyword_analysis("the meeting is on tuesday")

        assert score.polarity == 0.0
        assert score.confidence == 0.0
        assert score.label is SentimentLabel.NEUTRAL

    def test_matching_is_case_insensitive(self, keyword_analyzer):
        assert keyword_analyzer._keyword_analysis("STOCKS SURGE AND RALLY").polarity > 0

    def test_more_evidence_raises_confidence(self, keyword_analyzer):
        few = keyword_analyzer._keyword_analysis("surge")
        many = keyword_analyzer._keyword_analysis("surge soar rally gain profit growth")

        assert many.confidence > few.confidence

    def test_confidence_is_capped_at_one(self, keyword_analyzer):
        text = " ".join(FinancialSentimentAnalyzer.BULLISH_KEYWORDS | FinancialSentimentAnalyzer.BEARISH_KEYWORDS)

        assert keyword_analyzer._keyword_analysis(text).confidence <= 1.0

    def test_subjectivity_is_capped_at_one(self, keyword_analyzer):
        text = " ".join(FinancialSentimentAnalyzer.BULLISH_KEYWORDS | FinancialSentimentAnalyzer.BEARISH_KEYWORDS)

        assert keyword_analyzer._keyword_analysis(text).subjectivity <= 1.0

    def test_the_two_keyword_sets_do_not_overlap(self):
        """A word in both sets would cancel itself out and read as neutral."""
        overlap = FinancialSentimentAnalyzer.BULLISH_KEYWORDS & FinancialSentimentAnalyzer.BEARISH_KEYWORDS

        assert overlap == set()


# ── the financial label ladder ────────────────────────────────────────────────


class TestFinancialLabelLadder:
    @pytest.mark.parametrize(
        ("polarity", "expected"),
        [
            (0.9, SentimentLabel.VERY_POSITIVE),
            (0.5, SentimentLabel.VERY_POSITIVE),
            (0.2, SentimentLabel.POSITIVE),
            (0.05, SentimentLabel.POSITIVE),
            (0.0, SentimentLabel.NEUTRAL),
            (-0.04, SentimentLabel.NEUTRAL),
            (-0.05, SentimentLabel.NEGATIVE),
            (-0.5, SentimentLabel.VERY_NEGATIVE),
        ],
    )
    def test_it_turns_at_a_twentieth_not_a_tenth(self, keyword_analyzer, polarity, expected):
        assert keyword_analyzer._get_label(polarity) is expected

    def test_the_financial_ladder_is_more_sensitive_than_the_general_one(self, keyword_analyzer, monkeypatch):
        """VADER compounds cluster nearer zero, so the financial band is tighter.

        0.07 reads POSITIVE to the financial analyzer and NEUTRAL to the
        general one. That divergence is deliberate; collapsing the two ladders
        would silently re-tune every signal this module emits.
        """
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)

        assert keyword_analyzer._get_label(0.07) is SentimentLabel.POSITIVE
        assert SentimentAnalyzer()._get_label(0.07) is SentimentLabel.NEUTRAL


# ── entity extraction ─────────────────────────────────────────────────────────


class TestExtractEntities:
    def test_it_always_returns_the_three_buckets(self, keyword_analyzer):
        assert set(keyword_analyzer.extract_entities("nothing here")) == {
            "companies",
            "currencies",
            "instruments",
        }

    def test_a_slashed_currency_pair_is_found(self, keyword_analyzer):
        assert "EUR/USD" in keyword_analyzer.extract_entities("EUR/USD is rising")["currencies"]

    def test_a_six_letter_pair_is_found(self, keyword_analyzer):
        assert "XAUUSD" in keyword_analyzer.extract_entities("XAUUSD broke out")["currencies"]

    def test_duplicates_are_collapsed(self, keyword_analyzer):
        found = keyword_analyzer.extract_entities("XAUUSD then XAUUSD again")["currencies"]

        assert found.count("XAUUSD") == 1

    def test_a_symbol_before_the_word_stock_is_an_instrument(self, keyword_analyzer):
        assert "AAPL" in keyword_analyzer.extract_entities("AAPL stock rose")["instruments"]

    def test_a_bare_symbol_is_not_claimed_as_an_instrument(self, keyword_analyzer):
        assert keyword_analyzer.extract_entities("AAPL rose today")["instruments"] == []

    def test_lowercase_text_yields_nothing(self, keyword_analyzer):
        entities = keyword_analyzer.extract_entities("eurusd is rising")

        assert entities["currencies"] == []


class TestAnalyzeWithEntities:
    def test_it_returns_both_halves(self, keyword_analyzer):
        score, entities = keyword_analyzer.analyze_with_entities("XAUUSD will surge", title="Gold rally")

        assert isinstance(score, SentimentScore)
        assert "XAUUSD" in entities["currencies"]

    def test_the_title_is_searched_for_entities_too(self, keyword_analyzer):
        _score_, entities = keyword_analyzer.analyze_with_entities("body", title="EUR/USD update")

        assert "EUR/USD" in entities["currencies"]


# ── batch aggregation ─────────────────────────────────────────────────────────


class TestAnalyzeBatch:
    def test_an_empty_batch_is_neutral_with_no_confidence(self, keyword_analyzer):
        score = keyword_analyzer.analyze_batch([])

        assert score.polarity == 0.0
        assert score.confidence == 0.0
        assert score.label is SentimentLabel.NEUTRAL

    def test_it_averages_across_the_batch(self, keyword_analyzer):
        score = keyword_analyzer.analyze_batch(["a strong rally and record growth", "a plunge and a crash"])

        assert -1.0 <= score.polarity <= 1.0

    def test_a_uniformly_bullish_batch_is_bullish(self, keyword_analyzer):
        score = keyword_analyzer.analyze_batch(["surge rally gain", "profit growth strong"])

        assert score.is_bullish()

    def test_a_uniformly_bearish_batch_is_bearish(self, keyword_analyzer):
        score = keyword_analyzer.analyze_batch(["plunge crash loss", "decline weak downgrade"])

        assert score.is_bearish()

    def test_a_single_text_batch_matches_analyzing_it_alone(self, keyword_analyzer):
        batch = keyword_analyzer.analyze_batch(["a strong rally"])
        single = keyword_analyzer.analyze("a strong rally")

        assert batch.polarity == pytest.approx(single.polarity)

    def test_a_missing_compound_score_averages_as_zero_rather_than_raising(self, keyword_analyzer):
        """The keyword tier emits no compound score; summing None would raise."""
        score = keyword_analyzer.analyze_batch(["surge", "plunge"])

        assert score.compound_score == pytest.approx(0.0)

    def test_the_label_follows_the_averaged_polarity(self, keyword_analyzer):
        score = keyword_analyzer.analyze_batch(["surge rally gain profit"])

        assert score.label in (SentimentLabel.POSITIVE, SentimentLabel.VERY_POSITIVE)


# ── module singletons ─────────────────────────────────────────────────────────


class TestSingletons:
    def test_the_financial_analyzer_is_shared(self):
        assert get_financial_analyzer() is get_financial_analyzer()

    def test_the_general_analyzer_is_shared_when_textblob_is_present(self, monkeypatch):
        monkeypatch.setattr(sentiment_mod, "_sentiment_analyzer", None, raising=False)
        monkeypatch.setattr(sentiment_mod, "TEXTBLOB_AVAILABLE", True)

        assert get_sentiment_analyzer() is get_sentiment_analyzer()
