# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for backtesting/enhanced_engine.py

Covers: NanosecondTimestamp, TickData, TransactionCostModel, Position,
        TradeRecord, InstitutionalRiskManager, _compute_drawdown_series,
        _calculate_sortino, _calculate_calmar, EnhancedBacktestEngine,
        generate_test_data.
"""

import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Module-level import fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def eng():
    import backtesting.enhanced_engine as m
    return m


@pytest.fixture(scope="module")
def test_ticks(eng):
    """Small set of synthetic ticks for engine tests."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return eng.generate_test_data(n_ticks=200, symbol="XAUUSD")


# ---------------------------------------------------------------------------
# NanosecondTimestamp
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNanosecondTimestamp:
    def test_now_returns_instance(self, eng):
        ts = eng.NanosecondTimestamp.now()
        assert isinstance(ts, eng.NanosecondTimestamp)
        assert ts.seconds > 0
        assert 0 <= ts.nanoseconds < 1_000_000_000

    def test_from_datetime_roundtrip(self, eng):
        dt = datetime(2024, 6, 15, 12, 30, 45, 123456, tzinfo=UTC)
        ts = eng.NanosecondTimestamp.from_datetime(dt)
        recovered = ts.to_datetime()
        assert recovered.year == 2024
        assert recovered.month == 6
        assert recovered.day == 15

    def test_float_conversion(self, eng):
        ts = eng.NanosecondTimestamp(seconds=1_700_000_000, nanoseconds=500_000_000)
        assert float(ts) == pytest.approx(1_700_000_000.5)

    def test_ordering(self, eng):
        ts1 = eng.NanosecondTimestamp(seconds=100, nanoseconds=0)
        ts2 = eng.NanosecondTimestamp(seconds=100, nanoseconds=500)
        ts3 = eng.NanosecondTimestamp(seconds=101, nanoseconds=0)
        assert ts1 < ts2
        assert ts2 < ts3
        assert not ts3 < ts1

    def test_nanosecond_precision(self, eng):
        """from_datetime uses microsecond*1000 — sub-microsecond digits are zero."""
        dt = datetime(2024, 1, 1, 0, 0, 0, 999999, tzinfo=UTC)
        ts = eng.NanosecondTimestamp.from_datetime(dt)
        assert ts.nanoseconds == 999999 * 1000

    def test_immutable(self, eng):
        ts = eng.NanosecondTimestamp.now()
        with pytest.raises((AttributeError, TypeError)):
            ts.seconds = 0  # frozen dataclass


# ---------------------------------------------------------------------------
# TickData
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTickData:
    def _make_tick(self, eng, bid=1950.0, ask=1950.05):
        ts = eng.NanosecondTimestamp.now()
        return eng.TickData(
            timestamp=ts,
            symbol="XAUUSD",
            bid=bid,
            ask=ask,
            bid_size=10.0,
            ask_size=10.0,
            volume=100.0,
        )

    def test_mid_price(self, eng):
        tick = self._make_tick(eng, bid=1950.0, ask=1950.10)
        assert tick.mid == pytest.approx(1950.05)

    def test_spread(self, eng):
        tick = self._make_tick(eng, bid=1950.0, ask=1950.10)
        assert tick.spread == pytest.approx(0.10)

    def test_spread_bps(self, eng):
        tick = self._make_tick(eng, bid=1950.0, ask=1950.10)
        expected = (0.10 / 1950.05) * 10000
        assert tick.spread_bps == pytest.approx(expected, rel=1e-4)

    def test_imbalance_balanced(self, eng):
        ts = eng.NanosecondTimestamp.now()
        tick = eng.TickData(
            timestamp=ts, symbol="XAUUSD",
            bid=1950.0, ask=1950.05,
            bid_size=10.0, ask_size=10.0,
        )
        assert tick.imbalance == pytest.approx(0.0)

    def test_imbalance_bid_heavy(self, eng):
        ts = eng.NanosecondTimestamp.now()
        tick = eng.TickData(
            timestamp=ts, symbol="XAUUSD",
            bid=1950.0, ask=1950.05,
            bid_size=30.0, ask_size=10.0,
        )
        assert tick.imbalance == pytest.approx(0.5)

    def test_invalid_prices_raise(self, eng):
        ts = eng.NanosecondTimestamp.now()
        with pytest.raises(ValueError):
            eng.TickData(timestamp=ts, symbol="XAUUSD", bid=0.0, ask=1950.05)

    def test_negative_spread_raises(self, eng):
        ts = eng.NanosecondTimestamp.now()
        with pytest.raises(ValueError):
            eng.TickData(timestamp=ts, symbol="XAUUSD", bid=1951.0, ask=1950.0)

    def test_get_price_for_side_buy(self, eng):
        tick = self._make_tick(eng, bid=1950.0, ask=1950.10)
        assert tick.get_price_for_side(eng.OrderSide.BUY) == pytest.approx(1950.10)

    def test_get_price_for_side_sell(self, eng):
        tick = self._make_tick(eng, bid=1950.0, ask=1950.10)
        assert tick.get_price_for_side(eng.OrderSide.SELL) == pytest.approx(1950.0)

    def test_to_dict_keys(self, eng):
        tick = self._make_tick(eng)
        d = tick.to_dict()
        for key in ("timestamp", "symbol", "bid", "ask", "mid", "spread_bps"):
            assert key in d


