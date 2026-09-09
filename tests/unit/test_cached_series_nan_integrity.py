# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`IntegrityReport` called a series with NaN prices clean.

`_check_integrity` decides whether a bar is possible with three comparisons:

    hl = frame["high"] < frame["low"]
    hb = frame["high"] < body_hi
    lb = frame["low"]  > body_lo

Every comparison against NaN is False, so a bar whose high or low is missing
satisfies all three and is counted as fine. The report then says "no OHLC
violations" about a series that cannot be used for anything.

This is the finiteness trap `.claude/skills/hopefx-invariants` names outright —
"comparing floats before a finite guard: NaN passes every comparison" — and it
was found by the repository's own analyzer (`security/code_analyzer.py`,
category `nan_leak`), which is the only reason it is a test rather than a
surprise in a backtest.

It matters more here than in most places because the whole point of this module
is that a caller cannot tell a good series from a bad one by looking at a
DataFrame. An integrity report that clears bad data is worse than no report: it
is the fabricated-measurement shape the rest of this work has been removing.

A NaN bar is not "malformed" in the same sense as high < low — nothing
contradicts anything, the value is simply absent — so it is counted separately
and folded into the total, rather than being reported as an impossible price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit

from ml.cached_series import _check_integrity


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


class TestAMissingPriceIsNotACleanBar:
    def test_a_nan_high_is_counted(self) -> None:
        report = _check_integrity(_frame([(10.0, np.nan, 9.0, 9.5)]))
        assert not report.clean, "a bar with no high was reported as a valid bar"
        assert report.non_finite == 1

    def test_a_nan_low_is_counted(self) -> None:
        assert _check_integrity(_frame([(10.0, 11.0, np.nan, 9.5)])).non_finite == 1

    def test_a_nan_body_is_counted(self) -> None:
        # open/close are the prints; a missing one makes the extremes unjudgeable.
        assert _check_integrity(_frame([(np.nan, 11.0, 9.0, 9.5)])).non_finite == 1

    def test_an_infinite_price_is_counted(self) -> None:
        assert _check_integrity(_frame([(10.0, np.inf, 9.0, 9.5)])).non_finite == 1

    def test_it_counts_toward_the_total(self) -> None:
        report = _check_integrity(_frame([(10.0, np.nan, 9.0, 9.5), (10.0, 11.0, 9.0, 9.5)]))
        assert report.malformed == 1
        assert report.bars == 2

    def test_the_summary_says_so(self) -> None:
        summary = _check_integrity(_frame([(10.0, np.nan, 9.0, 9.5)])).summary()
        assert "non-finite" in summary, summary


class TestRealViolationsStillCountAsBefore:
    def test_high_below_low(self) -> None:
        report = _check_integrity(_frame([(10.0, 8.0, 9.0, 9.5)]))
        assert report.high_below_low == 1
        assert report.non_finite == 0

    def test_a_sound_bar_is_clean(self) -> None:
        report = _check_integrity(_frame([(10.0, 11.0, 9.0, 9.5)]))
        assert report.clean
        assert report.summary() == "no OHLC violations"

    def test_a_nan_bar_is_not_double_counted_as_an_impossible_price(self) -> None:
        """A missing value contradicts nothing — reporting it as high<low would
        put a violation in the record that the data does not contain."""
        report = _check_integrity(_frame([(10.0, np.nan, 9.0, 9.5)]))
        assert (report.high_below_low, report.high_below_body, report.low_above_body) == (0, 0, 0)
        assert report.malformed == 1


class TestTheAnalyzerAgrees:
    def test_the_module_no_longer_trips_the_nan_leak_rule(self) -> None:
        from security.code_analyzer import scan_codebase

        offenders = [f for f in scan_codebase() if f.file == "ml/cached_series.py"]
        assert not offenders, [f.snippet for f in offenders]
