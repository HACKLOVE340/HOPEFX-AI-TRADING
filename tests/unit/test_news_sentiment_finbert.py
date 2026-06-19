# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_news_sentiment_finbert.py
==========================================
Tests the FinBERT upgrade path in news/sentiment.py::FinancialSentimentAnalyzer.

The transformer itself isn't installed in CI, so a fake FinBERTScorer is
injected to exercise the analyze() branch deterministically, plus a test that
the analyzer degrades safely when FinBERT is unavailable.
"""

from __future__ import annotations

from news.sentiment import FinancialSentimentAnalyzer, SentimentLabel


class _FakeFinBERT:
    """Stand-in for data_layer FinBERTScorer."""

    def __init__(self, score: float, available: bool = True):
        self._score = score
        self._available = available

    @property
    def is_available(self) -> bool:
        return self._available

    def score(self, _text: str) -> float:
        return self._score


def _analyzer_with_finbert(score: float, available: bool = True) -> FinancialSentimentAnalyzer:
    # Build without auto-loading FinBERT, then inject the fake scorer.
    a = FinancialSentimentAnalyzer(use_finbert=False)
    a._finbert = _FakeFinBERT(score, available)
    return a


def test_finbert_positive_drives_polarity() -> None:
    a = _analyzer_with_finbert(0.85)
    s = a.analyze("Gold rallies on safe-haven demand", "Gold surges")
    assert s.polarity == 0.85
    assert s.compound_score == 0.85
    assert s.label in (SentimentLabel.POSITIVE, SentimentLabel.VERY_POSITIVE)
    assert 0.0 <= s.confidence <= 1.0


def test_finbert_negative_drives_polarity() -> None:
    a = _analyzer_with_finbert(-0.7)
    s = a.analyze("Gold plunges as the dollar strengthens", "Gold crashes")
    assert s.polarity == -0.7
    assert s.label in (SentimentLabel.NEGATIVE, SentimentLabel.VERY_NEGATIVE)


def test_finbert_unavailable_falls_back() -> None:
    # is_available False → analyzer must use VADER/keyword path, not FinBERT.
    a = _analyzer_with_finbert(0.9, available=False)
    s = a.analyze("Gold gains on strong economic data", "Bullish gold")
    # Still a valid score, and NOT the FinBERT value (0.9).
    assert -1.0 <= s.polarity <= 1.0
    assert s.polarity != 0.9


def test_use_finbert_false_disables_branch() -> None:
    a = FinancialSentimentAnalyzer(use_finbert=False)
    assert a._finbert is None
    s = a.analyze("Gold surges to a record high", "Record gold")
    assert -1.0 <= s.polarity <= 1.0
