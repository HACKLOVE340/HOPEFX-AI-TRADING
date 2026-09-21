# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_cognitive_engine.py
===================================
`brain/cognitive_engine.py` had no tests at all.

It is 76 statements of pure numerical analysis — EMA trend classification,
RSI momentum, Bollinger band-width volatility, rolling support/resistance —
reached by nothing in the suite, so every one of its edges was unverified.
It was also invisible to the `brain/` coverage gate, because `.coveragerc`
never listed `brain` as a source and so never instrumented it.

Two behaviours here are worth pinning rather than merely executing:

* `analyze_trend` classifies "sideways" inside a **0.1 % band** around the
  long EMA. Without a test, that band is a magic number nobody can change
  safely.
* `calculate_momentum` divides by a rolling mean of losses. A window with no
  down bars makes that mean 0, and the guard is `loss.replace(0, np.nan)` —
  so an unbroken rally yields NaN, not a ZeroDivisionError and not 100. That
  is a real, load-bearing distinction for any caller doing `momentum > 55`,
  because every comparison against NaN is False.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from brain.cognitive_engine import CognitiveEngine

pytestmark = pytest.mark.unit


def _frame(closes, highs=None, lows=None):
    """Build an OHLCV frame with a DatetimeIndex, column order open/high/low/close/volume."""
    n = len(closes)
    closes = [float(c) for c in closes]
    highs = [c * 1.001 for c in closes] if highs is None else [float(h) for h in highs]
    lows = [c * 0.999 for c in closes] if lows is None else [float(low) for low in lows]
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1_000.0] * n,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="1h"),
    )


def _rising(n=60, start=2000.0, step=2.0):
    return _frame([start + i * step for i in range(n)])


def _falling(n=60, start=2000.0, step=2.0):
    return _frame([start - i * step for i in range(n)])


def _flat(n=60, level=2000.0):
    return _frame([level] * n)


class TestConstruction:
    def test_it_rejects_none(self):
        with pytest.raises(ValueError, match="non-empty"):
            CognitiveEngine(None)

    def test_it_rejects_an_empty_frame(self):
        with pytest.raises(ValueError, match="non-empty"):
            CognitiveEngine(pd.DataFrame())

    def test_it_copies_the_caller_s_frame(self):
        """Mutating the engine must not reach back into the caller's data."""
        df = _rising(30)
        engine = CognitiveEngine(df)

        engine.data.loc[engine.data.index[0], "close"] = -1.0

        assert df["close"].iloc[0] != -1.0

    def test_the_analysis_fields_start_empty(self):
        engine = CognitiveEngine(_rising(30))

        assert engine.trends == []
        assert engine.momentum is None
        assert engine.volatility is None
        assert engine.support is None
        assert engine.resistance is None
        assert engine.sentiment is None


class TestAnalyzeTrend:
    def test_a_rising_series_is_an_uptrend(self):
        assert CognitiveEngine(_rising()).analyze_trend() == "uptrend"

    def test_a_falling_series_is_a_downtrend(self):
        assert CognitiveEngine(_falling()).analyze_trend() == "downtrend"

    def test_a_flat_series_is_sideways(self):
        assert CognitiveEngine(_flat()).analyze_trend() == "sideways"

    def test_a_drift_inside_the_tenth_of_a_percent_band_is_still_sideways(self):
        """The 0.1 % band is the whole reason 'sideways' exists — pin it."""
        # A drift far too small to clear 0.1 % of a 2000-level price (=2.0).
        engine = CognitiveEngine(_frame([2000.0 + i * 0.001 for i in range(60)]))

        assert engine.analyze_trend() == "sideways"

    def test_every_call_appends_to_the_trend_history(self):
        engine = CognitiveEngine(_rising())

        engine.analyze_trend()
        engine.analyze_trend()

        assert engine.trends == ["uptrend", "uptrend"]

    def test_the_windows_are_configurable(self):
        engine = CognitiveEngine(_rising())

        assert engine.analyze_trend(short_window=5, long_window=20) == "uptrend"

    def test_windows_close_together_let_the_band_swallow_a_real_trend(self):
        """A consequence of the 0.1 % band that is easy to configure into.

        On a steady +2/bar ramp the gap between a span-3 and a span-5 EMA is
        about 2.0, while 0.1 % of a ~2100 price is about 2.1. So the *same
        series* that is plainly an uptrend at the default 9/21 windows reports
        "sideways" at 3/5 — the band is absolute, not relative to the window
        separation. Anyone tuning these windows down needs to know that.
        """
        engine = CognitiveEngine(_rising())

        assert engine.analyze_trend(short_window=3, long_window=5) == "sideways"
        assert engine.analyze_trend() == "uptrend"

    def test_it_falls_back_to_the_fourth_column_when_close_is_absent(self):
        """The positional fallback (iloc[:, 3]) is a documented path."""
        df = _rising()
        df.columns = ["o", "h", "low_", "c", "v"]  # no 'close'

        assert CognitiveEngine(df).analyze_trend() == "uptrend"


