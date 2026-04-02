# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/sentiment/scorer.py
================================
GoldSentimentScorer — unified NLP scoring for gold-relevant news.

Scoring pipeline (in order of priority)
-----------------------------------------
1. Pre-scored articles (Alpha Vantage, NewsAPI.ai) — use native score directly
2. VADER sentiment analysis — fast, finance-tuned lexicon
3. Gold-specific keyword amplification — domain-specific signal boost
4. Gold relevance scoring — 0-1 relevance weight
5. Impact score — expected price impact based on relevance × |sentiment|

Gold-specific keyword amplification
-------------------------------------
Standard VADER misses finance-specific signals. We apply multipliers:
  - "rate hike", "hawkish", "taper"  → bearish gold (negative amplifier)
  - "rate cut", "dovish", "QE"       → bullish gold (positive amplifier)
  - "inflation", "CPI beat"          → bullish gold
  - "strong dollar", "DXY up"        → bearish gold
  - "geopolitical", "war", "crisis"  → bullish gold (safe haven)
  - "recession", "slowdown"          → bullish gold

Sentiment score range: -1.0 (strongly bearish) to +1.0 (strongly bullish)
Gold relevance range:   0.0 (irrelevant) to 1.0 (directly about gold)
Impact score range:     0.0 (no impact) to 1.0 (maximum expected impact)
"""

from __future__ import annotations

import logging
import re

from data_layer.types import NewsArticle

logger = logging.getLogger(__name__)

# ── Gold relevance keywords ───────────────────────────────────────────────────
# Tier 1: directly about gold
_GOLD_TIER1: set[str] = {
    "gold",
    "xau",
    "xauusd",
    "bullion",
    "gold price",
    "gold futures",
    "gold etf",
    "gld",
    "iau",
    "gold mining",
    "gold reserves",
    "troy ounce",
    "spot gold",
    "gold rally",
    "gold sell-off",
}

# Tier 2: macro drivers of gold
_GOLD_TIER2: set[str] = {
    "federal reserve",
    "fed rate",
    "interest rate",
    "rate hike",
    "rate cut",
    "inflation",
    "cpi",
    "pce",
    "deflation",
    "stagflation",
    "dollar index",
    "dxy",
    "us dollar",
    "dollar strength",
    "dollar weakness",
    "treasury yield",
    "10-year yield",
    "real yield",
    "tips",
    "quantitative easing",
    "qe",
    "tapering",
    "monetary policy",
    "fomc",
    "powell",
    "yellen",
    "central bank",
    "safe haven",
    "risk off",
    "flight to safety",
    "geopolitical",
    "war",
    "conflict",
    "sanctions",
    "crisis",
    "recession",
    "economic slowdown",
    "gdp miss",
    "silver",
    "platinum",
    "precious metal",
    "commodity",
}

# ── Sentiment amplifiers (gold-specific) ─────────────────────────────────────
# (pattern, multiplier) — multiplier > 1 = amplify, < 1 = dampen
# Positive multiplier = bullish for gold, negative = bearish
_BULLISH_PATTERNS: list[tuple[str, float]] = [
    (r"rate\s+cut", 1.5),
    (r"dovish", 1.4),
    (r"quantitative\s+eas", 1.4),
    (r"\bqe\b", 1.3),
    (r"inflation\s+(surge|spike|jump|rise|high)", 1.4),
    (r"cpi\s+(beat|above|hot|surge)", 1.4),
    (r"dollar\s+(weak|fall|drop|decline|plunge)", 1.3),
    (r"dxy\s+(down|fall|drop|decline)", 1.3),
    (r"geopolit", 1.5),
    (r"\bwar\b", 1.5),
    (r"\bconflict\b", 1.3),
    (r"safe\s+haven", 1.4),
    (r"recession", 1.3),
    (r"economic\s+slowdown", 1.2),
    (r"gdp\s+(miss|below|weak|contract)", 1.2),
    (r"yield\s+(fall|drop|decline)", 1.3),
    (r"real\s+yield\s+(fall|drop|negative)", 1.4),
    (r"gold\s+(rally|surge|jump|rise|soar|climb)", 1.6),
    (r"buy\s+gold", 1.4),
    (r"gold\s+bull", 1.5),
]

_BEARISH_PATTERNS: list[tuple[str, float]] = [
    (r"rate\s+hike", 1.5),
    (r"hawkish", 1.4),
    (r"taper", 1.3),
    (r"dollar\s+(strong|rise|surge|rally|gain)", 1.3),
    (r"dxy\s+(up|rise|surge|rally|gain)", 1.3),
    (r"inflation\s+(cool|ease|fall|drop|low)", 1.3),
    (r"cpi\s+(miss|below|cool|ease)", 1.3),
    (r"yield\s+(rise|surge|jump|climb)", 1.3),
    (r"real\s+yield\s+(rise|positive|high)", 1.4),
    (r"gold\s+(drop|fall|plunge|decline|sell)", 1.6),
    (r"sell\s+gold", 1.4),
    (r"gold\s+bear", 1.5),
    (r"risk\s+on", 1.2),
    (r"risk\s+appetite", 1.2),
]


def _compute_gold_relevance(text: str) -> float:
    """Return gold relevance score [0, 1]."""
    lower = text.lower()
    tier1_hits = sum(1 for kw in _GOLD_TIER1 if kw in lower)
    tier2_hits = sum(1 for kw in _GOLD_TIER2 if kw in lower)
    # Tier 1 is worth 3× tier 2
    raw = tier1_hits * 3 + tier2_hits
    return min(1.0, raw / 6.0)


def _apply_gold_amplifiers(text: str, base_score: float) -> float:
    """
    Apply gold-specific sentiment amplifiers to a base VADER score.

    Gold context overrides generic VADER polarity: a headline containing
    "rate cut" is bullish for gold regardless of VADER's generic score.
    Returns adjusted score in [-1, 1].
    """
    lower = text.lower()

    bullish_hits = sum(1 for p, _ in _BULLISH_PATTERNS if re.search(p, lower))
    bearish_hits = sum(1 for p, _ in _BEARISH_PATTERNS if re.search(p, lower))

    if bullish_hits == 0 and bearish_hits == 0:
        # No gold-specific signals — return VADER score as-is
        return max(-1.0, min(1.0, base_score))

    # Gold context dominates: compute a gold-direction score
    total_hits = bullish_hits + bearish_hits
    gold_direction = (bullish_hits - bearish_hits) / total_hits  # [-1, 1]

    # Blend: 60% gold context + 40% VADER (gold context is more reliable)
    blended = 0.60 * gold_direction + 0.40 * base_score

    # Amplify by the strength of gold signals
    max_mult = (
        max(
            (m for p, m in _BULLISH_PATTERNS if re.search(p, lower)),
            default=1.0,
        )
        if bullish_hits > 0
        else 1.0
    )
    max_mult_b = (
        max(
            (m for p, m in _BEARISH_PATTERNS if re.search(p, lower)),
            default=1.0,
        )
        if bearish_hits > 0
        else 1.0
    )

    dominant_mult = max_mult if bullish_hits >= bearish_hits else max_mult_b
    amplified = blended * min(dominant_mult, 1.8)

    return max(-1.0, min(1.0, amplified))


class GoldSentimentScorer:
    """
    Unified sentiment scorer for gold-relevant news articles.

    Uses VADER as the primary NLP engine with gold-specific amplifiers.
    Falls back to keyword-only scoring when VADER is unavailable.
    """

    def __init__(self) -> None:
        self._vader = None
        self._vader_available = False
        self._init_vader()

    def _init_vader(self) -> None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            self._vader = SentimentIntensityAnalyzer()
            self._vader_available = True
            logger.info("GoldSentimentScorer: VADER loaded")
        except ImportError:
            logger.warning(
                "GoldSentimentScorer: vaderSentiment not installed — "
                "using keyword-only scoring. Install: pip install vaderSentiment"
            )

    def score(self, article: NewsArticle) -> NewsArticle:
        """
        Score a NewsArticle for gold sentiment and relevance.

        Returns a new NewsArticle with sentiment_score, sentiment_label,
        gold_relevance, and impact_score populated.

        Causal guarantee: only uses the article's own text — no future data.
        """
        text = f"{article.headline} {article.summary}"

        # ── Gold relevance ────────────────────────────────────────────────
        gold_relevance = _compute_gold_relevance(text)

        # Skip scoring if not gold-relevant
        if gold_relevance < 0.05:
            return _replace(
                article,
                gold_relevance=0.0,
                sentiment_score=0.0,
                sentiment_label="neutral",
                impact_score=0.0,
            )

        # ── Sentiment score ───────────────────────────────────────────────
        # If article already has a pre-scored sentiment (Alpha Vantage, NewsAPI.ai)
        # use it directly — these are higher quality than VADER
        if abs(article.sentiment_score) > 0.01:
            raw_score = article.sentiment_score
        elif self._vader_available and self._vader:
            scores = self._vader.polarity_scores(text)
            raw_score = scores["compound"]  # [-1, 1]
        else:
            raw_score = self._keyword_score(text)

        # Apply gold-specific amplifiers
        final_score = _apply_gold_amplifiers(text, raw_score)

        # Weight by gold relevance
        weighted_score = final_score * gold_relevance

        # Label
        if weighted_score > 0.15:
            label = "bullish"
        elif weighted_score < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        # Impact score: relevance × |sentiment| × recency_factor
        impact = min(1.0, gold_relevance * abs(weighted_score) * 2.0)

        return _replace(
            article,
            sentiment_score=round(weighted_score, 4),
            sentiment_label=label,
            gold_relevance=round(gold_relevance, 4),
            impact_score=round(impact, 4),
        )

    def score_article(self, article: NewsArticle) -> NewsArticle:
        """Alias for score() — preferred public API name."""
        return self.score(article)

    def get_aggregate_signal(
        self,
        articles: list[NewsArticle] | None = None,
    ) -> dict[str, float]:
        """
        Return an aggregate sentiment signal dict from a list of articles.

        If articles is None, returns a neutral signal (used when no articles
        have been scored yet — e.g. at startup before any feeds are live).

        Keys match the orchestrator ML feature names so callers can merge
        directly into the feature dict:
          news_sentiment_score    : EMA of article sentiment scores [-1, 1]
          news_sentiment_momentum : rate of change (0.0 when no history)
          news_article_count_1h   : number of articles provided
          news_bullish_ratio      : fraction of bullish articles [0, 1]
        """
        if not articles:
            return {
                "news_sentiment_score": 0.0,
                "news_sentiment_momentum": 0.0,
                "news_article_count_1h": 0.0,
                "news_bullish_ratio": 0.5,
            }

        ema = 0.0
        alpha = 0.15
        bullish = 0
        for a in articles:
            ema = alpha * a.sentiment_score + (1.0 - alpha) * ema
            if a.sentiment_label == "bullish":
                bullish += 1

        bull_ratio = bullish / len(articles) if articles else 0.5
        return {
            "news_sentiment_score": round(ema, 4),
            "news_sentiment_momentum": 0.0,
            "news_article_count_1h": float(len(articles)),
            "news_bullish_ratio": round(bull_ratio, 4),
        }

    def score_batch(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Score a list of articles. Returns scored articles only (relevance > 0)."""
        scored = []
        for article in articles:
            try:
                s = self.score(article)
                if s.gold_relevance > 0.05:
                    scored.append(s)
            except Exception as exc:
                logger.debug("GoldSentimentScorer.score error: %s", exc)
        return scored

    def _keyword_score(self, text: str) -> float:
        """Fallback keyword-only sentiment when VADER unavailable."""
        lower = text.lower()
        bullish_hits = sum(1 for p, _ in _BULLISH_PATTERNS if re.search(p, lower))
        bearish_hits = sum(1 for p, _ in _BEARISH_PATTERNS if re.search(p, lower))
        total = bullish_hits + bearish_hits
        if total == 0:
            return 0.0
        return (bullish_hits - bearish_hits) / total

    @property
    def vader_available(self) -> bool:
        return self._vader_available


def _replace(article: NewsArticle, **kwargs) -> NewsArticle:
    """Return a new NewsArticle with updated fields (frozen dataclass workaround)."""
    import dataclasses

    return dataclasses.replace(article, **kwargs)


# Module-level singleton
gold_sentiment_scorer = GoldSentimentScorer()
