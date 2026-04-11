# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage-boosting tests for 0%/low-coverage ML modules:
  - ml/hourly_trainer.py
  - ml/macro_bootstrap.py
  - ml/mtf_features.py
  - ml/run_training.py

All tests use real implementations — no mocks of the modules under test.
External I/O (yfinance, CSV files, OnlineLearner) is patched at the boundary.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_daily_ohlcv(n: int = 300) -> pd.DataFrame:
    """Return a minimal daily OHLCV DataFrame suitable for MTF feature building."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    close = 1800.0 + np.cumsum(rng.normal(0, 5, n))
    high = close + rng.uniform(1, 10, n)
    low = close - rng.uniform(1, 10, n)
    open_ = close + rng.normal(0, 3, n)
    volume = rng.integers(1000, 5000, n).astype(float)
    return pd.DataFrame({"Date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})


def _make_h1_csv(tmp_dir: Path, symbol: str = "XAU_USD", n: int = 200) -> Path:
    """Write a minimal H1 CSV and return its path."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2023-01-01", periods=n, freq="h")
    close = 1900.0 + np.cumsum(rng.normal(0, 2, n))
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": close + rng.normal(0, 1, n),
            "high": close + rng.uniform(0, 5, n),
            "low": close - rng.uniform(0, 5, n),
            "close": close,
            "volume": rng.integers(100, 500, n).astype(float),
        }
    )
    path = tmp_dir / f"{symbol}_H1.csv"
    df.to_csv(path, index=False)
    return path


# ===========================================================================
# ml/mtf_features.py
# ===========================================================================


@pytest.mark.unit
class TestMtfHelpers:
    def test_resample_ohlcv_weekly(self):
        from ml.mtf_features import _resample_ohlcv

        df = _make_daily_ohlcv(100)
        weekly = _resample_ohlcv(df, "W-FRI")
        assert not weekly.empty
        assert "close" in weekly.columns
        assert len(weekly) < len(df)

    def test_resample_ohlcv_monthly(self):
        from ml.mtf_features import _resample_ohlcv

        df = _make_daily_ohlcv(200)
        monthly = _resample_ohlcv(df, "ME")
        assert not monthly.empty
        assert len(monthly) < 20

    def test_align_to_daily(self):
        from ml.mtf_features import _align_to_daily, _resample_ohlcv

        df = _make_daily_ohlcv(100)
        weekly = _resample_ohlcv(df, "W-FRI")
        daily_idx = pd.DatetimeIndex(df["Date"])
        aligned = _align_to_daily(weekly, daily_idx)
        assert len(aligned) == len(daily_idx)

    def test_ema(self):
        from ml.mtf_features import _ema

        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _ema(s, 3)
        assert len(result) == 5
        assert result.iloc[-1] > result.iloc[0]

    def test_rsi_range(self):
        from ml.mtf_features import _rsi

        s = pd.Series(np.linspace(1800, 2000, 50))
        result = _rsi(s, 14)
        assert result.between(0, 100).all()

    def test_atr_positive(self):
        from ml.mtf_features import _atr

        df = _make_daily_ohlcv(50)
        result = _atr(df["high"], df["low"], df["close"], 14)
        assert (result.dropna() >= 0).all()

    def test_zscore(self):
        from ml.mtf_features import _zscore

        s = pd.Series(np.random.default_rng(1).normal(0, 1, 100))
        result = _zscore(s, 20)
        assert len(result) == 100
        # z-score of constant series should be 0
        const = pd.Series([5.0] * 50)
        z = _zscore(const, 10)
        assert (z.dropna() == 0).all()

    def test_adx_range(self):
        from ml.mtf_features import _adx

        df = _make_daily_ohlcv(100)
        result = _adx(df["high"], df["low"], df["close"], 14)
        assert (result.dropna() >= 0).all()

    def test_hurst_proxy(self):
        from ml.mtf_features import _hurst_proxy

        s = pd.Series(np.linspace(1800, 2000, 60))
        result = _hurst_proxy(s, 20)
        assert len(result) == 60
        assert result.between(0, 1).all()

    def test_hurst_proxy_short_series(self):
        from ml.mtf_features import _hurst_proxy

        s = pd.Series([1.0, 2.0, 3.0])
        result = _hurst_proxy(s, 20)
        assert len(result) == 3


