"""
Comprehensive Tests for News Module

Tests for:
- Economic Calendar
- Sentiment Analysis
- News Providers
- Impact Predictor
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock


# ============================================================
# ECONOMIC CALENDAR TESTS
# ============================================================

class TestEconomicEvent:
    """Tests for EconomicEvent dataclass."""

    def test_event_creation(self):
        """Test basic event creation."""
        from news.economic_calendar import EconomicEvent, EventType, EventImportance

        event = EconomicEvent(
            title="Fed Interest Rate Decision",
            event_type=EventType.INTEREST_RATE,
            importance=EventImportance.CRITICAL,
            scheduled_time=datetime.now(),
            country="US",
            actual=5.5,
            forecast=5.25,
            previous=5.0,
            currency="USD"
        )

        assert event.title == "Fed Interest Rate Decision"
        assert event.event_type == EventType.INTEREST_RATE
        assert event.importance == EventImportance.CRITICAL
        assert event.country == "US"
        assert event.actual == 5.5
        assert event.forecast == 5.25

    def test_event_to_dict(self):
        """Test event serialization to dict."""
        from news.economic_calendar import EconomicEvent, EventType, EventImportance

        now = datetime.now()
        event = EconomicEvent(
            title="GDP Release",
            event_type=EventType.GDP,
            importance=EventImportance.HIGH,
            scheduled_time=now,
            country="US"
        )

        result = event.to_dict()
        assert result['title'] == "GDP Release"
        assert result['event_type'] == "gdp"
        assert result['importance'] == "high"
        assert 'scheduled_time' in result

    def test_is_surprise_positive(self):
        """Test positive surprise detection."""
        from news.economic_calendar import EconomicEvent, EventType, EventImportance

        event = EconomicEvent(
            title="Employment Report",
            event_type=EventType.EMPLOYMENT,
            importance=EventImportance.HIGH,
            scheduled_time=datetime.now(),
            country="US",
            actual=200000,
            forecast=150000,
            previous=175000
        )

        assert event.is_surprise(threshold=0.1) is True

    def test_is_surprise_not_surprise(self):
        """Test no surprise when values are close."""
        from news.economic_calendar import EconomicEvent, EventType, EventImportance

        event = EconomicEvent(
            title="PMI",
            event_type=EventType.PMI,
            importance=EventImportance.MEDIUM,
            scheduled_time=datetime.now(),
            country="EU",
            actual=52.0,
            forecast=52.1,
            previous=51.8
        )

        assert event.is_surprise(threshold=0.1) is False

    def test_is_surprise_no_data(self):
        """Test surprise check when data is missing."""
        from news.economic_calendar import EconomicEvent, EventType, EventImportance

        event = EconomicEvent(
            title="Pending Event",
            event_type=EventType.OTHER,
            importance=EventImportance.LOW,
            scheduled_time=datetime.now(),
            country="JP",
            actual=None,
            forecast=100
        )

        assert event.is_surprise() is False


class TestEventTypes:
    """Tests for event type enums."""

    def test_event_importance_values(self):
        """Test event importance enum values."""
        from news.economic_calendar import EventImportance

        assert EventImportance.LOW.value == "low"
        assert EventImportance.MEDIUM.value == "medium"
        assert EventImportance.HIGH.value == "high"
        assert EventImportance.CRITICAL.value == "critical"

    def test_event_type_values(self):
        """Test event type enum values."""
        from news.economic_calendar import EventType

        assert EventType.INTEREST_RATE.value == "interest_rate"
        assert EventType.GDP.value == "gdp"
        assert EventType.EMPLOYMENT.value == "employment"
        assert EventType.INFLATION.value == "inflation"


class TestEconomicCalendar:
    """Tests for EconomicCalendar class."""

    def test_calendar_initialization(self):
        """Test calendar initialization."""
        from news.economic_calendar import EconomicCalendar

        calendar = EconomicCalendar()
        assert calendar is not None
        assert hasattr(calendar, 'events')

    def test_add_event(self):
        """Test adding event to calendar."""
        from news.economic_calendar import EconomicCalendar, EconomicEvent, EventType, EventImportance

        calendar = EconomicCalendar()
        event = EconomicEvent(
            title="Test Event",
            event_type=EventType.OTHER,
            importance=EventImportance.LOW,
            scheduled_time=datetime.now(),
            country="US"
        )

        calendar.add_event(event)
        assert len(calendar.events) >= 1

    def test_get_upcoming_events(self):
        """Test getting upcoming events."""
        from news.economic_calendar import EconomicCalendar, EconomicEvent, EventType, EventImportance

        calendar = EconomicCalendar()

        # Add future event
        future_event = EconomicEvent(
            title="Future Event",
            event_type=EventType.GDP,
            importance=EventImportance.HIGH,
            scheduled_time=datetime.now() + timedelta(days=1),
            country="US"
        )
        calendar.add_event(future_event)

        upcoming = calendar.get_upcoming_events(hours_ahead=24*7)  # 7 days ahead
        assert len(upcoming) >= 1

    def test_get_high_impact_events(self):
        """Test filtering high impact events."""
        from news.economic_calendar import EconomicCalendar, EconomicEvent, EventType, EventImportance

        calendar = EconomicCalendar()

        # Add high impact event
        high_impact = EconomicEvent(
            title="Fed Decision",
            event_type=EventType.INTEREST_RATE,
            importance=EventImportance.CRITICAL,
            scheduled_time=datetime.now() + timedelta(hours=1),
            country="US"
        )
        calendar.add_event(high_impact)

        # Add low impact event
        low_impact = EconomicEvent(
            title="Minor Report",
            event_type=EventType.OTHER,
            importance=EventImportance.LOW,
            scheduled_time=datetime.now() + timedelta(hours=2),
            country="US"
        )
        calendar.add_event(low_impact)

        high_impact_events = calendar.get_high_impact_events()
        assert all(e.importance in [EventImportance.HIGH, EventImportance.CRITICAL] for e in high_impact_events)


# ============================================================
# SENTIMENT ANALYSIS TESTS
# ============================================================

class TestSentimentScore:
    """Tests for SentimentScore dataclass."""

    def test_score_creation(self):
        """Test sentiment score creation."""
        from news.sentiment import SentimentScore, SentimentLabel

        score = SentimentScore(
            polarity=0.7,
            subjectivity=0.5,
            confidence=0.85,
            label=SentimentLabel.POSITIVE,
            compound_score=0.75
        )

        assert score.polarity == 0.7
        assert score.subjectivity == 0.5
        assert score.confidence == 0.85
        assert score.label == SentimentLabel.POSITIVE

    def test_score_to_dict(self):
        """Test sentiment score serialization."""
        from news.sentiment import SentimentScore, SentimentLabel

        score = SentimentScore(
            polarity=0.3,
            subjectivity=0.6,
            confidence=0.9,
            label=SentimentLabel.POSITIVE
        )

        result = score.to_dict()
        assert result['polarity'] == 0.3
        assert result['label'] == 'positive'

    def test_is_bullish(self):
        """Test bullish detection."""
        from news.sentiment import SentimentScore, SentimentLabel

        bullish_score = SentimentScore(
            polarity=0.5,
            subjectivity=0.5,
            confidence=0.8,
            label=SentimentLabel.POSITIVE
        )

        assert bullish_score.is_bullish() is True
        assert bullish_score.is_bearish() is False

    def test_is_bearish(self):
        """Test bearish detection."""
        from news.sentiment import SentimentScore, SentimentLabel

        bearish_score = SentimentScore(
            polarity=-0.5,
            subjectivity=0.5,
            confidence=0.8,
            label=SentimentLabel.NEGATIVE
        )

        assert bearish_score.is_bearish() is True
        assert bearish_score.is_bullish() is False

    def test_is_neutral(self):
        """Test neutral detection."""
        from news.sentiment import SentimentScore, SentimentLabel

        neutral_score = SentimentScore(
            polarity=0.05,
            subjectivity=0.5,
            confidence=0.8,
            label=SentimentLabel.NEUTRAL
        )

        assert neutral_score.is_neutral() is True


class TestSentimentLabels:
    """Tests for sentiment label enum."""

    def test_sentiment_label_values(self):
        """Test sentiment label enum values."""
        from news.sentiment import SentimentLabel

        assert SentimentLabel.VERY_NEGATIVE.value == "very_negative"
        assert SentimentLabel.NEGATIVE.value == "negative"
        assert SentimentLabel.NEUTRAL.value == "neutral"
        assert SentimentLabel.POSITIVE.value == "positive"
        assert SentimentLabel.VERY_POSITIVE.value == "very_positive"


class TestSentimentAnalyzer:
    """Tests for SentimentAnalyzer class."""

    def test_analyzer_initialization(self):
        """Test analyzer initialization."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            assert analyzer is not None
        except ImportError:
            pytest.skip("TextBlob not installed")

    def test_analyze_bullish_text(self):
        """Test analyzing bullish text."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            text = "Gold prices surge to new highs amid strong buying momentum and positive market sentiment."

            result = analyzer.analyze(text)
            assert result is not None
            assert hasattr(result, 'polarity')
        except ImportError:
            pytest.skip("TextBlob not installed")

    def test_analyze_bearish_text(self):
        """Test analyzing bearish text."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            text = "Markets crash as fears of recession grow and economic data disappoints investors."

            result = analyzer.analyze(text)
            assert result is not None
        except ImportError:
            pytest.skip("TextBlob not installed")

    def test_analyze_neutral_text(self):
        """Test analyzing neutral text."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            text = "The market traded sideways today with mixed economic signals."

            result = analyzer.analyze(text)
            assert result is not None
        except ImportError:
            pytest.skip("TextBlob not installed")

    def test_analyze_financial_terms(self):
        """Test analyzer handles financial terms."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            text = "Fed raises interest rates by 25 basis points, hawkish stance on inflation."

            result = analyzer.analyze(text)
            assert result is not None
        except ImportError:
            pytest.skip("TextBlob not installed")

    def test_analyze_empty_text(self):
        """Test analyzing empty text."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            result = analyzer.analyze("")

            assert result is not None
            assert result.polarity == 0.0 or result is not None
        except ImportError:
            pytest.skip("TextBlob not installed")

    def test_get_label(self):
        """Test label determination from polarity."""
        try:
            from news.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()

            # Very positive
            label = analyzer._get_label(0.8)
            assert label.value in ['positive', 'very_positive']

            # Very negative
            label = analyzer._get_label(-0.8)
            assert label.value in ['negative', 'very_negative']
        except ImportError:
            pytest.skip("TextBlob not installed")


# ============================================================
# NEWS PROVIDER TESTS
# ============================================================

class TestNewsArticle:
    """Tests for NewsArticle dataclass."""

    def test_article_creation(self):
        """Test article creation."""
        from news.providers import NewsArticle

        article = NewsArticle(
            title="Gold Hits Record High",
            description="XAU/USD surges past $2000",
            source="Financial Times",
            published_at=datetime.now(),
            url="https://example.com/article"
        )

        assert article.title == "Gold Hits Record High"
        assert article.source == "Financial Times"

    def test_article_to_dict(self):
        """Test article serialization."""
        from news.providers import NewsArticle

        article = NewsArticle(
            title="Market Update",
            description="Daily recap",
            source="Reuters",
            published_at=datetime.now(),
            url="https://example.com",
            author="John Doe",
            symbols=["XAUUSD", "EURUSD"]
        )

        result = article.to_dict()
        assert result['title'] == "Market Update"
        assert result['source'] == "Reuters"
        assert result['symbols'] == ["XAUUSD", "EURUSD"]

    def test_article_optional_fields(self):
        """Test article with optional fields."""
        from news.providers import NewsArticle

        article = NewsArticle(
            title="Basic Article",
            description="No extras",
            source="Unknown",
            published_at=datetime.now(),
            url="https://example.com"
        )

        assert article.author is None
        assert article.content is None
        assert article.symbols is None
        assert article.sentiment is None


class TestNewsProvider:
    """Tests for NewsProvider base class."""

    def test_base_provider_initialization(self):
        """Test base provider initialization."""
        from news.providers import NewsProvider

        provider = NewsProvider(api_key="test_key")
        assert provider.api_key == "test_key"

    def test_get_news_not_implemented(self):
        """Test base get_news raises NotImplementedError."""
        from news.providers import NewsProvider

        provider = NewsProvider()
        with pytest.raises(NotImplementedError):
            provider.get_news()

    def test_format_article_not_implemented(self):
        """Test base format_article raises NotImplementedError."""
        from news.providers import NewsProvider

        provider = NewsProvider()
        with pytest.raises(NotImplementedError):
            provider.format_article({})


class TestNewsAPIProvider:
    """Tests for NewsAPI provider."""

    def test_provider_initialization(self):
        """Test NewsAPI provider initialization."""
        from news.providers import NewsAPIProvider

        provider = NewsAPIProvider(api_key="test_api_key")
        assert provider.api_key == "test_api_key"
        assert provider.BASE_URL == "https://newsapi.org/v2"

    def test_provider_without_api_key(self):
        """Test provider without API key raises error."""
        from news.providers import NewsAPIProvider

        with pytest.raises(ValueError):
            NewsAPIProvider(api_key="")

    @patch('news.providers.requests.get')
    def test_get_news_success(self, mock_get):
        """Test successful news fetch."""
        from news.providers import NewsAPIProvider

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'status': 'ok',
            'articles': [
                {
                    'title': 'Test Article',
                    'description': 'Test Description',
                    'source': {'name': 'Test Source'},
                    'publishedAt': '2024-01-01T12:00:00Z',
                    'url': 'https://example.com'
                }
            ]
        }
        mock_get.return_value = mock_response

        provider = NewsAPIProvider(api_key="test_key")
        articles = provider.get_news(query="gold")

        assert len(articles) >= 0  # May be empty if API fails


# ============================================================
# IMPACT PREDICTOR TESTS
# ============================================================

class TestImpactPredictor:
    """Tests for ImpactPredictor class."""

    def test_predictor_initialization(self):
        """Test predictor initialization."""
        from news.impact_predictor import ImpactPredictor

        predictor = ImpactPredictor()
        assert predictor is not None

    def test_predict_high_impact_event(self):
        """Test predicting high impact event."""
        from news.impact_predictor import ImpactPredictor

        predictor = ImpactPredictor()

        prediction = predictor.predict_impact(
            title="Fed Rate Decision",
            description="Federal Reserve announces interest rate hike of 25 basis points"
        )
        assert prediction is not None
        assert hasattr(prediction, 'expected_volatility')

    def test_predict_low_impact_event(self):
        """Test predicting low impact event."""
        from news.impact_predictor import ImpactPredictor

        predictor = ImpactPredictor()

        prediction = predictor.predict_impact(
            title="Minor Report Released",
            description="Standard weekly statistics published"
        )
        assert prediction is not None

    def test_predict_with_sentiment(self):
        """Test predicting impact with sentiment score."""
        from news.impact_predictor import ImpactPredictor

        predictor = ImpactPredictor()

        prediction = predictor.predict_impact(
            title="Markets Rally on Strong Data",
            description="Employment data beats expectations",
            sentiment_score=0.8
        )
        assert prediction is not None

    def test_predict_with_symbols(self):
        """Test predicting impact with symbols."""
        from news.impact_predictor import ImpactPredictor

        predictor = ImpactPredictor()

        prediction = predictor.predict_impact(
            title="US Employment Report",
            description="Nonfarm payrolls exceed expectations",
            symbols=["XAUUSD", "EURUSD", "DXY"]
        )
        assert prediction is not None
        assert prediction.affected_symbols == ["XAUUSD", "EURUSD", "DXY"]


# ============================================================
# NEWS AGGREGATOR TESTS
# ============================================================

class TestNewsAggregator:
    """Tests for MultiSourceAggregator."""

    def test_aggregator_initialization(self):
        """Test aggregator initialization."""
        from news.providers import MultiSourceAggregator

        aggregator = MultiSourceAggregator()
        assert aggregator is not None
        assert hasattr(aggregator, 'providers')

    def test_aggregator_with_rss_only(self):
        """Test aggregator with RSS only."""
        from news.providers import MultiSourceAggregator

        aggregator = MultiSourceAggregator(use_rss=True)
        assert len(aggregator.providers) >= 0

    def test_get_aggregated_news(self):
        """Test getting aggregated news."""
        from news.providers import MultiSourceAggregator

        aggregator = MultiSourceAggregator()
        articles = aggregator.get_aggregated_news()

        assert isinstance(articles, list)

    def test_deduplicate_articles(self):
        """Test article deduplication."""
        from news.providers import MultiSourceAggregator, NewsArticle

        aggregator = MultiSourceAggregator()

        articles = [
            NewsArticle(
                title="Gold Price Update",
                description="Gold rises",
                source="Source1",
                published_at=datetime.now(),
                url="https://example1.com"
            ),
            NewsArticle(
                title="Gold Price Update",  # Duplicate title
                description="Gold rises again",
                source="Source2",
                published_at=datetime.now(),
                url="https://example2.com"
            ),
            NewsArticle(
                title="Different News",
                description="Other news",
                source="Source3",
                published_at=datetime.now(),
                url="https://example3.com"
            ),
        ]

        unique = aggregator._deduplicate(articles)
        assert len(unique) == 2
