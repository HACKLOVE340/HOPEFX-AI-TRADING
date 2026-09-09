# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A cached price series must know, and say, how old it is.

`data/XAUUSD_40Y.csv` has been committed for a long time and the model predicts
on it happily — `advanced_oos_v1`, `fallback: False`, 222 features, a real
probability. What has been missing is a way to *reach* it that carries where the
data came from and when it ends.

Every existing reader loses that. `api/trading.py` opens the same file inline
for charts, `backtesting/cli_runner.py` has its own `load_ohlcv_csv`, and
neither returns an as-of date. A caller gets a DataFrame that looks exactly like
a live one.

That is the hazard this module exists to close, and it is the defect family this
repository keeps finding: **a stale value presented as a current one**. The
committed series ends months before today. Anything that renders it as the live
price, or lets it satisfy a freshness check, is fabricating a market.

So `load_cached_daily()` returns a `CachedSeries` — frame plus `source`,
`as_of`, `age_days`, `is_stale` — and never a bare DataFrame. The provenance
travels with the data instead of being something the caller is trusted to
remember.

Deliberately NOT done: this is not wired into the live inference path. Cached
history reaching `size_order()` through the data-quality gate would undo
MASTER_OUTSTANDING §E12 — the gate refuses when quality is unmeasured, and a
CSV has no tick confidence to measure. Offline prediction is an explicit
caller's choice, not a silent fallback.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def series():
    from ml.cached_series import load_cached_daily

    return load_cached_daily("XAUUSD")


class TestItLoadsTheCommittedSeries:
    def test_returns_daily_ohlcv_bars(self, series) -> None:
        assert isinstance(series.frame, pd.DataFrame)
        assert list(series.frame.columns) == ["open", "high", "low", "close", "volume"]
        assert len(series.frame) > 1000, "the 40Y file should carry thousands of daily bars"

    def test_index_is_tz_aware_ascending_and_unique(self, series) -> None:
        idx = series.frame.index
        assert isinstance(idx, pd.DatetimeIndex)
        assert idx.tz is not None, "a naive index invites the timezone bugs this repo already fixed once"
        assert idx.is_monotonic_increasing
        assert idx.is_unique

    def test_prices_are_positive(self, series) -> None:
        assert (series.frame["close"] > 0).all()


class TestItMeasuresIntegrityRatherThanAssumingIt:
    """The committed 40Y file is not clean, and the loader must say so.

    Writing `assert (high >= low).all()` here failed, and the failure was the
    data, not the test: 441 of 6415 bars in XAUUSD_40Y.csv carry impossible
    OHLC — one with high < low outright, plus 236 where high is below open or
    close and 227 where low is above them. All of them sit before 2020 (416 in
    the 2000s, 25 in the 2010s) and none in the recent window the model
    predicts on, but that file is the primary source: api/trading.py prefers it
    for charts and scripts/build_50y_data.py calls it "highest quality 2000+".
    Every rolling high/low, ATR and true-range feature over an affected window
    is wrong.

    Silently repairing or dropping those bars would be inventing prices. So the
    loader counts them and hands the count to the caller, and the decision about
    what to do with a 25-year series that is 6.9% malformed stays with the owner.
    """

    def test_integrity_is_reported(self, series) -> None:
        rep = series.integrity
        assert rep.bars == len(series.frame)
        assert rep.malformed > 0, (
            "XAUUSD_40Y.csv has known-bad OHLC bars; a report of zero means the "
            "check stopped working, not that the data got better"
        )

    def test_the_report_breaks_the_violations_down(self, series) -> None:
        rep = series.integrity
        assert rep.high_below_low >= 1
        assert rep.high_below_body >= 1
        assert rep.low_above_body >= 1
        assert rep.malformed <= rep.high_below_low + rep.high_below_body + rep.low_above_body

    def test_a_clean_file_reports_clean(self) -> None:
        # The 5Y and 2Y extracts have no violations. If this ever fails, the
        # check has become over-eager rather than the data having decayed.
        from ml.cached_series import load_cached_daily

        assert load_cached_daily("XAUUSD", filename="XAUUSD_5Y.csv").integrity.malformed == 0

    def test_describe_names_the_problem_when_there_is_one(self, series) -> None:
        assert "malformed" in series.describe().lower()

    def test_describe_stays_quiet_when_the_data_is_clean(self) -> None:
        from ml.cached_series import load_cached_daily

        assert "malformed" not in load_cached_daily("XAUUSD", filename="XAUUSD_5Y.csv").describe().lower()

    def test_column_case_differences_between_files_are_absorbed(self) -> None:
        # XAUUSD_2Y.csv uses "date"; XAUUSD_5Y.csv and _40Y.csv use "Date", and
        # their column order differs too. A caller should not have to know.
        from ml.cached_series import load_cached_daily

        for name in ("XAUUSD_2Y.csv", "XAUUSD_5Y.csv", "XAUUSD_40Y.csv"):
            s = load_cached_daily("XAUUSD", filename=name)
            assert list(s.frame.columns) == ["open", "high", "low", "close", "volume"], name


class TestItCarriesItsProvenance:
    def test_names_the_file_it_came_from(self, series) -> None:
        assert series.source.name.endswith(".csv")
        assert series.source.exists()

    def test_as_of_is_the_last_bar_not_now(self, series) -> None:
        # The whole point. `as_of` must describe the DATA, never the read.
        assert series.as_of == series.frame.index[-1]
        assert series.as_of < dt.datetime.now(dt.timezone.utc), "as_of is in the future"

    def test_age_is_measured_from_the_last_bar(self, series) -> None:
        expected = (dt.datetime.now(dt.timezone.utc) - series.as_of).days
        assert abs(series.age_days - expected) <= 1

    def test_the_committed_series_reports_itself_stale(self, series) -> None:
        # It ends months ago. A loader that called this fresh would be the bug.
        assert series.age_days > 30
        assert series.is_stale is True

    def test_staleness_budget_is_explicit(self, series) -> None:
        assert series.is_stale_beyond(dt.timedelta(days=1)) is True
        assert series.is_stale_beyond(dt.timedelta(days=100_000)) is False

    def test_it_describes_itself_in_one_line(self, series) -> None:
        d = series.describe()
        assert "XAUUSD" in d
        assert str(series.as_of.date()) in d
        assert "cached" in d.lower(), "the description must not read like live data"


class TestItRefusesRatherThanGuesses:
    def test_a_missing_file_raises_and_names_it(self) -> None:
        from ml.cached_series import load_cached_daily

        with pytest.raises(FileNotFoundError) as exc:
            load_cached_daily("XAUUSD", filename="no_such_series.csv")
        assert "no_such_series.csv" in str(exc.value)

    def test_an_unknown_symbol_raises(self) -> None:
        from ml.cached_series import load_cached_daily

        with pytest.raises((FileNotFoundError, KeyError, ValueError)):
            load_cached_daily("NOT_A_SYMBOL")


class TestTheModelCanPredictOnIt:
    """The point of the exercise: the AI produces a real decision offline."""

    @pytest.mark.slow
    def test_inference_engine_serves_a_real_prediction(self, series) -> None:
        from ml.inference_engine import get_inference_engine

        out = get_inference_engine().predict(series.frame.tail(400), symbol="XAU_USD")
        assert out["fallback"] is False, f"the model abstained: {out.get('reason')!r}"
        assert out["model_version"] != "fallback"
        assert 0.0 <= out["probability"] <= 1.0
