# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_ema_crossover_branches.py
==========================================
Every branch `EMAcrossoverStrategy` can take, and one label that is wrong.

Coverage-floor programme, Task 6c. 77.45% → the floor, with six of the nine
uncovered arcs being the continuation and reversal branches — the ones this
strategy spends almost all of its time in, since a crossover happens on a
handful of bars and a trend persists across the rest.

**The `backtesting-frameworks` bias sweep comes back clean here**, and that is
worth stating rather than leaving implicit: `close.ewm(span=..., adjust=False)`
is causal by construction, `prev_*` reads `iloc[-2]`, and nothing reaches
forward. Unlike its neighbour `strategies/breakout.py` (F275), this module's
windows are honest. These tests are coverage, not repair.

One thing is asserted rather than fixed — see
`TestTheMomentumBonusIsMisnamed`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def strategy():
    from strategies.ema_crossover import EMAcrossoverStrategy

    return EMAcrossoverStrategy("ema", "XAUUSD", MagicMock(), fast_period=12, slow_period=26)


def _frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _emas(strategy, closes: list[float]) -> tuple[float, float, float, float]:
    """The four numbers the branch logic actually reads, computed the same way."""
    close = pd.Series(closes)
    fast = close.ewm(span=strategy.fast_period, adjust=False).mean()
    slow = close.ewm(span=strategy.slow_period, adjust=False).mean()
    return float(fast.iloc[-2]), float(slow.iloc[-2]), float(fast.iloc[-1]), float(slow.iloc[-1])


class TestTheCrossings:
    def test_fast_crossing_up_through_slow_is_a_buy(self, strategy):
        # A long decline sets fast below slow; a sharp rally pulls it back through.
        # Truncated at the bar the crossing actually lands on: the EMAs cross
        # at index 45, so bar 45 is the one where prev <= and cur >.
        closes = (list(np.linspace(2000.0, 1900.0, 40)) + list(np.linspace(1900.0, 2100.0, 12)))[:46]
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert prev_f <= prev_s and cur_f > cur_s, "fixture does not straddle the crossing"

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] >= 0.80
        assert "Bullish EMA crossover" in signal["reason"]
        assert signal["metadata"]["trend"] == "bullish"

    def test_fast_crossing_down_through_slow_is_a_sell(self, strategy):
        closes = (list(np.linspace(1900.0, 2000.0, 40)) + list(np.linspace(2000.0, 1800.0, 12)))[:46]
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert prev_f >= prev_s and cur_f < cur_s, "fixture does not straddle the crossing"

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] >= 0.80
        assert "Bearish EMA crossover" in signal["reason"]
        assert signal["metadata"]["trend"] == "bearish"


class TestTheExactTouch:
    """`prev_fast <= prev_slow`, not `<`. A mutation found this untested.

    Tightening the comparison to `<` survived every other test here, and it is
    not a distinction without a market meaning: after a dead-flat stretch the
    two EMAs are *exactly* equal, so the first bar that rises out of it has
    `prev_fast == prev_slow`. Under `<` that bar is misread as a trend
    continuation at 0.60 instead of a fresh crossover at 0.80 — the strategy
    would under-weight the cleanest setup it can see, a break out of a
    flat range.
    """

    def test_the_first_rise_out_of_a_flat_range_is_a_crossover_not_a_continuation(self, strategy):
        closes = [2000.0] * 60 + [2010.0]
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert prev_f == prev_s, "fixture is not perfectly flat before the rise"
        assert cur_f > cur_s

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] >= 0.80, "an exact touch was read as a continuation"
        assert "Bullish EMA crossover" in signal["reason"]

    def test_the_first_fall_out_of_a_flat_range_is_a_crossover_not_a_continuation(self, strategy):
        closes = [2000.0] * 60 + [1990.0]
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert prev_f == prev_s
        assert cur_f < cur_s

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] >= 0.80
        assert "Bearish EMA crossover" in signal["reason"]


class TestTheContinuations:
    """Where the strategy spends its time, and where it was untested."""

    def test_both_emas_rising_above_the_slow_is_a_continuation_buy(self, strategy):
        closes = list(np.linspace(1900.0, 2200.0, 60))
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert cur_f > cur_s and cur_f > prev_f and cur_s > prev_s

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.60)
        assert signal["reason"] == "Strong uptrend continuation"

    def test_both_emas_falling_below_the_slow_is_a_continuation_sell(self, strategy):
        closes = list(np.linspace(2200.0, 1900.0, 60))
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert cur_f < cur_s and cur_f < prev_f and cur_s < prev_s

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.60)
        assert signal["reason"] == "Strong downtrend continuation"


class TestTheReversalWarnings:
    def test_a_fast_ema_turning_down_inside_an_uptrend_is_a_sell(self, strategy):
        """Still above the slow EMA, but rolling over. 0.55, not 0.80."""
        closes = list(np.linspace(1900.0, 2300.0, 60)) + [2150.0, 2050.0]
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert cur_f > cur_s, "fixture left the uptrend entirely"
        assert cur_f < prev_f, "fast EMA is not turning down"

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.55)
        assert signal["reason"] == "Uptrend weakening"

    def test_a_fast_ema_turning_up_inside_a_downtrend_is_a_buy(self, strategy):
        closes = list(np.linspace(2300.0, 1900.0, 60)) + [2050.0, 2150.0]
        prev_f, prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert cur_f < cur_s, "fixture left the downtrend entirely"
        assert cur_f > prev_f, "fast EMA is not turning up"

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.55)
        assert signal["reason"] == "Downtrend weakening"