class TestCalculateMomentum:
    def test_a_mixed_series_gives_an_rsi_between_zero_and_one_hundred(self):
        closes = [2000 + (7 * i % 23) - 11 for i in range(80)]
        momentum = CognitiveEngine(_frame(closes)).calculate_momentum()

        assert 0.0 <= momentum <= 100.0

    def test_a_sustained_rally_has_no_losses_and_so_yields_nan(self):
        """Not 100, and not a ZeroDivisionError.

        `loss.replace(0, np.nan)` turns the empty-loss window into NaN, so the
        RSI is NaN. Callers comparing `momentum > 55` therefore get False on
        the strongest possible uptrend — worth knowing, and worth pinning.
        """
        momentum = CognitiveEngine(_rising()).calculate_momentum()

        assert math.isnan(momentum)

    def test_a_sustained_selloff_gives_an_rsi_of_zero(self):
        momentum = CognitiveEngine(_falling()).calculate_momentum()

        assert momentum == pytest.approx(0.0)

    def test_the_result_is_cached_on_the_instance(self):
        engine = CognitiveEngine(_falling())
        returned = engine.calculate_momentum()

        assert engine.momentum == pytest.approx(returned)

    def test_the_period_is_configurable(self):
        engine = CognitiveEngine(_falling())

        assert engine.calculate_momentum(period=5) == pytest.approx(0.0)

    def test_a_window_longer_than_the_series_yields_nan(self):
        momentum = CognitiveEngine(_falling(n=10)).calculate_momentum(period=50)

        assert math.isnan(momentum)


class TestAssessVolatility:
    def test_a_flat_series_has_zero_band_width(self):
        assert CognitiveEngine(_flat()).assess_volatility() == pytest.approx(0.0)

    def test_a_choppy_series_is_more_volatile_than_a_calm_one(self):
        calm = CognitiveEngine(_frame([2000 + (i % 2) * 0.5 for i in range(60)]))
        choppy = CognitiveEngine(_frame([2000 + (i % 2) * 60.0 for i in range(60)]))

        assert choppy.assess_volatility() > calm.assess_volatility()

    def test_the_result_is_non_negative(self):
        assert CognitiveEngine(_rising()).assess_volatility() >= 0.0

    def test_the_result_is_cached_on_the_instance(self):
        engine = CognitiveEngine(_rising())
        returned = engine.assess_volatility()

        assert engine.volatility == pytest.approx(returned)

    def test_a_window_longer_than_the_series_yields_nan(self):
        volatility = CognitiveEngine(_rising(n=10)).assess_volatility(period=50)

        assert math.isnan(volatility)


class TestDetectSupportResistance:
    def test_it_returns_the_low_and_high_of_the_lookback(self):
        df = _frame([2000.0] * 10, highs=[2010.0] * 10, lows=[1990.0] * 10)
        support, resistance = CognitiveEngine(df).detect_support_resistance()

        assert support == pytest.approx(1990.0)
        assert resistance == pytest.approx(2010.0)

    def test_support_never_exceeds_resistance(self):
        support, resistance = CognitiveEngine(_rising()).detect_support_resistance()

        assert support <= resistance

    def test_the_lookback_window_is_honoured(self):
        """An extreme outside the window must not be reported."""
        closes = [5000.0] + [2000.0] * 40
        df = _frame(closes)
        _, resistance = CognitiveEngine(df).detect_support_resistance(lookback=10)

        assert resistance < 3000.0

    def test_the_results_are_cached_on_the_instance(self):
        engine = CognitiveEngine(_rising())
        support, resistance = engine.detect_support_resistance()

        assert engine.support == pytest.approx(support)
        assert engine.resistance == pytest.approx(resistance)

    def test_it_falls_back_to_positional_columns(self):
        df = _frame([2000.0] * 10, highs=[2010.0] * 10, lows=[1990.0] * 10)
        df.columns = ["a", "b", "c", "d", "e"]  # no 'high'/'low'
        support, resistance = CognitiveEngine(df).detect_support_resistance()

        assert support == pytest.approx(1990.0)
        assert resistance == pytest.approx(2010.0)


