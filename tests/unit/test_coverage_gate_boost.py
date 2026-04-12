# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Coverage boost tests targeting uncovered backtesting and analytics modules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _equity_df(values=None):
    if values is None:
        values = [100000, 101000, 102000, 101500, 103000, 102000, 104000]
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"equity": values}, index=idx)


def _trade_df(pnls=None):
    if pnls is None:
        pnls = [500, -200, 300, -100, 400, -150, 600]
    now = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i, p in enumerate(pnls):
        rows.append({
            "pnl": p,
            "entry_time": now + timedelta(days=i),
            "exit_time": now + timedelta(days=i, hours=4),
        })
    return pd.DataFrame(rows)


# ===========================================================================
# backtesting/metrics.py
# ===========================================================================

class TestPerformanceMetrics:
    def _make(self, equity=None, trades=None):
        from backtesting.metrics import PerformanceMetrics
        return PerformanceMetrics(
            equity_curve=_equity_df(equity),
            trade_history=_trade_df(trades),
            initial_capital=100_000.0,
        )

    def test_total_return_positive(self):
        m = self._make()
        assert m.calculate_total_return() > 0

    def test_total_return_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_total_return() == 0.0

    def test_annual_return_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_annual_return() == 0.0

    def test_annual_return_single_row(self):
        from backtesting.metrics import PerformanceMetrics
        df = pd.DataFrame({"equity": [100_000]}, index=pd.date_range("2024-01-01", periods=1))
        m = PerformanceMetrics(df, pd.DataFrame(), 100_000.0)
        assert m.calculate_annual_return() == 0.0

    def test_annual_return_same_day(self):
        from backtesting.metrics import PerformanceMetrics
        idx = pd.DatetimeIndex([datetime(2024, 1, 1), datetime(2024, 1, 1)])
        df = pd.DataFrame({"equity": [100_000, 101_000]}, index=idx)
        m = PerformanceMetrics(df, pd.DataFrame(), 100_000.0)
        assert m.calculate_annual_return() == 0.0

    def test_monthly_return(self):
        m = self._make()
        assert isinstance(m.calculate_monthly_return(), float)

    def test_sharpe_ratio(self):
        m = self._make()
        assert isinstance(m.calculate_sharpe_ratio(), float)

    def test_sharpe_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_sharpe_ratio() == 0.0

    def test_sharpe_zero_std(self):
        from backtesting.metrics import PerformanceMetrics
        df = pd.DataFrame({"equity": [100_000] * 5}, index=pd.date_range("2024-01-01", periods=5))
        m = PerformanceMetrics(df, pd.DataFrame(), 100_000.0)
        assert m.calculate_sharpe_ratio() == 0.0

    def test_sortino_ratio(self):
        m = self._make()
        assert isinstance(m.calculate_sortino_ratio(), float)

    def test_sortino_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_sortino_ratio() == 0.0

    def test_sortino_no_downside(self):
        from backtesting.metrics import PerformanceMetrics
        df = pd.DataFrame({"equity": [100_000, 101_000, 102_000, 103_000]},
                          index=pd.date_range("2024-01-01", periods=4))
        m = PerformanceMetrics(df, pd.DataFrame(), 100_000.0)
        assert m.calculate_sortino_ratio() == 0.0

    def test_max_drawdown_negative(self):
        m = self._make()
        assert m.calculate_max_drawdown() <= 0

    def test_max_drawdown_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_max_drawdown() == 0.0

    def test_calmar_ratio(self):
        m = self._make()
        assert isinstance(m.calculate_calmar_ratio(), float)

    def test_calmar_zero_drawdown(self):
        from backtesting.metrics import PerformanceMetrics
        df = pd.DataFrame({"equity": [100_000, 101_000, 102_000]},
                          index=pd.date_range("2024-01-01", periods=3))
        m = PerformanceMetrics(df, pd.DataFrame(), 100_000.0)
        assert m.calculate_calmar_ratio() == 0.0

    def test_volatility(self):
        m = self._make()
        assert m.calculate_volatility() >= 0

    def test_total_trades(self):
        m = self._make()
        assert m.calculate_total_trades() == 7

    def test_winning_trades(self):
        m = self._make()
        assert m.calculate_winning_trades() == 4

    def test_losing_trades(self):
        m = self._make()
        assert m.calculate_losing_trades() == 3

    def test_win_rate(self):
        m = self._make()
        assert 0 < m.calculate_win_rate() < 100

    def test_win_rate_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_win_rate() == 0.0

    def test_profit_factor(self):
        m = self._make()
        assert m.calculate_profit_factor() > 0

    def test_profit_factor_no_losses(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), _trade_df([100, 200, 300]), 100_000.0)
        assert m.calculate_profit_factor() == float("inf")

    def test_profit_factor_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_profit_factor() == 0.0

    def test_avg_win(self):
        m = self._make()
        assert m.calculate_avg_win() > 0

    def test_avg_loss(self):
        m = self._make()
        assert m.calculate_avg_loss() < 0

    def test_avg_win_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_avg_win() == 0.0

    def test_avg_loss_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_avg_loss() == 0.0

    def test_largest_win(self):
        m = self._make()
        assert m.calculate_largest_win() == 600

    def test_largest_loss(self):
        m = self._make()
        assert m.calculate_largest_loss() == -200

    def test_largest_win_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_largest_win() == 0.0

    def test_largest_loss_empty(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        assert m.calculate_largest_loss() == 0.0

    def test_avg_trade_duration(self):
        m = self._make()
        assert m.calculate_avg_trade_duration() > 0

    def test_avg_trade_duration_no_time_cols(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), _trade_df(), 100_000.0)
        # trade_df has entry_time/exit_time so should return > 0
        assert m.calculate_avg_trade_duration() >= 0

    def test_calculate_all_metrics_keys(self):
        m = self._make()
        result = m.calculate_all_metrics()
        for key in ("total_return", "sharpe_ratio", "max_drawdown", "win_rate", "profit_factor"):
            assert key in result

    def test_final_equity_in_all_metrics(self):
        m = self._make()
        result = m.calculate_all_metrics()
        assert result["final_equity"] == pytest.approx(104_000, rel=1e-3)

    def test_peak_equity_in_all_metrics(self):
        m = self._make()
        result = m.calculate_all_metrics()
        assert result["peak_equity"] == pytest.approx(104_000, rel=1e-3)

    def test_all_metrics_empty_equity(self):
        from backtesting.metrics import PerformanceMetrics
        m = PerformanceMetrics(pd.DataFrame(), pd.DataFrame(), 100_000.0)
        result = m.calculate_all_metrics()
        assert result["final_equity"] == 100_000.0







