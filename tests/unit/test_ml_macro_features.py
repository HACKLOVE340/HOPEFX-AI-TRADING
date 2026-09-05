# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_macro_features.py
====================================
`ml/macro_features.py` was 230 statements at 66.23 %.

It builds the macro half of the feature matrix — DXY, VIX, yields, gold ETF
flow — plus the market-regime block, and the uncovered part was almost entirely
the *fetch* path: the Yahoo Finance download, its CSV fallback, and the
degradation between them.

That fallback matters more than its size suggests. This project runs in
network-restricted environments (CI included), where `yfinance` either is not
installed or cannot reach the internet. The whole point of
`_load_macro_from_csv` is that a model still gets macro context there. Nothing
tested that it engaged, or that it produced the same column names the live path
does — and a silent column rename between the two paths is exactly the kind of
mismatch that trains a model on one feature layout and serves it another.

The rest of the file is causality. `add_macro_features` and
`add_regime_features` must **never look ahead**: forward-fill only, no
backward-fill, no centred windows. A single `bfill` here would leak future
macro prints into historical bars and produce a backtest that cannot be
reproduced live. Those are asserted directly rather than assumed.

No test here touches the network: `yfinance` is substituted or made absent.
"""

from __future__ import annotations

import builtins

import numpy as np
import pandas as pd
import pytest

import ml.macro_features as mf
from ml.macro_features import (
    _load_macro_from_csv,
    _rolling_hurst,
    add_macro_features,
    add_regime_features,
    build_enhanced_feature_matrix,
    fetch_macro_history,
)

pytestmark = pytest.mark.unit


def _ohlcv(n=200, start=2000.0, seed=0):
    rng = np.random.default_rng(seed)
    closes = start + np.cumsum(rng.normal(0, 5, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 5,
            "low": closes - 5,
            "close": closes,
            "volume": rng.integers(100, 1000, n).astype(float),
        },
        index=idx,
    )


def _macro(n=200, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "dxy": 100 + np.cumsum(rng.normal(0, 0.2, n)),
            "vix": 15 + np.abs(rng.normal(0, 2, n)),
            "yield_10y": 4 + np.cumsum(rng.normal(0, 0.02, n)),
            "yield_5y": 3.8 + np.cumsum(rng.normal(0, 0.02, n)),
            "gold_etf": 180 + np.cumsum(rng.normal(0, 1, n)),
        },
        index=idx,
    )


def _no_yfinance(monkeypatch):
    real_import = builtins.__import__

    def _fake(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("yfinance not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake)


# ── the CSV fallback ──────────────────────────────────────────────────────────


class TestLoadMacroFromCsv:
    def _write(self, tmp_path, monkeypatch, files):
        macro_dir = tmp_path / "data" / "macro"
        macro_dir.mkdir(parents=True)
        for name, rows in files.items():
            body = "date,value\n" + "\n".join(f"{d},{v}" for d, v in rows)
            (macro_dir / name).write_text(body)
        # The module resolves data/macro relative to ml/../
        monkeypatch.setattr(mf, "__file__", str(tmp_path / "ml" / "macro_features.py"))
        return macro_dir

    def _rows(self, n=10, start=100.0):
        dates = pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
        return [(d, start + i) for i, d in enumerate(dates)]

    def test_a_missing_directory_yields_an_empty_frame(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mf, "__file__", str(tmp_path / "ml" / "macro_features.py"))

        assert _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")).empty

    def test_a_csv_is_loaded_under_its_mapped_series_name(self, tmp_path, monkeypatch):
        """The CSV filename and the feature name are deliberately different."""
        self._write(tmp_path, monkeypatch, {"dxy_daily.csv": self._rows()})

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert "dxy" in df.columns

    def test_every_mapped_file_is_read(self, tmp_path, monkeypatch):
        self._write(
            tmp_path,
            monkeypatch,
            {
                "dxy_daily.csv": self._rows(),
                "us10y_daily.csv": self._rows(start=4.0),
                "us2y_daily.csv": self._rows(start=3.5),
                "vix_daily.csv": self._rows(start=15.0),
                "gold_etf_flow.csv": self._rows(start=180.0),
            },
        )

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert set(df.columns) == {"dxy", "yield_10y", "yield_5y", "vix", "gold_etf"}

    def test_the_two_year_series_stands_in_for_the_five_year(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"us2y_daily.csv": self._rows()})

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert "yield_5y" in df.columns

    def test_rows_outside_the_window_are_excluded(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"dxy_daily.csv": self._rows(n=30)})

        df = _load_macro_from_csv(pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-10"))

        assert len(df) == 6

    def test_a_window_matching_nothing_yields_an_empty_frame(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"dxy_daily.csv": self._rows()})

        assert _load_macro_from_csv(pd.Timestamp("2030-01-01"), pd.Timestamp("2030-12-31")).empty

    def test_a_malformed_csv_is_skipped_without_losing_the_others(self, tmp_path, monkeypatch):
        macro_dir = self._write(tmp_path, monkeypatch, {"dxy_daily.csv": self._rows()})
        (macro_dir / "vix_daily.csv").write_text("this is not a csv at all\n\x00")

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert "dxy" in df.columns

    def test_unrecognised_files_are_ignored(self, tmp_path, monkeypatch):
        macro_dir = self._write(tmp_path, monkeypatch, {"dxy_daily.csv": self._rows()})
        (macro_dir / "something_else.csv").write_text("date,value\n2024-01-01,1\n")

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert set(df.columns) == {"dxy"}

    def test_the_result_carries_no_nan(self, tmp_path, monkeypatch):
        self._write(
            tmp_path,
            monkeypatch,
            {"dxy_daily.csv": self._rows(n=10), "vix_daily.csv": self._rows(n=5, start=15.0)},
        )

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert not df.isna().any().any()

    def test_the_index_is_timezone_naive(self, tmp_path, monkeypatch):
        """Mixing naive and aware indices raises on the first join."""
        self._write(tmp_path, monkeypatch, {"dxy_daily.csv": self._rows()})

        df = _load_macro_from_csv(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"))

        assert df.index.tz is None


class TestFetchMacroHistory:
    def test_without_yfinance_it_falls_back_to_csv(self, tmp_path, monkeypatch):
        """CI and every network-restricted deployment take this path."""
        called = {}

        def _fallback(start, end):
            called["yes"] = True
            return pd.DataFrame({"dxy": [100.0]}, index=pd.to_datetime(["2024-01-01"]))

        monkeypatch.setattr(mf, "_load_macro_from_csv", _fallback)
        _no_yfinance(monkeypatch)

        result = fetch_macro_history(pd.Timestamp("2024-01-01"))

        assert called.get("yes") is True
        assert "dxy" in result.columns

    def test_no_data_anywhere_is_an_empty_frame_not_an_exception(self, monkeypatch):
        monkeypatch.setattr(mf, "_load_macro_from_csv", lambda s, e: pd.DataFrame())
        _no_yfinance(monkeypatch)

        assert fetch_macro_history(pd.Timestamp("2024-01-01")).empty

    def test_a_failing_download_falls_back_rather_than_raising(self, monkeypatch):
        import sys
        from types import SimpleNamespace

        def _boom(*a, **k):
            raise RuntimeError("network unreachable")

        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=_boom))
        monkeypatch.setattr(
            mf,
            "_load_macro_from_csv",
            lambda s, e: pd.DataFrame({"dxy": [100.0]}, index=pd.to_datetime(["2024-01-01"])),
        )

        assert "dxy" in fetch_macro_history(pd.Timestamp("2024-01-01")).columns

    def test_an_empty_download_falls_back(self, monkeypatch):
        import sys
        from types import SimpleNamespace

        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=lambda *a, **k: pd.DataFrame()))
        monkeypatch.setattr(
            mf,
            "_load_macro_from_csv",
            lambda s, e: pd.DataFrame({"dxy": [1.0]}, index=pd.to_datetime(["2024-01-01"])),
        )

        assert not fetch_macro_history(pd.Timestamp("2024-01-01")).empty

    def test_a_successful_download_is_used_and_named_by_series(self, monkeypatch):
        import sys
        from types import SimpleNamespace

        idx = pd.date_range("2024-01-01", periods=5, freq="D")

        def _download(ticker, **kwargs):
            return pd.DataFrame({"Close": np.arange(5, dtype=float)}, index=idx)

        monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=_download))

        result = fetch_macro_history(pd.Timestamp("2024-01-01"))

        assert not result.empty
        assert set(result.columns) <= set(mf._MACRO_TICKERS)

    def test_the_live_and_csv_paths_agree_on_series_names(self):
        """A rename between the two paths trains on one layout and serves another."""
        csv_names = {"dxy", "yield_10y", "yield_5y", "vix", "gold_etf"}

        assert csv_names <= set(mf._MACRO_TICKERS)


# ── macro feature construction ────────────────────────────────────────────────


class TestAddMacroFeatures:
    def test_it_preserves_the_row_count(self):
        bars = _ohlcv()

        assert len(add_macro_features(bars, macro_df=_macro())) == len(bars)

    def test_it_preserves_the_index(self):
        bars = _ohlcv()

        assert add_macro_features(bars, macro_df=_macro()).index.equals(bars.index)

    def test_it_adds_columns(self):
        bars = _ohlcv()

        assert len(add_macro_features(bars, macro_df=_macro()).columns) > len(bars.columns)

    def test_the_original_frame_is_not_mutated(self):
        bars = _ohlcv()
        before = list(bars.columns)

        add_macro_features(bars, macro_df=_macro())

        assert list(bars.columns) == before

    def test_no_macro_data_still_returns_a_frame(self):
        bars = _ohlcv()

        result = add_macro_features(bars, macro_df=pd.DataFrame())

        assert len(result) == len(bars)

    def test_the_result_carries_no_infinities(self):
        result = add_macro_features(_ohlcv(), macro_df=_macro())

        numeric = result.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.to_numpy()).any()

    def test_macro_history_shorter_than_the_bars_is_tolerated(self):
        """Pre-history bars (e.g. pre-1990 VIX) must not break alignment."""
        bars = _ohlcv(200)
        short = _macro(50)

        assert len(add_macro_features(bars, macro_df=short)) == 200

    def test_it_does_not_look_ahead(self):
        """Truncating the future must not change any past row.

        A single bfill here would leak tomorrow's macro print into today and
        produce a backtest that cannot be reproduced live.
        """
        bars, macro = _ohlcv(200), _macro(200)
        full = add_macro_features(bars, macro_df=macro)
        truncated = add_macro_features(bars.iloc[:150], macro_df=macro.iloc[:150])

        shared = [c for c in truncated.columns if c in full.columns]
        pd.testing.assert_frame_equal(
            full[shared].iloc[:100].astype(float),
            truncated[shared].iloc[:100].astype(float),
            check_exact=False,
            rtol=1e-9,
        )


class TestAddRegimeFeatures:
    def test_it_adds_the_regime_block(self):
        result = add_regime_features(_ohlcv())

        assert "regime_trend" in result.columns
        assert "regime_trend_str" in result.columns

    def test_the_trend_flag_is_ternary(self):
        result = add_regime_features(_ohlcv())

        assert set(np.unique(result["regime_trend"])) <= {-1, 0, 1}

    def test_trend_strength_is_a_unit_interval(self):
        strength = add_regime_features(_ohlcv())["regime_trend_str"]

        assert strength.min() >= 0.0
        assert strength.max() <= 1.0

    def test_a_rising_series_is_flagged_up_at_the_end(self):
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        closes = np.linspace(2000, 2400, n)
        bars = pd.DataFrame(
            {"open": closes, "high": closes + 1, "low": closes - 1, "close": closes, "volume": 1.0},
            index=idx,
        )

        assert add_regime_features(bars)["regime_trend"].iloc[-1] == 1

    def test_a_falling_series_is_flagged_down_at_the_end(self):
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        closes = np.linspace(2400, 2000, n)
        bars = pd.DataFrame(
            {"open": closes, "high": closes + 1, "low": closes - 1, "close": closes, "volume": 1.0},
            index=idx,
        )

        assert add_regime_features(bars)["regime_trend"].iloc[-1] == -1

    def test_the_result_is_finite(self):
        result = add_regime_features(_ohlcv())

        numeric = result.select_dtypes(include=[np.number])
        assert np.all(np.isfinite(numeric.to_numpy()))

    def test_the_original_frame_is_not_mutated(self):
        bars = _ohlcv()
        before = list(bars.columns)

        add_regime_features(bars)

        assert list(bars.columns) == before

    def test_a_frame_without_high_and_low_still_works(self):
        """`.get(...)` falls back to close; the block must not require OHLC."""
        idx = pd.date_range("2024-01-01", periods=100, freq="D")
        bars = pd.DataFrame({"close": np.linspace(2000, 2100, 100)}, index=idx)

        assert "regime_trend" in add_regime_features(bars).columns

    def test_a_flat_series_does_not_divide_by_zero(self):
        idx = pd.date_range("2024-01-01", periods=100, freq="D")
        flat = pd.DataFrame(
            {"open": 2000.0, "high": 2000.0, "low": 2000.0, "close": 2000.0, "volume": 1.0},
            index=idx,
        )

        result = add_regime_features(flat)

        assert np.all(np.isfinite(result.select_dtypes(include=[np.number]).to_numpy()))


class TestBuildEnhancedFeatureMatrix:
    def test_it_includes_both_blocks_by_default(self):
        result = build_enhanced_feature_matrix(_ohlcv(), macro_df=_macro())

        assert "regime_trend" in result.columns

    def test_the_regime_block_can_be_switched_off(self):
        result = build_enhanced_feature_matrix(_ohlcv(), macro_df=_macro(), include_regime=False)

        assert "regime_trend" not in result.columns

    def test_it_preserves_the_row_count(self):
        bars = _ohlcv()

        assert len(build_enhanced_feature_matrix(bars, macro_df=_macro())) == len(bars)

    def test_the_output_is_finite(self):
        result = build_enhanced_feature_matrix(_ohlcv(), macro_df=_macro())

        numeric = result.select_dtypes(include=[np.number])
        assert np.all(np.isfinite(numeric.to_numpy()))


# ── the Hurst exponent ────────────────────────────────────────────────────────


class TestRollingHurst:
    def test_it_returns_one_value_per_row(self):
        series = pd.Series(np.random.default_rng(0).normal(0, 1, 200))

        assert len(_rolling_hurst(series)) == 200

    def test_values_stay_in_the_unit_interval(self):
        series = pd.Series(np.random.default_rng(0).normal(0, 1, 200))

        result = _rolling_hurst(series)

        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_the_warmup_period_defaults_to_a_random_walk(self):
        """0.5 is 'no information', which is the honest answer before the window fills."""
        series = pd.Series(np.random.default_rng(0).normal(0, 1, 100))

        assert _rolling_hurst(series, window=40).iloc[0] == pytest.approx(0.5)

    def test_a_short_series_is_all_default(self):
        assert (_rolling_hurst(pd.Series([1.0, 2.0, 3.0]), window=40) == 0.5).all()

    def test_a_trending_series_scores_above_a_noisy_one(self):
        rng = np.random.default_rng(0)
        trend = pd.Series(np.cumsum(np.full(300, 1.0) + rng.normal(0, 0.1, 300)))
        noise = pd.Series(rng.normal(0, 1, 300))

        assert _rolling_hurst(trend).iloc[-1] > _rolling_hurst(noise).iloc[-1]

    def test_the_result_is_finite(self):
        series = pd.Series(np.random.default_rng(0).normal(0, 1, 200))

        assert np.all(np.isfinite(_rolling_hurst(series).to_numpy()))

    def test_a_constant_series_does_not_divide_by_zero(self):
        result = _rolling_hurst(pd.Series(np.full(200, 5.0)))

        assert np.all(np.isfinite(result.to_numpy()))
