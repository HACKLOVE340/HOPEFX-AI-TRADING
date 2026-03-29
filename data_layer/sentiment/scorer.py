# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/sentiment/scorer.py
================================
GoldSentimentScorer — scores news articles for gold price impact.

Scoring pipeline
----------------
1. Gold relevance filter  — keyword density score (0-1)
2. Sentiment polarity     — VADER lexicon (no model download required) or
                            pre-scored value from API (Alpha Vantage, Finnhub)
3. Impact amplification   — high-impact keywords (war, Fed, CPI) boost score
4. Recency decay          — articles older than 4h are exponentially decayed
5. Aggregate signal       — EMA of scored articles → single float [-1, +1]
                            where +1 = strongly bullish for gold

The scorer injects three features into the ML pipeline:
  - news_sentiment_score   : EMA of article scores [-1, +1]
  - news_sentiment_momentum: rate of change of EMA
  - news_article_count_1h  : articles processed in last hour (buzz proxy)

No external model downloads required — VADER is pure Python.
Falls back to keyword-only scoring if VADER is unavailable.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from data_layer.types import NewsArticle

logger = logging.getLogger(__name__)

# ── VADER sentiment (optional) ────────────────────────────────────────────────
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore
    _VADER = SentimentIntensityAnalyzer()
    _HAS_VADER = True
except ImportError:
    _VADER = None
    _HAS_VADER = False
    logger.debug("vaderSentiment not installed — using keyword-only scoring")

# ── Gold-specific lexicon adjustments ─────────────────────────────────────────
# Words that are bullish for gold (positive score)
_GOLD_BULLISH: Dict[str, float] = {
    "war": 0.6, "conflict": 0.5, "crisis": 0.5, "recession": 0.4,
    "inflation": 0.4, "stagflation": 0.6, "default": 0.5,
    "rate cut": 0.5, "dovish": 0.4, "stimulus": 0.3,
    "safe haven": 0.7, "flight to safety": 0.7, "uncertainty": 0.3,
    "geopolit": 0.5, "sanctions": 0.4, "devaluation": 0.5,
    "debt ceiling": 0.4, "banking crisis": 0.6, "bank run": 0.6,
    "gold rally": 0.8, "gold surge": 0.8, "gold hits": 0.5,
    "buy gold": 0.6, "gold demand": 0.4, "etf inflow": 0.4,
    "central bank buying": 0.7, "reserve accumulation": 0.5,
}

# Words that are bearish for gold (negative score)
_GOLD_BEARISH: Dict[str, float] = {
    "rate hike": -0.5, "hawkish": -0.4, "tightening": -0.4,
    "strong dollar": -0.4, "dollar rally": -0.4, "risk on": -0.3,
    "gold falls": -0.6, "gold drops": -0.6, "gold slumps": -0.7,
    "sell gold": -0.5, "gold outflow": -0.4, "etf outflow": -0.4,
    "profit taking": -0.3, "gold weakness": -0.5,
    "economic growth": -0.2, "jobs report beat": -0.3,
}

# High-impact event keywords that amplify the score
_HIGH_IMPACT: set = {
    "federal reserve", "fomc", "powell", "yellen", "ecb", "boe",
    "cpi", "inflation data", "nonfarm payroll", "gdp", "unemployment",
    "nuclear", "war", "invasion", "default", "banking crisis",
    "fed rate", "interest rate decision",
}

_RECENCY_HALF_LIFE_H = 4.0   # score halves every 4 hours
_EMA_ALPHA           = 0.15  # EMA smoothing factor for aggregate signal
_WINDOW_SIZE         = 500   # rolling article window


