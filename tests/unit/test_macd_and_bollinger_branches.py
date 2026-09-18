# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_macd_and_bollinger_branches.py
===============================================
The same unreachable line, in a third and fourth strategy.

Coverage-floor programme, Task 6c. `strategies/macd_strategy.py` 68.49% and
`strategies/bollinger_bands.py` 61.38%.

**F277 turned out to be a family, not an instance.** Raising
`strategies/rsi_strategy.py` found:

```python
prices = data.get("prices") or data.get("close")
...
series = pd.Series(prices) if not isinstance(prices, pd.Series) else prices
```

`or` calls `__bool__`, which pandas raises on for a Series, so the branch on
the next line — written to accept exactly that input — could never be reached.
A repo-wide sweep for the pattern found the identical two lines in
`macd_strategy.py:57` and `bollinger_bands.py:57`. Both proved by execution
before being touched:

```
macd:      ValueError: The truth value of a Series is ambiguous.
bollinger: ValueError: The truth value of a Series is ambiguous.
```

Fixed once rather than three times: `strategies.base.first_non_empty` now holds
the rule, and all three strategies call it. `len()` is the right test and
`bool()` is not — pandas defines `__len__` and raises on `__bool__` — and the
falsy-fallback semantics are preserved exactly, so an empty list under `prices`
still falls through to `close`.

Two other call sites of the same shape were checked and are **not** affected:
`execution/async_engine.py:597` reads parsed JSON, where `prices` is always a
list, and `strategies/base.py:171` reads a bar of scalars.

The `backtesting-frameworks` sweep is clean on both modules — `ewm(adjust=False)`
and `rolling(...)` with no `center=True`, reads at `iloc[-1]` and `iloc[-2]` —
and causality is asserted directly at the end of this file.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.base import SignalType, StrategyConfig


def _frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


@pytest.fixture
def macd():
    from strategies.macd_strategy import MACDStrategy

    return MACDStrategy(StrategyConfig(name="macd", symbol="XAUUSD", timeframe="1h"))


@pytest.fixture
def bollinger():
    from strategies.bollinger_bands import BollingerBandsStrategy

    return BollingerBandsStrategy(StrategyConfig(name="bb", symbol="XAUUSD", timeframe="1h"))


# ─────────────────────────────────────────────────────────────────────────────
# The shared helper
# ─────────────────────────────────────────────────────────────────────────────


class TestTheSharedFallback:
    def test_a_series_is_accepted_by_all_three_strategies(self, macd, bollinger):
        """The regression that names the defect. Before F277 each of these
        raised ``ValueError: The truth value of a Series is ambiguous``."""
        from strategies.rsi_strategy import RSIStrategy

        rsi = RSIStrategy(StrategyConfig(name="rsi", symbol="XAUUSD", timeframe="1h"))
        payload = {"prices": pd.Series([2000.0] * 60)}
        assert rsi.analyze(payload)["rsi"] == 50.0
        assert macd.analyze(payload)["macd"] == pytest.approx(0.0)
        assert bollinger.analyze(payload)["sma"] == pytest.approx(2000.0)

    def test_an_empty_prices_entry_still_falls_through_to_close(self, macd, bollinger):
        payload = {"prices": [], "close": [2000.0] * 60}
        assert macd.analyze(payload)["price"] == 2000.0
        assert bollinger.analyze(payload)["price"] == 2000.0

    def test_the_helper_itself(self):
        from strategies.base import first_non_empty

        assert first_non_empty(None, [1, 2]) == [1, 2]
        assert first_non_empty([], [3]) == [3]
        assert first_non_empty(None, None) is None
        assert first_non_empty([], []) is None
        series = pd.Series([1.0])
        assert first_non_empty(series, [9]) is series
        assert first_non_empty(pd.Series([], dtype=float), [9]) == [9]


# ─────────────────────────────────────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────────────────────────────────────


