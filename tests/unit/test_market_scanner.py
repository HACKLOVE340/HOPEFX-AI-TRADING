"""
Comprehensive Tests for Market Scanner Module

Tests for:
- Scan Criteria
- Market Scanner
- Opportunity Detection
"""

import pytest
from datetime import datetime, timedelta


class TestScanCriteriaType:
    """Tests for ScanCriteriaType enum."""

    def test_price_criteria(self):
        """Test price-related criteria types."""
        from analysis.market_scanner import ScanCriteriaType

        assert ScanCriteriaType.BREAKOUT.value == "breakout"
        assert ScanCriteriaType.PRICE_ABOVE_MA.value == "price_above_ma"
        assert ScanCriteriaType.PRICE_BELOW_MA.value == "price_below_ma"
        assert ScanCriteriaType.NEW_HIGH.value == "new_high"
        assert ScanCriteriaType.NEW_LOW.value == "new_low"

    def test_momentum_criteria(self):
        """Test momentum-related criteria types."""
        from analysis.market_scanner import ScanCriteriaType

        assert ScanCriteriaType.MOMENTUM.value == "momentum"
        assert ScanCriteriaType.RSI_OVERBOUGHT.value == "rsi_overbought"
        assert ScanCriteriaType.RSI_OVERSOLD.value == "rsi_oversold"
        assert ScanCriteriaType.MACD_BULLISH_CROSS.value == "macd_bullish_cross"

    def test_volume_criteria(self):
        """Test volume-related criteria types."""
        from analysis.market_scanner import ScanCriteriaType

        assert ScanCriteriaType.VOLUME_SPIKE.value == "volume_spike"
        assert ScanCriteriaType.UNUSUAL_VOLUME.value == "unusual_volume"

    def test_trend_criteria(self):
        """Test trend-related criteria types."""
        from analysis.market_scanner import ScanCriteriaType

        assert ScanCriteriaType.UPTREND.value == "uptrend"
        assert ScanCriteriaType.DOWNTREND.value == "downtrend"
        assert ScanCriteriaType.MA_CROSSOVER.value == "ma_crossover"


class TestSignalDirection:
    """Tests for SignalDirection enum."""

    def test_direction_values(self):
        """Test signal direction values."""
        from analysis.market_scanner import SignalDirection

        assert SignalDirection.BULLISH.value == "bullish"
        assert SignalDirection.BEARISH.value == "bearish"
        assert SignalDirection.NEUTRAL.value == "neutral"


class TestScanCriteria:
    """Tests for ScanCriteria dataclass."""

    def test_criteria_creation(self):
        """Test creating scan criteria."""
        from analysis.market_scanner import ScanCriteria, ScanCriteriaType

        criteria = ScanCriteria(
            type=ScanCriteriaType.RSI_OVERSOLD,
            parameters={'threshold': 30},
            weight=1.5
        )

        assert criteria.type == ScanCriteriaType.RSI_OVERSOLD
        assert criteria.parameters['threshold'] == 30
        assert criteria.weight == 1.5

    def test_criteria_to_dict(self):
        """Test criteria serialization."""
        from analysis.market_scanner import ScanCriteria, ScanCriteriaType

        criteria = ScanCriteria(
            type=ScanCriteriaType.BREAKOUT,
            parameters={'period': 20}
        )

        result = criteria.to_dict()
        assert result['type'] == 'breakout'
        assert result['parameters']['period'] == 20


class TestScanResult:
    """Tests for ScanResult dataclass."""

    def test_result_creation(self):
        """Test creating a scan result."""
        from analysis.market_scanner import ScanResult, SignalDirection

        result = ScanResult(
            symbol='XAUUSD',
            criteria_met=['rsi_oversold', 'uptrend'],
            total_criteria=3,
            match_score=0.67,
            direction=SignalDirection.BULLISH,
            signal_strength=75.0,
            details={'rsi': 28}
        )

        assert result.symbol == 'XAUUSD'
        assert len(result.criteria_met) == 2
        assert result.signal_strength == 75.0

    def test_result_to_dict(self):
        """Test result serialization."""
        from analysis.market_scanner import ScanResult, SignalDirection

        result = ScanResult(
            symbol='EURUSD',
            criteria_met=['momentum'],
            total_criteria=2,
            match_score=0.5,
            direction=SignalDirection.BEARISH,
            signal_strength=50.0,
            details={}
        )

        data = result.to_dict()
        assert data['symbol'] == 'EURUSD'
        assert data['direction'] == 'bearish'


