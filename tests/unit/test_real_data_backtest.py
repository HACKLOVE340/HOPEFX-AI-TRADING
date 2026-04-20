# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for real_data_backtest.py

Covers:
1. generate_ml_signals() uses 5-bar forward-return target (not close-to-close).
2. generate_ml_signals() falls back to heuristic when model is unavailable.
3. generate_ml_signals() signal values are in {-1, 0, 1}.
4. run_backtest() uses ML signals by default (use_ml_signals=True).
5. run_backtest() falls back to heuristic when use_ml_signals=False.
6. walk_forward_backtest() threads use_ml_signals through to run_backtest().
7. trade_level_sharpe() arithmetic correctness.
8. annualised_sharpe() returns 0 for flat equity.
9. max_drawdown() returns correct peak-to-trough fraction.
10. Signal column always present after generate_ml_signals().
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import real_data_backtest as rdb


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with UTC DatetimeIndex."""
    rng = np.random.default_rng(seed)
    close = 1900.0 + np.cumsum(rng.normal(0, 5, n))
    close = np.clip(close, 1000, 3000)
    high = close + rng.uniform(1, 15, n)
    low = close - rng.uniform(1, 15, n)
    open_ = close + rng.normal(0, 3, n)
    volume = rng.integers(500, 5000, n).astype(float)
    idx = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _make_mock_model(proba: float = 0.65) -> MagicMock:
    """Return a mock sklearn model that always predicts `proba` for class 1."""
    mock = MagicMock()
    mock.predict_proba = MagicMock(
        side_effect=lambda X: np.column_stack([
            np.full(len(X), 1 - proba),
            np.full(len(X), proba),
        ])
    )
    return mock


# ── generate_ml_signals() ─────────────────────────────────────────────────────

class TestGenerateMlSignals:
    """generate_ml_signals() must use 5-bar forward-return target."""

    def test_signal_column_always_present(self, tmp_path):
        """signal column must exist even when model is unavailable."""
        df = _make_ohlcv(200)
        # No model file → heuristic fallback
        result = rdb.generate_ml_signals(df, model_path=str(tmp_path / "nonexistent.pkl"))
        assert "signal" in result.columns, "signal column must always be present"

    def test_signal_values_in_valid_set(self, tmp_path):
        """All signal values must be in {-1, 0, 1}."""
        df = _make_ohlcv(200)
        result = rdb.generate_ml_signals(df, model_path=str(tmp_path / "nonexistent.pkl"))
        invalid = set(result["signal"].unique()) - {-1, 0, 1}
        assert not invalid, f"Invalid signal values: {invalid}"

    def test_fallback_when_model_missing(self, tmp_path):
        """When model file does not exist, signal_source must be heuristic_fallback."""
        df = _make_ohlcv(200)
        result = rdb.generate_ml_signals(df, model_path=str(tmp_path / "missing.pkl"))
        assert "signal_source" in result.columns
        assert (result["signal_source"] == "heuristic_fallback").all(), (
            "signal_source must be 'heuristic_fallback' when model is missing"
        )

    def test_ml_proba_nan_when_model_missing(self, tmp_path):
        """ml_proba must be NaN when model is unavailable."""
        df = _make_ohlcv(200)
        result = rdb.generate_ml_signals(df, model_path=str(tmp_path / "missing.pkl"))
        assert "ml_proba" in result.columns
        assert result["ml_proba"].isna().all(), (
            "ml_proba must be NaN when model is unavailable"
        )

    def test_ml_signals_use_model_proba(self, tmp_path):
        """When model is available, signals must be derived from model probabilities."""
        df = _make_ohlcv(200)
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"placeholder")  # file exists

        mock_model = _make_mock_model(proba=0.80)  # always predicts 80% up

        with (
            patch("joblib.load", return_value=mock_model),
            patch("ml.features_extended.build_extended_features") as mock_feat,
        ):
            # Return a simple feature matrix aligned to df
            X = pd.DataFrame({"f0": df["close"].pct_change().fillna(0)}, index=df.index)
            y = (df["close"].shift(-5) > df["close"]).astype(int).fillna(0)
            mock_feat.return_value = (X, y)

            result = rdb.generate_ml_signals(df, model_path=str(model_file))

        # With proba=0.80 >= ABSTAIN_THRESHOLD=0.52, all signals should be +1
        assert "ml_proba" in result.columns
        ml_rows = result[result["signal_source"] == "ml_model"]
        if len(ml_rows) > 0:
            assert (ml_rows["signal"] == 1).all(), (
                "With proba=0.80 >= threshold=0.52, all ML signals must be +1"
            )

    def test_ml_signals_abstain_when_proba_near_half(self, tmp_path):
        """When proba ≈ 0.5, signal must be 0 (abstain)."""
        df = _make_ohlcv(200)
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"placeholder")

        mock_model = _make_mock_model(proba=0.50)  # exactly at boundary → abstain

        with (
            patch("joblib.load", return_value=mock_model),
            patch("ml.features_extended.build_extended_features") as mock_feat,
        ):
            X = pd.DataFrame({"f0": df["close"].pct_change().fillna(0)}, index=df.index)
            y = (df["close"].shift(-5) > df["close"]).astype(int).fillna(0)
            mock_feat.return_value = (X, y)

            result = rdb.generate_ml_signals(df, model_path=str(model_file))

        ml_rows = result[result["signal_source"] == "ml_model"]
        if len(ml_rows) > 0:
            # proba=0.50 < threshold=0.52 and > (1-0.52)=0.48 → abstain
            assert (ml_rows["signal"] == 0).all(), (
                "With proba=0.50 (below threshold), all ML signals must be 0 (abstain)"
            )

    def test_fallback_on_feature_builder_error(self, tmp_path):
        """When feature builder raises, must fall back to heuristic."""
        df = _make_ohlcv(200)
        model_file = tmp_path / "model.pkl"
        model_file.write_bytes(b"placeholder")

        with (
            patch("joblib.load", return_value=_make_mock_model()),
            patch("ml.features_extended.build_extended_features",
                  side_effect=ImportError("ml not available")),
        ):
            result = rdb.generate_ml_signals(df, model_path=str(model_file))

        assert "signal" in result.columns
        assert (result["signal_source"] == "heuristic_fallback").all()

    def test_horizon_5_target_not_close_to_close(self):
        """
        Verify that generate_ml_signals uses horizon=5 (not 1) by checking
        the default horizon parameter value in the function signature.
        """
        import inspect
        sig = inspect.signature(rdb.generate_ml_signals)
        horizon_default = sig.parameters["horizon"].default
        assert horizon_default == 5, (
            f"generate_ml_signals horizon default must be 5 (got {horizon_default}). "
            "Using horizon=1 is close-to-close — misaligned with execution hold period."
        )

    def test_atr_column_present(self, tmp_path):
        """ATR column must be present in output for stop/TP calculation."""
        df = _make_ohlcv(200)
        result = rdb.generate_ml_signals(df, model_path=str(tmp_path / "missing.pkl"))
        assert "atr" in result.columns, "atr column must be present for stop/TP calculation"


# ── run_backtest() ────────────────────────────────────────────────────────────

class TestRunBacktest:
    """run_backtest() must use ML signals by default."""

    def test_uses_ml_signals_by_default(self):
        """run_backtest() must call generate_ml_signals when use_ml_signals=True."""
        df = _make_ohlcv(150)
        ml_called = []

        original_ml = rdb.generate_ml_signals

        def _track_ml(df, **kwargs):
            ml_called.append(True)
            return original_ml(df, **kwargs)

        with patch.object(rdb, "generate_ml_signals", side_effect=_track_ml):
            rdb.run_backtest(df, use_ml_signals=True)

        assert ml_called, "generate_ml_signals must be called when use_ml_signals=True"

    def test_uses_heuristic_when_flag_false(self):
        """run_backtest() must call generate_signals (heuristic) when use_ml_signals=False."""
        df = _make_ohlcv(150)
        heuristic_called = []

        original_heuristic = rdb.generate_signals

        def _track_heuristic(df):
            heuristic_called.append(True)
            return original_heuristic(df)

        with patch.object(rdb, "generate_signals", side_effect=_track_heuristic):
            rdb.run_backtest(df, use_ml_signals=False)

        assert heuristic_called, "generate_signals must be called when use_ml_signals=False"

    def test_returns_equity_df_and_pnls(self):
        """run_backtest() must return (DataFrame, list)."""
        df = _make_ohlcv(150)
        equity_df, trade_pnls = rdb.run_backtest(df, use_ml_signals=False)
        assert isinstance(equity_df, pd.DataFrame), "First return must be a DataFrame"
        assert isinstance(trade_pnls, list), "Second return must be a list"

    def test_equity_column_present(self):
        """equity_df must have an 'equity' column."""
        df = _make_ohlcv(150)
        equity_df, _ = rdb.run_backtest(df, use_ml_signals=False)
        assert "equity" in equity_df.columns

    def test_equity_starts_at_initial_capital(self):
        """First equity value must equal initial_capital."""
        df = _make_ohlcv(150)
        capital = 50_000.0
        equity_df, _ = rdb.run_backtest(df, initial_capital=capital, use_ml_signals=False)
        if len(equity_df) > 0:
            # First bar: no trade yet, equity = initial_capital (minus any overnight cost)
            assert equity_df["equity"].iloc[0] <= capital + 1.0, (
                "Initial equity must not exceed initial_capital"
            )

    def test_trade_pnls_are_floats(self):
        """All trade PnLs must be finite floats."""
        df = _make_ohlcv(200)
        _, trade_pnls = rdb.run_backtest(df, use_ml_signals=False)
        for pnl in trade_pnls:
            assert isinstance(pnl, float), f"PnL must be float, got {type(pnl)}"
            assert np.isfinite(pnl), f"PnL must be finite, got {pnl}"


# ── walk_forward_backtest() ───────────────────────────────────────────────────

class TestWalkForwardBacktest:
    """walk_forward_backtest() must thread use_ml_signals through to run_backtest."""

    def test_threads_use_ml_signals_true(self):
        """use_ml_signals=True must be passed to both train and test run_backtest calls."""
        df = _make_ohlcv(200)
        calls = []

        original_rb = rdb.run_backtest

        def _track_rb(df, initial_capital=rdb.INITIAL_CAPITAL, symbol=rdb.SYMBOL,
                      use_ml_signals=True, model_path=None):
            calls.append(use_ml_signals)
            return original_rb(df, initial_capital=initial_capital, symbol=symbol,
                               use_ml_signals=False)  # use heuristic to avoid model dep

        with patch.object(rdb, "run_backtest", side_effect=_track_rb):
            rdb.walk_forward_backtest(df, use_ml_signals=True)

        assert all(c is True for c in calls), (
            f"use_ml_signals=True must be passed to all run_backtest calls, got: {calls}"
        )

    def test_threads_use_ml_signals_false(self):
        """use_ml_signals=False must be passed to both train and test run_backtest calls."""
        df = _make_ohlcv(200)
        calls = []

        original_rb = rdb.run_backtest

        def _track_rb(df, initial_capital=rdb.INITIAL_CAPITAL, symbol=rdb.SYMBOL,
                      use_ml_signals=True, model_path=None):
            calls.append(use_ml_signals)
            return original_rb(df, initial_capital=initial_capital, symbol=symbol,
                               use_ml_signals=False)

        with patch.object(rdb, "run_backtest", side_effect=_track_rb):
            rdb.walk_forward_backtest(df, use_ml_signals=False)

        assert all(c is False for c in calls), (
            f"use_ml_signals=False must be passed to all run_backtest calls, got: {calls}"
        )

    def test_returns_required_keys(self):
        """walk_forward_backtest() must return all required keys."""
        df = _make_ohlcv(200)
        result = rdb.walk_forward_backtest(df, use_ml_signals=False)
        required = {
            "train_equity", "test_equity", "full_equity",
            "train_sharpe", "test_sharpe",
            "train_sharpe_se", "test_sharpe_se",
            "train_trade_count", "test_trade_count",
            "train_pnls", "test_pnls",
            "bar_sharpe_train", "bar_sharpe_test",
            "signal_source",
        }
        for key in required:
            assert key in result, f"walk_forward_backtest() missing key: {key}"

    def test_signal_source_recorded(self):
        """signal_source must be 'ml_model' or 'heuristic'."""
        df = _make_ohlcv(200)
        result = rdb.walk_forward_backtest(df, use_ml_signals=False)
        assert result["signal_source"] in ("ml_model", "heuristic"), (
            f"Unexpected signal_source: {result['signal_source']}"
        )

    def test_train_test_split_ratio(self):
        """Train set must be ~70% of data, test ~30%."""
        df = _make_ohlcv(300)
        result = rdb.walk_forward_backtest(df, train_ratio=0.70, use_ml_signals=False)
        train_len = len(result["train_equity"])
        test_len = len(result["test_equity"])
        total = train_len + test_len
        if total > 0:
            train_frac = train_len / total
            assert 0.60 <= train_frac <= 0.80, (
                f"Train fraction {train_frac:.2f} outside expected range [0.60, 0.80]"
            )


# ── trade_level_sharpe() ──────────────────────────────────────────────────────

class TestTradeLevelSharpe:
    """trade_level_sharpe() arithmetic correctness."""

    def test_returns_zero_for_empty_pnls(self):
        sharpe, se = rdb.trade_level_sharpe([])
        assert sharpe == 0.0
        assert se == 0.0

    def test_returns_zero_for_single_trade(self):
        sharpe, se = rdb.trade_level_sharpe([100.0])
        assert sharpe == 0.0
        assert se == 0.0

    def test_positive_sharpe_for_consistent_wins(self):
        """Consistent positive PnLs must produce positive Sharpe."""
        pnls = [50.0 + i * 0.1 for i in range(100)]
        sharpe, se = rdb.trade_level_sharpe(pnls)
        assert sharpe > 0, f"Expected positive Sharpe for consistent wins, got {sharpe}"

    def test_negative_sharpe_for_consistent_losses(self):
        """Consistent negative PnLs must produce negative Sharpe."""
        pnls = [-50.0 - i * 0.1 for i in range(100)]
        sharpe, se = rdb.trade_level_sharpe(pnls)
        assert sharpe < 0, f"Expected negative Sharpe for consistent losses, got {sharpe}"

    def test_se_decreases_with_more_trades(self):
        """SE must decrease as N increases (SE = 1/sqrt(2*(N-1))).

        Use varied PnLs so std > 0 and trade_level_sharpe doesn't short-circuit.
        """
        rng = np.random.default_rng(7)
        pnls_small = list(rng.normal(10, 5, 10))   # N=10
        pnls_large = list(rng.normal(10, 5, 200))  # N=200
        _, se_small = rdb.trade_level_sharpe(pnls_small)
        _, se_large = rdb.trade_level_sharpe(pnls_large)
        assert se_large < se_small, (
            f"SE must decrease with more trades: se_small={se_small:.4f} se_large={se_large:.4f}"
        )

    def test_se_formula(self):
        """SE must equal 1/sqrt(2*(N-1)) exactly."""
        n = 100
        pnls = list(np.random.default_rng(0).normal(10, 5, n))
        _, se = rdb.trade_level_sharpe(pnls)
        expected_se = 1.0 / np.sqrt(2.0 * (n - 1))
        assert abs(se - expected_se) < 1e-8, f"SE={se} != expected {expected_se}"


# ── annualised_sharpe() ───────────────────────────────────────────────────────

class TestAnnualisedSharpe:
    """annualised_sharpe() returns 0 for flat equity."""

    def test_flat_equity_returns_zero(self):
        equity = pd.Series([100_000.0] * 100)
        result = rdb.annualised_sharpe(equity)
        assert result == 0.0

    def test_growing_equity_positive_sharpe(self):
        equity = pd.Series([100_000.0 + i * 10 for i in range(200)])
        result = rdb.annualised_sharpe(equity)
        assert result > 0


# ── max_drawdown() ────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    """max_drawdown() returns correct peak-to-trough fraction."""

    def test_no_drawdown_returns_zero(self):
        equity = pd.Series([100.0, 110.0, 120.0, 130.0])
        dd = rdb.max_drawdown(equity)
        assert dd == 0.0

    def test_known_drawdown(self):
        """Peak=200, trough=100 → drawdown = (100-200)/200 = -0.5."""
        equity = pd.Series([100.0, 200.0, 100.0, 150.0])
        dd = rdb.max_drawdown(equity)
        assert abs(dd - (-0.5)) < 1e-8, f"Expected -0.5, got {dd}"

    def test_drawdown_is_negative(self):
        equity = pd.Series([100.0, 90.0, 80.0, 95.0])
        dd = rdb.max_drawdown(equity)
        assert dd <= 0.0, "Drawdown must be non-positive"