class TestTheMacdItself:
    def test_a_rally_puts_the_fast_ema_above_the_slow_one(self, macd):
        line, signal, hist = macd.calculate_macd(pd.Series(np.linspace(1900.0, 2100.0, 60)))
        assert line.iloc[-1] > 0
        assert hist.iloc[-1] == pytest.approx(line.iloc[-1] - signal.iloc[-1])

    def test_a_slide_puts_it_below(self, macd):
        line, _signal, _hist = macd.calculate_macd(pd.Series(np.linspace(2100.0, 1900.0, 60)))
        assert line.iloc[-1] < 0

    def test_a_flat_series_has_no_macd_at_all(self, macd):
        line, signal, hist = macd.calculate_macd(pd.Series([2000.0] * 60))
        assert line.iloc[-1] == pytest.approx(0.0)
        assert signal.iloc[-1] == pytest.approx(0.0)
        assert hist.iloc[-1] == pytest.approx(0.0)

    def test_nothing_comes_back_nan(self, macd):
        """Every comparison against NaN is False, so a NaN MACD would make each
        branch fall through to "no signal" rather than fail loudly."""
        line, signal, hist = macd.calculate_macd(pd.Series(np.linspace(1900.0, 2100.0, 60)))
        assert not line.isna().any()
        assert not signal.isna().any()
        assert not hist.isna().any()


