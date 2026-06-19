# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Sentiment Analysis Module

Analyzes news articles to determine market sentiment using multiple approaches:
- TextBlob: General purpose sentiment
- VADER: Social media and financial text sentiment
- Custom financial sentiment model

Author: HOPEFX Development Team
"""

import logging
import os
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Try importing sentiment libraries
try:
    from textblob import TextBlob

    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False
    logger.debug("TextBlob not available — VADER is the primary analyzer")

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    logger.warning("VADER not available. Install with: pip install vaderSentiment")


class SentimentLabel(Enum):
    """Sentiment classification labels"""

    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


@dataclass
class SentimentScore:
    """
    Represents sentiment analysis results
    """

    polarity: float  # -1 (negative) to +1 (positive)
    subjectivity: float  # 0 (objective) to 1 (subjective)
    confidence: float  # 0 to 1
    label: SentimentLabel
    compound_score: float | None = None  # VADER compound score

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "polarity": self.polarity,
            "subjectivity": self.subjectivity,
            "confidence": self.confidence,
            "label": self.label.value,
            "compound_score": self.compound_score,
        }

    def is_bullish(self, threshold: float = 0.1) -> bool:
        """Check if sentiment is bullish"""
        return self.polarity > threshold

    def is_bearish(self, threshold: float = -0.1) -> bool:
        """Check if sentiment is bearish"""
        return self.polarity < threshold

    def is_neutral(self, threshold: float = 0.1) -> bool:
        """Check if sentiment is neutral"""
        return abs(self.polarity) <= threshold


class SentimentAnalyzer:
    """
    General sentiment analyzer using TextBlob
    """

    def __init__(self):
        if not TEXTBLOB_AVAILABLE:
            raise ImportError("TextBlob is required. Install with: pip install textblob")
        self.logger = logging.getLogger(self.__class__.__name__)

    def analyze(self, text: str) -> SentimentScore:
        """
        Analyze sentiment of text using TextBlob

        Args:
            text: Text to analyze

        Returns:
            SentimentScore object
        """
        try:
            # Create TextBlob object
            blob = TextBlob(text)

            # Get polarity and subjectivity
            polarity = blob.sentiment.polarity  # -1 to 1
            subjectivity = blob.sentiment.subjectivity  # 0 to 1

            # Calculate confidence (inverse of subjectivity)
            confidence = 1 - subjectivity

            # Determine label
            label = self._get_label(polarity)

            return SentimentScore(
                polarity=polarity,
                subjectivity=subjectivity,
                confidence=confidence,
                label=label,
            )

        except Exception as e:
            self.logger.error("Error analyzing sentiment: %s", e)

            # Return neutral sentiment on error
            return SentimentScore(
                polarity=0.0,
                subjectivity=0.5,
                confidence=0.0,
                label=SentimentLabel.NEUTRAL,
            )

    def _get_label(self, polarity: float) -> SentimentLabel:
        """Convert polarity score to sentiment label"""
        if polarity >= 0.5:
            return SentimentLabel.VERY_POSITIVE
        if polarity >= 0.1:
            return SentimentLabel.POSITIVE
        if polarity <= -0.5:
            return SentimentLabel.VERY_NEGATIVE
        if polarity <= -0.1:
            return SentimentLabel.NEGATIVE
        return SentimentLabel.NEUTRAL

    def analyze_multiple(self, texts: list[str]) -> list[SentimentScore]:
        """Analyze multiple texts"""
        return [self.analyze(text) for text in texts]

    def get_average_sentiment(self, texts: list[str]) -> SentimentScore:
        """Get average sentiment across multiple texts"""
        scores = self.analyze_multiple(texts)

        avg_polarity = sum(s.polarity for s in scores) / len(scores)
        avg_subjectivity = sum(s.subjectivity for s in scores) / len(scores)
        avg_confidence = sum(s.confidence for s in scores) / len(scores)

        return SentimentScore(
            polarity=avg_polarity,
            subjectivity=avg_subjectivity,
            confidence=avg_confidence,
            label=self._get_label(avg_polarity),
        )


class FinancialSentimentAnalyzer:
    """
    Financial-specific sentiment analyzer using VADER with financial keywords
    """

    # Financial keywords and their sentiment weights
    BULLISH_KEYWORDS = {
        "surge",
        "soar",
        "rally",
        "gain",
        "profit",
        "growth",
        "bullish",
        "upgrade",
        "breakthrough",
        "record",
        "outperform",
        "beat",
        "strong",
        "robust",
        "solid",
        "positive",
        "optimistic",
    }

    BEARISH_KEYWORDS = {
        "plunge",
        "crash",
        "fall",
        "loss",
        "decline",
        "bearish",
        "downgrade",
        "miss",
        "underperform",
        "weak",
        "disappointing",
        "negative",
        "pessimistic",
        "concern",
        "risk",
        "warning",
    }

    def __init__(self, use_vader: bool = True, use_finbert: bool | None = None):
        self.use_vader = use_vader and VADER_AVAILABLE

        if self.use_vader:
            self.vader = SentimentIntensityAnalyzer()
        else:
            self.vader = None
            if use_vader:
                logger.warning("VADER requested but not available")

        self.logger = logging.getLogger(self.__class__.__name__)

        # Optional FinBERT upgrade. When enabled (env NEWS_FINBERT_SENTIMENT=true
        # by default, override via the kwarg) the analyzer prefers the
        # transformer over VADER/keywords. FinBERTScorer itself degrades to VADER
        # when transformers/torch are unavailable, so enabling this is always
        # safe — behaviour is unchanged unless the deps are actually installed.
        if use_finbert is None:
            use_finbert = os.getenv("NEWS_FINBERT_SENTIMENT", "true").lower() in ("1", "true", "yes")
        self._finbert = None
        if use_finbert:
            try:
                from data_layer.sentiment.engine import FinBERTScorer

                self._finbert = FinBERTScorer()
            except Exception as exc:  # pragma: no cover - import guard
                self.logger.debug("FinBERT scorer unavailable (%s) — using VADER/keywords", exc)

    def analyze(self, text: str, title: str = "") -> SentimentScore:
        """
        Analyze financial sentiment

        Args:
            text: Article text
            title: Article title (weighted higher)

        Returns:
            SentimentScore object
        """
        try:
            # Combine title and text (weight title more)
            combined_text = f"{title} {title} {text}"

            # Prefer FinBERT (real financial transformer) when available.
            if self._finbert is not None and self._finbert.is_available:
                polarity = float(self._finbert.score(combined_text))  # [-1, 1]
                magnitude = min(abs(polarity), 1.0)
                return SentimentScore(
                    polarity=polarity,
                    subjectivity=magnitude,            # strong sentiment ≈ more subjective
                    confidence=max(magnitude, 0.5),    # softmax prob of winning class
                    label=self._get_label(polarity),
                    compound_score=polarity,
                )

            # Get VADER sentiment if available
            if self.vader:
                scores = self.vader.polarity_scores(combined_text)
                polarity = scores["compound"]  # -1 to 1

                # Calculate confidence from positive, negative, neutral scores
                confidence = max(scores["pos"], scores["neg"], scores["neu"])

                # Subjectivity estimation (higher when strong pos/neg)
                subjectivity = 1 - scores["neu"]

                return SentimentScore(
                    polarity=polarity,
                    subjectivity=subjectivity,
                    confidence=confidence,
                    label=self._get_label(polarity),
                    compound_score=polarity,
                )
            # Fallback to keyword-based analysis
            return self._keyword_analysis(combined_text)

        except Exception as e:
            self.logger.error("Error in financial sentiment analysis: %s", e)

            return SentimentScore(
                polarity=0.0,
                subjectivity=0.5,
                confidence=0.0,
                label=SentimentLabel.NEUTRAL,
            )

    def _keyword_analysis(self, text: str) -> SentimentScore:
        """Fallback keyword-based sentiment analysis"""
        text_lower = text.lower()

        # Count bullish and bearish keywords
        bullish_count = sum(1 for word in self.BULLISH_KEYWORDS if word in text_lower)
        bearish_count = sum(1 for word in self.BEARISH_KEYWORDS if word in text_lower)

        # Calculate polarity
        total = bullish_count + bearish_count
        if total == 0:
            polarity = 0.0
            confidence = 0.0
        else:
            polarity = (bullish_count - bearish_count) / total
            confidence = min(total / 10, 1.0)  # Cap at 1.0

        # Estimate subjectivity (higher if more keywords)
        subjectivity = min(total / 20, 1.0)

        return SentimentScore(
            polarity=polarity,
            subjectivity=subjectivity,
            confidence=confidence,
            label=self._get_label(polarity),
        )

    def _get_label(self, polarity: float) -> SentimentLabel:
        """Convert polarity score to sentiment label"""
        if polarity >= 0.5:
            return SentimentLabel.VERY_POSITIVE
        if polarity >= 0.05:
            return SentimentLabel.POSITIVE
        if polarity <= -0.5:
            return SentimentLabel.VERY_NEGATIVE
        if polarity <= -0.05:
            return SentimentLabel.NEGATIVE
        return SentimentLabel.NEUTRAL

    def extract_entities(self, text: str) -> dict[str, list[str]]:
        """
        Extract financial entities from text

        Returns:
            Dictionary with 'companies', 'currencies', 'instruments'
        """
        # Simple regex-based entity extraction
        # In production, use spaCy or similar NLP library

        entities = {"companies": [], "currencies": [], "instruments": []}

        # Common currency pairs
        currency_pattern = r"\b([A-Z]{3}/[A-Z]{3}|[A-Z]{6})\b"
        currencies = re.findall(currency_pattern, text)
        entities["currencies"] = list(set(currencies))

        # Stock symbols (simplified)
        symbol_pattern = r"\b[A-Z]{1,5}\b(?=\s+(?:stock|shares|equity))"
        symbols = re.findall(symbol_pattern, text)
        entities["instruments"] = list(set(symbols))

        return entities

    def analyze_with_entities(self, text: str, title: str = "") -> tuple[SentimentScore, dict]:
        """Analyze sentiment and extract entities"""
        sentiment = self.analyze(text, title)
        entities = self.extract_entities(f"{title} {text}")
        return sentiment, entities

    def analyze_batch(self, texts: list[str]) -> SentimentScore:
        """
        Analyze a list of texts and return an aggregated SentimentScore.

        Scores are averaged across all texts.  Returns a neutral score when
        the list is empty.  Used by the /api/news/sentiment/{symbol} endpoint
        to aggregate multiple search-term results into a single signal.
        """
        if not texts:
            return SentimentScore(
                polarity=0.0,
                subjectivity=0.5,
                confidence=0.0,
                label=SentimentLabel.NEUTRAL,
            )

        scores = [self.analyze(t) for t in texts]
        avg_polarity = sum(s.polarity for s in scores) / len(scores)
        avg_subjectivity = sum(s.subjectivity for s in scores) / len(scores)
        avg_confidence = sum(s.confidence for s in scores) / len(scores)
        avg_compound = sum(s.compound_score or 0.0 for s in scores) / len(scores)

        return SentimentScore(
            polarity=avg_polarity,
            subjectivity=avg_subjectivity,
            confidence=avg_confidence,
            label=self._get_label(avg_polarity),
            compound_score=avg_compound,
        )


# Global analyzer instances
_sentiment_analyzer = None
_financial_analyzer = None


def get_sentiment_analyzer() -> SentimentAnalyzer:
    """Get or create global sentiment analyzer"""
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        _sentiment_analyzer = SentimentAnalyzer()
    return _sentiment_analyzer


def get_financial_analyzer() -> FinancialSentimentAnalyzer:
    """Get or create global financial sentiment analyzer"""
    global _financial_analyzer
    if _financial_analyzer is None:
        _financial_analyzer = FinancialSentimentAnalyzer()
    return _financial_analyzer