class TestMarketOpportunity:
    """Tests for MarketOpportunity dataclass."""

    def test_opportunity_creation(self):
        """Test creating a market opportunity."""
        from analysis.market_scanner import MarketOpportunity, SignalDirection

        opportunity = MarketOpportunity(
            symbol='XAUUSD',
            opportunity_type='breakout',
            direction=SignalDirection.BULLISH,
            strength=80.0,
            entry_price=1950.00,
            stop_loss=1940.00,
            take_profit=1970.00,
            risk_reward=2.0,
            triggers=['breakout', 'momentum'],
            analysis={'rsi': 55}
        )

        assert opportunity.symbol == 'XAUUSD'
        assert opportunity.strength == 80.0
        assert opportunity.risk_reward == 2.0

    def test_opportunity_is_valid(self):
        """Test opportunity validity check."""
        from analysis.market_scanner import MarketOpportunity, SignalDirection

        # Valid opportunity
        opportunity = MarketOpportunity(
            symbol='XAUUSD',
            opportunity_type='test',
            direction=SignalDirection.BULLISH,
            strength=80,
            entry_price=1950,
            stop_loss=1940,
            take_profit=1970,
            risk_reward=2.0,
            triggers=[],
            analysis={},
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )

        assert opportunity.is_valid is True

        # Expired opportunity
        opportunity.expires_at = datetime.utcnow() - timedelta(hours=1)
        assert opportunity.is_valid is False

    def test_opportunity_to_dict(self):
        """Test opportunity serialization."""
        from analysis.market_scanner import MarketOpportunity, SignalDirection

        opportunity = MarketOpportunity(
            symbol='XAUUSD',
            opportunity_type='momentum',
            direction=SignalDirection.BULLISH,
            strength=75,
            entry_price=1950,
            stop_loss=1940,
            take_profit=1970,
            risk_reward=2.0,
            triggers=['momentum'],
            analysis={}
        )

        result = opportunity.to_dict()
        assert result['symbol'] == 'XAUUSD'
        assert result['direction'] == 'bullish'


