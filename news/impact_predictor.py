"""
Impact Predictor Module

Predicts market impact of news events based on:
- Historical correlations
- Event categorization
- Sentiment analysis
- Volatility patterns

Author: HOPEFX Development Team
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ImpactLevel(Enum):
    """Market impact classification"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class EventCategory(Enum):
    """News event categories"""
    ECONOMIC_DATA = "economic_data"
    CENTRAL_BANK = "central_bank"
    EARNINGS = "earnings"
    GEOPOLITICAL = "geopolitical"
    REGULATORY = "regulatory"
    CORPORATE = "corporate"
    MARKET_MOVE = "market_move"
    OTHER = "other"


@dataclass
class MarketImpact:
    """Represents predicted market impact"""
    level: ImpactLevel
    category: EventCategory
    confidence: float  # 0 to 1
    expected_volatility: float  # Percentage
    direction_bias: Optional[str] = None  # 'bullish', 'bearish', or None
    affected_symbols: Optional[List[str]] = None
    timeframe: str = "intraday"  # 'intraday', 'short_term', 'medium_term'

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'level': self.level.value,
            'category': self.category.value,
            'confidence': self.confidence,
            'expected_volatility': self.expected_volatility,
            'direction_bias': self.direction_bias,
            'affected_symbols': self.affected_symbols,
            'timeframe': self.timeframe
        }


