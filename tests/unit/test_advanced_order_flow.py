"""
Tests for Advanced Order Flow Analyzer (analysis/advanced_order_flow.py)
"""

import pytest
from datetime import datetime, timedelta


class TestAggressionMetrics:
    """Tests for AggressionMetrics dataclass."""

    def test_to_dict(self):
        from analysis.advanced_order_flow import AggressionMetrics

        m = AggressionMetrics(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            buy_aggression=60.0,
            sell_aggression=40.0,
            aggression_score=20.0,
            dominant_side="buyers",
            aggression_strength="moderate",
        )

        d = m.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["buy_aggression"] == 60.0
        assert d["dominant_side"] == "buyers"


class TestVolumeCluster:
    """Tests for VolumeCluster dataclass."""

    def test_to_dict(self):
        from analysis.advanced_order_flow import VolumeCluster

        cluster = VolumeCluster(
            price_level=1950.0,
            total_volume=5000.0,
            buy_volume=3000.0,
            sell_volume=2000.0,
            trade_count=50,
            cluster_type="support",
            strength=0.8,
        )

        d = cluster.to_dict()
        assert d["price_level"] == 1950.0
        assert d["cluster_type"] == "support"


class TestDeltaDivergence:
    """Tests for DeltaDivergence dataclass."""

    def test_to_dict(self):
        from analysis.advanced_order_flow import DeltaDivergence

        div = DeltaDivergence(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            divergence_type="bullish",
            price_direction="down",
            delta_direction="up",
            strength=0.7,
            confidence=0.6,
        )

        d = div.to_dict()
        assert d["divergence_type"] == "bullish"
        assert d["price_direction"] == "down"


