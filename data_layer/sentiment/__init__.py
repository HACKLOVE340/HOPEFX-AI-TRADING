# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/sentiment — Multi-source news sentiment engine for gold.

Public API
----------
    NewsSentimentEngine   Orchestrates Finnhub, FMP, NewsData, AlphaVantage,
                          and NewsAPI feeds. Scores articles with VADER +
                          gold-specific keyword weighting. Produces 4 ML
                          features: sentiment_score, momentum, article_count_1h,
                          bullish_ratio.

    GoldSentimentScorer   Standalone VADER + keyword scorer. Can be used
                          independently of the full engine.

Usage
-----
    from data_layer.sentiment import NewsSentimentEngine
    engine = NewsSentimentEngine()
    await engine.start()
    features = engine.get_ml_features()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.sentiment.engine import NewsSentimentEngine  # noqa: F401
except Exception as _exc:
    logger.debug("data_layer.sentiment: NewsSentimentEngine unavailable: %s", _exc)
    NewsSentimentEngine = None  # type: ignore[assignment,misc]

try:
    from data_layer.sentiment.scorer import GoldSentimentScorer  # noqa: F401
except Exception as _exc:
    logger.debug("data_layer.sentiment: GoldSentimentScorer unavailable: %s", _exc)
    GoldSentimentScorer = None  # type: ignore[assignment,misc]

__all__ = ["GoldSentimentScorer", "NewsSentimentEngine"]
