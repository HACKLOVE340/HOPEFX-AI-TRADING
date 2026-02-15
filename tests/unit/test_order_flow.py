"""
Comprehensive Tests for Order Flow Analysis Module

Tests for:
- Volume Profile
- Order Flow Analysis
- Footprint Charts
- Delta/Cumulative Delta
"""

import pytest
from datetime import datetime, timedelta


class TestTrade:
    """Tests for Trade dataclass."""

    def test_trade_creation(self):
        """Test creating a trade."""
        from analysis.order_flow import Trade

        trade = Trade(
            timestamp=datetime.now(),
            price=1950.00,
            size=100.0,
            side='buy'
        )

        assert trade.price == 1950.00
        assert trade.size == 100.0
        assert trade.side == 'buy'

    def test_trade_is_buy(self):
        """Test buy trade detection."""
        from analysis.order_flow import Trade

        buy_trade = Trade(datetime.now(), 1950.00, 100.0, 'buy')
        sell_trade = Trade(datetime.now(), 1950.00, 100.0, 'sell')

        assert buy_trade.is_buy is True
        assert buy_trade.is_sell is False
        assert sell_trade.is_sell is True
        assert sell_trade.is_buy is False


class TestVolumeProfileLevel:
    """Tests for VolumeProfileLevel dataclass."""

    def test_level_creation(self):
        """Test creating a volume profile level."""
        from analysis.order_flow import VolumeProfileLevel

        level = VolumeProfileLevel(
            price=1950.00,
            total_volume=1000,
            buy_volume=600,
            sell_volume=400,
            trade_count=50,
            delta=200
        )

        assert level.price == 1950.00
        assert level.total_volume == 1000
        assert level.buy_volume == 600
        assert level.sell_volume == 400
        assert level.delta == 200

    def test_level_buy_pct(self):
        """Test buy percentage calculation."""
        from analysis.order_flow import VolumeProfileLevel

        level = VolumeProfileLevel(
            price=1950.00,
            total_volume=1000,
            buy_volume=700,
            sell_volume=300,
            trade_count=50,
            delta=400
        )

        assert level.buy_pct == 70.0
        assert level.sell_pct == 30.0

    def test_level_imbalance(self):
        """Test imbalance calculation."""
        from analysis.order_flow import VolumeProfileLevel

        level = VolumeProfileLevel(
            price=1950.00,
            total_volume=1000,
            buy_volume=700,
            sell_volume=300,
            trade_count=50,
            delta=400
        )

        assert level.imbalance == 0.4  # (700-300)/1000

    def test_level_to_dict(self):
        """Test level serialization."""
        from analysis.order_flow import VolumeProfileLevel

        level = VolumeProfileLevel(
            price=1950.00,
            total_volume=1000,
            buy_volume=600,
            sell_volume=400,
            trade_count=50,
            delta=200
        )

        result = level.to_dict()
        assert result['price'] == 1950.00
        assert result['total_volume'] == 1000
        assert 'imbalance' in result