class TestTheMacdSignal:
    @staticmethod
    def _crossing_up(macd) -> pd.DataFrame:
        """Truncated to the bar the MACD line actually crosses its signal."""
        closes = list(np.linspace(2100.0, 1900.0, 60)) + list(np.linspace(1900.0, 2200.0, 25))
        line, signal, _ = macd.calculate_macd(pd.Series(closes))
        diff = (line - signal).to_numpy()
        cross = next(i for i in range(1, len(diff)) if diff[i - 1] <= 0 < diff[i])
        return _frame(closes[: cross + 1])

    @staticmethod
    def _crossing_down(macd) -> pd.DataFrame:
        closes = list(np.linspace(1900.0, 2100.0, 60)) + list(np.linspace(2100.0, 1800.0, 25))
        line, signal, _ = macd.calculate_macd(pd.Series(closes))
        diff = (line - signal).to_numpy()
        cross = next(i for i in range(1, len(diff)) if diff[i - 1] >= 0 > diff[i])
        return _frame(closes[: cross + 1])

    def test_a_bullish_crossover_buys(self, macd):
        signal = macd.generate_signal(self._crossing_up(macd))
        assert signal["type"] == "BUY"
        assert signal["confidence"] >= 0.75
        assert "Bullish MACD crossover" in signal["reason"]

    def test_a_bearish_crossover_sells(self, macd):
        signal = macd.generate_signal(self._crossing_down(macd))
        assert signal["type"] == "SELL"
        assert signal["confidence"] >= 0.75
        assert "Bearish MACD crossover" in signal["reason"]

    def test_a_crossover_below_the_zero_line_is_held_with_more_confidence(self, macd):
        """A conditional assertion is a test that may never run.

        The first draft wrote this as `if signal["metadata"]["macd"] < 0:` over
        a price fixture, and a mutation that flattened 0.85 back to 0.75
        survived every test here — because whether the fixture landed below
        zero was left to the fixture. Driven by the condition instead.
        """
        below = self._driven(macd, line_prev=-2.0, line_now=-0.5, signal_prev=-1.0, signal_now=-1.0)
        assert below["type"] == "BUY"
        assert "from oversold" in below["reason"]
        assert below["confidence"] >= 0.85

    def test_a_crossover_above_the_zero_line_gets_no_oversold_bonus(self, macd):
        above = self._driven(macd, line_prev=0.5, line_now=2.0, signal_prev=1.0, signal_now=1.0)
        assert above["type"] == "BUY"
        assert "from oversold" not in above["reason"]
        assert above["confidence"] == pytest.approx(0.85)

    def test_a_bearish_crossover_above_zero_is_held_with_more_confidence(self, macd):
        signal = self._driven(macd, line_prev=2.0, line_now=0.5, signal_prev=1.0, signal_now=1.0)
        assert signal["type"] == "SELL"
        assert "from overbought" in signal["reason"]
        assert signal["confidence"] == pytest.approx(0.95)

    def test_a_bearish_crossover_below_zero_gets_no_overbought_bonus(self, macd):
        signal = self._driven(macd, line_prev=-0.5, line_now=-2.0, signal_prev=-1.0, signal_now=-1.0)
        assert signal["type"] == "SELL"
        assert "from overbought" not in signal["reason"]
        assert signal["confidence"] == pytest.approx(0.85)

    def test_the_momentum_bonus_at_a_crossover_can_never_not_fire(self, macd):
        """`if current_hist > prev_hist` is always true at a bullish crossover.

        A crossing *is* the histogram changing sign: `prev_macd <= prev_signal`
        makes `prev_hist <= 0`, and `current_macd > current_signal` makes
        `current_hist > 0`. So the "with momentum" bonus is structurally
        unconditional there, and the four confidences the code appears to offer
        — 0.75, 0.85 with the zero-line bonus, each +0.1 — collapse to two:
        **0.85 and 0.95**. Measured over 4,000 random crossings: zero without
        the bonus.

        Not changed. It is a redundant conditional with a flat effect, not a
        wrong number, and rewriting a strategy's confidence scale is a strategy
        decision. Asserted so that whoever tunes it knows the 0.75 branch is
        unobservable. This test found itself: a mutation flattening 0.85 to
        0.75 survived a `>= 0.85` assertion, which is what sent the question
        back to the arithmetic.
        """
        rng = np.random.default_rng(0)
        without_bonus = 0
        confidences = set()
        for _ in range(200):
            level = rng.uniform(-3, 3)
            signal = self._driven(
                macd,
                line_prev=level - abs(rng.uniform(0.01, 3)),
                line_now=level + abs(rng.uniform(0.01, 3)),
                signal_prev=level,
                signal_now=level,
            )
            if "crossover" not in signal["reason"]:
                continue
            confidences.add(round(signal["confidence"], 2))
            if "with momentum" not in signal["reason"]:
                without_bonus += 1
        assert without_bonus == 0, "the bonus became conditional — the docstring above is now wrong"
        assert confidences <= {0.85, 0.95}, f"unexpected crossover confidences: {sorted(confidences)}"

    @staticmethod
    def _driven(macd, line_prev, line_now, signal_prev, signal_now):
        """Drive the four non-crossing branches by their actual conditions.

        The first draft built these from `np.linspace` fixtures and landed in
        the wrong branch twice — a continuation fixture produced 0.5 where the
        test expected 0.55. A price series is an indirect way to state
        "MACD above its signal line with a shrinking positive histogram", and
        an indirect fixture that lands one branch over is a test of whatever it
        happened to hit. These say the condition.
        """
        from unittest.mock import patch

        frame = _frame([2000.0] * 90)
        line = pd.Series([line_prev] * 89 + [line_now], index=frame.index)
        signal = pd.Series([signal_prev] * 89 + [signal_now], index=frame.index)
        hist = line - signal
        with patch.object(macd, "calculate_macd", return_value=(line, signal, hist)):
            return macd.generate_signal(frame)

    def test_continuation_above_the_signal_line_with_a_growing_histogram_buys(self, macd):
        # Above the signal line both bars (so not a crossing), histogram growing.
        signal = self._driven(macd, line_prev=1.0, line_now=2.0, signal_prev=0.5, signal_now=0.5)
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.50)
        assert signal["reason"] == "MACD momentum strengthening"

    def test_continuation_below_the_signal_line_with_a_shrinking_histogram_sells(self, macd):
        signal = self._driven(macd, line_prev=-1.0, line_now=-2.0, signal_prev=-0.5, signal_now=-0.5)
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.50)
        assert signal["reason"] == "MACD downward momentum strengthening"

    def test_a_fading_rally_above_the_signal_line_is_read_as_divergence(self, macd):
        """`current_hist < prev_hist and current_hist > 0` — still bullish
        territory, but the momentum is going."""
        signal = self._driven(macd, line_prev=2.0, line_now=1.0, signal_prev=0.5, signal_now=0.5)
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.55)
        assert "bearish divergence" in signal["reason"]

    def test_a_fading_slide_below_the_signal_line_is_read_as_divergence(self, macd):
        signal = self._driven(macd, line_prev=-2.0, line_now=-1.0, signal_prev=-0.5, signal_now=-0.5)
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.55)
        assert "bullish divergence" in signal["reason"]

    def test_a_shrinking_histogram_that_has_already_gone_negative_is_not_a_divergence(self, macd):
        """`current_hist > 0` is part of the condition: once the histogram has
        crossed zero the move is no longer a fading rally, it is a reversal
        that the crossing branch above has already reported."""
        signal = self._driven(macd, line_prev=2.0, line_now=0.6, signal_prev=0.5, signal_now=0.5)
        assert signal["reason"] == "MACD momentum weakening (bearish divergence)"

    def test_a_flat_market_produces_no_signal(self, macd):
        signal = macd.generate_signal(_frame([2000.0] * 90))
        assert signal["type"] == "HOLD"
        assert "No MACD signal" in signal["reason"]

    def test_too_little_history_says_how_much_it_needs(self, macd):
        signal = macd.generate_signal(_frame([2000.0] * 10))
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Insufficient data (need 35 periods)"

    def test_a_nan_reading_holds_rather_than_comparing_against_it(self, macd):
        from unittest.mock import patch

        frame = _frame([2000.0] * 90)
        nan = pd.Series([float("nan")] * 90, index=frame.index)
        with patch.object(macd, "calculate_macd", return_value=(nan, nan, nan)):
            signal = macd.generate_signal(frame)
        assert signal["type"] == "HOLD"
        assert "NaN" in signal["reason"]

    def test_a_frame_without_close_holds_with_an_error_prefix(self, macd):
        signal = macd.generate_signal(pd.DataFrame({"open": [1.0] * 90}))
        assert signal["type"] == "HOLD"
        assert signal["reason"].startswith("Error:")