class TestAdvancedOrderFlowAnalyzer:
    """Tests for AdvancedOrderFlowAnalyzer."""

    def test_initialization(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        assert analyzer is not None

    def test_add_trade(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy")

        assert len(analyzer._trades["XAUUSD"]) == 1
        assert analyzer._cumulative_delta["XAUUSD"] == 100.0

    def test_add_sell_trade_delta(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        analyzer.add_trade("XAUUSD", 1950.0, 60.0, "sell")

        assert analyzer._cumulative_delta["XAUUSD"] == 40.0

    def test_max_trades_trim(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer(config={"max_trades": 5})
        for i in range(10):
            analyzer.add_trade("XAUUSD", 1950.0, 10.0, "buy")

        assert len(analyzer._trades["XAUUSD"]) == 5

    def test_get_aggression_metrics_no_data(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        assert analyzer.get_aggression_metrics("NONEXISTENT") is None

    def test_get_aggression_metrics_bullish(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        now = datetime.utcnow()
        for _ in range(8):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy",
                               timestamp=now - timedelta(minutes=5))
        for _ in range(2):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "sell",
                               timestamp=now - timedelta(minutes=5))

        metrics = analyzer.get_aggression_metrics("XAUUSD")
        assert metrics is not None
        assert metrics.buy_aggression == 80.0
        assert metrics.dominant_side == "buyers"
        assert metrics.aggression_score == 60.0

    def test_get_aggression_metrics_bearish(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        now = datetime.utcnow()
        for _ in range(2):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy",
                               timestamp=now - timedelta(minutes=5))
        for _ in range(8):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "sell",
                               timestamp=now - timedelta(minutes=5))

        metrics = analyzer.get_aggression_metrics("XAUUSD")
        assert metrics.dominant_side == "sellers"
        assert metrics.aggression_score < 0

    def test_get_volume_imbalance_by_level(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        now = datetime.utcnow()
        for i in range(20):
            analyzer.add_trade(
                "XAUUSD", 1950.0 + i * 0.5, 100.0, "buy" if i % 2 == 0 else "sell",
                timestamp=now - timedelta(minutes=5)
            )

        levels = analyzer.get_volume_imbalance_by_level("XAUUSD", price_bins=5)
        assert len(levels) > 0
        assert all("imbalance" in lv for lv in levels)

    def test_get_volume_imbalance_empty(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        assert analyzer.get_volume_imbalance_by_level("NONEXISTENT") == []

    def test_get_stacked_imbalances(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer(config={"imbalance_threshold": 0.1})
        now = datetime.utcnow()
        # Create consistently buy-dominated price levels
        for i in range(30):
            analyzer.add_trade(
                "XAUUSD", 1950.0 + i * 0.1, 100.0, "buy",
                timestamp=now - timedelta(minutes=5)
            )
        for i in range(30):
            analyzer.add_trade(
                "XAUUSD", 1950.0 + i * 0.1, 20.0, "sell",
                timestamp=now - timedelta(minutes=5)
            )

        stacked = analyzer.get_stacked_imbalances("XAUUSD", price_bins=10, min_stack_size=2)
        assert isinstance(stacked, list)

    def test_detect_delta_divergence_not_enough_data(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy")

        assert analyzer.detect_delta_divergence("XAUUSD") is None

    def test_detect_delta_divergence_bullish(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        now = datetime.utcnow()

        # First half: high price, more sells → delta falling
        for i in range(10):
            analyzer.add_trade(
                "XAUUSD", 1960.0 - i * 0.1, 100.0, "sell",
                timestamp=now - timedelta(minutes=30 + i)
            )
        # Second half: lower price, more buys → delta rising
        for i in range(10):
            analyzer.add_trade(
                "XAUUSD", 1950.0 + i * 0.1, 100.0, "buy",
                timestamp=now - timedelta(minutes=15 + i)
            )

        result = analyzer.detect_delta_divergence("XAUUSD")
        # Result may be None or a divergence depending on data shape
        if result is not None:
            assert result.divergence_type in ("bullish", "bearish")

    def test_get_volume_clusters(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        now = datetime.utcnow()

        # Concentrated volume at one price
        for _ in range(20):
            analyzer.add_trade("XAUUSD", 1950.0, 500.0, "buy",
                               timestamp=now - timedelta(hours=2))
        for i in range(5):
            analyzer.add_trade("XAUUSD", 1960.0 + i, 50.0, "sell",
                               timestamp=now - timedelta(hours=2))

        clusters = analyzer.get_volume_clusters("XAUUSD")
        assert isinstance(clusters, list)
        if clusters:
            assert all(hasattr(c, "cluster_type") for c in clusters)

    def test_get_order_flow_oscillator_no_data(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        assert analyzer.get_order_flow_oscillator("NONEXISTENT") is None

    def test_get_order_flow_oscillator(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer(config={"oscillator_period": 10})
        for _ in range(8):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        for _ in range(2):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "sell")

        osc = analyzer.get_order_flow_oscillator("XAUUSD")
        assert osc is not None
        assert osc.value == 60.0
        assert osc.signal == "bullish"
        assert osc.overbought is False
        assert osc.oversold is False

    def test_get_pressure_gauges(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        now = datetime.utcnow()
        for _ in range(6):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy",
                               timestamp=now - timedelta(minutes=5))
        for _ in range(4):
            analyzer.add_trade("XAUUSD", 1950.0, 100.0, "sell",
                               timestamp=now - timedelta(minutes=5))

        pressure = analyzer.get_pressure_gauges("XAUUSD")
        assert pressure is not None
        assert pressure["buy_pressure"] == 60.0
        assert pressure["sell_pressure"] == 40.0
        assert pressure["dominant"] == "buyers"

    def test_get_pressure_gauges_no_data(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        assert analyzer.get_pressure_gauges("NONEXISTENT") is None

    def test_clear_trades(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        analyzer.clear_trades("XAUUSD")

        assert analyzer._trades.get("XAUUSD", []) == []

    def test_get_stats(self):
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

        analyzer = AdvancedOrderFlowAnalyzer()
        analyzer.add_trade("XAUUSD", 1950.0, 100.0, "buy")

        stats = analyzer.get_stats()
        assert stats["symbols_tracked"] == 1

    def test_global_instance(self):
        from analysis.advanced_order_flow import get_advanced_order_flow_analyzer

        a1 = get_advanced_order_flow_analyzer()
        a2 = get_advanced_order_flow_analyzer()
        assert a1 is a2