class TestWhenItSaysNothing:
    def test_a_flat_market_leaves_the_emas_equal_and_produces_hold(self, strategy):
        closes = [2000.0] * 60
        _prev_f, _prev_s, cur_f, cur_s = _emas(strategy, closes)
        assert cur_f == cur_s

        signal = strategy.generate_signal(_frame(closes))
        assert signal["type"] == "HOLD"
        assert signal["confidence"] == 0.0
        assert signal["reason"].startswith("No clear signal")

    def test_too_little_history_holds_without_computing_anything(self, strategy):
        signal = strategy.generate_signal(_frame([2000.0] * 10))
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Insufficient data"
        assert "metadata" not in signal

    def test_a_frame_without_a_close_column_holds_rather_than_raising(self, strategy):
        """The blanket ``except`` again — worth pinning so its output stays
        distinguishable from a genuine HOLD by the ``Error:`` prefix."""
        signal = strategy.generate_signal(pd.DataFrame({"open": [1.0] * 60}))
        assert signal["type"] == "HOLD"
        assert signal["reason"].startswith("Error:")


class TestTheMomentumBonusIsMisnamed:
    """`ema_diff < 0.001` is labelled "strong momentum". It means the opposite.

    ``ema_diff`` is ``abs(fast - slow) / price`` — the *gap* between the two
    averages. At a crossover that gap is near zero by definition, so the bonus
    fires on essentially every crossover and the comment above it
    ("Higher confidence if EMAs are converging with momentum") describes
    convergence while the label claims momentum.

    **Not changed.** Whether a tight crossover deserves more or less confidence
    is a strategy decision with an owner, not a defect: both readings are
    defensible and neither is what the code currently argues. Asserted here so
    that whoever does decide has to change a test that says what today's
    behaviour is.
    """

    def test_the_bonus_fires_when_the_emas_are_close_not_when_they_are_far(self, strategy):
        closes = (list(np.linspace(2000.0, 1900.0, 40)) + list(np.linspace(1900.0, 2100.0, 12)))[:46]
        signal = strategy.generate_signal(_frame(closes))
        assert "crossover" in signal["reason"], "fixture is not on the crossing bar"
        gap = signal["metadata"]["ema_diff"]
        if gap < 0.001:
            assert "strong momentum" in signal["reason"]
            assert signal["confidence"] == pytest.approx(0.90)
        else:
            assert "strong momentum" not in signal["reason"]
            assert signal["confidence"] == pytest.approx(0.80)

    def test_a_violent_crossover_gets_no_bonus(self, strategy):
        """A crossing with a wide gap scores lower than a gentle one — which is
        the consequence of the rule above, stated on a fixture that is
        genuinely on the crossing bar."""
        closes = (list(np.linspace(2000.0, 1000.0, 40)) + list(np.linspace(1000.0, 6000.0, 12)))[:44]
        signal = strategy.generate_signal(_frame(closes))
        assert "crossover" in signal["reason"], signal["reason"]
        assert signal["metadata"]["ema_diff"] >= 0.001
        assert signal["confidence"] == pytest.approx(0.80)


class TestTheSnapshot:
    def test_analyze_returns_both_emas_and_the_price(self, strategy):
        out = strategy.analyze(_frame(list(np.linspace(1900.0, 2100.0, 60))))
        assert out["price"] == pytest.approx(2100.0)
        assert out["fast_ema"] > out["slow_ema"]

    def test_analyze_accepts_a_dict_of_columns(self, strategy):
        assert strategy.analyze({"close": [2000.0] * 40})["fast_ema"] == pytest.approx(2000.0)

    def test_analyze_refuses_a_frame_with_no_close(self, strategy):
        assert strategy.analyze(pd.DataFrame({"open": [1.0]}))["error"] == "no close prices"

    def test_analyze_refuses_an_empty_frame(self, strategy):
        assert strategy.analyze(pd.DataFrame())["error"] == "no close prices"


class TestTheEmasAreCausal:
    """`backtesting-frameworks`: assert it rather than trusting the reading.

    The EMA at bar *i* must not move when bars after *i* change. This is the
    property `strategies/breakout.py` violated in a different form, and it is
    cheap to state directly.
    """

    def test_appending_future_bars_does_not_change_an_earlier_signal(self, strategy):
        closes = list(np.linspace(2000.0, 1900.0, 40)) + list(np.linspace(1900.0, 2100.0, 12))
        first = strategy.generate_signal(_frame(closes))

        extended = _frame([*closes, 5000.0, 100.0, 3000.0]).iloc[: len(closes)]
        second = strategy.generate_signal(extended)

        assert first["type"] == second["type"]
        assert first["metadata"]["fast_ema"] == pytest.approx(second["metadata"]["fast_ema"])
        assert first["metadata"]["slow_ema"] == pytest.approx(second["metadata"]["slow_ema"])