class GoldSentimentScorer:
    """
    Scores news articles for gold price impact and maintains
    a rolling aggregate sentiment signal.
    """

    def __init__(self) -> None:
        self._ema: float = 0.0
        self._prev_ema: float = 0.0
        self._article_window: deque = deque(maxlen=_WINDOW_SIZE)
        self._scored_count: int = 0
        self._last_update: float = time.time()

    # ── Public API ────────────────────────────────────────────────────────────

    def score_article(self, article: NewsArticle) -> NewsArticle:
        """
        Score a single article and return an updated NewsArticle with
        sentiment_score, sentiment_label, gold_relevance, and impact_score set.
        """
        text = f"{article.headline} {article.summary}".lower()

        # 1. Gold relevance
        relevance = self._gold_relevance(text)
        if relevance < 0.05:
            # Not gold-relevant — return with zero scores
            return _replace(article, gold_relevance=0.0, sentiment_score=0.0,
                            sentiment_label="neutral", impact_score=0.0)

        # 2. Base sentiment
        if article.sentiment_score != 0.0:
            # API already provided a score (Alpha Vantage, Finnhub)
            base_score = float(article.sentiment_score)
        elif _HAS_VADER:
            vs = _VADER.polarity_scores(f"{article.headline} {article.summary}")
            base_score = vs["compound"]   # -1 to +1
        else:
            base_score = self._keyword_sentiment(text)

        # 3. Gold-specific lexicon adjustment
        gold_adj = self._gold_lexicon_score(text)
        combined = base_score * 0.6 + gold_adj * 0.4

        # 4. High-impact amplification
        impact_mult = 1.5 if any(kw in text for kw in _HIGH_IMPACT) else 1.0
        final_score = max(-1.0, min(1.0, combined * impact_mult))

        # 5. Recency decay
        age_h = (datetime.now(timezone.utc) - article.published_at).total_seconds() / 3600
        decay = math.exp(-math.log(2) * age_h / _RECENCY_HALF_LIFE_H)
        decayed_score = final_score * decay

        # 6. Impact score (0-1, magnitude of expected price move)
        impact_score = min(1.0, abs(decayed_score) * relevance * impact_mult)

        # 7. Label
        if final_score > 0.15:
            label = "bullish"
        elif final_score < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        # Update aggregate EMA
        self._update_ema(decayed_score)
        self._article_window.append({
            "ts":    time.time(),
            "score": decayed_score,
        })
        self._scored_count += 1

        return _replace(
            article,
            sentiment_score = round(final_score, 4),
            sentiment_label = label,
            gold_relevance  = round(relevance, 4),
            impact_score    = round(impact_score, 4),
        )

    def score_batch(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """Score a list of articles, sorted by published_at ascending (causal order)."""
        sorted_articles = sorted(articles, key=lambda a: a.published_at)
        return [self.score_article(a) for a in sorted_articles]

    def get_aggregate_signal(self) -> Dict[str, float]:
        """
        Return the current aggregate sentiment signal for ML injection.

        Keys:
          news_sentiment_score    : EMA of recent article scores [-1, +1]
          news_sentiment_momentum : EMA delta (rate of change)
          news_article_count_1h   : articles scored in last hour
          news_bullish_ratio      : fraction of recent articles that are bullish
        """
        now = time.time()
        recent = [r for r in self._article_window if now - r["ts"] < 3600]
        count_1h = len(recent)

        bullish = sum(1 for r in recent if r["score"] > 0.05)
        bullish_ratio = bullish / max(count_1h, 1)

        return {
            "news_sentiment_score":    round(self._ema, 4),
            "news_sentiment_momentum": round(self._ema - self._prev_ema, 4),
            "news_article_count_1h":   float(count_1h),
            "news_bullish_ratio":      round(bullish_ratio, 4),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _update_ema(self, score: float) -> None:
        self._prev_ema = self._ema
        self._ema = _EMA_ALPHA * score + (1 - _EMA_ALPHA) * self._ema

    def _gold_relevance(self, text: str) -> float:
        """Keyword density score for gold relevance (0-1)."""
        from data_layer.feeds.news.base import GOLD_KEYWORDS
        hits = sum(1 for kw in GOLD_KEYWORDS if kw in text)
        return min(1.0, hits / 3.0)   # 3+ hits = max relevance

    def _gold_lexicon_score(self, text: str) -> float:
        """Gold-specific lexicon score (-1 to +1)."""
        score = 0.0
        for phrase, val in _GOLD_BULLISH.items():
            if phrase in text:
                score += val
        for phrase, val in _GOLD_BEARISH.items():
            if phrase in text:
                score += val   # val is already negative
        return max(-1.0, min(1.0, score))

    def _keyword_sentiment(self, text: str) -> float:
        """Fallback keyword-only sentiment when VADER is unavailable."""
        pos_words = {"surge", "rally", "gain", "rise", "jump", "soar", "strong",
                     "bullish", "positive", "growth", "beat", "record"}
        neg_words = {"fall", "drop", "decline", "slump", "crash", "weak",
                     "bearish", "negative", "miss", "loss", "concern", "fear"}
        words = set(text.split())
        pos = len(words & pos_words)
        neg = len(words & neg_words)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total


# ── Dataclass replace helper (frozen dataclass workaround) ────────────────────

def _replace(article: NewsArticle, **kwargs) -> NewsArticle:
    """Return a new NewsArticle with updated fields."""
    import dataclasses
    return dataclasses.replace(article, **kwargs)


# Module-level singleton
gold_sentiment_scorer = GoldSentimentScorer()