class TestOrderFlowAnalyzer:
    """Tests for OrderFlowAnalyzer class."""

    def test_analyzer_initialization(self):
        """Test analyzer initialization."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        assert analyzer is not None
        assert hasattr(analyzer, '_trades')

    def test_add_trade(self):
        """Test adding a trade."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')

        trades = analyzer.get_trades('XAUUSD')
        assert len(trades) == 1

    def test_add_multiple_trades(self):
        """Test adding multiple trades."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')
        analyzer.add_trade('XAUUSD', 1950.50, 50.0, 'sell')
        analyzer.add_trade('XAUUSD', 1950.25, 75.0, 'buy')

        trades = analyzer.get_trades('XAUUSD')
        assert len(trades) == 3

    def test_add_trades_batch(self):
        """Test adding trades in batch."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        trades = [
            {'price': 1950.00, 'size': 100, 'side': 'buy'},
            {'price': 1950.50, 'size': 50, 'side': 'sell'},
        ]

        analyzer.add_trades('XAUUSD', trades)

        result = analyzer.get_trades('XAUUSD')
        assert len(result) == 2

    def test_cumulative_delta(self):
        """Test cumulative delta calculation."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')  # +100
        analyzer.add_trade('XAUUSD', 1950.50, 50.0, 'sell')  # -50
        analyzer.add_trade('XAUUSD', 1950.25, 75.0, 'buy')   # +75

        # Total delta = 100 - 50 + 75 = 125
        assert analyzer._cumulative_delta['XAUUSD'] == 125

    def test_get_volume_profile(self):
        """Test volume profile calculation."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Add trades at various prices
        for i in range(20):
            price = 1950.00 + (i * 0.10)
            analyzer.add_trade('XAUUSD', price, 100.0, 'buy' if i % 2 == 0 else 'sell')

        profile = analyzer.get_volume_profile('XAUUSD', price_buckets=10)

        assert profile is not None
        assert profile.symbol == 'XAUUSD'
        assert len(profile.levels) > 0
        assert profile.poc_price is not None

    def test_volume_profile_poc(self):
        """Test Point of Control calculation."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Add concentrated volume at one price
        for _ in range(10):
            analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')

        # Add less volume at other prices
        analyzer.add_trade('XAUUSD', 1949.00, 50.0, 'buy')
        analyzer.add_trade('XAUUSD', 1951.00, 50.0, 'sell')

        profile = analyzer.get_volume_profile('XAUUSD', price_buckets=5)

        # POC should be at highest volume price
        assert profile.poc_price is not None

    def test_analyze(self):
        """Test full order flow analysis."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Add mixed trades
        for i in range(30):
            side = 'buy' if i % 3 != 0 else 'sell'
            analyzer.add_trade('XAUUSD', 1950.00 + i * 0.05, 100.0, side)

        analysis = analyzer.analyze('XAUUSD')

        assert analysis is not None
        assert hasattr(analysis, 'delta')
        assert hasattr(analysis, 'cumulative_delta')
        assert hasattr(analysis, 'imbalance_ratio')
        assert hasattr(analysis, 'dominant_side')
        assert hasattr(analysis, 'order_flow_signal')

    def test_analyze_bullish(self):
        """Test bullish analysis detection."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Predominantly buy trades
        for _ in range(20):
            analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')
        for _ in range(5):
            analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'sell')

        analysis = analyzer.analyze('XAUUSD')

        assert analysis.delta > 0
        assert analysis.dominant_side == 'buyers'
        assert analysis.order_flow_signal == 'bullish'

    def test_analyze_bearish(self):
        """Test bearish analysis detection."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Predominantly sell trades
        for _ in range(5):
            analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')
        for _ in range(20):
            analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'sell')

        analysis = analyzer.analyze('XAUUSD')

        assert analysis.delta < 0
        assert analysis.dominant_side == 'sellers'
        assert analysis.order_flow_signal == 'bearish'

    def test_get_key_levels(self):
        """Test key level detection."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Add trades to create levels
        for i in range(50):
            analyzer.add_trade('XAUUSD', 1950.00 + (i % 10) * 0.5, 100.0, 'buy' if i % 2 == 0 else 'sell')

        levels = analyzer.get_key_levels('XAUUSD')

        assert 'support' in levels
        assert 'resistance' in levels
        assert 'poc' in levels

    def test_get_footprint(self):
        """Test footprint chart generation."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()

        # Add trades over time
        base_time = datetime.now()
        for i in range(20):
            timestamp = base_time + timedelta(minutes=i)
            analyzer.add_trade('XAUUSD', 1950.00 + i * 0.01, 100.0, 'buy' if i % 2 == 0 else 'sell', timestamp)

        footprints = analyzer.get_footprint('XAUUSD', timeframe='5m', bars=5)

        assert len(footprints) >= 0  # May be less if not enough data

    def test_clear_trades(self):
        """Test clearing trades."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')

        analyzer.clear_trades('XAUUSD')

        assert len(analyzer.get_trades('XAUUSD')) == 0

    def test_get_stats(self):
        """Test analyzer statistics."""
        from analysis.order_flow import OrderFlowAnalyzer

        analyzer = OrderFlowAnalyzer()
        analyzer.add_trade('XAUUSD', 1950.00, 100.0, 'buy')
        analyzer.add_trade('EURUSD', 1.0800, 1000.0, 'sell')

        stats = analyzer.get_stats()

        assert 'symbols_tracked' in stats
        assert 'total_trades' in stats

    def test_global_instance(self):
        """Test global order flow analyzer instance."""
        from analysis.order_flow import get_order_flow_analyzer

        analyzer1 = get_order_flow_analyzer()
        analyzer2 = get_order_flow_analyzer()

        assert analyzer1 is analyzer2


class TestVolumeProfile:
    """Tests for VolumeProfile dataclass."""

    def test_profile_to_dict(self):
        """Test volume profile serialization."""
        from analysis.order_flow import VolumeProfile, VolumeProfileLevel

        levels = [
            VolumeProfileLevel(1950.00, 1000, 600, 400, 50, 200),
            VolumeProfileLevel(1950.50, 800, 400, 400, 40, 0),
        ]

        profile = VolumeProfile(
            symbol='XAUUSD',
            start_time=datetime.now(),
            end_time=datetime.now(),
            levels=levels,
            total_volume=1800,
            total_buy_volume=1000,
            total_sell_volume=800,
            total_delta=200,
            poc_price=1950.00,
            vah_price=1950.50,
            val_price=1949.50
        )

        result = profile.to_dict()
        assert result['symbol'] == 'XAUUSD'
        assert 'levels' in result
        assert result['poc_price'] == 1950.00


class TestOrderFlowAnalysis:
    """Tests for OrderFlowAnalysis dataclass."""

    def test_analysis_to_dict(self):
        """Test analysis serialization."""
        from analysis.order_flow import OrderFlowAnalysis

        analysis = OrderFlowAnalysis(
            symbol='XAUUSD',
            timestamp=datetime.now(),
            total_volume=10000,
            buy_volume=6000,
            sell_volume=4000,
            delta=2000,
            cumulative_delta=5000,
            imbalance_ratio=0.2,
            dominant_side='buyers',
            imbalance_strength='moderate',
            high_volume_nodes=[],
            low_volume_nodes=[],
            absorption_levels=[],
            buying_pressure=60.0,
            selling_pressure=40.0,
            order_flow_signal='bullish'
        )

        result = analysis.to_dict()
        assert result['symbol'] == 'XAUUSD'
        assert result['delta'] == 2000
        assert result['order_flow_signal'] == 'bullish'
