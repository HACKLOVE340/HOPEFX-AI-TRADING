# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Tests for simple backtesting modules:
  - backtesting/events.py
  - backtesting/reports.py
  - backtesting/plots.py
  - backtesting/execution.py
  - backtesting/transaction_costs.py
  - ml/features/feature_engineering.py
"""

import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/events.py
# ─────────────────────────────────────────────────────────────────────────────


class TestEventTypes:
    def test_event_type_values(self):
        from backtesting.events import EventType

        assert EventType.MARKET.value == "MARKET"
        assert EventType.SIGNAL.value == "SIGNAL"
        assert EventType.ORDER.value == "ORDER"
        assert EventType.FILL.value == "FILL"

    def test_market_event_type(self):
        from backtesting.events import EventType, MarketEvent

        ev = MarketEvent()
        assert ev.type == EventType.MARKET
        assert isinstance(ev.timestamp, datetime)

    def test_signal_event_defaults(self):
        from backtesting.events import EventType, SignalEvent

        ev = SignalEvent(symbol="EURUSD", signal_type="BUY")
        assert ev.type == EventType.SIGNAL
        assert ev.symbol == "EURUSD"
        assert ev.signal_type == "BUY"
        assert ev.strength == 1.0
        assert ev.metadata == {}

    def test_signal_event_custom_strength_and_metadata(self):
        from backtesting.events import SignalEvent

        meta = {"confidence": 0.9}
        ev = SignalEvent(symbol="XAUUSD", signal_type="SELL", strength=0.7, metadata=meta)
        assert ev.strength == 0.7
        assert ev.metadata == {"confidence": 0.9}

    def test_order_event_market(self):
        from backtesting.events import EventType, OrderEvent

        ev = OrderEvent(symbol="BTCUSD", order_type="MARKET", quantity=1.0, direction="BUY")
        assert ev.type == EventType.ORDER
        assert ev.symbol == "BTCUSD"
        assert ev.order_type == "MARKET"
        assert ev.quantity == 1.0
        assert ev.direction == "BUY"
        assert ev.price is None

    def test_order_event_limit_with_price(self):
        from backtesting.events import OrderEvent

        ev = OrderEvent(symbol="EURUSD", order_type="LIMIT", quantity=10000, direction="SELL", price=1.0850)
        assert ev.price == 1.0850

    def test_fill_event_defaults(self):
        from backtesting.events import EventType, FillEvent

        ev = FillEvent(symbol="GBPUSD", quantity=5000, direction="BUY", fill_price=1.265)
        assert ev.type == EventType.FILL
        assert ev.symbol == "GBPUSD"
        assert ev.quantity == 5000
        assert ev.direction == "BUY"
        assert ev.fill_price == 1.265
        assert ev.commission == 0.0

    def test_fill_event_with_commission(self):
        from backtesting.events import FillEvent

        ev = FillEvent(symbol="XAUUSD", quantity=1, direction="SELL", fill_price=1980.0, commission=5.0)
        assert ev.commission == 5.0

    def test_event_timestamp_is_utc(self):
        from backtesting.events import MarketEvent

        ev = MarketEvent()
        assert ev.timestamp.tzinfo is not None


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/transaction_costs.py
# ─────────────────────────────────────────────────────────────────────────────


class TestTransactionCostModel:
    def test_known_ticker_gold(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost = tc.round_trip_cost_frac("GC=F")
        # 2*1.5 + 3.5 = 6.5 bps = 0.00065
        assert abs(cost - 0.00065) < 1e-9

    def test_known_ticker_btc(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost = tc.round_trip_cost_frac("BTC-USD")
        # 2*1.0 + 10.0 = 12 bps = 0.0012
        assert abs(cost - 0.0012) < 1e-9

    def test_known_ticker_eurusd(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost = tc.round_trip_cost_frac("EURUSD=X")
        # 2*0.92 + 3.0 = 4.84 bps = 0.000484
        assert abs(cost - 0.000484) < 1e-9

    def test_unknown_ticker_uses_default(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost = tc.round_trip_cost_frac("UNKNOWN/PAIR")
        # 2*2.0 + 10.0 = 14 bps = 0.0014
        assert abs(cost - 0.0014) < 1e-9

    def test_apply_reduces_pnl(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        net = tc.apply(raw_pnl_pct=0.005, entry_price=1980.0, ticker="GC=F")
        assert net < 0.005

    def test_apply_xauusd_alias(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        net_gc = tc.apply(raw_pnl_pct=0.005, entry_price=1980.0, ticker="GC=F")
        net_xau = tc.apply(raw_pnl_pct=0.005, entry_price=1980.0, ticker="XAU/USD")
        assert abs(net_gc - net_xau) < 1e-12

    def test_extra_spread_increases_cost(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc_base = TransactionCostModel(extra_spread_bps=0.0)
        tc_extra = TransactionCostModel(extra_spread_bps=2.0)
        cost_base = tc_base.round_trip_cost_frac("GC=F")
        cost_extra = tc_extra.round_trip_cost_frac("GC=F")
        assert cost_extra > cost_base

    def test_cost_summary_keys(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        summary = tc.cost_summary(entry_price=1980.0, ticker="GC=F")
        for key in (
            "ticker",
            "entry_price",
            "half_spread_bps",
            "round_trip_spread_bps",
            "commission_bps",
            "total_cost_bps",
            "total_cost_pct",
            "approx_cost_usd_per_unit",
        ):
            assert key in summary

    def test_cost_summary_ticker_preserved(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        summary = tc.cost_summary(entry_price=50000.0, ticker="BTC-USD")
        assert summary["ticker"] == "BTC-USD"
        assert summary["entry_price"] == 50000.0

    def test_cost_summary_unknown_ticker(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        summary = tc.cost_summary(entry_price=100.0, ticker="WEIRD/PAIR")
        assert summary["half_spread_bps"] == 2.0
        assert summary["commission_bps"] == 10.0

    def test_get_tc_model_singleton(self):
        from backtesting.transaction_costs import get_tc_model

        m1 = get_tc_model()
        m2 = get_tc_model()
        assert m1 is m2

    def test_get_tc_model_extra_spread_creates_new(self):
        from backtesting.transaction_costs import TransactionCostModel, get_tc_model

        m = get_tc_model(extra_spread_bps=1.0)
        assert isinstance(m, TransactionCostModel)

    def test_gbpusd_alias(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost_x = tc.round_trip_cost_frac("GBPUSD=X")
        cost_slash = tc.round_trip_cost_frac("GBP/USD")
        assert abs(cost_x - cost_slash) < 1e-12

    def test_silver_cost(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost = tc.round_trip_cost_frac("SI=F")
        # 2*8.33 + 3.5 = 20.16 bps
        assert abs(cost - 0.002016) < 1e-9

    def test_crude_oil_cost(self):
        from backtesting.transaction_costs import TransactionCostModel

        tc = TransactionCostModel()
        cost = tc.round_trip_cost_frac("CL=F")
        # 2*4.0 + 3.5 = 11.5 bps
        assert abs(cost - 0.00115) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/reports.py
# ─────────────────────────────────────────────────────────────────────────────


class TestReportGenerator:
    def _make_results(self):
        return {
            "metrics": {
                "total_return": 15.5,
                "annual_return": 12.3,
                "sharpe_ratio": 1.45,
                "sortino_ratio": 2.1,
                "max_drawdown": -8.2,
                "calmar_ratio": 1.5,
                "volatility": 10.0,
                "total_trades": 100,
                "winning_trades": 60,
                "losing_trades": 40,
                "win_rate": 60.0,
                "profit_factor": 1.8,
                "avg_win": 250.0,
                "avg_loss": -150.0,
                "largest_win": 1200.0,
                "largest_loss": -600.0,
            }
        }

    def test_generate_text_report_returns_string(self):
        from backtesting.reports import ReportGenerator

        rg = ReportGenerator(self._make_results())
        report = rg.generate_text_report()
        assert isinstance(report, str)

    def test_report_contains_header(self):
        from backtesting.reports import ReportGenerator

        rg = ReportGenerator(self._make_results())
        report = rg.generate_text_report()
        assert "BACKTEST REPORT" in report

    def test_report_contains_metrics(self):
        from backtesting.reports import ReportGenerator

        rg = ReportGenerator(self._make_results())
        report = rg.generate_text_report()
        assert "Total Return" in report
        assert "Sharpe Ratio" in report
        assert "Win Rate" in report

    def test_report_contains_trade_stats(self):
        from backtesting.reports import ReportGenerator

        rg = ReportGenerator(self._make_results())
        report = rg.generate_text_report()
        assert "Total Trades" in report
        assert "Profit Factor" in report

    def test_save_to_file(self):
        from backtesting.reports import ReportGenerator

        rg = ReportGenerator(self._make_results())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            fname = f.name
        try:
            rg.save_to_file(fname)
            with open(fname) as f:
                content = f.read()
            assert "BACKTEST REPORT" in content
        finally:
            os.unlink(fname)

    def test_results_stored(self):
        from backtesting.reports import ReportGenerator

        results = self._make_results()
        rg = ReportGenerator(results)
        assert rg.results is results


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/plots.py
# ─────────────────────────────────────────────────────────────────────────────


class TestPerformancePlotter:
    def _make_results(self):
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        equity = pd.DataFrame({"equity": np.linspace(100000, 115000, 50)}, index=dates)
        return {"equity_curve": equity}

    def test_init_stores_results(self):
        from backtesting.plots import PerformancePlotter

        results = self._make_results()
        p = PerformancePlotter(results)
        assert p.results is results

    def test_plot_equity_curve_no_matplotlib(self, monkeypatch):
        """When matplotlib is unavailable, plot_equity_curve returns without error."""
        import backtesting.plots as plots_mod

        monkeypatch.setattr(plots_mod, "MATPLOTLIB_AVAILABLE", False)
        p = plots_mod.PerformancePlotter(self._make_results())
        # Should return None without raising
        result = p.plot_equity_curve()
        assert result is None

    def test_plot_drawdown_no_matplotlib(self, monkeypatch):
        import backtesting.plots as plots_mod

        monkeypatch.setattr(plots_mod, "MATPLOTLIB_AVAILABLE", False)
        p = plots_mod.PerformancePlotter(self._make_results())
        result = p.plot_drawdown()
        assert result is None

    def test_plot_equity_curve_saves_file(self, tmp_path):
        """When matplotlib is available, saving to file works."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            from backtesting.plots import PerformancePlotter, MATPLOTLIB_AVAILABLE

            if not MATPLOTLIB_AVAILABLE:
                pytest.skip("matplotlib not installed")
            p = PerformancePlotter(self._make_results())
            fname = str(tmp_path / "equity.png")
            p.plot_equity_curve(filename=fname)
            assert os.path.exists(fname)
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_plot_drawdown_saves_file(self, tmp_path):
        try:
            import matplotlib

            matplotlib.use("Agg")
            from backtesting.plots import PerformancePlotter, MATPLOTLIB_AVAILABLE

            if not MATPLOTLIB_AVAILABLE:
                pytest.skip("matplotlib not installed")
            p = PerformancePlotter(self._make_results())
            fname = str(tmp_path / "drawdown.png")
            p.plot_drawdown(filename=fname)
            assert os.path.exists(fname)
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_plot_equity_curve_show_path(self, monkeypatch):
        """Covers the plt.show() branch (filename=None with matplotlib available)."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt_mod
            import backtesting.plots as plots_mod

            if not plots_mod.MATPLOTLIB_AVAILABLE:
                pytest.skip("matplotlib not installed")
            monkeypatch.setattr(plt_mod, "show", lambda: None)
            p = plots_mod.PerformancePlotter(self._make_results())
            p.plot_equity_curve(filename=None)
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_plot_drawdown_show_path(self, monkeypatch):
        """Covers the plt.show() branch for drawdown (filename=None)."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt_mod
            import backtesting.plots as plots_mod

            if not plots_mod.MATPLOTLIB_AVAILABLE:
                pytest.skip("matplotlib not installed")
            monkeypatch.setattr(plt_mod, "show", lambda: None)
            p = plots_mod.PerformancePlotter(self._make_results())
            p.plot_drawdown(filename=None)
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_matplotlib_unavailable_import_branch(self, monkeypatch):
        """Covers the except ImportError branch in plots.py module-level code."""
        import sys
        import importlib

        # Temporarily hide matplotlib to force the except branch
        real_matplotlib = sys.modules.get("matplotlib.pyplot")
        sys.modules["matplotlib.pyplot"] = None  # type: ignore
        try:
            import backtesting.plots as plots_mod

            importlib.reload(plots_mod)
            # After reload with matplotlib blocked, MATPLOTLIB_AVAILABLE should be False
            # (or the module handles it gracefully)
        except Exception:
            pass
        finally:
            if real_matplotlib is not None:
                sys.modules["matplotlib.pyplot"] = real_matplotlib
            elif "matplotlib.pyplot" in sys.modules:
                del sys.modules["matplotlib.pyplot"]


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/execution.py
# ─────────────────────────────────────────────────────────────────────────────