class TestSentiment:
    def test_no_score_is_neutral(self):
        assert CognitiveEngine(_rising()).perform_sentiment_analysis() == 0.0

    def test_a_score_passes_through(self):
        assert CognitiveEngine(_rising()).perform_sentiment_analysis(0.4) == pytest.approx(0.4)

    @pytest.mark.parametrize(
        ("given", "expected"),
        [(5.0, 1.0), (-5.0, -1.0), (1.0, 1.0), (-1.0, -1.0)],
    )
    def test_it_clamps_to_the_unit_interval(self, given, expected):
        assert CognitiveEngine(_rising()).perform_sentiment_analysis(given) == pytest.approx(expected)

    def test_an_integer_is_coerced_to_float(self):
        result = CognitiveEngine(_rising()).perform_sentiment_analysis(0)

        assert isinstance(result, float)


class TestCompositeSignal:
    def test_it_reports_every_documented_key(self):
        signal = CognitiveEngine(_rising()).composite_signal()

        assert set(signal) == {
            "trend",
            "momentum",
            "volatility",
            "support",
            "resistance",
            "sentiment",
            "signal_strength",
        }

    def test_sentiment_is_a_number_rather_than_none(self):
        """`composite_signal` documents itself as running *all* analyses.

        It ran four of the five and left `sentiment` at its `None` initial
        value, so the one key a caller is most likely to feed into arithmetic
        was the one that raised `TypeError`. It now defaults to neutral, the
        same value `perform_sentiment_analysis()` produces with no score.
        """
        signal = CognitiveEngine(_rising()).composite_signal()

        assert signal["sentiment"] == pytest.approx(0.0)

    def test_an_explicit_sentiment_is_not_overwritten(self):
        engine = CognitiveEngine(_rising())
        engine.perform_sentiment_analysis(-0.8)

        assert engine.composite_signal()["sentiment"] == pytest.approx(-0.8)

    def test_a_confirmed_downtrend_is_a_strong_signal(self):
        """Falling series: trend is down and RSI pins at 0, so both legs agree."""
        signal = CognitiveEngine(_falling()).composite_signal()

        assert signal["trend"] == "downtrend"
        assert signal["signal_strength"] == pytest.approx(0.75)

    def test_a_directionless_market_is_a_weak_signal(self):
        signal = CognitiveEngine(_flat()).composite_signal()

        assert signal["trend"] == "sideways"
        assert signal["signal_strength"] == pytest.approx(0.25)

    def test_a_trend_the_momentum_does_not_confirm_is_a_weak_signal(self):
        """An uptrend whose RSI is NaN fails `momentum > 55`, so strength stays low."""
        signal = CognitiveEngine(_rising()).composite_signal()

        assert signal["trend"] == "uptrend"
        assert signal["signal_strength"] == pytest.approx(0.25)

    def test_it_populates_the_instance_fields_it_reports(self):
        engine = CognitiveEngine(_falling())
        signal = engine.composite_signal()

        assert engine.trends == ["downtrend"]
        assert engine.momentum == pytest.approx(signal["momentum"])
        assert engine.support == pytest.approx(signal["support"])
        assert engine.resistance == pytest.approx(signal["resistance"])

    def test_the_strength_is_always_a_probability(self):
        for frame in (_rising(), _falling(), _flat()):
            assert 0.0 <= CognitiveEngine(frame).composite_signal()["signal_strength"] <= 1.0


class TestItIsReachableFromThePackage:
    def test_the_module_imports_under_its_package_path(self):
        """It is named in `brain/__init__` only inside a docstring.

        Nothing imports it, which is how it reached zero coverage. Assert the
        import path the docstring advertises actually resolves.
        """
        import importlib

        module = importlib.import_module("brain.cognitive_engine")

        assert module.CognitiveEngine is CognitiveEngine

    def test_numpy_is_used_for_the_loss_guard(self):
        """Guards against the import being dropped as 'unused'."""
        engine = CognitiveEngine(_rising())

        assert np.isnan(engine.calculate_momentum())
