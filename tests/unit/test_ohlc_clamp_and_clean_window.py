# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Repairing 441 impossible bars, without the repair passing as the original.

`data/XAUUSD_40Y.csv` carries 441 bars (6.9%) whose OHLC cannot have happened —
high below low, or high below the open/close body, or low above it — all before
2020. §E15 measured them and deliberately left them alone, because rewriting a
price is inventing one. The owner chose: clamp with recorded provenance, and
default to the genuinely clean 2020+ window.

Both halves matter, and the second is what keeps the first honest. A clamped
bar is a *reconstruction*: `high = max(high, open, close)` is the smallest edit
that makes the bar possible, and it is still not what the market printed. So:

* the original file is never modified;
* the repair lands in a new file beside a provenance sidecar naming every
  edited bar, its before and its after, and the sha256 of the source it came
  from;
* a loaded series knows it was repaired and says so in `describe()`;
* `CLEAN_SINCE` records the date from which each series needs no repair at all,
  and that window is what training and backtests should default to.

The failure this guards against is the one this repository keeps finding: a
value that was reconstructed, or defaulted, or never measured, reaching a
consumer that cannot tell it apart from a real one.
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def dirty_csv(tmp_path):
    """A tiny series with one clean bar and three distinct violations."""
    rows = [
        # date,       open,  high,  low,   close      -- state
        ("2019-01-01", 100.0, 105.0, 99.0, 104.0),  # clean
        ("2019-01-02", 100.0, 98.0, 99.0, 104.0),  # high < low AND high < body
        ("2019-01-03", 100.0, 105.0, 101.5, 104.0),  # low > open
        ("2019-01-04", 100.0, 103.0, 99.0, 104.0),  # high < close
    ]
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])
    frame["volume"] = 1000.0
    path = tmp_path / "TESTSYM_dirty.csv"
    frame.to_csv(path, index=False)
    return path


def _read(path):
    frame = pd.read_csv(path)
    frame.columns = [c.lower() for c in frame.columns]
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    return frame.set_index("date").sort_index()


class TestClampingMakesEveryBarPossible:
    def test_the_output_has_no_violations(self, dirty_csv, tmp_path):
        from scripts.clamp_ohlc import clamp_file

        out, _ = clamp_file(dirty_csv, tmp_path / "out.csv")
        f = _read(out)
        assert (f["high"] >= f["low"]).all()
        assert (f["high"] >= f[["open", "close"]].max(axis=1)).all()
        assert (f["low"] <= f[["open", "close"]].min(axis=1)).all()

    def test_clean_bars_are_untouched(self, dirty_csv, tmp_path):
        # The smallest possible edit. A repair that moves a bar nobody
        # complained about is a second, unrecorded fabrication.
        from scripts.clamp_ohlc import clamp_file

        out, _ = clamp_file(dirty_csv, tmp_path / "out.csv")
        before, after = _read(dirty_csv), _read(out)
        clean_day = pd.Timestamp("2019-01-01", tz="UTC")
        for col in ("open", "high", "low", "close", "volume"):
            assert before.loc[clean_day, col] == after.loc[clean_day, col], col

    def test_the_open_and_close_are_never_altered(self, dirty_csv, tmp_path):
        # Only the extremes are reconstructed. Open and close are prints.
        from scripts.clamp_ohlc import clamp_file

        out, _ = clamp_file(dirty_csv, tmp_path / "out.csv")
        before, after = _read(dirty_csv), _read(out)
        pd.testing.assert_series_equal(before["open"], after["open"])
        pd.testing.assert_series_equal(before["close"], after["close"])

    def test_the_source_file_is_not_modified(self, dirty_csv, tmp_path):
        from scripts.clamp_ohlc import clamp_file

        original = dirty_csv.read_bytes()
        clamp_file(dirty_csv, tmp_path / "out.csv")
        assert dirty_csv.read_bytes() == original, "the clamp edited the source in place"