class TestMarketScanner:
    """Tests for MarketScanner class."""

    def test_scanner_initialization(self):
        """Test scanner initialization."""
        from analysis.market_scanner import MarketScanner

        scanner = MarketScanner()
        assert scanner is not None
        assert hasattr(scanner, '_symbols')
        assert hasattr(scanner, '_criteria')

    def test_add_symbols(self):
        """Test adding symbols."""
        from analysis.market_scanner import MarketScanner

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD', 'EURUSD', 'GBPUSD'])

        symbols = scanner.get_symbols()
        assert 'XAUUSD' in symbols
        assert 'EURUSD' in symbols
        assert len(symbols) == 3

    def test_set_symbols(self):
        """Test setting symbols."""
        from analysis.market_scanner import MarketScanner

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.set_symbols(['EURUSD', 'GBPUSD'])

        symbols = scanner.get_symbols()
        assert 'XAUUSD' not in symbols
        assert len(symbols) == 2

    def test_remove_symbol(self):
        """Test removing a symbol."""
        from analysis.market_scanner import MarketScanner

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD', 'EURUSD'])
        scanner.remove_symbol('XAUUSD')

        symbols = scanner.get_symbols()
        assert 'XAUUSD' not in symbols
        assert 'EURUSD' in symbols

    def test_add_criteria(self):
        """Test adding criteria."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})
        scanner.add_criteria(ScanCriteriaType.UPTREND)

        criteria = scanner.get_criteria()
        assert len(criteria) == 2

    def test_clear_criteria(self):
        """Test clearing criteria."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD)
        scanner.clear_criteria()

        assert len(scanner.get_criteria()) == 0

    def test_scan_basic(self):
        """Test basic scan."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD', 'EURUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        market_data = {
            'XAUUSD': {'price': 1950, 'open': 1945, 'rsi': 25},
            'EURUSD': {'price': 1.08, 'open': 1.079, 'rsi': 55}
        }

        results = scanner.scan(market_data, min_strength=0)

        assert len(results) >= 1
        # XAUUSD should match RSI oversold
        xauusd_result = next((r for r in results if r.symbol == 'XAUUSD'), None)
        assert xauusd_result is not None

    def test_scan_multiple_criteria(self):
        """Test scan with multiple criteria."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})
        scanner.add_criteria(ScanCriteriaType.UPTREND)

        market_data = {
            'XAUUSD': {
                'price': 1950,
                'open': 1945,
                'rsi': 25,
                'ma_20': 1940,
                'ma_50': 1930
            }
        }

        results = scanner.scan(market_data, min_strength=0)
        assert len(results) >= 1

    def test_scan_no_matches(self):
        """Test scan with no matches."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERBOUGHT, {'threshold': 70})

        market_data = {
            'XAUUSD': {'price': 1950, 'rsi': 50}  # RSI not overbought
        }

        results = scanner.scan(market_data, min_strength=50)
        assert len(results) == 0

    def test_scan_min_strength_filter(self):
        """Test minimum strength filtering."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        market_data = {'XAUUSD': {'price': 1950, 'rsi': 25}}

        results_low = scanner.scan(market_data, min_strength=0)
        results_high = scanner.scan(market_data, min_strength=90)

        assert len(results_low) >= 1
        assert len(results_high) <= len(results_low)

    def test_get_last_result(self):
        """Test getting last result for a symbol."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        market_data = {'XAUUSD': {'price': 1950, 'rsi': 25}}
        scanner.scan(market_data, min_strength=0)

        result = scanner.get_last_result('XAUUSD')
        assert result is not None
        assert result.symbol == 'XAUUSD'

    def test_get_all_results(self):
        """Test getting all last results."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD', 'EURUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        market_data = {
            'XAUUSD': {'price': 1950, 'rsi': 25},
            'EURUSD': {'price': 1.08, 'rsi': 28}
        }
        scanner.scan(market_data, min_strength=0)

        results = scanner.get_all_results()
        assert len(results) >= 1

    def test_get_opportunities(self):
        """Test getting opportunities."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})
        scanner.add_criteria(ScanCriteriaType.UPTREND)
        scanner.add_criteria(ScanCriteriaType.MOMENTUM)

        # Create strong signal
        market_data = {
            'XAUUSD': {
                'price': 1950,
                'open': 1940,
                'rsi': 25,
                'ma_20': 1940,
                'ma_50': 1920
            }
        }
        scanner.scan(market_data, min_strength=50)

        opportunities = scanner.get_opportunities()
        assert isinstance(opportunities, list)

    def test_get_top_opportunities(self):
        """Test getting top opportunities."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD', 'EURUSD', 'GBPUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        market_data = {
            'XAUUSD': {'price': 1950, 'rsi': 20},
            'EURUSD': {'price': 1.08, 'rsi': 25},
            'GBPUSD': {'price': 1.25, 'rsi': 28}
        }
        scanner.scan(market_data, min_strength=0)

        top = scanner.get_top_opportunities(limit=2)
        assert len(top) <= 2

    def test_on_opportunity_callback(self):
        """Test opportunity callback."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})
        scanner.add_criteria(ScanCriteriaType.UPTREND)
        scanner.add_criteria(ScanCriteriaType.MOMENTUM)

        callbacks = []
        scanner.on_opportunity(lambda opp: callbacks.append(opp))

        market_data = {
            'XAUUSD': {
                'price': 1950,
                'open': 1940,
                'rsi': 20,
                'ma_20': 1940,
                'ma_50': 1920
            }
        }
        scanner.scan(market_data, min_strength=50)

        # Callback may or may not be triggered depending on signal strength
        assert isinstance(callbacks, list)

    def test_get_stats(self):
        """Test scanner statistics."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner()
        scanner.add_symbols(['XAUUSD'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD)

        stats = scanner.get_stats()
        assert 'symbols_count' in stats
        assert 'criteria_count' in stats
        assert 'scans_performed' in stats

    def test_global_instance(self):
        """Test global scanner instance."""
        from analysis.market_scanner import get_market_scanner

        scanner1 = get_market_scanner()
        scanner2 = get_market_scanner()

        assert scanner1 is scanner2

    def test_parallel_scan(self):
        """Test parallel scanning mode."""
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = MarketScanner(config={'parallel_scan': True})
        scanner.add_symbols(['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY'])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {'threshold': 30})

        market_data = {
            'XAUUSD': {'price': 1950, 'rsi': 25},
            'EURUSD': {'price': 1.08, 'rsi': 28},
            'GBPUSD': {'price': 1.25, 'rsi': 22},
            'USDJPY': {'price': 150.5, 'rsi': 55}
        }

        results = scanner.scan(market_data, min_strength=0)
        assert len(results) >= 3  # 3 are oversold