# ---------------------------------------------------------------------------
# TransactionCostModel
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTransactionCostModel:
    def test_default_init(self, eng):
        model = eng.TransactionCostModel()
        assert model.commission_per_lot > 0
        assert model.overnight_rate_annual > 0

    def test_calibrate_xauusd(self, eng):
        model = eng.TransactionCostModel.calibrate_xauusd()
        assert model.temporary_impact_coefficient == pytest.approx(0.050)
        assert model.permanent_impact_coefficient == pytest.approx(0.100)
        assert model.decay_exponent == pytest.approx(0.55)

    def test_calculate_market_impact_returns_dict(self, eng):
        model = eng.TransactionCostModel()
        result = model.calculate_market_impact(
            order_size=100.0,
            participation_rate=0.05,
            daily_volatility=0.01,
        )
        assert isinstance(result, dict)
        for key in ("temporary_bps", "permanent_bps", "total_bps"):
            assert key in result

    def test_calculate_market_impact_positive_values(self, eng):
        model = eng.TransactionCostModel()
        result = model.calculate_market_impact(
            order_size=100.0,
            participation_rate=0.05,
            daily_volatility=0.01,
        )
        assert result["temporary_bps"] >= 0
        assert result["permanent_bps"] >= 0
        assert result["total_bps"] >= 0

    def test_invalid_participation_rate_raises(self, eng):
        model = eng.TransactionCostModel()
        with pytest.raises(ValueError):
            model.calculate_market_impact(100.0, participation_rate=0.0, daily_volatility=0.01)

    def test_toxic_flow_increases_impact(self, eng):
        model = eng.TransactionCostModel()
        normal = model.calculate_market_impact(100.0, 0.05, 0.01, order_flow_toxicity=0.0)
        toxic = model.calculate_market_impact(100.0, 0.05, 0.01, order_flow_toxicity=0.9)
        assert toxic["temporary_bps"] > normal["temporary_bps"]

    def test_total_cost_structure(self, eng):
        model = eng.TransactionCostModel()
        result = model.total_cost(order_size=100.0, price=1950.0, is_maker=False)
        assert isinstance(result, dict)
        assert "total_cost" in result

    def test_estimate_decay_time_returns_timedelta(self, eng):
        model = eng.TransactionCostModel()
        td = model._estimate_decay_time(0.05)
        assert isinstance(td, timedelta)
        assert td.total_seconds() > 0


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPosition:
    def test_init(self, eng):
        pos = eng.Position(symbol="XAUUSD", side=eng.OrderSide.BUY)
        assert pos.size == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.unrealized_pnl == 0.0

    def test_update_mfe_mae_long(self, eng):
        pos = eng.Position(
            symbol="XAUUSD",
            side=eng.OrderSide.BUY,
            size=10.0,
            avg_entry_price=1950.0,
        )
        ts = eng.NanosecondTimestamp.now()
        # Price moves up — MFE should increase
        pos.update_mfe_mae(1960.0, ts)
        assert pos.max_favorable_excursion == pytest.approx(100.0)
        assert pos.unrealized_pnl == pytest.approx(100.0)

    def test_update_mfe_mae_adverse(self, eng):
        pos = eng.Position(
            symbol="XAUUSD",
            side=eng.OrderSide.BUY,
            size=10.0,
            avg_entry_price=1950.0,
        )
        ts = eng.NanosecondTimestamp.now()
        pos.update_mfe_mae(1940.0, ts)
        assert pos.max_adverse_excursion == pytest.approx(100.0)

    def test_update_mfe_mae_zero_size_noop(self, eng):
        pos = eng.Position(symbol="XAUUSD", side=eng.OrderSide.BUY, size=0.0)
        ts = eng.NanosecondTimestamp.now()
        pos.update_mfe_mae(2000.0, ts)
        assert pos.max_favorable_excursion == 0.0

    def test_add_trade_opening(self, eng):
        pos = eng.Position(symbol="XAUUSD", side=eng.OrderSide.BUY)
        ts = eng.NanosecondTimestamp.now()
        pos.add_trade(10.0, 1950.0, commission=5.0, slippage=1.0, timestamp=ts, is_opening=True)
        assert len(pos.opening_trades) == 1
        assert pos.opening_trades[0]["price"] == 1950.0

    def test_add_trade_closing_updates_realized_pnl(self, eng):
        pos = eng.Position(
            symbol="XAUUSD",
            side=eng.OrderSide.BUY,
            size=10.0,
            avg_entry_price=1950.0,
        )
        ts = eng.NanosecondTimestamp.now()
        pos.add_trade(10.0, 1960.0, commission=5.0, slippage=1.0, timestamp=ts, is_opening=False)
        # PnL = (1960-1950)*10 - 5 - 1 = 100 - 6 = 94
        assert pos.realized_pnl == pytest.approx(94.0)

    def test_get_performance_metrics_empty(self, eng):
        pos = eng.Position(symbol="XAUUSD", side=eng.OrderSide.BUY)
        assert pos.get_performance_metrics() == {}

    def test_get_performance_metrics_after_trade(self, eng):
        pos = eng.Position(
            symbol="XAUUSD",
            side=eng.OrderSide.BUY,
            size=10.0,
            avg_entry_price=1950.0,
        )
        ts = eng.NanosecondTimestamp.now()
        pos.add_trade(10.0, 1950.0, 5.0, 1.0, ts, is_opening=True)
        metrics = pos.get_performance_metrics()
        assert "realized_pnl" in metrics
        assert "total_pnl" in metrics


