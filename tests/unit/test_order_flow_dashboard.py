"""
Tests for Order Flow Dashboard (analysis/order_flow_dashboard.py)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock


class TestOrderFlowDashboard:
    """Tests for OrderFlowDashboard."""

    def _make_dashboard(self):
        """Create a dashboard with fresh service instances."""
        from analysis.order_flow import OrderFlowAnalyzer
        from analysis.institutional_flow import InstitutionalFlowDetector
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer
        from data.time_and_sales import TimeAndSalesService
        from data.depth_of_market import DepthOfMarketService
        from analysis.order_flow_dashboard import OrderFlowDashboard

        return OrderFlowDashboard(
            order_flow_analyzer=OrderFlowAnalyzer(),
            institutional_detector=InstitutionalFlowDetector(),
            advanced_analyzer=AdvancedOrderFlowAnalyzer(),
            time_and_sales=TimeAndSalesService(),
            dom_service=DepthOfMarketService(),
        )

    def _populate_services(self, dashboard, symbol="XAUUSD", n=30):
        """Populate all services with test trade data."""
        now = datetime.utcnow()
        for i in range(n):
            side = "buy" if i % 3 != 0 else "sell"
            price = 1950.0 + i * 0.05
            size = 100.0 if i % 5 == 0 else 50.0
            ts = now - timedelta(minutes=n - i)

            dashboard._of.add_trade(symbol, price, size, side, timestamp=ts)
            dashboard._inst.add_trade(symbol, price, size, side, timestamp=ts)
            dashboard._adv.add_trade(symbol, price, size, side, timestamp=ts)
            dashboard._ts.add_trade(symbol, price, size, side, timestamp=ts)

    def test_initialization(self):
        from analysis.order_flow_dashboard import OrderFlowDashboard

        dashboard = OrderFlowDashboard()
        assert dashboard is not None

    def test_initialization_with_custom_services(self):
        dashboard = self._make_dashboard()
        assert dashboard._of is not None
        assert dashboard._inst is not None
        assert dashboard._adv is not None
        assert dashboard._ts is not None
        assert dashboard._dom is not None

    def test_get_complete_analysis_no_data(self):
        dashboard = self._make_dashboard()
        result = dashboard.get_complete_analysis("XAUUSD")

        assert result["symbol"] == "XAUUSD"
        assert "timestamp" in result
        assert "summary" in result
        # Subsystems should be None or empty with no data
        assert result["order_flow"] is None
        assert result["institutional"] is not None  # dict, but signals empty

    def test_get_complete_analysis_with_data(self):
        dashboard = self._make_dashboard()
        self._populate_services(dashboard, n=40)

        result = dashboard.get_complete_analysis("XAUUSD")

        assert result["symbol"] == "XAUUSD"
        assert result["order_flow"] is not None
        assert result["institutional"] is not None
        assert result["advanced"] is not None
        assert result["time_and_sales"] is not None
        assert result["summary"] is not None

    def test_complete_analysis_structure(self):
        dashboard = self._make_dashboard()
        self._populate_services(dashboard)

        result = dashboard.get_complete_analysis("XAUUSD")

        # Check top-level keys
        expected_keys = [
            "symbol", "timestamp", "lookback_minutes",
            "order_flow", "institutional", "advanced",
            "time_and_sales", "dom", "summary",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_summary_bias_bullish(self):
        dashboard = self._make_dashboard()
        now = datetime.utcnow()
        symbol = "XAUUSD"

        # Predominantly buy volume
        for _ in range(20):
            ts = now - timedelta(minutes=5)
            dashboard._of.add_trade(symbol, 1950.0, 100.0, "buy", timestamp=ts)
            dashboard._adv.add_trade(symbol, 1950.0, 100.0, "buy", timestamp=ts)
            dashboard._inst.add_trade(symbol, 1950.0, 300.0, "buy", timestamp=ts)
            dashboard._ts.add_trade(symbol, 1950.0, 100.0, "buy", timestamp=ts)

        for _ in range(3):
            ts = now - timedelta(minutes=5)
            dashboard._of.add_trade(symbol, 1950.0, 100.0, "sell", timestamp=ts)
            dashboard._adv.add_trade(symbol, 1950.0, 100.0, "sell", timestamp=ts)
            dashboard._inst.add_trade(symbol, 1950.0, 300.0, "sell", timestamp=ts)
            dashboard._ts.add_trade(symbol, 1950.0, 100.0, "sell", timestamp=ts)

        result = dashboard.get_complete_analysis(symbol)
        summary = result["summary"]
        assert summary["bias"] in ("bullish", "neutral")

    def test_summary_bias_bearish(self):
        dashboard = self._make_dashboard()
        now = datetime.utcnow()
        symbol = "XAUUSD"

        for _ in range(3):
            ts = now - timedelta(minutes=5)
            dashboard._of.add_trade(symbol, 1950.0, 100.0, "buy", timestamp=ts)
            dashboard._adv.add_trade(symbol, 1950.0, 100.0, "buy", timestamp=ts)
            dashboard._inst.add_trade(symbol, 1950.0, 300.0, "buy", timestamp=ts)
            dashboard._ts.add_trade(symbol, 1950.0, 100.0, "buy", timestamp=ts)

        for _ in range(20):
            ts = now - timedelta(minutes=5)
            dashboard._of.add_trade(symbol, 1950.0, 100.0, "sell", timestamp=ts)
            dashboard._adv.add_trade(symbol, 1950.0, 100.0, "sell", timestamp=ts)
            dashboard._inst.add_trade(symbol, 1950.0, 300.0, "sell", timestamp=ts)
            dashboard._ts.add_trade(symbol, 1950.0, 100.0, "sell", timestamp=ts)

        result = dashboard.get_complete_analysis(symbol)
        summary = result["summary"]
        assert summary["bias"] in ("bearish", "neutral")

    def test_get_market_bias(self):
        dashboard = self._make_dashboard()
        self._populate_services(dashboard)

        bias = dashboard.get_market_bias("XAUUSD")
        assert "bias" in bias
        assert bias["bias"] in ("bullish", "bearish", "neutral")

    def test_get_key_levels(self):
        dashboard = self._make_dashboard()
        self._populate_services(dashboard)

        levels = dashboard.get_key_levels("XAUUSD")
        assert "support" in levels
        assert "resistance" in levels
        assert "poc" in levels

    def test_get_key_levels_no_data(self):
        dashboard = self._make_dashboard()

        levels = dashboard.get_key_levels("NONEXISTENT")
        assert "support" in levels
        assert "resistance" in levels

    def test_dom_included_when_available(self):
        dashboard = self._make_dashboard()
        self._populate_services(dashboard)

        dashboard._dom.update_order_book(
            "XAUUSD",
            bids=[(1950.0, 100), (1949.5, 150)],
            asks=[(1950.5, 80), (1951.0, 120)],
        )

        result = dashboard.get_complete_analysis("XAUUSD")
        assert result["dom"] is not None
        assert "spread" in result["dom"]

    def test_dashboard_handles_service_errors_gracefully(self):
        """Dashboard should not crash if a subsystem raises."""
        from analysis.order_flow_dashboard import OrderFlowDashboard

        broken = MagicMock()
        broken.analyze.side_effect = RuntimeError("boom")
        broken.get_key_levels.return_value = {"support": [], "resistance": [], "poc": None}

        from analysis.institutional_flow import InstitutionalFlowDetector
        from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer
        from data.time_and_sales import TimeAndSalesService
        from data.depth_of_market import DepthOfMarketService

        dashboard = OrderFlowDashboard(
            order_flow_analyzer=broken,
            institutional_detector=InstitutionalFlowDetector(),
            advanced_analyzer=AdvancedOrderFlowAnalyzer(),
            time_and_sales=TimeAndSalesService(),
            dom_service=DepthOfMarketService(),
        )

        # Should not raise
        result = dashboard.get_complete_analysis("XAUUSD")
        assert result is not None
        # order_flow should be None since the analyzer raised
        assert result["order_flow"] is None

    def test_global_instance(self):
        from analysis.order_flow_dashboard import get_order_flow_dashboard

        d1 = get_order_flow_dashboard()
        d2 = get_order_flow_dashboard()
        assert d1 is d2
