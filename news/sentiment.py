"""
Sentiment Analysis Module

Analyzes news articles to determine market sentiment using multiple approaches:
- TextBlob: General purpose sentiment
- VADER: Social media and financial text sentiment
- Custom financial sentiment model

Author: HOPEFX Development Team
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re

logger = logging.getLogger(__name__)

# Try importing sentiment libraries
try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False
    logger.warning("TextBlob not available. Install with: pip install textblob")

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
    compound_score: Optional[float] = None  # VADER compound score
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'polarity': self.polarity,
            'subjectivity': self.subjectivity,
            'confidence': self.confidence,
            'label': self.label.value,
            'compound_score': self.compound_score
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
                label=label
            )
            
        except Exception as e:
            self.logger.error(f"Error analyzing sentiment: {e}")
            # Return neutral sentiment on error
            return SentimentScore(
                polarity=0.0,
                subjectivity=0.5,
                confidence=0.0,
                label=SentimentLabel.NEUTRAL
            )
    
    def _get_label(self, polarity: float) -> SentimentLabel:
        """Convert polarity score to sentiment label"""
        if polarity >= 0.5:
            return SentimentLabel.VERY_POSITIVE
        elif polarity >= 0.1:
            return SentimentLabel.POSITIVE
        elif polarity <= -0.5:
            return SentimentLabel.VERY_NEGATIVE
        elif polarity <= -0.1:
            return SentimentLabel.NEGATIVE
        else:
            return SentimentLabel.NEUTRAL
    
    def analyze_multiple(self, texts: List[str]) -> List[SentimentScore]:
        """Analyze multiple texts"""
        return [self.analyze(text) for text in texts]
    
    def get_average_sentiment(self, texts: List[str]) -> SentimentScore:
        """Get average sentiment across multiple texts"""
        scores = self.analyze_multiple(texts)
        
        avg_polarity = sum(s.polarity for s in scores) / len(scores)
        avg_subjectivity = sum(s.subjectivity for s in scores) / len(scores)
        avg_confidence = sum(s.confidence for s in scores) / len(scores)
        
        return SentimentScore(
            polarity=avg_polarity,
            subjectivity=avg_subjectivity,
            confidence=avg_confidence,
            label=self._get_label(avg_polarity)
        )


class FinancialSentimentAnalyzer:
    """
    Financial-specific sentiment analyzer using VADER with financial keywords
    """
    
    # Financial keywords and their sentiment weights
    BULLISH_KEYWORDS = {
        'surge', 'soar', 'rally', 'gain', 'profit', 'growth', 'bullish',
        'upgrade', 'breakthrough', 'record', 'outperform', 'beat',
        'strong', 'robust', 'solid', 'positive', 'optimistic'
    }
    
    BEARISH_KEYWORDS = {
        'plunge', 'crash', 'fall', 'loss', 'decline', 'bearish',
        'downgrade', 'miss', 'underperform', 'weak', 'disappointing',
        'negative', 'pessimistic', 'concern', 'risk', 'warning'
    }
    
    def __init__(self, use_vader: bool = True):
        self.use_vader = use_vader and VADER_AVAILABLE
        
        if self.use_vader:
            self.vader = SentimentIntensityAnalyzer()
        else:
            self.vader = None
            if use_vader:
                logger.warning("VADER requested but not available")
        
        self.logger = logging.getLogger(self.__class__.__name__)
    
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
            
            # Get VADER sentiment if available
            if self.vader:
                scores = self.vader.polarity_scores(combined_text)
                polarity = scores['compound']  # -1 to 1
                
                # Calculate confidence from positive, negative, neutral scores
                confidence = max(scores['pos'], scores['neg'], scores['neu'])
                
                # Subjectivity estimation (higher when strong pos/neg)
                subjectivity = 1 - scores['neu']
                
                return SentimentScore(
                    polarity=polarity,
                    subjectivity=subjectivity,
                    confidence=confidence,
                    label=self._get_label(polarity),
                    compound_score=polarity
                )
            else:
                # Fallback to keyword-based analysis
                return self._keyword_analysis(combined_text)
                
        except Exception as e:
            self.logger.error(f"Error in financial sentiment analysis: {e}")
            return SentimentScore(
                polarity=0.0,
                subjectivity=0.5,
                confidence=0.0,
                label=SentimentLabel.NEUTRAL
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
            label=self._get_label(polarity)
        )
    
    def _get_label(self, polarity: float) -> SentimentLabel:
        """Convert polarity score to sentiment label"""
        if polarity >= 0.5:
            return SentimentLabel.VERY_POSITIVE
        elif polarity >= 0.05:
            return SentimentLabel.POSITIVE
        elif polarity <= -0.5:
            return SentimentLabel.VERY_NEGATIVE
        elif polarity <= -0.05:
            return SentimentLabel.NEGATIVE
        else:
            return SentimentLabel.NEUTRAL
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract financial entities from text
        
        Returns:
            Dictionary with 'companies', 'currencies', 'instruments'
        """
        # Simple regex-based entity extraction
        # In production, use spaCy or similar NLP library
        
        entities = {
            'companies': [],
            'currencies': [],
            'instruments': []
        }
        
        # Common currency pairs
        currency_pattern = r'\b([A-Z]{3}/[A-Z]{3}|[A-Z]{6})\b'
        currencies = re.findall(currency_pattern, text)
        entities['currencies'] = list(set(currencies))
        
        # Stock symbols (simplified)
        symbol_pattern = r'\b[A-Z]{1,5}\b(?=\s+(?:stock|shares|equity))'
        symbols = re.findall(symbol_pattern, text)
        entities['instruments'] = list(set(symbols))
        
        return entities
    
    def analyze_with_entities(self, text: str, title: str = "") -> Tuple[SentimentScore, Dict]:
        """Analyze sentiment and extract entities"""
        sentiment = self.analyze(text, title)
        entities = self.extract_entities(f"{title} {text}")
        return sentiment, entities


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