class ImpactPredictor:
    """
    Predicts market impact of news events
    """

    # High-impact keywords
    HIGH_IMPACT_KEYWORDS = {
        'central bank', 'fed', 'ecb', 'boj', 'interest rate', 'rate hike',
        'rate cut', 'quantitative easing', 'monetary policy', 'inflation',
        'gdp', 'employment', 'unemployment', 'nonfarm payrolls', 'cpi',
        'war', 'crisis', 'pandemic', 'emergency', 'collapse', 'bankruptcy'
    }

    # Category keywords
    CATEGORY_KEYWORDS = {
        EventCategory.CENTRAL_BANK: ['fed', 'ecb', 'boj', 'central bank', 'fomc', 'rate decision'],
        EventCategory.ECONOMIC_DATA: ['gdp', 'cpi', 'inflation', 'employment', 'retail sales', 'pmi'],
        EventCategory.EARNINGS: ['earnings', 'profit', 'revenue', 'eps', 'quarterly results'],
        EventCategory.GEOPOLITICAL: ['war', 'conflict', 'sanctions', 'election', 'trade war'],
        EventCategory.REGULATORY: ['regulation', 'sec', 'fda', 'approval', 'ban', 'restriction'],
        EventCategory.CORPORATE: ['merger', 'acquisition', 'ceo', 'dividend', 'buyback'],
        EventCategory.MARKET_MOVE: ['surge', 'plunge', 'rally', 'crash', 'selloff']
    }

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.historical_impacts = {}  # Store historical patterns

    def predict_impact(
        self,
        title: str,
        description: str,
        sentiment_score: Optional[float] = None,
        symbols: Optional[List[str]] = None
    ) -> MarketImpact:
        """
        Predict market impact of a news event

        Args:
            title: News title
            description: News description
            sentiment_score: Sentiment polarity (-1 to 1)
            symbols: Related symbols

        Returns:
            MarketImpact object
        """
        try:
            # Combine text for analysis
            text = f"{title} {description}".lower()

            # Determine event category
            category = self._categorize_event(text)

            # Calculate base impact level
            impact_level = self._calculate_impact_level(text, category)

            # Calculate confidence
            confidence = self._calculate_confidence(text, category, sentiment_score)

            # Estimate volatility
            volatility = self._estimate_volatility(impact_level, category)

            # Determine direction bias
            direction_bias = self._determine_direction(sentiment_score)

            # Estimate timeframe
            timeframe = self._estimate_timeframe(category)

            return MarketImpact(
                level=impact_level,
                category=category,
                confidence=confidence,
                expected_volatility=volatility,
                direction_bias=direction_bias,
                affected_symbols=symbols,
                timeframe=timeframe
            )

        except Exception as e:
            self.logger.error(f"Error predicting impact: {e}")
            # Return low impact on error
            return MarketImpact(
                level=ImpactLevel.LOW,
                category=EventCategory.OTHER,
                confidence=0.0,
                expected_volatility=0.0
            )

    def _categorize_event(self, text: str) -> EventCategory:
        """Categorize the news event"""
        # Count keyword matches for each category
        scores = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword in text)
            scores[category] = score

        # Return category with highest score
        if scores:
            max_category = max(scores, key=scores.get)
            if scores[max_category] > 0:
                return max_category

        return EventCategory.OTHER

    def _calculate_impact_level(self, text: str, category: EventCategory) -> ImpactLevel:
        """Calculate impact level based on keywords and category"""
        # Count high-impact keywords
        high_impact_count = sum(1 for keyword in self.HIGH_IMPACT_KEYWORDS if keyword in text)

        # Category-based base impact
        category_impact = {
            EventCategory.CENTRAL_BANK: 4,
            EventCategory.ECONOMIC_DATA: 3,
            EventCategory.GEOPOLITICAL: 3,
            EventCategory.EARNINGS: 2,
            EventCategory.REGULATORY: 2,
            EventCategory.CORPORATE: 1,
            EventCategory.MARKET_MOVE: 3,
            EventCategory.OTHER: 1
        }

        # Calculate total score
        score = category_impact.get(category, 1) + high_impact_count

        # Map score to impact level
        if score >= 6:
            return ImpactLevel.VERY_HIGH
        elif score >= 4:
            return ImpactLevel.HIGH
        elif score >= 3:
            return ImpactLevel.MEDIUM
        elif score >= 2:
            return ImpactLevel.LOW
        else:
            return ImpactLevel.VERY_LOW

    def _calculate_confidence(
        self,
        text: str,
        category: EventCategory,
        sentiment_score: Optional[float]
    ) -> float:
        """Calculate confidence in prediction"""
        confidence = 0.5  # Base confidence

        # Increase confidence if we have sentiment
        if sentiment_score is not None:
            confidence += 0.2

        # Increase confidence for well-defined categories
        if category != EventCategory.OTHER:
            confidence += 0.1

        # Increase confidence if high-impact keywords present
        keyword_count = sum(1 for keyword in self.HIGH_IMPACT_KEYWORDS if keyword in text)
        confidence += min(keyword_count * 0.1, 0.2)

        return min(confidence, 1.0)

    def _estimate_volatility(self, impact_level: ImpactLevel, category: EventCategory) -> float:
        """Estimate expected volatility (as percentage)"""
        # Base volatility by impact level
        volatility_map = {
            ImpactLevel.VERY_LOW: 0.1,
            ImpactLevel.LOW: 0.3,
            ImpactLevel.MEDIUM: 0.6,
            ImpactLevel.HIGH: 1.0,
            ImpactLevel.VERY_HIGH: 2.0
        }

        base_volatility = volatility_map.get(impact_level, 0.3)

        # Adjust for category
        if category == EventCategory.CENTRAL_BANK:
            base_volatility *= 1.5
        elif category == EventCategory.GEOPOLITICAL:
            base_volatility *= 1.3

        return base_volatility

    def _determine_direction(self, sentiment_score: Optional[float]) -> Optional[str]:
        """Determine market direction bias"""
        if sentiment_score is None:
            return None

        if sentiment_score > 0.1:
            return 'bullish'
        elif sentiment_score < -0.1:
            return 'bearish'
        else:
            return None

    def _estimate_timeframe(self, category: EventCategory) -> str:
        """Estimate impact timeframe"""
        # Central bank and geopolitical events have longer-term impact
        if category in [EventCategory.CENTRAL_BANK, EventCategory.GEOPOLITICAL]:
            return 'medium_term'
        # Economic data has short-term impact
        elif category == EventCategory.ECONOMIC_DATA:
            return 'short_term'
        # Most others are intraday
        else:
            return 'intraday'

    def batch_predict(
        self,
        articles: List[Dict]
    ) -> List[MarketImpact]:
        """
        Predict impact for multiple articles

        Args:
            articles: List of article dictionaries with title, description, etc.

        Returns:
            List of MarketImpact objects
        """
        impacts = []
        for article in articles:
            impact = self.predict_impact(
                title=article.get('title', ''),
                description=article.get('description', ''),
                sentiment_score=article.get('sentiment'),
                symbols=article.get('symbols')
            )
            impacts.append(impact)

        return impacts

    def get_high_impact_events(
        self,
        articles: List[Dict],
        min_level: ImpactLevel = ImpactLevel.HIGH
    ) -> List[Dict]:
        """Filter articles for high-impact events"""
        high_impact = []

        for article in articles:
            impact = self.predict_impact(
                title=article.get('title', ''),
                description=article.get('description', ''),
                sentiment_score=article.get('sentiment'),
                symbols=article.get('symbols')
            )

            # Check if impact level is high enough
            impact_values = {
                ImpactLevel.VERY_LOW: 1,
                ImpactLevel.LOW: 2,
                ImpactLevel.MEDIUM: 3,
                ImpactLevel.HIGH: 4,
                ImpactLevel.VERY_HIGH: 5
            }

            if impact_values[impact.level] >= impact_values[min_level]:
                article['predicted_impact'] = impact.to_dict()
                high_impact.append(article)

        return high_impact


# Global predictor instance
_impact_predictor = None


def get_impact_predictor() -> ImpactPredictor:
    """Get or create global impact predictor"""
    global _impact_predictor
    if _impact_predictor is None:
        _impact_predictor = ImpactPredictor()
    return _impact_predictor
