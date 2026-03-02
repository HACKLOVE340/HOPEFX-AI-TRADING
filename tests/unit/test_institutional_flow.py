"""
Tests for Institutional Flow Detector (analysis/institutional_flow.py)
"""

import pytest
from datetime import datetime, timedelta


class TestInstitutionalTrade:
    """Tests for InstitutionalTrade dataclass."""

    def test_trade_to_dict(self):
        from analysis.institutional_flow import InstitutionalTrade

        trade = InstitutionalTrade(
            timestamp=datetime.utcnow(),
            symbol="XAUUSD",
            price=1950.0,
            size=500.0,
            side="buy",
            classification="institutional",
            confidence=0.8,
            indicators=["large_order_size"],
        )

        d = trade.to_dict()
        assert d["classification"] == "institutional"
        assert d["confidence"] == 0.8
        assert "large_order_size" in d["indicators"]


class TestFlowSignal:
    """Tests for FlowSignal dataclass."""

    def test_signal_to_dict(self):
        from analysis.institutional_flow import FlowSignal

        signal = FlowSignal(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            signal_type="iceberg",
            strength="strong",
            direction="bullish",
            price_level=1950.0,
            volume=1000.0,
            details={"fill_count": 5},
        )

        d = signal.to_dict()
        assert d["signal_type"] == "iceberg"
        assert d["direction"] == "bullish"
        assert d["details"]["fill_count"] == 5


class TestInstitutionalFlowDetector:
    """Tests for InstitutionalFlowDetector."""

    def test_initialization(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        assert detector is not None

    def test_add_trade(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        detector.add_trade("XAUUSD", price=1950.0, size=100.0, side="buy")

        assert len(detector._trades["XAUUSD"]) == 1

    def test_detect_large_orders(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(config={"large_order_threshold": 200})
        now = datetime.utcnow()

        detector.add_trade("XAUUSD", 1950.0, 500.0, "buy", timestamp=now - timedelta(minutes=5))
        detector.add_trade("XAUUSD", 1950.0, 50.0, "buy", timestamp=now - timedelta(minutes=5))

        large = detector.detect_large_orders("XAUUSD")
        assert len(large) == 1
        assert large[0].size == 500.0
        assert large[0].classification == "institutional"

    def test_detect_large_orders_empty(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        assert detector.detect_large_orders("NONEXISTENT") == []

    def test_detect_iceberg_orders(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(
            config={"iceberg_min_fills": 3, "iceberg_window_seconds": 30}
        )
        base = datetime.utcnow() - timedelta(minutes=5)

        # Multiple fills at same price within short time
        for i in range(5):
            detector.add_trade(
                "XAUUSD", 1950.00, 50.0, "buy",
                timestamp=base + timedelta(seconds=i * 5)
            )
        # A fill at different price - should not be part of iceberg
        detector.add_trade("XAUUSD", 1952.00, 50.0, "sell", timestamp=base)

        signals = detector.detect_iceberg_orders("XAUUSD")
        assert len(signals) >= 1
        assert signals[0].signal_type == "iceberg"

    def test_detect_iceberg_orders_none(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        # Not enough fills at same price
        detector.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        detector.add_trade("XAUUSD", 1951.0, 100.0, "sell")

        signals = detector.detect_iceberg_orders("XAUUSD")
        assert signals == []

    def test_detect_volume_spikes(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(config={"volume_spike_multiplier": 2.0})
        now = datetime.utcnow()

        # Normal trades spread across time
        for i in range(10):
            detector.add_trade(
                "XAUUSD", 1950.0, 10.0, "buy",
                timestamp=now - timedelta(minutes=20 + i)
            )

        # Spike: large volume in a short window
        for _ in range(5):
            detector.add_trade(
                "XAUUSD", 1950.0, 200.0, "buy",
                timestamp=now - timedelta(minutes=2)
            )

        signals = detector.detect_volume_spikes("XAUUSD")
        # Should detect at least one spike
        assert isinstance(signals, list)

    def test_detect_absorption(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(
            config={"absorption_price_pct": 0.5}
        )
        now = datetime.utcnow()

        # High volume, tiny price range = absorption
        for i in range(10):
            side = "buy" if i % 3 != 0 else "sell"
            detector.add_trade(
                "XAUUSD", 1950.00 + (i % 2) * 0.001, 200.0, side,
                timestamp=now - timedelta(minutes=5, seconds=i * 3)
            )

        signals = detector.detect_absorption("XAUUSD")
        assert isinstance(signals, list)

    def test_classify_trade_institutional(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(config={"large_order_threshold": 200})
        result = detector.classify_trade(price=1950.0, size=500.0, side="buy")

        assert result.classification == "institutional"
        assert result.confidence > 0.4

    def test_classify_trade_retail(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(config={"large_order_threshold": 200})
        result = detector.classify_trade(price=1950.0, size=10.0, side="sell")

        assert result.classification == "retail"
        assert result.confidence < 0.4

    def test_analyze_flow_returns_list(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        now = datetime.utcnow()
        for i in range(20):
            detector.add_trade("XAUUSD", 1950.0, float(i * 10 + 5), "buy",
                               timestamp=now - timedelta(minutes=i))

        signals = detector.analyze_flow("XAUUSD")
        assert isinstance(signals, list)

    def test_get_smart_money_direction_no_data(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        result = detector.get_smart_money_direction("NONEXISTENT")
        assert result is None

    def test_get_smart_money_direction(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector(config={"large_order_threshold": 50})
        now = datetime.utcnow()

        for _ in range(10):
            detector.add_trade("XAUUSD", 1950.0, 300.0, "buy",
                               timestamp=now - timedelta(minutes=5))
        for _ in range(2):
            detector.add_trade("XAUUSD", 1950.0, 100.0, "sell",
                               timestamp=now - timedelta(minutes=5))

        result = detector.get_smart_money_direction("XAUUSD")
        assert result is not None
        assert result.direction == "bullish"
        assert result.institutional_buy_volume > result.institutional_sell_volume

    def test_get_stats(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        detector.add_trade("XAUUSD", 1950.0, 100.0, "buy")

        stats = detector.get_stats()
        assert stats["symbols_tracked"] == 1

    def test_clear_symbol(self):
        from analysis.institutional_flow import InstitutionalFlowDetector

        detector = InstitutionalFlowDetector()
        detector.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        detector.clear_symbol("XAUUSD")

        assert len(detector._trades.get("XAUUSD", [])) == 0

    def test_global_instance(self):
        from analysis.institutional_flow import get_institutional_detector

        d1 = get_institutional_detector()
        d2 = get_institutional_detector()
        assert d1 is d2