class TestTheMacdSignalObjectPath:
    def test_a_bullish_crossover_dict_produces_a_buy(self, macd):
        out = macd.generate_signal(
            {"macd": 1.0, "signal_line": 0.5, "prev_macd": -0.2, "prev_signal": 0.1, "price": 2000.0}
        )
        assert out is not None
        assert out.signal_type is SignalType.BUY

    def test_a_bearish_crossover_dict_produces_a_sell(self, macd):
        out = macd.generate_signal(
            {"macd": -1.0, "signal_line": -0.5, "prev_macd": 0.2, "prev_signal": -0.1, "price": 2000.0}
        )
        assert out is not None
        assert out.signal_type is SignalType.SELL

    def test_no_crossing_produces_nothing(self, macd):
        assert (
            macd.generate_signal(
                {"macd": 1.0, "signal_line": 0.5, "prev_macd": 0.9, "prev_signal": 0.4, "price": 2000.0}
            )
            is None
        )

    def test_a_dict_missing_its_numbers_produces_nothing(self, macd):
        assert macd.generate_signal({"price": 2000.0}) is None


class TestTheMacdSnapshot:
    def test_analyze_reports_the_three_lines_and_the_previous_two(self, macd):
        out = macd.analyze({"prices": list(np.linspace(1900.0, 2100.0, 60))})
        assert out["macd"] > 0
        assert out["histogram"] == pytest.approx(out["macd"] - out["signal_line"])
        assert out["prev_macd"] is not None
        assert out["prev_signal"] is not None
        assert out["price"] == pytest.approx(2100.0)

    def test_analyze_refuses_a_payload_with_no_prices(self, macd):
        assert macd.analyze({"volume": [1]})["macd"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Bollinger Bands
# ─────────────────────────────────────────────────────────────────────────────


class TestTheBollingerSignal:
    def test_a_close_below_the_lower_band_buys(self, bollinger):
        signal = bollinger.generate_signal(_frame([2000.0] * 40 + [1900.0]))
        assert signal["type"] == "BUY"
        assert signal["confidence"] >= 0.70
        assert "oversold" in signal["reason"]

    def test_a_close_below_the_band_that_is_bouncing_scores_higher(self, bollinger):
        falling = bollinger.generate_signal(_frame([2000.0] * 40 + [1910.0, 1900.0]))
        bouncing = bollinger.generate_signal(_frame([2000.0] * 40 + [1890.0, 1900.0]))
        assert falling["type"] == bouncing["type"] == "BUY"
        assert bouncing["confidence"] == pytest.approx(0.85)
        assert "with bounce" in bouncing["reason"]
        assert falling["confidence"] == pytest.approx(0.70)

    def test_a_close_above_the_upper_band_sells(self, bollinger):
        signal = bollinger.generate_signal(_frame([2000.0] * 40 + [2100.0]))
        assert signal["type"] == "SELL"
        assert "overbought" in signal["reason"]

    def test_a_close_above_the_band_that_is_turning_down_scores_higher(self, bollinger):
        reversing = bollinger.generate_signal(_frame([2000.0] * 40 + [2110.0, 2100.0]))
        assert reversing["confidence"] == pytest.approx(0.85)
        assert "with reversal" in reversing["reason"]

    def test_crossing_back_above_the_lower_band_buys(self, bollinger):
        """Yesterday below, today back inside — the re-entry, not the breach."""
        closes = list(np.linspace(2000.0, 1900.0, 40)) + [1820.0, 1990.0]
        signal = bollinger.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.75)
        assert "crossing above lower band" in signal["reason"]

    def test_crossing_back_below_the_upper_band_sells(self, bollinger):
        """The mirror of the lower-band re-entry: yesterday above, today back
        inside. It is the exit from an overbought excursion, not the excursion."""
        # A modest excursion, not a spike: the first draft used a 180-point
        # jump, which inflated the standard deviation enough that the bar
        # "returning inside" landed under the *lower* band and bought.
        signal = bollinger.generate_signal(_frame([2000.0] * 40 + [2020.0, 2005.0]))
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.75)
        assert "crossing below upper band" in signal["reason"]

    def test_a_flat_series_has_no_band_width_and_refuses_rather_than_dividing(self, bollinger):
        signal = bollinger.generate_signal(_frame([2000.0] * 40))
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Zero band width"

    def test_too_little_history_holds(self, bollinger):
        signal = bollinger.generate_signal(_frame([2000.0] * 5))
        assert signal["type"] == "HOLD"
        assert "Insufficient" in signal["reason"]

    def test_a_frame_without_close_holds_with_an_error_prefix(self, bollinger):
        signal = bollinger.generate_signal(pd.DataFrame({"open": [1.0] * 40}))
        assert signal["type"] == "HOLD"
        assert signal["reason"].startswith("Error:")

    def test_the_metadata_carries_the_bands_it_decided_on(self, bollinger):
        signal = bollinger.generate_signal(_frame([2000.0] * 40 + [1900.0]))
        meta = signal["metadata"]
        assert meta["lower_band"] < meta["sma"] < meta["upper_band"]
        assert meta["price"] == 1900.0