class TestEveryEditIsRecorded:
    def test_provenance_names_each_changed_bar(self, dirty_csv, tmp_path):
        from scripts.clamp_ohlc import clamp_file

        _, prov_path = clamp_file(dirty_csv, tmp_path / "out.csv")
        prov = json.loads(prov_path.read_text())
        edited = {e["date"] for e in prov["edits"]}
        assert edited == {"2019-01-02", "2019-01-03", "2019-01-04"}
        assert "2019-01-01" not in edited

    def test_each_edit_carries_before_and_after(self, dirty_csv, tmp_path):
        from scripts.clamp_ohlc import clamp_file

        _, prov_path = clamp_file(dirty_csv, tmp_path / "out.csv")
        edit = next(e for e in json.loads(prov_path.read_text())["edits"] if e["date"] == "2019-01-02")
        assert edit["before"]["high"] == 98.0
        assert edit["after"]["high"] == 104.0  # max(high, open, close)
        assert edit["before"]["low"] == 99.0
        assert edit["after"]["low"] == 99.0  # already below the body: unchanged

    def test_provenance_fingerprints_the_source(self, dirty_csv, tmp_path):
        # So a later reader can tell whether the repair still matches its input.
        from scripts.clamp_ohlc import clamp_file

        _, prov_path = clamp_file(dirty_csv, tmp_path / "out.csv")
        prov = json.loads(prov_path.read_text())
        assert prov["source"]["name"] == dirty_csv.name
        assert len(prov["source"]["sha256"]) == 64
        assert prov["rule"]
        assert prov["generated_at"]

    def test_provenance_counts_agree_with_the_edits(self, dirty_csv, tmp_path):
        from scripts.clamp_ohlc import clamp_file

        _, prov_path = clamp_file(dirty_csv, tmp_path / "out.csv")
        prov = json.loads(prov_path.read_text())
        assert prov["bars_total"] == 4
        assert prov["bars_edited"] == len(prov["edits"]) == 3


class TestARepairedSeriesSaysSo:
    def test_describe_reports_the_repair(self, dirty_csv, tmp_path):
        from ml.cached_series import load_series_file
        from scripts.clamp_ohlc import clamp_file

        out, _ = clamp_file(dirty_csv, tmp_path / "out.csv")
        series = load_series_file(out, symbol="TESTSYM")
        assert series.repaired is True
        assert "repaired" in series.describe().lower()
        assert "3" in series.describe(), "the number of reconstructed bars is not shown"

    def test_an_unrepaired_series_does_not_claim_a_repair(self, dirty_csv):
        from ml.cached_series import load_series_file

        series = load_series_file(dirty_csv, symbol="TESTSYM")
        assert series.repaired is False
        assert "repaired" not in series.describe().lower()


class TestTheCleanWindowIsRecordedAndUsable:
    def test_clean_since_names_the_date_the_data_stops_needing_repair(self):
        from ml.cached_series import CLEAN_SINCE

        assert CLEAN_SINCE["XAUUSD"] == dt.date(2020, 1, 1)

    def test_since_trims_the_series(self):
        from ml.cached_series import load_cached_daily

        series = load_cached_daily("XAUUSD", since=dt.date(2020, 1, 1))
        assert series.frame.index[0].date() >= dt.date(2020, 1, 1)

    def test_the_clean_window_of_the_committed_file_really_is_clean(self):
        # The claim behind the whole option: 2020+ needs no repair at all.
        from ml.cached_series import CLEAN_SINCE, load_cached_daily

        series = load_cached_daily("XAUUSD", since=CLEAN_SINCE["XAUUSD"])
        assert series.integrity.malformed == 0, (
            f"the window advertised as clean is not: {series.integrity.summary()}"
        )

    def test_the_full_history_is_still_reachable_on_request(self):
        from ml.cached_series import load_cached_daily

        assert load_cached_daily("XAUUSD").frame.index[0].year < 2010