# ---------------------------------------------------------------------------
# Standalone analytics functions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAnalyticsFunctions:
    def test_compute_drawdown_no_drawdown(self, eng):
        ts = eng.NanosecondTimestamp.now()
        curve = [(ts, 100_000 + i * 1000) for i in range(10)]
        max_dd, periods = eng._compute_drawdown_series(curve, 100_000)
        assert max_dd == pytest.approx(0.0)
        assert periods == []

    def test_compute_drawdown_simple(self, eng):
        ts_base = eng.NanosecondTimestamp(seconds=1_700_000_000, nanoseconds=0)
        curve = [
            (eng.NanosecondTimestamp(seconds=1_700_000_000 + i, nanoseconds=0), eq)
            for i, eq in enumerate([100_000, 110_000, 90_000, 95_000, 105_000])
        ]
        max_dd, _ = eng._compute_drawdown_series(curve, 100_000)
        # Peak is 110_000, trough is 90_000 → dd = 20_000/110_000
        assert max_dd == pytest.approx(20_000 / 110_000, rel=1e-4)

    def test_calculate_sortino_all_positive(self, eng):
        returns = np.array([0.01, 0.02, 0.015, 0.03])
        result = eng._calculate_sortino(returns, target=0.0)
        # No downside returns → ratio is 0
        assert result == 0.0

    def test_calculate_sortino_mixed(self, eng):
        returns = np.array([0.02, -0.01, 0.03, -0.005, 0.01])
        result = eng._calculate_sortino(returns, target=0.0)
        assert isinstance(result, float)

    def test_calculate_calmar_zero_drawdown(self, eng):
        returns = np.array([0.01, 0.02])
        assert eng._calculate_calmar(returns, max_dd=0.0) == 0.0

    def test_calculate_calmar_positive(self, eng):
        returns = np.array([0.001] * 252)  # ~25% annual
        result = eng._calculate_calmar(returns, max_dd=0.10)
        assert result > 0