class TestSimulatedExecutionHandler:
    def _make_data_handler(self, bar=None):
        dh = MagicMock()
        dh.get_latest_bar.return_value = bar
        return dh

    def _make_order(self, order_type="MARKET", direction="BUY", price=None, quantity=1.0, symbol="EURUSD"):
        from backtesting.events import OrderEvent

        return OrderEvent(symbol=symbol, order_type=order_type, quantity=quantity, direction=direction, price=price)

    def test_init_stores_params(self):
        from backtesting.execution import SimulatedExecutionHandler

        dh = self._make_data_handler()
        handler = SimulatedExecutionHandler(dh, commission_pct=0.002, slippage_pct=0.001)
        assert handler.commission_pct == 0.002
        assert handler.slippage_pct == 0.001

    def test_market_buy_fills(self):
        from backtesting.execution import SimulatedExecutionHandler
        from backtesting.events import FillEvent

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="MARKET", direction="BUY")
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)
        assert fill.direction == "BUY"
        assert fill.fill_price > 1.085  # slippage applied

    def test_market_sell_fills(self):
        from backtesting.execution import SimulatedExecutionHandler
        from backtesting.events import FillEvent

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="MARKET", direction="SELL")
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)
        assert fill.fill_price < 1.085  # slippage applied

    def test_no_bar_returns_none(self):
        from backtesting.execution import SimulatedExecutionHandler

        dh = self._make_data_handler(None)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order()
        fill = handler.execute_order(order)
        assert fill is None

    def test_limit_buy_fills_when_price_reached(self):
        from backtesting.execution import SimulatedExecutionHandler
        from backtesting.events import FillEvent

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="LIMIT", direction="BUY", price=1.075)
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)

    def test_limit_buy_no_fill_when_price_not_reached(self):
        from backtesting.execution import SimulatedExecutionHandler

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="LIMIT", direction="BUY", price=1.065)
        fill = handler.execute_order(order)
        assert fill is None

    def test_limit_sell_fills_when_price_reached(self):
        from backtesting.execution import SimulatedExecutionHandler
        from backtesting.events import FillEvent

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="LIMIT", direction="SELL", price=1.088)
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)

    def test_limit_sell_no_fill_when_price_not_reached(self):
        from backtesting.execution import SimulatedExecutionHandler

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="LIMIT", direction="SELL", price=1.095)
        fill = handler.execute_order(order)
        assert fill is None

    def test_stop_buy_fills_when_triggered(self):
        from backtesting.execution import SimulatedExecutionHandler
        from backtesting.events import FillEvent

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="STOP", direction="BUY", price=1.088)
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)

    def test_stop_buy_no_fill_when_not_triggered(self):
        from backtesting.execution import SimulatedExecutionHandler

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="STOP", direction="BUY", price=1.095)
        fill = handler.execute_order(order)
        assert fill is None

    def test_stop_sell_fills_when_triggered(self):
        from backtesting.execution import SimulatedExecutionHandler
        from backtesting.events import FillEvent

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="STOP", direction="SELL", price=1.072)
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)

    def test_stop_sell_no_fill_when_not_triggered(self):
        from backtesting.execution import SimulatedExecutionHandler

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="STOP", direction="SELL", price=1.065)
        fill = handler.execute_order(order)
        assert fill is None

    def test_unknown_order_type_returns_none(self):
        from backtesting.execution import SimulatedExecutionHandler

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh)
        order = self._make_order(order_type="ICEBERG", direction="BUY")
        fill = handler.execute_order(order)
        assert fill is None

    def test_commission_applied(self):
        from backtesting.execution import SimulatedExecutionHandler

        bar = {"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}
        dh = self._make_data_handler(bar)
        handler = SimulatedExecutionHandler(dh, commission_pct=0.001)
        order = self._make_order(order_type="MARKET", direction="BUY", quantity=10000)
        fill = handler.execute_order(order)
        assert fill.commission > 0

    def test_audit_log_creation(self):
        from backtesting.execution import OrderResult, create_audit_log

        # Order is a dataclass — build a minimal one
        order = MagicMock()
        result = OrderResult(success=True, fill_price=1.085, message="filled")
        log = create_audit_log(order, result)
        assert log["success"] is True
        assert log["fill_price"] == 1.085
        assert "order_hash" in log
        assert "timestamp" in log
        assert log["compliance_version"] == "1.0"

    def test_order_result_attributes(self):
        from backtesting.execution import OrderResult

        r = OrderResult(success=False, fill_price=0.0, message="rejected")
        assert r.success is False
        assert r.fill_price == 0.0
        assert r.message == "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# ml/features/feature_engineering.py
# ─────────────────────────────────────────────────────────────────────────────


class TestFeatureEngineeringShim:
    def test_import_succeeds(self):
        from ml.features.feature_engineering import AdvancedFeatureEngineer

        assert AdvancedFeatureEngineer is not None

    def test_is_same_class_as_advanced(self):
        from ml.features.feature_engineering import AdvancedFeatureEngineer as FE_shim
        from ml.features.advanced_features import AdvancedFeatureEngineer as FE_real

        assert FE_shim is FE_real

    def test_all_exports(self):
        import ml.features.feature_engineering as mod

        assert "AdvancedFeatureEngineer" in mod.__all__
