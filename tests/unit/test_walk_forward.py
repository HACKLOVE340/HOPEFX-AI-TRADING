# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_walk_forward.py

Unit tests for backtesting/walk_forward.py.

Covers:
  1.  _trade_level_sharpe: correct formula for mixed trades
  2.  _trade_level_sharpe: returns 0.0 for < 2 trades
  3.  _trade_level_sharpe: returns 0.0 when std < epsilon
  4.  _trade_level_sharpe: annualisation scales with avg_hold_days
  5.  WalkForwardEngine: produces correct number of windows
  6.  WalkForwardEngine: purge/embargo gap is respected
  7.  WalkForwardEngine: Sharpe values are finite floats
  8.  WalkForwardEngine: open positions force-closed at last bar
  9.  WalkForwardEngine: get_aggregate_stats returns expected keys
  10. WalkForwardEngine: overfit detection triggers on Sharpe degradation
"""

import math

import numpy as np
import pandas as pd

from backtesting.walk_forward import WalkForwardEngine, _trade_level_sharpe


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 1800.0 + np.cumsum(rng.normal(0, 5, n))
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": price,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price,
            "volume": 1000,
        },
        index=dates,
    )


class _BuyOnceStrategy:
    """Emits a single BUY on bar 0, never sells — tests force-close logic."""

    def __init__(self):
        self._bar = 0

    def on_tick(self, row):
        self._bar += 1
        if self._bar == 1:
            return {"action": "BUY"}
        return None


class _AlternateBuySellStrategy:
    """Alternates BUY / SELL every bar."""

    def __init__(self):
        self._bar = 0

    def on_tick(self, row):
        self._bar += 1
        return {"action": "BUY" if self._bar % 2 == 1 else "SELL"}


class _NeverTradeStrategy:
    def on_tick(self, row):
        return None


# ── _trade_level_sharpe ───────────────────────────────────────────────────────


class TestTradeLevelSharpe:
    def test_correct_formula(self):
        pnls = [0.02, -0.01, 0.03, -0.005, 0.015]
        trades = [{"pnl_pct": p, "hold_bars": 5, "win": p > 0} for p in pnls]
        sharpe = _trade_level_sharpe(trades, bars_per_day=1)
        arr = np.array(pnls)
        expected = float(np.mean(arr) / np.std(arr, ddof=1) * math.sqrt(252 / 5))
        assert abs(sharpe - expected) < 1e-9

    def test_fewer_than_two_trades_returns_zero(self):
        assert _trade_level_sharpe([]) == 0.0
        assert _trade_level_sharpe([{"pnl_pct": 0.01, "hold_bars": 1, "win": True}]) == 0.0

    def test_zero_std_returns_zero(self):
        # All identical returns -> std ~ 0 -> should return 0.0, not inf
        trades = [{"pnl_pct": 0.01, "hold_bars": 5, "win": True}] * 20
        assert _trade_level_sharpe(trades) == 0.0

    def test_annualisation_scales_with_hold_period(self):
        # Longer hold period -> smaller annualisation factor -> smaller Sharpe
        pnls = [0.02, -0.01, 0.03, -0.005, 0.015]
        trades_short = [{"pnl_pct": p, "hold_bars": 1, "win": p > 0} for p in pnls]
        trades_long = [{"pnl_pct": p, "hold_bars": 20, "win": p > 0} for p in pnls]
        sharpe_short = _trade_level_sharpe(trades_short, bars_per_day=1)
        sharpe_long = _trade_level_sharpe(trades_long, bars_per_day=1)
        assert sharpe_short > sharpe_long

    def test_h1_bars_per_day_24(self):
        # With bars_per_day=24, hold_bars=24 means 1 day avg hold
        pnls = [0.02, -0.01, 0.03, -0.005, 0.015]
        trades = [{"pnl_pct": p, "hold_bars": 24, "win": p > 0} for p in pnls]
        sharpe = _trade_level_sharpe(trades, bars_per_day=24)
        arr = np.array(pnls)
        # avg_hold_days = 24/24 = 1 day
        expected = float(np.mean(arr) / np.std(arr, ddof=1) * math.sqrt(252))
        assert abs(sharpe - expected) < 1e-9


# ── WalkForwardEngine ─────────────────────────────────────────────────────────


class TestWalkForwardEngine:
    def test_window_count(self):
        # n=500, train=100, purge=10, test=50, step=50
        # windows: floor((500 - 100 - 10 - 50) / 50) + 1 = 7
        df = _make_ohlcv(500)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=10, step_size=50)
        results = engine.run(df, lambda: _AlternateBuySellStrategy(), [{}])
        expected = (500 - 100 - 10 - 50) // 50 + 1
        assert len(results) == expected

    def test_purge_gap_respected(self):
        # test_start index must be >= train_end + purge_size
        df = _make_ohlcv(400)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=20, step_size=50)
        results = engine.run(df, lambda: _AlternateBuySellStrategy(), [{}])
        for r in results:
            gap = (r.test_start - r.train_end).days
            assert gap >= 20, f"Purge gap too small: {gap} days"

    def test_sharpe_values_are_finite(self):
        df = _make_ohlcv(400)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=10, step_size=50)
        results = engine.run(df, lambda: _AlternateBuySellStrategy(), [{}])
        for r in results:
            s = r.test_performance["sharpe_ratio"]
            assert math.isfinite(s), f"Sharpe not finite: {s}"

    def test_force_close_open_positions(self):
        # BuyOnceStrategy never sells — position must be force-closed at last bar
        df = _make_ohlcv(300)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=10, step_size=50)
        results = engine.run(df, lambda: _BuyOnceStrategy(), [{}])
        # Should complete without error and return finite Sharpe
        for r in results:
            assert math.isfinite(r.test_performance["sharpe_ratio"])

    def test_no_trades_returns_zero_sharpe(self):
        df = _make_ohlcv(300)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=10, step_size=50)
        results = engine.run(df, lambda: _NeverTradeStrategy(), [{}])
        for r in results:
            assert r.test_performance["sharpe_ratio"] == 0.0
            assert r.test_performance["num_trades"] == 0

    def test_aggregate_stats_keys(self):
        df = _make_ohlcv(400)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=10, step_size=50)
        engine.run(df, lambda: _AlternateBuySellStrategy(), [{}])
        stats = engine.get_aggregate_stats()
        for key in (
            "num_windows",
            "overfit_windows",
            "avg_test_return",
            "avg_test_sharpe",
            "consistency",
            "is_robust",
        ):
            assert key in stats, f"Missing key: {key}"

    def test_aggregate_stats_empty_returns_empty_dict(self):
        engine = WalkForwardEngine()
        assert engine.get_aggregate_stats() == {}

    def test_overfit_detection_triggers(self):
        # Manually inject a result where train Sharpe >> test Sharpe
        engine = WalkForwardEngine()
        is_overfit = engine._detect_overfit(
            train_perf={"sharpe_ratio": 3.0, "total_return": 0.5},
            test_perf={"sharpe_ratio": 0.1, "total_return": 0.05},
        )
        assert is_overfit is True

    def test_overfit_detection_does_not_trigger_on_good_oos(self):
        engine = WalkForwardEngine()
        is_overfit = engine._detect_overfit(
            train_perf={"sharpe_ratio": 1.5, "total_return": 0.3},
            test_perf={"sharpe_ratio": 1.2, "total_return": 0.25},
        )
        assert is_overfit is False

    def test_win_rate_between_zero_and_one(self):
        df = _make_ohlcv(400)
        engine = WalkForwardEngine(train_size=100, test_size=50, purge_size=10, step_size=50)
        results = engine.run(df, lambda: _AlternateBuySellStrategy(), [{}])
        for r in results:
            wr = r.test_performance["win_rate"]
            assert 0.0 <= wr <= 1.0, f"Win rate out of range: {wr}"
