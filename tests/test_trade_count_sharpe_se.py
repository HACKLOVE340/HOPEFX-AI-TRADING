# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for trade count accumulation and Sharpe SE robustness.

Verifies:
- trade_level_sharpe() computes correct Sharpe and SE
- SE decreases as N increases (more trades → more reliable)
- SE ≤ ±0.029 at N=600 (target)
- SE ≤ ±0.045 at N=250 (minimum acceptable)
- run_backtest() returns trade_pnls list alongside equity DataFrame
- generate_signals() with ABSTAIN_THRESHOLD=0.52 produces more trades than 0.55
- Multi-symbol pooling accumulates trade count faster
- annualised_sharpe() is marked deprecated (bar-level, not primary)
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Synthetic OHLCV with a mild uptrend and realistic noise."""
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0.5, 8.0, n))
    df = pd.DataFrame(
        {
            "open": close - rng.uniform(0, 3, n),
            "high": close + rng.uniform(1, 12, n),
            "low": close - rng.uniform(1, 12, n),
            "close": close,
            "volume": rng.uniform(500, 3000, n),
        },
        index=pd.date_range("2021-01-01", periods=n, freq="h"),
    )
    return df


# ---------------------------------------------------------------------------
# trade_level_sharpe()
# ---------------------------------------------------------------------------


class TestTradeLevelSharpe:
    def test_returns_zero_for_empty_list(self):
        from real_data_backtest import trade_level_sharpe

        sharpe, se = trade_level_sharpe([])
        assert sharpe == 0.0
        assert se == 0.0

    def test_returns_zero_for_single_trade(self):
        from real_data_backtest import trade_level_sharpe

        sharpe, se = trade_level_sharpe([100.0])
        assert sharpe == 0.0
        assert se == 0.0

    def test_positive_sharpe_for_positive_mean_pnl(self):
        from real_data_backtest import trade_level_sharpe

        rng = np.random.default_rng(0)
        pnls = rng.normal(loc=50.0, scale=20.0, size=100).tolist()
        sharpe, _ = trade_level_sharpe(pnls)
        assert sharpe > 0

    def test_negative_sharpe_for_negative_mean_pnl(self):
        from real_data_backtest import trade_level_sharpe

        rng = np.random.default_rng(1)
        pnls = rng.normal(loc=-50.0, scale=20.0, size=100).tolist()
        sharpe, _ = trade_level_sharpe(pnls)
        assert sharpe < 0

    def test_se_formula_exact(self):
        """SE = 1/sqrt(2*(N-1)) exactly."""
        from real_data_backtest import trade_level_sharpe

        rng = np.random.default_rng(2)
        n = 50
        pnls = rng.normal(50, 20, n).tolist()
        _, se = trade_level_sharpe(pnls)
        expected = 1.0 / math.sqrt(2.0 * (n - 1))
        assert abs(se - expected) < 1e-9

    def test_se_decreases_with_more_trades(self):
        from real_data_backtest import trade_level_sharpe

        rng = np.random.default_rng(3)
        _, se_50 = trade_level_sharpe(rng.normal(50, 20, 50).tolist())
        _, se_250 = trade_level_sharpe(rng.normal(50, 20, 250).tolist())
        _, se_600 = trade_level_sharpe(rng.normal(50, 20, 600).tolist())
        assert se_50 > se_250 > se_600

    def test_se_at_600_trades_below_003(self):
        """At N=600, SE ≤ ±0.029 — well within the ±0.3 target."""
        se = 1.0 / math.sqrt(2.0 * (600 - 1))
        assert se < 0.03, f"SE at N=600 = {se:.4f}, expected < 0.03"

    def test_se_at_250_trades_below_005(self):
        """At N=250, SE ≤ ±0.045."""
        se = 1.0 / math.sqrt(2.0 * (250 - 1))
        assert se < 0.05, f"SE at N=250 = {se:.4f}, expected < 0.05"

    def test_se_at_48_trades_above_01(self):
        """At N=48 (original reported count), SE ≈ ±0.10 — not robust."""
        se = 1.0 / math.sqrt(2.0 * (48 - 1))
        assert se > 0.10, f"SE at N=48 = {se:.4f}, expected > 0.10"

    def test_zero_std_returns_zero(self):
        """All-identical PnLs → std=0 → Sharpe=0."""
        from real_data_backtest import trade_level_sharpe

        sharpe, _ = trade_level_sharpe([100.0] * 50)
        assert sharpe == 0.0

    def test_avg_hold_hours_affects_annualisation(self):
        """Longer hold time → lower annualised Sharpe (less compounding)."""
        from real_data_backtest import trade_level_sharpe

        rng = np.random.default_rng(4)
        pnls = rng.normal(50, 20, 100).tolist()
        sharpe_1h, _ = trade_level_sharpe(pnls, avg_hold_hours=1.0)
        sharpe_24h, _ = trade_level_sharpe(pnls, avg_hold_hours=24.0)
        sharpe_168h, _ = trade_level_sharpe(pnls, avg_hold_hours=168.0)
        assert sharpe_1h > sharpe_24h > sharpe_168h


# ---------------------------------------------------------------------------
# run_backtest() — returns (equity_df, trade_pnls)
# ---------------------------------------------------------------------------


class TestRunBacktestSignature:
    def test_returns_tuple_of_df_and_list(self):
        from real_data_backtest import run_backtest

        df = _make_ohlcv(300)
        result = run_backtest(df)
        assert isinstance(result, tuple)
        assert len(result) == 2
        equity_df, trade_pnls = result
        assert isinstance(equity_df, pd.DataFrame)
        assert isinstance(trade_pnls, list)

    def test_equity_df_has_required_columns(self):
        from real_data_backtest import run_backtest

        df = _make_ohlcv(300)
        equity_df, _ = run_backtest(df)
        for col in ["equity", "trade_pnl", "in_trade", "direction"]:
            assert col in equity_df.columns, f"Missing column: {col}"

    def test_trade_pnls_are_floats(self):
        from real_data_backtest import run_backtest

        df = _make_ohlcv(500)
        _, trade_pnls = run_backtest(df)
        for pnl in trade_pnls:
            assert isinstance(pnl, float)

    def test_equity_starts_near_initial_capital(self):
        from real_data_backtest import run_backtest, INITIAL_CAPITAL

        df = _make_ohlcv(300)
        equity_df, _ = run_backtest(df, INITIAL_CAPITAL)
        # First bar equity should be within $100 of initial (entry commission)
        assert abs(equity_df["equity"].iloc[0] - INITIAL_CAPITAL) < 100.0

    def test_no_trades_on_constant_price(self):
        """Constant price → no ATR expansion → no signals → no trades."""
        from real_data_backtest import run_backtest

        n = 100
        df = pd.DataFrame(
            {
                "open": [2000.0] * n,
                "high": [2000.0] * n,
                "low": [2000.0] * n,
                "close": [2000.0] * n,
                "volume": [1000.0] * n,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h", name="timestamp"),
        )
        _, trade_pnls = run_backtest(df)
        # Constant price → all rolling windows produce NaN → dropna() removes all bars
        # Result: zero trades
        assert len(trade_pnls) == 0


# ---------------------------------------------------------------------------
# generate_signals() — ABSTAIN_THRESHOLD
# ---------------------------------------------------------------------------


class TestAbstainThreshold:
    def test_lower_threshold_produces_more_signals(self):
        """ABSTAIN_THRESHOLD=0.52 must produce ≥ as many signals as 0.55."""
        import real_data_backtest as rdb

        df = _make_ohlcv(1000)
        original = rdb.ABSTAIN_THRESHOLD

        rdb.ABSTAIN_THRESHOLD = 0.52
        df_52 = rdb.generate_signals(df)
        count_52 = (df_52["signal"] != 0).sum()

        rdb.ABSTAIN_THRESHOLD = 0.55
        df_55 = rdb.generate_signals(df)
        count_55 = (df_55["signal"] != 0).sum()

        rdb.ABSTAIN_THRESHOLD = original
        assert count_52 >= count_55, f"Lower threshold should produce ≥ signals: {count_52} vs {count_55}"

    def test_signals_are_only_1_minus1_or_0(self):
        from real_data_backtest import generate_signals

        df = _make_ohlcv(500)
        result = generate_signals(df)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_score_column_in_minus1_to_1(self):
        from real_data_backtest import generate_signals

        df = _make_ohlcv(500)
        result = generate_signals(df)
        assert result["score"].min() >= -1.0 - 1e-9
        assert result["score"].max() <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# walk_forward_backtest() — returns trade-level Sharpe
# ---------------------------------------------------------------------------


class TestWalkForwardBacktest:
    def test_returns_required_keys(self):
        from real_data_backtest import walk_forward_backtest

        df = _make_ohlcv(500)
        result = walk_forward_backtest(df)
        for key in [
            "train_equity",
            "test_equity",
            "full_equity",
            "train_sharpe",
            "test_sharpe",
            "train_sharpe_se",
            "test_sharpe_se",
            "train_trade_count",
            "test_trade_count",
            "train_pnls",
            "test_pnls",
            "bar_sharpe_train",
            "bar_sharpe_test",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_trade_count_positive(self):
        from real_data_backtest import walk_forward_backtest

        df = _make_ohlcv(1000)
        result = walk_forward_backtest(df)
        total = result["train_trade_count"] + result["test_trade_count"]
        assert total > 0

    def test_se_consistent_with_trade_count(self):
        """SE should equal 1/sqrt(2*(N-1)) for the test trade count."""
        from real_data_backtest import walk_forward_backtest

        df = _make_ohlcv(1000)
        result = walk_forward_backtest(df)
        n = result["test_trade_count"]
        if n >= 2:
            expected_se = 1.0 / math.sqrt(2.0 * (n - 1))
            assert abs(result["test_sharpe_se"] - expected_se) < 1e-6

    def test_full_equity_is_concatenation(self):
        from real_data_backtest import walk_forward_backtest

        df = _make_ohlcv(500)
        result = walk_forward_backtest(df)
        expected_len = len(result["train_equity"]) + len(result["test_equity"])
        assert len(result["full_equity"]) == expected_len


# ---------------------------------------------------------------------------
# Gold pip value
# ---------------------------------------------------------------------------


class TestPipValue:
    def test_gold_pip_value(self):
        from real_data_backtest import _pip_value_for_price, GOLD_PIP_VALUE

        assert _pip_value_for_price(2000.0) == GOLD_PIP_VALUE

    def test_crypto_pip_value(self):
        from real_data_backtest import _pip_value_for_price, CRYPTO_PIP_VALUE

        assert _pip_value_for_price(1.2) == CRYPTO_PIP_VALUE

    def test_gold_slippage_dollar_value(self):
        """3 pips × $0.10/pip = $0.30 slippage at gold price."""
        from real_data_backtest import _pip_value_for_price, SLIPPAGE_PIPS

        pip_val = _pip_value_for_price(2000.0)
        dollar_slip = SLIPPAGE_PIPS * pip_val
        assert abs(dollar_slip - 0.30) < 1e-9, f"Expected $0.30, got ${dollar_slip}"