# ---------------------------------------------------------------------------
# InstitutionalRiskManager
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInstitutionalRiskManager:
    def test_init(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=100_000)
        assert rm.current_capital == 100_000
        assert rm.kill_switch_active is False
        assert rm.circuit_breaker_level == 0

    def test_pre_trade_allows_small_order(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=1_000_000)
        allowed, reason, _ = rm.check_pre_trade_risk(
            "XAUUSD", eng.OrderSide.BUY, size=1.0, price=1950.0, portfolio_state={}
        )
        assert allowed is True
        assert reason == "OK"

    def test_pre_trade_blocks_kill_switch(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=1_000_000)
        rm.kill_switch_active = True
        allowed, reason, _ = rm.check_pre_trade_risk(
            "XAUUSD", eng.OrderSide.BUY, size=1.0, price=1950.0, portfolio_state={}
        )
        assert allowed is False
        assert "KILL_SWITCH" in reason

    def test_pre_trade_blocks_circuit_breaker(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=1_000_000)
        rm.circuit_breaker_level = 2
        allowed, reason, _ = rm.check_pre_trade_risk(
            "XAUUSD", eng.OrderSide.BUY, size=1.0, price=1950.0, portfolio_state={}
        )
        assert allowed is False
        assert "CIRCUIT_BREAKER" in reason

    def test_pre_trade_blocks_oversized_order(self, eng):
        rm = eng.InstitutionalRiskManager(
            initial_capital=100_000,
            max_position_pct=0.05,
        )
        # 100 lots at $1950 = $195,000 notional > 5% of $100k = $5,000
        allowed, reason, _ = rm.check_pre_trade_risk(
            "XAUUSD", eng.OrderSide.BUY, size=100.0, price=1950.0, portfolio_state={}
        )
        assert allowed is False

    def test_update_capital(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=100_000)
        ts = eng.NanosecondTimestamp.now()
        rm.update_capital(5000.0, ts)
        assert rm.current_capital == pytest.approx(105_000)
        assert rm.daily_pnl == pytest.approx(5000.0)

    def test_calculate_var_no_history_returns_parametric_fallback(self, eng):
        """With < 30 returns, VaR falls back to 2% of capital."""
        rm = eng.InstitutionalRiskManager(initial_capital=100_000)
        var = rm.calculate_var(confidence=0.95)
        # Parametric fallback: 2% of 100_000 = 2000
        assert var == pytest.approx(2000.0)

    def test_calculate_var_with_history(self, eng):
        """VaR is expressed as a signed dollar amount (negative = loss)."""
        rm = eng.InstitutionalRiskManager(initial_capital=100_000)
        rng = np.random.default_rng(42)
        for r in rng.normal(0.001, 0.01, 100):
            rm.returns_history.append(r)
        var = rm.calculate_var(confidence=0.95)
        # VaR is a dollar amount; just verify it's a finite number
        assert isinstance(float(var), float)
        assert abs(var) < rm.current_capital  # sanity: can't lose more than capital

    def test_register_emergency_callback(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=100_000)
        called = []
        rm.register_emergency_callback(lambda reason: called.append(reason))
        assert len(rm.emergency_callbacks) == 1

    def test_intraday_risk_ok(self, eng):
        rm = eng.InstitutionalRiskManager(initial_capital=100_000)
        ts = eng.NanosecondTimestamp.now()
        ok, reason = rm.check_intraday_risk(ts)
        assert ok is True
        assert reason == "OK"