# ===========================================================================
# backtesting/events.py
# ===========================================================================

class TestBacktestEvents:
    def test_event_type_values(self):
        from backtesting.events import EventType
        assert EventType.MARKET.value == "MARKET"
        assert EventType.SIGNAL.value == "SIGNAL"
        assert EventType.ORDER.value == "ORDER"
        assert EventType.FILL.value == "FILL"

    def test_market_event_type(self):
        from backtesting.events import EventType, MarketEvent
        e = MarketEvent()
        assert e.type == EventType.MARKET
        assert e.timestamp is not None

    def test_signal_event_defaults(self):
        from backtesting.events import EventType, SignalEvent
        e = SignalEvent("XAUUSD", "BUY")
        assert e.type == EventType.SIGNAL
        assert e.symbol == "XAUUSD"
        assert e.strength == 1.0
        assert e.metadata == {}

    def test_signal_event_custom(self):
        from backtesting.events import SignalEvent
        e = SignalEvent("EURUSD", "SELL", strength=0.7, metadata={"reason": "trend"})
        assert e.strength == 0.7
        assert e.metadata["reason"] == "trend"

    def test_order_event(self):
        from backtesting.events import EventType, OrderEvent
        e = OrderEvent("XAUUSD", "MARKET", 1.0, "BUY")
        assert e.type == EventType.ORDER
        assert e.quantity == 1.0
        assert e.price is None

    def test_order_event_with_price(self):
        from backtesting.events import OrderEvent
        e = OrderEvent("XAUUSD", "LIMIT", 1.0, "BUY", price=2000.0)
        assert e.price == 2000.0

    def test_fill_event(self):
        from backtesting.events import EventType, FillEvent
        e = FillEvent("XAUUSD", 1.0, "BUY", 2005.0, commission=5.0)
        assert e.type == EventType.FILL
        assert e.fill_price == 2005.0
        assert e.commission == 5.0

    def test_fill_event_default_commission(self):
        from backtesting.events import FillEvent
        e = FillEvent("XAUUSD", 1.0, "SELL", 1995.0)
        assert e.commission == 0.0


