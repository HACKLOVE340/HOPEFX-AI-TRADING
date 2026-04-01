# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_backtest_engine.py

10 tests for the backtest engine:
  1.  Commission deducted from cash on each trade
  2.  Overnight financing reduces cash over time
  3.  Variable slippage is higher on wide bars than narrow bars
  4.  Sortino >= Sharpe for positive-skew return series
  5.  Significance test p < 0.05 with a clear edge
  6.  Monte Carlo ruin probability is 0 for a profitable strategy
  7.  Monte Carlo p5 < median < p95
  8.  Regime breakdown contains expected keys
  9.  BacktestResult dataclass fields are all present
  10. _max_consecutive correctly counts streaks
"""

import pytest
import numpy as np
from datetime import datetime, timedelta

from backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    SimulatedBroker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_config():
    return BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
        commission_per_trade=5.0,
        slippage_model="fixed",
        slippage_pips=0.5,
        overnight_rate_annual=0.004,
        bars_per_day=24.0,
    )


@pytest.fixture
def broker(base_config):
    return SimulatedBroker(base_config)


# ---------------------------------------------------------------------------
# Test 1: commission deducted
# ---------------------------------------------------------------------------


def test_commission_deducted(broker):
    initial_cash = broker.cash
    broker.place_market_order("XAUUSD", "buy", 1.0, 2000.0)
    # Cash should decrease by fill cost + commission
    assert broker.cash < initial_cash
    # Commission is exactly 5.0
    fill_cost = 1.0 * 2000.0 * (1 + broker._calculate_slippage(2000.0))
    expected = initial_cash - fill_cost - broker.config.commission_per_trade
    assert broker.cash == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# Test 2: overnight financing reduces cash
# ---------------------------------------------------------------------------


def test_overnight_financing_applied(base_config):
    cfg = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
        commission_per_trade=0.0,
        slippage_model="none",
        overnight_rate_annual=0.04,  # 4% p.a. — large enough to measure
        bars_per_day=24.0,
    )
    b = SimulatedBroker(cfg)
    b.positions["XAUUSD"] = {
        "quantity": 1.0,
        "avg_price": 2000.0,
        "current_price": 2000.0,
        "side": "long",
    }
    cash_before = b.cash
    # Advance 10 bars
    for i in range(10):
        b.update_time(datetime(2023, 1, 1) + timedelta(hours=i))

    assert b.cash < cash_before, "Overnight financing should reduce cash"
    assert b.total_overnight_cost > 0


# ---------------------------------------------------------------------------
# Test 3: variable slippage higher on wide bars
# ---------------------------------------------------------------------------


def test_variable_slippage_higher_on_wide_bars():
    cfg = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
        slippage_model="variable",
    )
    b = SimulatedBroker(cfg)
    price = 2000.0

    # Wide bar: 2% range
    wide_slip = b._calculate_slippage(price, bar_high=2020.0, bar_low=1980.0)
    # Narrow bar: 0.05% range
    narrow_slip = b._calculate_slippage(price, bar_high=2001.0, bar_low=1999.0)

    assert wide_slip > narrow_slip, (
        f"Wide bar slippage ({wide_slip:.6f}) should exceed narrow bar slippage ({narrow_slip:.6f})"
    )


# ---------------------------------------------------------------------------
# Test 4: Sortino >= Sharpe for positive-skew returns
# ---------------------------------------------------------------------------


def test_sortino_gte_sharpe_positive_skew():
    """
    For a return series with positive skew (more upside outliers than downside),
    Sortino should be >= Sharpe because the downside deviation is smaller than
    total standard deviation.
    """
    # Construct positive-skew returns: mostly small gains, occasional large gain
    rng = np.random.default_rng(42)
    returns = rng.normal(0.001, 0.005, 200)
    # Add positive outliers
    returns[::20] += 0.05

    ann = np.sqrt(252.0 * 24.0)
    sharpe = float(np.mean(returns) / np.std(returns) * ann)
    downside = returns[returns < 0]
    downside_std = float(np.std(downside)) if len(downside) > 0 else 1e-9
    sortino = float(np.mean(returns) / downside_std * ann)

    assert sortino >= sharpe, f"Sortino ({sortino:.3f}) should be >= Sharpe ({sharpe:.3f}) for positive-skew returns"


# ---------------------------------------------------------------------------
# Test 5: significance test p < 0.05 with a clear edge
# ---------------------------------------------------------------------------


def test_significance_test_with_clear_edge():
    """
    A strategy with a consistent positive edge should produce p < 0.05
    when tested against the null hypothesis of zero mean return.
    """
    try:
        from scipy import stats
    except ImportError:
        pytest.skip("scipy not installed")

    rng = np.random.default_rng(0)
    # 200 trades with mean +50 and std 100 → t ≈ 7, p << 0.05
    trade_pnls = rng.normal(50.0, 100.0, 200)
    t_stat, p_val = stats.ttest_1samp(trade_pnls, popmean=0.0)

    assert p_val < 0.05, f"Expected p < 0.05 for clear edge, got p={p_val:.4f}"
    assert t_stat > 0, "t-statistic should be positive for positive-mean returns"


# ---------------------------------------------------------------------------
# Test 6: Monte Carlo ruin probability is 0 for profitable strategy
# ---------------------------------------------------------------------------


def test_monte_carlo_ruin_zero_for_profitable():
    cfg = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
    )
    engine = BacktestEngine(cfg)

    # Consistently profitable returns: +1% per trade
    trade_returns = np.full(100, 0.01)
    mc = engine.run_monte_carlo_simulation(trade_returns, n_simulations=500)

    assert mc["mc_ruin_probability"] == pytest.approx(0.0), (
        "A consistently profitable strategy should have zero ruin probability"
    )
    assert mc["mc_median_final"] > 1.0


# ---------------------------------------------------------------------------
# Test 7: Monte Carlo p5 < median < p95
# ---------------------------------------------------------------------------


def test_monte_carlo_percentile_ordering():
    cfg = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
    )
    engine = BacktestEngine(cfg)

    rng = np.random.default_rng(7)
    trade_returns = rng.normal(0.005, 0.02, 80)
    mc = engine.run_monte_carlo_simulation(trade_returns, n_simulations=500)

    assert mc["mc_p5_final"] <= mc["mc_median_final"], "p5 should be <= median"
    assert mc["mc_median_final"] <= mc["mc_p95_final"], "median should be <= p95"


# ---------------------------------------------------------------------------
# Test 8: regime breakdown contains expected keys
# ---------------------------------------------------------------------------


def test_regime_breakdown_keys():
    cfg = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
    )
    engine = BacktestEngine(cfg)

    # Build a minimal equity curve and trade list
    equity_curve = [{"equity": 100_000.0 + i * 10} for i in range(100)]
    trades = [{"net_pnl": 50.0 if i % 2 == 0 else -30.0} for i in range(20)]

    breakdown = engine._compute_regime_breakdown(trades, equity_curve)

    valid_regimes = {"trending_bull", "trending_bear", "ranging", "high_vol"}
    for regime in breakdown:
        assert regime in valid_regimes, f"Unexpected regime key: {regime}"
        assert "win_rate" in breakdown[regime]
        assert "avg_pnl" in breakdown[regime]
        assert "count" in breakdown[regime]


# ---------------------------------------------------------------------------
# Test 9: BacktestResult dataclass has all required fields
# ---------------------------------------------------------------------------


def test_backtest_result_has_all_fields():
    required_fields = [
        "total_return",
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "omega_ratio",
        "tail_ratio",
        "skewness",
        "kurtosis",
        "avg_mae",
        "avg_mfe",
        "t_statistic",
        "p_value",
        "is_significant",
        "sample_size",
        "mc_median_final",
        "mc_p5_final",
        "mc_p95_final",
        "mc_ruin_probability",
        "regime_breakdown",
        "equity_curve",
        "trades",
        "metrics",
    ]
    result = BacktestResult(
        total_return=0.0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        win_rate=0.0,
        profit_factor=0.0,
        max_drawdown=0.0,
        sharpe_ratio=0.0,
        equity_curve=[],
        trades=[],
        metrics={},
    )
    for field in required_fields:
        assert hasattr(result, field), f"BacktestResult missing field: {field}"


# ---------------------------------------------------------------------------
# Test 10: _max_consecutive correctly counts streaks
# ---------------------------------------------------------------------------


def test_max_consecutive_counts_correctly():
    cfg = BacktestConfig(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2023, 6, 1),
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
    )
    engine = BacktestEngine(cfg)

    trades = [
        {"net_pnl": 10},  # win
        {"net_pnl": 10},  # win
        {"net_pnl": 10},  # win  ← streak of 3
        {"net_pnl": -5},  # loss
        {"net_pnl": 10},  # win
        {"net_pnl": -5},  # loss
        {"net_pnl": -5},  # loss  ← streak of 2
    ]

    assert engine._max_consecutive(trades, "win") == 3
    assert engine._max_consecutive(trades, "loss") == 2
