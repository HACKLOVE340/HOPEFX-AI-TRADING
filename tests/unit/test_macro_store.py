# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for ml/macro_store.py

Verifies:
- update() upserts single observations
- load_csv() loads and parses CSV correctly
- load_csv() silently skips missing files
- align_to_hourly() forward-fills daily values to hourly bars
- align_to_hourly() handles missing series with zeros
- align_to_hourly() handles timezone-naive hourly index
- snapshot() returns latest values
- Multiple series don't interfere
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_store():
    from ml.macro_store import MacroStore

    return MacroStore()


def _hourly_index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="h", tz="UTC")


def _make_ohlcv(start: str = "2026-01-05", periods: int = 48) -> pd.DataFrame:
    idx = _hourly_index(start, periods)
    n = len(idx)
    return pd.DataFrame(
        {
            "open": np.random.uniform(2000, 2100, n),
            "high": np.random.uniform(2050, 2150, n),
            "low": np.random.uniform(1950, 2050, n),
            "close": np.random.uniform(2000, 2100, n),
            "volume": np.random.uniform(1000, 5000, n),
        },
        index=idx,
    )


# ── update() ─────────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_creates_series(self):
        store = _make_store()
        store.update("dxy", "2026-01-05", 102.34)
        assert "dxy" in store.series_names()

    def test_update_upserts_value(self):
        store = _make_store()
        store.update("dxy", "2026-01-05", 102.34)
        store.update("dxy", "2026-01-05", 103.00)  # overwrite
        assert store._series["dxy"].iloc[-1] == pytest.approx(103.00)

    def test_update_multiple_dates_sorted(self):
        store = _make_store()
        store.update("dxy", "2026-01-07", 104.0)
        store.update("dxy", "2026-01-05", 102.0)
        store.update("dxy", "2026-01-06", 103.0)
        dates = store._series["dxy"].index.tolist()
        assert dates == sorted(dates)

    def test_update_accepts_datetime_object(self):
        from datetime import date as dt_date

        store = _make_store()
        store.update("us10y", dt_date(2026, 1, 5), 4.25)
        assert len(store._series["us10y"]) == 1


# ── load_csv() ────────────────────────────────────────────────────────────────


class TestLoadCsv:
    def test_load_csv_parses_correctly(self, tmp_path):
        csv = tmp_path / "dxy.csv"
        csv.write_text("date,value\n2026-01-05,102.34\n2026-01-06,101.89\n2026-01-07,103.10\n")
        store = _make_store()
        n = store.load_csv(csv, "dxy")
        assert n == 3
        assert "dxy" in store.series_names()
        assert store._series["dxy"].iloc[0] == pytest.approx(102.34)

    def test_load_csv_missing_file_returns_zero(self):
        store = _make_store()
        n = store.load_csv("/nonexistent/path/dxy.csv", "dxy")
        assert n == 0
        assert "dxy" not in store.series_names()

    def test_load_csv_custom_column_names(self, tmp_path):
        csv = tmp_path / "yield.csv"
        csv.write_text("dt,yield_val\n2026-01-05,4.25\n2026-01-06,4.30\n")
        store = _make_store()
        n = store.load_csv(csv, "us10y", date_col="dt", value_col="yield_val")
        assert n == 2

    def test_load_csv_drops_na_rows(self, tmp_path):
        csv = tmp_path / "data.csv"
        csv.write_text("date,value\n2026-01-05,102.34\n2026-01-06,\n2026-01-07,103.10\n")
        store = _make_store()
        n = store.load_csv(csv, "dxy")
        assert n == 2  # NaN row dropped


# ── align_to_hourly() ─────────────────────────────────────────────────────────


class TestAlignToHourly:
    def test_forward_fill_propagates_daily_to_hourly(self):
        store = _make_store()
        # Monday value should fill all Monday+Tuesday hourly bars
        store.update("dxy", "2026-01-05", 102.34)  # Monday
        store.update("dxy", "2026-01-06", 103.00)  # Tuesday

        ohlcv = _make_ohlcv("2026-01-05 00:00", periods=48)  # Mon + Tue
        result = store.align_to_hourly(ohlcv)

        assert "dxy" in result.columns
        # All Monday bars should have Monday's value
        monday_bars = result[result.index.date == pd.Timestamp("2026-01-05").date()]
        assert np.allclose(monday_bars["dxy"].values, 102.34)

    def test_missing_series_is_nan_not_zero(self):
        """A series that is not loaded is unknown, and 0.0 is not unknown.

        This asserted 0.0 until the macro-staleness work. A US 10Y yield of
        0.0 — or a VIX of 0.0 — is not "no data", it is an extreme real
        reading, and `_classify_macro` reads a zero VIX as LOW_VOL. NaN routes
        to `InferenceEngine._features_are_unusable`, which abstains.
        """
        store = _make_store()
        # Only load dxy, not us10y
        store.update("dxy", "2026-01-05", 102.34)

        ohlcv = _make_ohlcv()
        result = store.align_to_hourly(ohlcv, series=["dxy", "us10y"])

        assert "us10y" in result.columns
        assert result["us10y"].isna().all()
        assert not (result["us10y"] == 0.0).any()

    def test_empty_store_returns_empty_dataframe(self):
        store = _make_store()
        ohlcv = _make_ohlcv()
        result = store.align_to_hourly(ohlcv)
        assert result.empty or len(result.columns) == 0

    def test_timezone_naive_ohlcv_is_handled(self):
        store = _make_store()
        store.update("dxy", "2026-01-05", 102.34)

        # Timezone-naive index
        idx = pd.date_range("2026-01-05", periods=24, freq="h")  # no tz
        ohlcv = pd.DataFrame({"close": np.ones(24)}, index=idx)

        result = store.align_to_hourly(ohlcv)
        assert "dxy" in result.columns
        assert len(result) == 24

    def test_result_has_same_length_as_ohlcv(self):
        store = _make_store()
        store.update("dxy", "2026-01-05", 102.34)
        store.update("us10y", "2026-01-05", 4.25)

        ohlcv = _make_ohlcv(periods=72)
        result = store.align_to_hourly(ohlcv)
        assert len(result) == len(ohlcv)

    def test_leading_bars_before_first_observation_filled_with_zero(self):
        store = _make_store()
        # Data starts Jan 6, but OHLCV starts Jan 5
        store.update("dxy", "2026-01-06", 102.34)

        ohlcv = _make_ohlcv("2026-01-05 00:00", periods=48)
        result = store.align_to_hourly(ohlcv)

        # Jan 5 bars have no prior observation → filled with 0
        jan5_bars = result[result.index.date == pd.Timestamp("2026-01-05").date()]
        assert (jan5_bars["dxy"] == 0.0).all()


# ── snapshot() ───────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_returns_latest_values(self):
        store = _make_store()
        store.update("dxy", "2026-01-05", 102.34)
        store.update("dxy", "2026-01-06", 103.00)
        store.update("us10y", "2026-01-05", 4.25)

        snap = store.snapshot()
        assert snap["dxy"]["value"] == pytest.approx(103.00)
        assert snap["dxy"]["date"] == "2026-01-06"
        assert snap["us10y"]["value"] == pytest.approx(4.25)

    def test_snapshot_empty_store(self):
        store = _make_store()
        assert store.snapshot() == {}

    def test_len_returns_series_count(self):
        store = _make_store()
        store.update("dxy", "2026-01-05", 102.0)
        store.update("us10y", "2026-01-05", 4.25)
        assert len(store) == 2