# ===========================================================================
# backtesting/portfolio.py
# ===========================================================================

class TestPortfolioFull:
    def _fill(self, symbol="XAUUSD", qty=1.0, price=2000.0, direction="BUY", commission=5.0):
        from backtesting.events import FillEvent
        return FillEvent(symbol, qty, direction, price, commission)

    def test_init(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(50_000.0)
        assert p.cash == 50_000.0
        assert p.equity == 50_000.0

    def test_buy_fill_updates_cash(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        f = self._fill(price=2000.0, qty=1.0, commission=5.0)
        p.update_fill(f, {"XAUUSD": 2000.0})
        assert p.cash == pytest.approx(100_000.0 - 2000.0 - 5.0)

    def test_buy_creates_position(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_fill(self._fill(), {"XAUUSD": 2000.0})
        assert p.positions["XAUUSD"] == 1.0

    def test_sell_closes_position(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_fill(self._fill(direction="BUY", price=2000.0, commission=0.0), {"XAUUSD": 2000.0})
        p.update_fill(self._fill(direction="SELL", price=2010.0, commission=0.0), {"XAUUSD": 2010.0})
        assert p.positions["XAUUSD"] == 0.0
        assert p.total_trades == 1

    def test_winning_trade_counted(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_fill(self._fill(direction="BUY", price=2000.0, commission=0.0), {"XAUUSD": 2000.0})
        p.update_fill(self._fill(direction="SELL", price=2010.0, commission=0.0), {"XAUUSD": 2010.0})
        assert p.winning_trades == 1

    def test_losing_trade_counted(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_fill(self._fill(direction="BUY", price=2000.0, commission=0.0), {"XAUUSD": 2000.0})
        p.update_fill(self._fill(direction="SELL", price=1990.0, commission=0.0), {"XAUUSD": 1990.0})
        assert p.losing_trades == 1

    def test_average_up(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(200_000.0)
        p.update_fill(self._fill(price=2000.0, qty=1.0, commission=0.0), {"XAUUSD": 2000.0})
        p.update_fill(self._fill(price=2010.0, qty=1.0, commission=0.0), {"XAUUSD": 2010.0})
        assert p.positions["XAUUSD"] == 2.0
        assert p.avg_prices["XAUUSD"] == pytest.approx(2005.0)

    def test_flip_to_short(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(200_000.0)
        p.update_fill(self._fill(direction="BUY", price=2000.0, qty=1.0, commission=0.0), {"XAUUSD": 2000.0})
        p.update_fill(self._fill(direction="SELL", price=1990.0, qty=2.0, commission=0.0), {"XAUUSD": 1990.0})
        assert p.positions["XAUUSD"] == -1.0

    def test_update_timeindex(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_timeindex(datetime(2024, 1, 1, tzinfo=UTC), {})
        assert len(p.equity_curve) == 1

    def test_get_equity_curve_df(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_timeindex(datetime(2024, 1, 1, tzinfo=UTC), {})
        p.update_timeindex(datetime(2024, 1, 2, tzinfo=UTC), {})
        df = p.get_equity_curve()
        assert len(df) == 2

    def test_get_equity_curve_empty(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        assert p.get_equity_curve().empty

    def test_get_trade_history_df(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_fill(self._fill(direction="BUY", price=2000.0, commission=0.0), {"XAUUSD": 2000.0})
        p.update_fill(self._fill(direction="SELL", price=2010.0, commission=0.0), {"XAUUSD": 2010.0})
        df = p.get_trade_history()
        assert len(df) == 1

    def test_get_trade_history_empty(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        assert p.get_trade_history().empty

    def test_get_holdings(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        p.update_fill(self._fill(direction="BUY", price=2000.0, commission=0.0), {"XAUUSD": 2000.0})
        h = p.get_holdings()
        assert "XAUUSD" in h

    def test_get_total_pnl_zero(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        assert p.get_total_pnl() == 0.0

    def test_get_total_return_zero(self):
        from backtesting.portfolio import Portfolio
        p = Portfolio(100_000.0)
        assert p.get_total_return() == 0.0


# ===========================================================================
# backtesting/walk_forward.py
# ===========================================================================

class TestWalkForwardEngine:
    def _make_data(self, n=800):
        rng = np.random.default_rng(42)
        prices = 2000.0 + np.cumsum(rng.normal(0, 5, n))
        idx = pd.date_range("2020-01-01", periods=n, freq="D")
        return pd.DataFrame({"close": prices, "open": prices, "high": prices + 2, "low": prices - 2}, index=idx)

    def _factory(self, threshold=0.0):
        class _S:
            def __init__(self, threshold):
                self.threshold = threshold
            def on_tick(self, row):
                return {"action": "BUY"} if row["close"] > self.threshold else {"action": "SELL"}
        return _S(threshold)

    def test_init_defaults(self):
        from backtesting.walk_forward import WalkForwardEngine
        e = WalkForwardEngine()
        assert e.train_size == 1000
        assert e.test_size == 200

    def test_run_returns_results(self):
        from backtesting.walk_forward import WalkForwardEngine, WalkForwardResult
        e = WalkForwardEngine(train_size=400, test_size=100, purge_size=20, step_size=400)
        results = e.run(self._make_data(), self._factory, [{"threshold": 1900.0}, {"threshold": 2100.0}])
        assert len(results) >= 1
        assert type(results[0]).__name__ == "WalkForwardResult"

    def test_result_has_fields(self):
        from backtesting.walk_forward import WalkForwardEngine
        e = WalkForwardEngine(train_size=400, test_size=100, purge_size=20, step_size=400)
        results = e.run(self._make_data(), self._factory, [{"threshold": 1900.0}])
        r = results[0]
        assert hasattr(r, "train_performance")
        assert hasattr(r, "is_overfit")
        assert r.is_overfit in (True, False, 0, 1) or isinstance(r.is_overfit, (bool, int))

    def test_get_aggregate_stats_empty(self):
        from backtesting.walk_forward import WalkForwardEngine
        assert WalkForwardEngine().get_aggregate_stats() == {}

    def test_get_aggregate_stats_after_run(self):
        from backtesting.walk_forward import WalkForwardEngine
        e = WalkForwardEngine(train_size=400, test_size=100, purge_size=20, step_size=400)
        e.run(self._make_data(), self._factory, [{"threshold": 1900.0}])
        stats = e.get_aggregate_stats()
        assert "num_windows" in stats
        assert "is_robust" in stats

    def test_max_drawdown_flat(self):
        from backtesting.walk_forward import WalkForwardEngine
        assert WalkForwardEngine()._calculate_max_drawdown([1.0, 1.0, 1.0]) == 0.0

    def test_max_drawdown_declining(self):
        from backtesting.walk_forward import WalkForwardEngine
        dd = WalkForwardEngine()._calculate_max_drawdown([1.0, 0.9, 0.8])
        assert dd == pytest.approx(0.2, rel=1e-3)

    def test_detect_overfit_true(self):
        from backtesting.walk_forward import WalkForwardEngine
        e = WalkForwardEngine()
        assert e._detect_overfit({"sharpe_ratio": 2.0, "total_return": 0.3}, {"sharpe_ratio": 0.5, "total_return": 0.05}) is True

    def test_detect_overfit_false(self):
        from backtesting.walk_forward import WalkForwardEngine
        e = WalkForwardEngine()
        assert e._detect_overfit({"sharpe_ratio": 1.0, "total_return": 0.1}, {"sharpe_ratio": 0.9, "total_return": 0.09}) is False

    def test_alias(self):
        from backtesting.walk_forward import WalkForwardAnalysis, WalkForwardEngine
        assert WalkForwardAnalysis is WalkForwardEngine


# ===========================================================================
# backtesting/transaction_costs.py
# ===========================================================================

class TestTransactionCostModel:
    def test_known_symbol_spread(self):
        from backtesting.transaction_costs import TransactionCostModel
        assert TransactionCostModel().round_trip_cost_frac("XAUUSD") > 0

    def test_unknown_symbol_default(self):
        from backtesting.transaction_costs import TransactionCostModel
        assert TransactionCostModel().round_trip_cost_frac("UNKNOWN_XYZ") > 0

    def test_apply_reduces_pnl(self):
        from backtesting.transaction_costs import TransactionCostModel
        net = TransactionCostModel().apply(raw_pnl_pct=0.01, entry_price=2000.0, ticker="XAUUSD")
        assert net < 0.01

    def test_apply_large_loss(self):
        from backtesting.transaction_costs import TransactionCostModel
        net = TransactionCostModel().apply(raw_pnl_pct=-0.05, entry_price=2000.0, ticker="XAUUSD")
        assert net < -0.05

    def test_cost_summary_returns_dict(self):
        from backtesting.transaction_costs import TransactionCostModel
        s = TransactionCostModel().cost_summary(entry_price=2000.0, ticker="XAUUSD")
        assert isinstance(s, dict) and len(s) > 0

    def test_extra_spread_increases_cost(self):
        from backtesting.transaction_costs import TransactionCostModel
        base = TransactionCostModel(extra_spread_bps=0.0).round_trip_cost_frac("XAUUSD")
        extra = TransactionCostModel(extra_spread_bps=5.0).round_trip_cost_frac("XAUUSD")
        assert extra > base

    def test_get_tc_model(self):
        from backtesting.transaction_costs import get_tc_model
        assert get_tc_model() is not None

    def test_btc_spread(self):
        from backtesting.transaction_costs import TransactionCostModel
        assert TransactionCostModel().round_trip_cost_frac("BTC-USD") > 0

    def test_forex_spread(self):
        from backtesting.transaction_costs import TransactionCostModel
        assert TransactionCostModel().round_trip_cost_frac("EURUSD=X") > 0


# ===========================================================================
# backtesting/engine.py  (dataclasses + engine init/validation)
# ===========================================================================

class TestBacktestEngineCore:
    def test_tick_mid(self):
        from backtesting.engine import TickData
        t = TickData(datetime.now(UTC), "XAUUSD", bid=1999.0, ask=2001.0)
        assert t.mid == pytest.approx(2000.0)

    def test_tick_spread(self):
        from backtesting.engine import TickData
        t = TickData(datetime.now(UTC), "XAUUSD", bid=1999.0, ask=2001.0)
        assert t.spread == pytest.approx(2.0)

    def test_order_type_enum(self):
        from backtesting.engine import OrderType
        assert OrderType.MARKET.value == "market"

    def test_order_side_enum(self):
        from backtesting.engine import OrderSide
        assert OrderSide.BUY.value == "buy"

    def test_position_unrealized_buy(self):
        from backtesting.engine import OrderSide, Position
        pos = Position("XAUUSD", OrderSide.BUY, 1.0, 2000.0, datetime.now(UTC))
        assert pos.update_unrealized_pnl(2010.0) == pytest.approx(10.0)

    def test_position_unrealized_sell(self):
        from backtesting.engine import OrderSide, Position
        pos = Position("XAUUSD", OrderSide.SELL, 1.0, 2000.0, datetime.now(UTC))
        assert pos.update_unrealized_pnl(1990.0) == pytest.approx(10.0)

    def test_tc_model_fixed_slippage(self):
        from backtesting.engine import Order, OrderSide, OrderType, TickData, TransactionCostModel
        tc = TransactionCostModel(slippage_model="fixed", slippage_pips=1.0)
        tick = TickData(datetime.now(UTC), "XAUUSD", bid=1999.0, ask=2001.0)
        order = Order(order_id="o1", timestamp=datetime.now(UTC), symbol="XAUUSD",
                      side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1.0)
        fill_price, commission, slippage = tc.calculate_costs(order, tick, 1.0)
        assert fill_price > 0

    def test_tc_model_gaussian_slippage(self):
        from backtesting.engine import Order, OrderSide, OrderType, TickData, TransactionCostModel
        tc = TransactionCostModel(slippage_model="gaussian", slippage_pips=1.0, slippage_std=0.5, seed=0)
        tick = TickData(datetime.now(UTC), "XAUUSD", bid=1999.0, ask=2001.0)
        order = Order(order_id="o1", timestamp=datetime.now(UTC), symbol="XAUUSD",
                      side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=1.0)
        fill_price, _, _ = tc.calculate_costs(order, tick, 1.0)
        assert fill_price > 0

    def test_tc_model_commission_per_lot(self):
        from backtesting.engine import Order, OrderSide, OrderType, TickData, TransactionCostModel
        tc = TransactionCostModel(commission_per_lot=7.0)
        tick = TickData(datetime.now(UTC), "XAUUSD", bid=1999.0, ask=2001.0)
        order = Order(order_id="o1", timestamp=datetime.now(UTC), symbol="XAUUSD",
                      side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100_000.0)
        _, commission, _ = tc.calculate_costs(order, tick, 100_000.0)
        assert commission == pytest.approx(7.0)

    def test_tc_model_commission_rate(self):
        from backtesting.engine import Order, OrderSide, OrderType, TickData, TransactionCostModel
        tc = TransactionCostModel(commission_rate=0.001)
        tick = TickData(datetime.now(UTC), "XAUUSD", bid=1999.0, ask=2001.0)
        order = Order(order_id="o1", timestamp=datetime.now(UTC), symbol="XAUUSD",
                      side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1.0)
        _, commission, _ = tc.calculate_costs(order, tick, 1.0)
        assert commission > 0

    def test_performance_metrics_to_dict(self):
        from backtesting.engine import PerformanceMetrics
        m = PerformanceMetrics(
            total_return=0.05, annualized_return=0.12, volatility=0.15,
            sharpe_ratio=1.2, sortino_ratio=1.5, calmar_ratio=0.8,
            max_drawdown=-0.1, max_drawdown_duration=10, avg_drawdown=-0.05,
            total_trades=50, winning_trades=30, losing_trades=20,
            win_rate=0.6, avg_trade_return=0.001, avg_win=0.002, avg_loss=-0.001,
            profit_factor=1.5, expectancy=0.0005,
            start_date=datetime(2024, 1, 1, tzinfo=UTC),
            end_date=datetime(2024, 6, 1, tzinfo=UTC),
            trading_days=150,
        )
        d = m.to_dict()
        assert d["total_return"] == 0.05
        assert "start_date" in d

    def test_engine_init(self):
        from backtesting.engine import BacktestEngine
        e = BacktestEngine(initial_capital=50_000.0)
        assert e.initial_capital == 50_000.0

    def test_engine_set_strategy(self):
        from backtesting.engine import BacktestEngine
        e = BacktestEngine()
        e.set_strategy(lambda **kw: None, ["XAUUSD"])
        assert e.strategy is not None

    def test_engine_run_no_strategy_raises(self):
        from backtesting.engine import BacktestEngine
        e = BacktestEngine()
        e.set_data_handler(MagicMock())
        with pytest.raises(ValueError, match="Strategy not set"):
            e.run(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC))

    def test_engine_run_no_handler_raises(self):
        from backtesting.engine import BacktestEngine
        e = BacktestEngine()
        e.set_strategy(lambda **kw: None, ["XAUUSD"])
        with pytest.raises(ValueError, match="Data handler not set"):
            e.run(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC))


# ===========================================================================
# analytics/risk.py
# ===========================================================================

class TestRiskAnalyzer:
    def _returns(self):
        rng = np.random.default_rng(0)
        return list(rng.normal(-0.001, 0.02, 200))

    def test_var_historical(self):
        from analytics.risk import RiskAnalyzer
        var = RiskAnalyzer().calculate_var(self._returns(), method="historical")
        assert isinstance(var, float)

    def test_var_parametric(self):
        from analytics.risk import RiskAnalyzer
        var = RiskAnalyzer().calculate_var(self._returns(), method="parametric")
        assert isinstance(var, float)

    def test_var_99_more_extreme(self):
        from analytics.risk import RiskAnalyzer
        r = RiskAnalyzer()
        rets = self._returns()
        assert r.calculate_var(rets, 0.99, "parametric") <= r.calculate_var(rets, 0.95, "parametric")

    def test_cvar_lte_var(self):
        from analytics.risk import RiskAnalyzer
        r = RiskAnalyzer()
        rets = self._returns()
        assert r.calculate_cvar(rets) <= r.calculate_var(rets)

    def test_cvar_empty_tail(self):
        from analytics.risk import RiskAnalyzer
        cvar = RiskAnalyzer().calculate_cvar([0.01] * 100, 0.95)
        assert isinstance(cvar, float)

    def test_risk_attribution_keys(self):
        from analytics.risk import RiskAnalyzer
        weights = np.array([0.5, 0.5])
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        result = RiskAnalyzer().risk_attribution(weights, cov)
        assert "total_risk" in result and "marginal_risk" in result

    def test_risk_attribution_positive(self):
        from analytics.risk import RiskAnalyzer
        weights = np.array([0.4, 0.6])
        cov = np.array([[0.04, 0.01], [0.01, 0.09]])
        assert RiskAnalyzer().risk_attribution(weights, cov)["total_risk"] > 0


# ===========================================================================
# analytics/options.py
# ===========================================================================

class TestOptionsAnalyzer:
    def test_call_price_positive(self):
        from analytics.options import OptionsAnalyzer
        assert OptionsAnalyzer().price_option("call", 2000.0, 2000.0, 0.25, 0.2) > 0

    def test_put_price_positive(self):
        from analytics.options import OptionsAnalyzer
        assert OptionsAnalyzer().price_option("put", 2000.0, 2000.0, 0.25, 0.2) > 0

    def test_call_put_parity(self):
        import math
        from analytics.options import OptionsAnalyzer
        o = OptionsAnalyzer()
        S, K, T, v, r = 2000.0, 2000.0, 0.25, 0.2, 0.05
        call = o.price_option("call", S, K, T, v, r)
        put = o.price_option("put", S, K, T, v, r)
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 1.0

    def test_greeks_keys(self):
        from analytics.options import OptionsAnalyzer
        g = OptionsAnalyzer().calculate_greeks("call", 2000.0, 2000.0, 0.25, 0.2)
        for k in ("delta", "gamma", "theta", "vega", "rho"):
            assert k in g

    def test_norm_cdf_midpoint(self):
        from analytics.options import OptionsAnalyzer
        assert OptionsAnalyzer()._norm_cdf(0.0) == pytest.approx(0.5, abs=1e-6)

    def test_norm_cdf_large(self):
        from analytics.options import OptionsAnalyzer
        assert OptionsAnalyzer()._norm_cdf(10.0) > 0.999


# ===========================================================================
# analytics/simulations.py
# ===========================================================================

class TestSimulationEngine:
    def _pnls(self, n=60):
        return list(np.random.default_rng(1).normal(100, 300, n))

    def test_monte_carlo_returns_dict(self):
        from analytics.simulations import SimulationEngine
        result = SimulationEngine().monte_carlo_simulation(self._pnls(), n_paths=200)
        assert isinstance(result, dict)

    def test_monte_carlo_legacy_keys(self):
        from analytics.simulations import SimulationEngine
        result = SimulationEngine().monte_carlo_simulation(self._pnls(), n_paths=200)
        for k in ("mean_return", "max_drawdown", "var_95"):
            assert k in result

    def test_monte_carlo_block(self):
        from analytics.simulations import SimulationEngine
        result = SimulationEngine().monte_carlo_simulation(self._pnls(), n_paths=200, method="block")
        assert isinstance(result, dict)

    def test_genetic_algorithm(self):
        from analytics.simulations import SimulationEngine
        result = SimulationEngine().genetic_algorithm_optimization(
            {"fast": 10, "slow": 50},
            fitness_function=lambda p: -(p["fast"] - 10) ** 2,
            population_size=10, generations=5,
        )
        assert "best_parameters" in result and "fitness_score" in result


# ===========================================================================
# backtesting/data_handler.py
# ===========================================================================

class TestDataHandler:
    def _source(self, df=None):
        src = MagicMock()
        if df is None:
            idx = pd.date_range("2024-01-01", periods=10, freq="D")
            df = pd.DataFrame({
                "open": [2000.0] * 10, "high": [2010.0] * 10,
                "low": [1990.0] * 10, "close": [2005.0] * 10, "volume": [1000.0] * 10,
            }, index=idx)
        src.get_data.return_value = df
        return src

    def test_load_data_populates(self):
        from backtesting.data_handler import DataHandler
        dh = DataHandler(self._source(), ["XAUUSD"], "2024-01-01", "2024-01-10")
        dh.load_data()
        assert "XAUUSD" in dh.data

    def test_load_data_empty_raises(self):
        from backtesting.data_handler import DataHandler
        src = MagicMock()
        src.get_data.return_value = pd.DataFrame()
        dh = DataHandler(src, ["XAUUSD"], "2024-01-01", "2024-01-10")
        with pytest.raises(ValueError, match="No data loaded"):
            dh.load_data()

    def test_load_data_none_raises(self):
        from backtesting.data_handler import DataHandler
        src = MagicMock()
        src.get_data.return_value = None
        dh = DataHandler(src, ["XAUUSD"], "2024-01-01", "2024-01-10")
        with pytest.raises(ValueError, match="No data loaded"):
            dh.load_data()

    def test_get_latest_bar(self):
        from backtesting.data_handler import DataHandler
        dh = DataHandler(self._source(), ["XAUUSD"], "2024-01-01", "2024-01-10")
        dh.load_data()
        dh.update_bars()  # advance past index 0
        assert dh.get_latest_bar("XAUUSD") is not None

    def test_get_latest_bars(self):
        from backtesting.data_handler import DataHandler
        dh = DataHandler(self._source(), ["XAUUSD"], "2024-01-01", "2024-01-10")
        dh.load_data()
        for _ in range(3):
            dh.update_bars()
        assert dh.get_latest_bars("XAUUSD", n=3) is not None

    def test_get_latest_bar_unknown(self):
        from backtesting.data_handler import DataHandler
        dh = DataHandler(self._source(), ["XAUUSD"], "2024-01-01", "2024-01-10")
        dh.load_data()
        assert dh.get_latest_bar("UNKNOWN") is None

    def test_update_bars_advances(self):
        from backtesting.data_handler import DataHandler
        dh = DataHandler(self._source(), ["XAUUSD"], "2024-01-01", "2024-01-10")
        dh.load_data()
        before = dh.current_index
        dh.update_bars()
        assert dh.current_index == before + 1

    def test_reset(self):
        from backtesting.data_handler import DataHandler
        dh = DataHandler(self._source(), ["XAUUSD"], "2024-01-01", "2024-01-10")
        dh.load_data()
        dh.update_bars()
        dh.reset()
        assert dh.current_index == 0

    def test_missing_columns_raises(self):
        from backtesting.data_handler import DataHandler
        src = MagicMock()
        src.get_data.return_value = pd.DataFrame({"close": [2000.0] * 5})
        dh = DataHandler(src, ["XAUUSD"], "2024-01-01", "2024-01-10")
        with pytest.raises(ValueError, match="No data loaded"):
            dh.load_data()