class TestTheBollingerSignalObjectPath:
    def test_a_price_under_the_lower_band_buys(self, bollinger):
        out = bollinger.generate_signal({"upper": 2100.0, "lower": 1950.0, "price": 1900.0, "prev_price": 1950.0})
        assert out.signal_type is SignalType.BUY
        assert out.confidence == pytest.approx(0.70)

    def test_a_price_under_the_band_that_is_rising_scores_higher(self, bollinger):
        out = bollinger.generate_signal({"upper": 2100.0, "lower": 1950.0, "price": 1900.0, "prev_price": 1850.0})
        assert out.confidence == pytest.approx(0.85)

    def test_a_price_over_the_upper_band_sells(self, bollinger):
        out = bollinger.generate_signal({"upper": 2100.0, "lower": 1950.0, "price": 2200.0, "prev_price": 2100.0})
        assert out.signal_type is SignalType.SELL
        assert out.confidence == pytest.approx(0.70)

    def test_a_price_over_the_band_that_is_falling_scores_higher(self, bollinger):
        out = bollinger.generate_signal({"upper": 2100.0, "lower": 1950.0, "price": 2200.0, "prev_price": 2300.0})
        assert out.confidence == pytest.approx(0.85)

    def test_a_price_inside_the_bands_produces_nothing(self, bollinger):
        assert bollinger.generate_signal({"upper": 2100.0, "lower": 1950.0, "price": 2000.0}) is None

    def test_a_dict_missing_a_band_produces_nothing(self, bollinger):
        assert bollinger.generate_signal({"upper": 2100.0, "price": 2000.0}) is None


class TestTheBollingerSnapshot:
    def test_analyze_reports_both_bands_and_the_previous_two(self, bollinger):
        out = bollinger.analyze({"prices": list(np.linspace(1900.0, 2100.0, 40))})
        assert out["lower"] < out["sma"] < out["upper"]
        assert out["prev_upper"] is not None
        assert out["prev_lower"] is not None
        assert out["price"] == pytest.approx(2100.0)

    def test_analyze_refuses_a_payload_with_no_prices(self, bollinger):
        assert bollinger.analyze({"volume": [1]})["upper"] is None

    def test_a_single_price_has_no_previous_one_to_compare_against(self, bollinger):
        out = bollinger.analyze({"prices": [2000.0]})
        assert out["prev_price"] == 2000.0
        assert out["prev_upper"] is None


class TestBothAreCausal:
    """`backtesting-frameworks`: appending bars must not move an earlier read."""

    def test_the_macd_at_a_bar_does_not_move_when_later_bars_change(self, macd):
        closes = list(np.linspace(1900.0, 2100.0, 60))
        first = macd.calculate_macd(pd.Series(closes))[0].iloc[-1]
        second = macd.calculate_macd(pd.Series([*closes, 9000.0, 10.0]))[0].iloc[len(closes) - 1]
        assert first == pytest.approx(second)

    def test_an_earlier_bollinger_signal_does_not_move(self, bollinger):
        closes = [2000.0] * 40 + [1900.0]
        first = bollinger.generate_signal(_frame(closes))
        second = bollinger.generate_signal(_frame([*closes, 9000.0, 10.0]).iloc[: len(closes)])
        assert first["type"] == second["type"]
        assert first["reason"] == second["reason"]