# ---------------------------------------------------------------------------
# generate_test_data
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGenerateTestData:
    def test_raises_in_production(self, eng, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(RuntimeError, match="production"):
            eng.generate_test_data(n_ticks=10)

    def test_returns_list_in_dev(self, eng, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            ticks = eng.generate_test_data(n_ticks=50)
        assert isinstance(ticks, list)
        assert len(ticks) == 50

    def test_all_ticks_are_tickdata(self, eng, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            ticks = eng.generate_test_data(n_ticks=20)
        assert all(isinstance(t, eng.TickData) for t in ticks)

    def test_ticks_have_positive_prices(self, eng, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            ticks = eng.generate_test_data(n_ticks=50)
        assert all(t.bid > 0 and t.ask > 0 for t in ticks)

    def test_ticks_ordered_by_time(self, eng, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            ticks = eng.generate_test_data(n_ticks=50)
        for i in range(1, len(ticks)):
            assert ticks[i - 1].timestamp < ticks[i].timestamp


# ---------------------------------------------------------------------------
# EnhancedBacktestEngine
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEnhancedBacktestEngine:
    def test_init_defaults(self, eng):
        engine = eng.EnhancedBacktestEngine()
        assert engine.initial_capital == 1_000_000.0
        assert engine.capital == 1_000_000.0
        assert engine.positions == {}
        assert engine.closed_trades == []

    def test_init_custom_capital(self, eng):
        engine = eng.EnhancedBacktestEngine(initial_capital=500_000.0)
        assert engine.initial_capital == 500_000.0
        assert engine.capital == 500_000.0

    def test_process_tick_updates_price_history(self, eng, test_ticks):
        engine = eng.EnhancedBacktestEngine(initial_capital=1_000_000.0)
        tick = test_ticks[0]
        engine.process_tick(tick)
        assert tick.symbol in engine.price_history
        assert len(engine.price_history[tick.symbol]) > 0

    def test_process_tick_updates_equity_curve(self, eng, test_ticks):
        engine = eng.EnhancedBacktestEngine(initial_capital=1_000_000.0)
        for tick in test_ticks[:5]:
            engine.process_tick(tick)
        assert len(engine.equity_curve) > 0

    def test_submit_order_no_price_data_fails(self, eng):
        engine = eng.EnhancedBacktestEngine(initial_capital=1_000_000.0)
        ok, reason, order_id = engine.submit_order(
            "XAUUSD", eng.OrderSide.BUY, size=1.0
        )
        assert ok is False
        assert reason == "NO_PRICE_DATA"
        assert order_id is None

    def test_submit_order_after_tick_succeeds(self, eng, test_ticks):
        engine = eng.EnhancedBacktestEngine(initial_capital=1_000_000.0)
        engine.process_tick(test_ticks[0])
        ok, reason, order_id = engine.submit_order(
            "XAUUSD", eng.OrderSide.BUY, size=0.1
        )
        assert ok is True
        assert reason == "OK"
        assert order_id is not None

    def test_submit_order_blocked_by_kill_switch(self, eng, test_ticks):
        engine = eng.EnhancedBacktestEngine(initial_capital=1_000_000.0)
        engine.process_tick(test_ticks[0])
        engine.risk_manager.kill_switch_active = True
        ok, reason, _ = engine.submit_order("XAUUSD", eng.OrderSide.BUY, size=0.1)
        assert ok is False
        assert "KILL_SWITCH" in reason

    def test_process_multiple_ticks(self, eng, test_ticks):
        engine = eng.EnhancedBacktestEngine(initial_capital=1_000_000.0)
        for tick in test_ticks[:50]:
            engine.process_tick(tick)
        assert len(engine.equity_curve) == 50

    def test_execution_quality_latency_model(self, eng):
        hft = eng.EnhancedBacktestEngine(
            execution_quality=eng.ExecutionQuality.HFT_COLOCATED
        )
        retail = eng.EnhancedBacktestEngine(
            execution_quality=eng.ExecutionQuality.RETAIL
        )
        assert hft.latency_model["mean"] < retail.latency_model["mean"]