@pytest.mark.unit
class TestBuildMtfFeatures:
    def test_returns_dataframe_with_mtf_columns(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        assert isinstance(result, pd.DataFrame)
        mtf_cols = [c for c in result.columns if c.startswith("mtf_")]
        assert len(mtf_cols) >= 50

    def test_preserves_row_count(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        assert len(result) == len(df)

    def test_date_column_preserved(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        assert "Date" in result.columns

    def test_alignment_score_bounded(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        assert result["mtf_alignment_score"].between(-1, 1).all()

    def test_confluence_columns_present(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        assert "mtf_bull_confluence" in result.columns
        assert "mtf_bear_confluence" in result.columns
        assert "mtf_net_confluence" in result.columns

    def test_seasonal_columns(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        assert "mtf_gold_seasonal" in result.columns
        assert "mtf_jan_effect" in result.columns
        assert "mtf_year_end" in result.columns

    def test_no_inf_values(self):
        from ml.mtf_features import build_mtf_features

        df = _make_daily_ohlcv(300)
        result = build_mtf_features(df)
        numeric = result.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.values).any()

    def test_minimum_rows(self):
        from ml.mtf_features import build_mtf_features

        # Should work with fewer rows (some features will be NaN)
        df = _make_daily_ohlcv(60)
        result = build_mtf_features(df)
        assert len(result) == 60


# ===========================================================================
# ml/macro_bootstrap.py
# ===========================================================================


@pytest.mark.unit
class TestMacroBootstrap:
    def test_bootstrap_skips_fresh_files(self, tmp_path):
        """Files < 24h old are counted as available without re-fetching."""
        from ml import macro_bootstrap

        # Create fresh CSV files
        for meta in macro_bootstrap._SERIES_MAP.values():
            p = tmp_path / meta["file"]
            p.write_text("date,value\n2024-01-01,100\n")

        with patch.object(macro_bootstrap, "_MACRO_DIR", tmp_path):
            count = macro_bootstrap.bootstrap(force=False)

        assert count == len(macro_bootstrap._SERIES_MAP)

    def test_bootstrap_force_fetches(self, tmp_path):
        """force=True triggers fetch even for fresh files."""
        from ml import macro_bootstrap

        mock_df = pd.DataFrame({"date": ["2024-01-01"], "value": [100.0]})

        with (
            patch.object(macro_bootstrap, "_MACRO_DIR", tmp_path),
            patch.object(macro_bootstrap, "_fetch_series", return_value=mock_df),
        ):
            count = macro_bootstrap.bootstrap(force=True)

        assert count == len(macro_bootstrap._SERIES_MAP)

    def test_bootstrap_handles_fetch_failure(self, tmp_path):
        """None return from _fetch_series is handled gracefully."""
        from ml import macro_bootstrap

        with (
            patch.object(macro_bootstrap, "_MACRO_DIR", tmp_path),
            patch.object(macro_bootstrap, "_fetch_series", return_value=None),
        ):
            count = macro_bootstrap.bootstrap(force=True)

        assert count == 0

    def test_daily_refresh_calls_bootstrap_force(self, tmp_path):
        from ml import macro_bootstrap

        with (
            patch.object(macro_bootstrap, "_MACRO_DIR", tmp_path),
            patch.object(macro_bootstrap, "bootstrap", return_value=3) as mock_bs,
        ):
            result = macro_bootstrap.daily_refresh()

        mock_bs.assert_called_once_with(force=True)
        assert result == 3

    def test_fetch_series_no_yfinance(self):
        """Returns None gracefully when yfinance is not installed."""
        from ml import macro_bootstrap

        with patch.dict("sys.modules", {"yfinance": None}):
            result = macro_bootstrap._fetch_series("DX-Y.NYB", years=1)

        assert result is None

    def test_fetch_series_yfinance_empty(self):
        """Returns None when yfinance returns empty DataFrame."""
        from ml import macro_bootstrap

        mock_yf = MagicMock()
        mock_yf.download.return_value = pd.DataFrame()

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = macro_bootstrap._fetch_series("DX-Y.NYB", years=1)

        assert result is None

    def test_fetch_series_yfinance_success(self):
        """Returns DataFrame with date/value columns on success."""
        from ml import macro_bootstrap

        dates = pd.date_range("2023-01-01", periods=5, freq="D")
        mock_df = pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=dates)
        mock_yf = MagicMock()
        mock_yf.download.return_value = mock_df

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = macro_bootstrap._fetch_series("DX-Y.NYB", years=1)

        assert result is not None
        assert "date" in result.columns
        assert "value" in result.columns

    def test_load_into_store(self, tmp_path):
        """load_into_store calls store.load_csv for each series."""
        from ml import macro_bootstrap

        mock_store = MagicMock()
        mock_store.load_csv.return_value = 10

        with patch.object(macro_bootstrap, "_MACRO_DIR", tmp_path):
            count = macro_bootstrap.load_into_store(mock_store)

        assert mock_store.load_csv.call_count == len(macro_bootstrap._SERIES_MAP)
        assert count == len(macro_bootstrap._SERIES_MAP)

    def test_load_into_store_partial(self, tmp_path):
        """load_into_store counts only series with n > 0."""
        from ml import macro_bootstrap

        mock_store = MagicMock()
        mock_store.load_csv.return_value = 0  # nothing loaded

        with patch.object(macro_bootstrap, "_MACRO_DIR", tmp_path):
            count = macro_bootstrap.load_into_store(mock_store)

        assert count == 0


# ===========================================================================
# ml/hourly_trainer.py
# ===========================================================================


@pytest.mark.unit
class TestHourlyTrainerInit:
    def test_default_construction(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        assert t.enabled is False
        assert t.interval_secs > 0
        assert isinstance(t.symbols, list)

    def test_custom_construction(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(
            enabled=True,
            interval_secs=60,
            full_retrain_hrs=6,
            symbols=["XAU_USD", "EUR_USD"],
            model_dir="/tmp/models",
        )
        assert t.interval_secs == 60
        assert t.full_retrain_hrs == 6
        assert t.symbols == ["XAU_USD", "EUR_USD"]

    def test_status_returns_dict(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        s = t.status()
        assert isinstance(s, dict)
        assert "enabled" in s
        assert "running" in s
        assert "online_update_count" in s
        assert "full_retrain_count" in s

    def test_get_hourly_trainer_singleton(self):
        from ml.hourly_trainer import get_hourly_trainer

        a = get_hourly_trainer()
        b = get_hourly_trainer()
        assert a is b


@pytest.mark.unit
class TestHourlyTrainerAsync:
    @pytest.mark.asyncio
    async def test_start_disabled_returns_immediately(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        await t.start()  # should return without running loop
        assert t._running is False

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=True, interval_secs=1)
        t._running = True
        await t.stop()
        assert t._running is False

    @pytest.mark.asyncio
    async def test_run_cycle_increments_counters(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=True, symbols=["XAU_USD"], full_retrain_hrs=0)

        async def _fake_online(sym):
            pass

        async def _fake_full(sym):
            pass

        t._online_update = _fake_online
        t._full_retrain = _fake_full
        t._last_full_retrain = {}

        await t._run_cycle()
        assert t._online_update_count == 1
        assert t._full_retrain_count == 1

    @pytest.mark.asyncio
    async def test_run_cycle_skips_full_retrain_when_recent(self):
        from ml.hourly_trainer import HourlyTrainer
        import time

        t = HourlyTrainer(enabled=True, symbols=["XAU_USD"], full_retrain_hrs=24)

        async def _fake_online(sym):
            pass

        async def _fake_full(sym):
            pass

        t._online_update = _fake_online
        t._full_retrain = _fake_full
        t._last_full_retrain = {"XAU_USD": time.time()}  # just ran

        await t._run_cycle()
        assert t._online_update_count == 1
        assert t._full_retrain_count == 0  # skipped

    @pytest.mark.asyncio
    async def test_fetch_recent_bars_missing_csv(self, tmp_path):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        result = await t._fetch_recent_bars("NONEXISTENT_SYMBOL", n=10)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_recent_bars_with_csv(self, tmp_path):
        from ml.hourly_trainer import HourlyTrainer

        csv_path = _make_h1_csv(tmp_path, "XAU_USD", n=50)
        t = HourlyTrainer(enabled=False)

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pandas.read_csv", return_value=pd.read_csv(csv_path, parse_dates=["timestamp"])),
        ):
            result = await t._fetch_recent_bars("XAU_USD", n=10)

        assert result is not None
        assert len(result) <= 10

    @pytest.mark.asyncio
    async def test_online_update_no_learner(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        with patch("ml.online_learner.get_online_learner", return_value=None):
            await t._online_update("XAU_USD")  # should not raise

    @pytest.mark.asyncio
    async def test_online_update_import_error(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        with patch.dict("sys.modules", {"ml.online_learner": None}):
            await t._online_update("XAU_USD")  # should not raise

    @pytest.mark.asyncio
    async def test_reload_live_inference_handles_exception(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=False)
        with patch.dict("sys.modules", {"ml.live_inference": None}):
            await t._reload_live_inference("XAU_USD")  # should not raise

    @pytest.mark.asyncio
    async def test_loop_stops_when_running_false(self):
        from ml.hourly_trainer import HourlyTrainer

        t = HourlyTrainer(enabled=True, interval_secs=0, symbols=["XAU_USD"])
        call_count = 0

        async def _fake_cycle():
            nonlocal call_count
            call_count += 1
            t._running = False  # stop after first cycle

        t._running = True
        t._run_cycle = _fake_cycle
        await t._loop()
        assert call_count == 1


# ===========================================================================
# ml/run_training.py
# ===========================================================================


@pytest.mark.unit
class TestRunTrainingLoadH1Csv:
    def test_load_h1_csv_missing_file(self, tmp_path):
        from ml.run_training import load_h1_csv

        result = load_h1_csv("NONEXISTENT", csv_dir=str(tmp_path))
        assert result is None

    def test_load_h1_csv_valid(self, tmp_path):
        from ml.run_training import load_h1_csv

        _make_h1_csv(tmp_path, "XAU_USD", n=100)
        result = load_h1_csv("XAU_USD", csv_dir=str(tmp_path))
        assert result is not None
        assert len(result) == 100
        assert "close" in result.columns

    def test_load_h1_csv_missing_columns(self, tmp_path):
        """CSV without required OHLC columns returns None."""
        from ml.run_training import load_h1_csv

        bad_csv = tmp_path / "XAU_USD_H1.csv"
        bad_csv.write_text("timestamp,volume\n2023-01-01,100\n")
        result = load_h1_csv("XAU_USD", csv_dir=str(tmp_path))
        assert result is None

    def test_load_h1_csv_no_volume_column(self, tmp_path):
        """CSV without volume column gets volume=0 added."""
        from ml.run_training import load_h1_csv

        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2023-01-01", periods=10, freq="h"),
                "open": [1.0] * 10,
                "high": [1.1] * 10,
                "low": [0.9] * 10,
                "close": [1.0] * 10,
            }
        )
        csv_path = tmp_path / "XAU_USD_H1.csv"
        df.to_csv(csv_path, index=False)
        result = load_h1_csv("XAU_USD", csv_dir=str(tmp_path))
        assert result is not None
        assert "volume" in result.columns
        assert (result["volume"] == 0).all()


@pytest.mark.unit
class TestRunTrainingLoadData:
    def test_load_data_explicit_csv(self, tmp_path):
        from ml.run_training import load_data

        csv_path = _make_h1_csv(tmp_path, "XAU_USD", n=50)
        # Rename to match explicit CSV format (with timestamp column)
        result = load_data("XAU_USD", csv_path=str(csv_path), period="1y")
        assert result is not None
        assert len(result) == 50

    def test_load_data_h1_csv_fallback(self, tmp_path):
        import ml.run_training as rt

        _make_h1_csv(tmp_path, "XAU_USD", n=80)
        # Patch load_h1_csv directly to return our test data
        expected = pd.read_csv(str(tmp_path / "XAU_USD_H1.csv"), parse_dates=["timestamp"])
        expected.columns = [c.lower() for c in expected.columns]
        expected = expected.rename(columns={"timestamp": "datetime"})
        expected["volume"] = expected.get("volume", 0)
        expected = expected[["open", "high", "low", "close", "volume"]].dropna()

        with patch.object(rt, "load_h1_csv", return_value=expected):
            result = rt.load_data("XAU_USD", csv_path=None, period="1y")
        assert result is not None
        assert len(result) == 80

    def test_load_data_yfinance_fallback(self, tmp_path):
        import ml.run_training as rt

        mock_df = pd.DataFrame(
            {
                "open": [1.0] * 10,
                "high": [1.1] * 10,
                "low": [0.9] * 10,
                "close": [1.0] * 10,
                "volume": [100.0] * 10,
            }
        )

        with (
            patch.object(rt, "load_h1_csv", return_value=None),
            patch.object(rt, "fetch_ohlcv_yfinance", return_value=mock_df),
        ):
            result = rt.load_data("XAU_USD", csv_path=None, period="1y")

        assert result is not None
        assert len(result) == 10


@pytest.mark.unit
class TestFetchOhlcvYfinance:
    def test_raises_when_yfinance_missing(self):
        from ml.run_training import fetch_ohlcv_yfinance

        with patch.dict("sys.modules", {"yfinance": None}):
            with pytest.raises(RuntimeError, match="yfinance not installed"):
                fetch_ohlcv_yfinance("XAU_USD")

    def test_raises_on_empty_data(self):
        from ml.run_training import fetch_ohlcv_yfinance

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            with pytest.raises(ValueError, match="No data returned"):
                fetch_ohlcv_yfinance("XAU_USD")

    def test_returns_dataframe_on_success(self):
        from ml.run_training import fetch_ohlcv_yfinance

        dates = pd.date_range("2023-01-01", periods=20, freq="D")
        mock_data = pd.DataFrame(
            {
                "Open": [1.0] * 20,
                "High": [1.1] * 20,
                "Low": [0.9] * 20,
                "Close": [1.0] * 20,
                "Volume": [100.0] * 20,
            },
            index=dates,
        )
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_data
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = fetch_ohlcv_yfinance("XAU_USD", period="1y", interval="1d")

        assert isinstance(result, pd.DataFrame)
        assert "close" in result.columns


@pytest.mark.unit
class TestRunPipeline:
    def test_run_pipeline_with_csv(self, tmp_path):
        """run_pipeline loads data and calls train_ml_pipeline."""
        from ml.run_training import run_pipeline

        csv_path = _make_h1_csv(tmp_path, "XAU_USD", n=200)
        model_dir = tmp_path / "models"

        mock_results = {
            "random_forest": {
                "model_path": str(model_dir / "XAU_USD" / "rf.pkl"),
                "metrics": {"accuracy": 0.55},
            }
        }

        with (
            patch("ml.run_training.load_data") as mock_load,
            patch("importlib.util.spec_from_file_location") as mock_spec,
        ):
            mock_load.return_value = pd.read_csv(csv_path, parse_dates=["timestamp"]).rename(
                columns={"timestamp": "datetime"}
            )
            # Mock the dynamic module loading
            mock_mod = MagicMock()
            mock_mod.train_ml_pipeline.return_value = mock_results
            mock_spec_obj = MagicMock()
            mock_spec_obj.loader.exec_module = lambda m: setattr(m, "train_ml_pipeline", mock_mod.train_ml_pipeline)
            mock_spec.return_value = mock_spec_obj

            with patch("importlib.util.module_from_spec", return_value=mock_mod):
                results = run_pipeline(
                    symbol="XAU_USD",
                    model_types=["random_forest"],
                    model_dir=str(model_dir),
                    csv_path=str(csv_path),
                )

        assert isinstance(results, dict)