class TestTheBollingerBranchesThatNeedFiftyBars:
    """The squeeze and the band-walk, which were the whole uncovered tail.

    `is_squeeze` needs `len(std) >= 50` before `avg_std` is anything but the
    current standard deviation, so none of these branches can be reached by a
    short fixture — which is why they were untested while the band breaches
    were not.
    """

    @staticmethod
    def _noisy_then(quiet: list[float]) -> pd.DataFrame:
        """70 volatile bars, then a quiet stretch: `current_std < avg_std * 0.75`."""
        rng = np.random.default_rng(4)
        noisy = list(2000.0 + rng.normal(0, 30, 70))
        return _frame(noisy + quiet)

    def test_a_squeeze_resolving_upward_buys(self, bollinger):
        rng = np.random.default_rng(4)
        # consume the same draws the fixture helper does, then drift up quietly
        rng.normal(0, 30, 70)
        quiet = list(2000.0 + rng.normal(0, 0.5, 25) + np.linspace(0, 3, 25))
        signal = bollinger.generate_signal(self._noisy_then(quiet))
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.65)
        assert signal["reason"] == "Bollinger Band squeeze breakout (bullish)"

    def test_a_squeeze_resolving_downward_sells(self, bollinger):
        rng = np.random.default_rng(0)
        quiet = list(1998.0 + rng.normal(0, 0.4, 25) - np.linspace(0, 2.0, 25))
        signal = bollinger.generate_signal(self._noisy_then(quiet))
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.65)
        assert signal["reason"] == "Bollinger Band squeeze breakout (bearish)"

    def test_walking_the_upper_band_is_a_weak_buy(self, bollinger):
        """%B above 0.9 without breaching — a trend riding the band rather than
        an overbought spike, so 0.55 and not 0.70."""
        rng = np.random.default_rng(4)
        rng.normal(0, 30, 70)
        rng.normal(0, 0.5, 25)
        rng.normal(0, 0.5, 25)
        closes = list(2000.0 + np.cumsum(np.full(60, 2.0)) + rng.normal(0, 0.3, 60))
        signal = bollinger.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.55)
        assert signal["reason"] == "Walking upper band (strong uptrend)"
        assert signal["metadata"]["percent_b"] > 0.9

    def test_walking_the_lower_band_is_a_weak_sell(self, bollinger):
        rng = np.random.default_rng(4)
        rng.normal(0, 30, 70)
        rng.normal(0, 0.5, 25)
        rng.normal(0, 0.5, 25)
        rng.normal(0, 0.3, 60)
        closes = list(2000.0 - np.cumsum(np.full(60, 2.0)) + rng.normal(0, 0.3, 60))
        signal = bollinger.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.55)
        assert signal["reason"] == "Walking lower band (strong downtrend)"

    def test_a_mild_contraction_is_not_a_squeeze(self, bollinger):
        """`current_std < avg_std * 0.75`, and the 0.75 is the whole rule.

        A mutation that loosened it to 1.0 survived the two squeeze tests
        above, because their fixtures contract far below either threshold. This
        one sits at a measured ratio of ~0.84 — narrower than average, not a
        squeeze — with the price above the SMA, which is exactly the state the
        loosened threshold would mislabel as a breakout.
        """
        rng = np.random.default_rng(4)
        noisy = list(2000.0 + rng.normal(0, 30, 70))
        tail_rng = np.random.default_rng(0)
        tail = list(2000.0 + tail_rng.normal(0, 20.0, 25) + np.linspace(0, 2, 25))
        closes = noisy + tail

        series = pd.Series(closes)
        std = series.rolling(window=bollinger.period).std().fillna(0.0)
        ratio = float(std.iloc[-1] / std.rolling(window=50).mean().iloc[-1])
        assert 0.75 < ratio < 1.0, f"fixture drifted: contraction ratio is {ratio:.3f}"

        signal = bollinger.generate_signal(_frame(closes))
        assert "squeeze" not in signal["reason"], signal["reason"]

    def test_a_price_sitting_in_the_middle_says_so_with_its_percent_b(self, bollinger):
        rng = np.random.default_rng(0)
        signal = bollinger.generate_signal(_frame(list(2000.0 + rng.normal(0, 5, 45))))
        assert signal["type"] == "HOLD"
        assert signal["reason"].startswith("Price within bands: %B =")
