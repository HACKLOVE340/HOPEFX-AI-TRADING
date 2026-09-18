# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_reversion_exits_are_never_reached.py
====================================================
Two mean-reverting strategies that can enter and cannot take profit at the mean.

Coverage-floor programme, Task 6c: `strategies/mean_reversion.py` 68.29% and
`strategies/rsi_strategy.py` 65.55%.

**The finding, before the coverage.** Both strategies carry exit branches gated
on the strategy's own position:

    strategies/mean_reversion.py:143  elif hasattr(self, "position") and self.position == "LONG" and ...
    strategies/rsi_strategy.py:182    elif hasattr(self, "position") and self.position == "LONG" and ...

**Nothing in production ever sets `.position` on a strategy instance.** Both
classes declare it — `strategies/mean_reversion.py:53` and
`strategies/rsi_strategy.py:54`, both `self.position: str | None = None` with the
comment *"tracks current position side"* — and neither ever writes it again, so
`hasattr` is always True and the value is always `None`. `BaseStrategy` defines
something different: `self.positions`, plural, a list
(`strategies/base.py:100`). The only assignments to a singular `.position`
anywhere outside `tests/` are
`backtesting/strategy_adapter.py:172,188`, and those are the **adapter's** own
state — it wraps `self.strategy` and never reaches inside it — plus
`examples/backtest_example.py`, which is an example.

So a mean-reversion strategy buys the lower band and never signals the exit at
the mean. It holds until the *opposite* extreme, which is a materially different
strategy from the one the code describes. Same for RSI: it buys below 30 and
holds past 50 until 70. First dead-control shape, *a guard that can never open*,
and one letter from `positions`.

**Not fixed here.** Teaching a strategy its own position is an architecture
decision — `execution/position_tracker.py` owns live positions and the strategies
are stateless by design — and the two candidate fixes (thread position state in,
or move the exit rule into the adapter) have different consequences for
backtests. Raised as F276 / MASTER_OUTSTANDING §A18.

**What made this hard to see** is worth recording, because
`hopefx-dead-controls` predicts it exactly: the existing suite covers these
branches by doing `strat.position = "LONG"` by hand
(`tests/unit/test_strategy_signal_paths.py:586,602,683,694`). Those tests pass,
the lines are green, and the condition they create has never existed in
production. *A suite cannot tell you a control is off.* The tests below that
exercise the exits say so in their own names.

The `backtesting-frameworks` sweep is clean on both modules: `rolling(...)` with
no `center=True`, `ewm(adjust=False)`, `diff()`, and reads at `iloc[-1]` /
`iloc[-2]`. Causality is asserted directly at the end of this file.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


def _frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


# ─────────────────────────────────────────────────────────────────────────────
# strategies/mean_reversion.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def reversion():
    from strategies.mean_reversion import MeanReversionStrategy

    return MeanReversionStrategy("mr", "XAUUSD", MagicMock(), period=20, std_dev=2.0)


class TestNothingSetsPositionInProduction:
    """The claim the finding rests on, asserted rather than left in prose."""

    def test_the_position_is_declared_and_left_none(self, reversion):
        assert reversion.position is None, (
            "something now sets .position — update F276 before relying on the exit branch"
        )

    def test_the_hasattr_guard_is_therefore_always_true_and_never_enough(self, reversion):
        """Which is why reading the guard does not tell you the branch runs.

        ``hasattr(self, "position")`` passes on a freshly constructed strategy.
        The branch still cannot fire, because the *value* is None and the
        comparison is against ``"LONG"``. A reviewer checking the guard finds it
        satisfied.
        """
        assert hasattr(reversion, "position") is True
        assert reversion.position != "LONG"
        assert reversion.position != "SHORT"

    def test_what_the_base_class_actually_maintains_is_the_plural_list(self, reversion):
        assert reversion.positions == []

    def test_the_rsi_strategy_declares_it_and_leaves_it_none(self):
        from strategies.base import StrategyConfig
        from strategies.rsi_strategy import RSIStrategy

        strategy = RSIStrategy(StrategyConfig(name="rsi", symbol="XAUUSD", timeframe="1h"))
        assert strategy.position is None, "something now sets .position — update F276 before relying on the exit branch"


class TestTheBandEntries:
    def test_a_close_below_the_lower_band_is_a_buy(self, reversion):
        closes = [2000.0] * 25 + [1900.0]
        signal = reversion.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] >= 0.5
        assert "oversold" in signal["reason"]
        assert signal["metadata"]["price"] == 1900.0

    def test_a_close_above_the_upper_band_is_a_sell(self, reversion):
        closes = [2000.0] * 25 + [2100.0]
        signal = reversion.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] >= 0.5
        assert "overbought" in signal["reason"]

    def test_a_close_inside_the_bands_is_a_hold(self, reversion):
        closes = list(np.linspace(1990.0, 2010.0, 25)) + [2002.0]
        signal = reversion.generate_signal(_frame(closes))
        assert signal["type"] == "HOLD"
        assert "within bands" in signal["reason"]

    def test_confidence_grows_with_the_distance_past_the_band(self, reversion):
        mild = reversion.generate_signal(_frame([*([2000.0] * 25), 1975.0]))
        wild = reversion.generate_signal(_frame([*([2000.0] * 25), 1500.0]))
        assert mild["type"] == wild["type"] == "BUY"
        assert wild["confidence"] > mild["confidence"]
        assert wild["confidence"] <= 0.9, "the cap is the point of the min()"

    def test_too_little_history_holds(self, reversion):
        signal = reversion.generate_signal(_frame([2000.0] * 5))
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Insufficient data"

    def test_a_flat_series_has_no_band_width_and_refuses_rather_than_dividing(self, reversion):
        """std is 0, so the bands collapse onto the mean.

        Without the guard this is a ZeroDivisionError into the blanket except,
        which would have produced a HOLD with an "Error:" reason — the same
        output shape, and indistinguishable in a log from a quiet market.
        """
        signal = reversion.generate_signal(_frame([2000.0] * 30))
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Zero band width"
        assert "metadata" not in signal

    def test_a_frame_without_close_holds_with_an_error_prefix(self, reversion):
        signal = reversion.generate_signal(pd.DataFrame({"open": [1.0] * 30}))
        assert signal["type"] == "HOLD"
        assert signal["reason"].startswith("Error:")


class TestTheExitsThatProductionCannotReach:
    """These pass only because the test sets `.position` by hand.

    Read them as a specification of what the branch *would* do if the wiring in
    F276 is ever built — not as evidence that it fires today. The assertion in
    `TestNothingSetsPositionInProduction` is the one that says whether it does.
    """

    def test_a_long_whose_price_returns_to_the_mean_would_be_closed(self, reversion):
        reversion.position = "LONG"
        closes = list(np.linspace(1900.0, 2000.0, 25)) + [2000.0]
        signal = reversion.generate_signal(_frame(closes))
        assert signal["type"] == "SELL"
        assert signal["confidence"] == pytest.approx(0.6)
        assert "reverted to mean" in signal["reason"]

    def test_a_short_whose_price_returns_to_the_mean_would_be_closed(self, reversion):
        reversion.position = "SHORT"
        closes = list(np.linspace(2100.0, 2000.0, 25)) + [1999.0]
        signal = reversion.generate_signal(_frame(closes))
        assert signal["type"] == "BUY"
        assert signal["confidence"] == pytest.approx(0.6)
        assert "reverted to mean" in signal["reason"]

    def test_a_long_still_away_from_the_mean_is_left_alone(self, reversion):
        reversion.position = "LONG"
        closes = list(np.linspace(2100.0, 2000.0, 25)) + [1999.0]
        assert reversion.generate_signal(_frame(closes))["type"] == "HOLD"


class TestTheReversionSnapshot:
    def test_analyze_reports_the_bands_and_the_zscore(self, reversion):
        out = reversion.analyze(_frame([*([2000.0] * 24), 2050.0]))
        assert out["sma"] > 0
        assert out["upper_band"] > out["sma"] > out["lower_band"]
        assert out["zscore"] > 0

    def test_analyze_reports_a_zero_zscore_when_there_is_no_deviation(self, reversion):
        """Rather than dividing by a zero standard deviation."""
        assert reversion.analyze(_frame([2000.0] * 25))["zscore"] == 0.0

    def test_analyze_accepts_a_dict_of_columns(self, reversion):
        assert reversion.analyze({"close": [2000.0] * 25})["sma"] == pytest.approx(2000.0)

    def test_analyze_refuses_a_frame_with_no_close(self, reversion):
        assert reversion.analyze(pd.DataFrame({"open": [1.0]}))["error"] == "no close prices"

    def test_analyze_refuses_an_empty_frame(self, reversion):
        assert reversion.analyze(pd.DataFrame())["error"] == "no close prices"


# ─────────────────────────────────────────────────────────────────────────────
# strategies/rsi_strategy.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def rsi():
    from strategies.base import StrategyConfig
    from strategies.rsi_strategy import RSIStrategy

    return RSIStrategy(StrategyConfig(name="rsi", symbol="XAUUSD", timeframe="1h"))


class TestTheRsiItself:
    def test_a_monotonic_rally_pins_it_near_a_hundred(self, rsi):
        series = rsi.calculate_rsi(pd.Series(np.linspace(1900.0, 2100.0, 40)))
        assert series.iloc[-1] > 95

    def test_a_monotonic_slide_pins_it_near_zero(self, rsi):
        series = rsi.calculate_rsi(pd.Series(np.linspace(2100.0, 1900.0, 40)))
        assert series.iloc[-1] < 5

    def test_a_flat_series_has_no_gains_and_no_losses(self, rsi):
        """0/0 is filled with the neutral 50 rather than left as NaN.

        `rs = gain / loss.replace(0, nan)` then `.fillna(50.0)` — an RSI of NaN
        propagating into the comparison would make every branch false and the
        strategy silently neutral.
        """
        series = rsi.calculate_rsi(pd.Series([2000.0] * 40))
        assert series.iloc[-1] == 50.0
        assert not series.isna().any()

    def test_it_stays_inside_its_own_bounds(self, rsi):
        rng = np.random.default_rng(7)
        series = rsi.calculate_rsi(pd.Series(2000.0 + np.cumsum(rng.normal(0, 5, 300))))
        assert series.min() >= 0.0
        assert series.max() <= 100.0


class TestTheRsiDictSignal:
    def test_a_deeply_oversold_reading_buys(self, rsi):
        signal = rsi.generate_signal(_frame(list(np.linspace(2100.0, 1900.0, 40))))
        assert signal["type"] == "BUY"
        assert "oversold" in signal["reason"]

    def test_a_deeply_overbought_reading_sells(self, rsi):
        signal = rsi.generate_signal(_frame(list(np.linspace(1900.0, 2100.0, 40))))
        assert signal["type"] == "SELL"
        assert "overbought" in signal["reason"]

    def test_a_neutral_reading_holds(self, rsi):
        signal = rsi.generate_signal(_frame([2000.0] * 40))
        assert signal["type"] == "HOLD"
        assert "neutral" in signal["reason"]

    def test_too_little_history_holds(self, rsi):
        signal = rsi.generate_signal(_frame([2000.0] * 5))
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Insufficient data for RSI calculation"

    def test_an_oversold_reading_that_is_turning_up_scores_higher(self, rsi):
        """The RSI level held fixed, only its direction varied.

        The first draft of this test compared a pure slide against a slide with
        a bounce on the last bar, and failed: the pure slide reads RSI 0 and
        earns the capped 0.9, while the bounce is *less* oversold and earns
        0.83 even with the rising bonus. That is the confidence formula working
        as written, not a defect — but it means a cross-fixture comparison
        measures the level, not the turn. Fixing the level isolates the bonus.
        """
        from unittest.mock import patch

        frame = _frame([2000.0] * 40)
        falling = pd.Series([26.0] * 39 + [25.0], index=frame.index)
        rising = pd.Series([24.0] * 39 + [25.0], index=frame.index)

        with patch.object(rsi, "calculate_rsi", return_value=falling):
            without = rsi.generate_signal(frame)
        with patch.object(rsi, "calculate_rsi", return_value=rising):
            with_bonus = rsi.generate_signal(frame)

        assert without["type"] == with_bonus["type"] == "BUY"
        assert "and rising" not in without["reason"]
        assert "and rising" in with_bonus["reason"]
        assert with_bonus["confidence"] == pytest.approx(without["confidence"] + 0.1)

    def test_an_overbought_reading_that_is_turning_down_scores_higher(self, rsi):
        from unittest.mock import patch

        frame = _frame([2000.0] * 40)
        rising = pd.Series([74.0] * 39 + [75.0], index=frame.index)
        falling = pd.Series([76.0] * 39 + [75.0], index=frame.index)

        with patch.object(rsi, "calculate_rsi", return_value=rising):
            without = rsi.generate_signal(frame)
        with patch.object(rsi, "calculate_rsi", return_value=falling):
            with_bonus = rsi.generate_signal(frame)

        assert without["type"] == with_bonus["type"] == "SELL"
        assert "and falling" in with_bonus["reason"]
        assert with_bonus["confidence"] == pytest.approx(without["confidence"] + 0.1)

    def test_a_nan_reading_holds_rather_than_comparing_against_it(self, rsi):
        """Every comparison against NaN is False, so without this guard the
        strategy would fall through to "neutral" and report a number it knows
        is not one."""
        from unittest.mock import patch

        frame = _frame([2000.0] * 40)
        with patch.object(rsi, "calculate_rsi", return_value=pd.Series([float("nan")] * 40, index=frame.index)):
            signal = rsi.generate_signal(frame)
        assert signal["type"] == "HOLD"
        assert "NaN" in signal["reason"]


class TestTheRsiSignalObjectPath:
    """`generate_signal` dual-dispatches: a DataFrame gives a dict, a dict gives
    a `Signal` or `None`. The dict path is the `BaseStrategy` contract."""

    def test_an_oversold_dict_produces_a_buy_signal_object(self, rsi):
        from strategies.base import SignalType

        signal = rsi.generate_signal({"rsi": 20.0, "price": 1900.0})
        assert signal.signal_type is SignalType.BUY
        assert signal.price == 1900.0
        assert 0.5 <= signal.confidence <= 0.95

    def test_an_overbought_dict_produces_a_sell_signal_object(self, rsi):
        from strategies.base import SignalType

        assert rsi.generate_signal({"rsi": 85.0, "price": 2100.0}).signal_type is SignalType.SELL

    def test_a_neutral_dict_produces_nothing(self, rsi):
        assert rsi.generate_signal({"rsi": 50.0, "price": 2000.0}) is None

    def test_a_dict_with_no_rsi_produces_nothing(self, rsi):
        assert rsi.generate_signal({"price": 2000.0}) is None

    def test_the_legacy_helper_still_returns_the_dict_shape(self, rsi):
        out = rsi.generate_signal_from_data(_frame(list(np.linspace(2100.0, 1900.0, 40))))
        assert out["type"] == "BUY"


class TestTheRsiSnapshot:
    def test_analyze_reads_the_prices_key(self, rsi):
        out = rsi.analyze({"prices": list(np.linspace(1900.0, 2100.0, 40))})
        assert out["rsi"] > 95
        assert out["oversold"] == 30
        assert out["overbought"] == 70

    def test_analyze_also_reads_close(self, rsi):
        assert rsi.analyze({"close": [2000.0] * 40})["rsi"] == 50.0

    def test_analyze_refuses_a_payload_with_neither(self, rsi):
        assert rsi.analyze({"volume": [1]})["error"] == "no price data"

    def test_analyze_accepts_a_series_without_rewrapping_it(self, rsi):
        assert rsi.analyze({"prices": pd.Series([2000.0] * 40)})["rsi"] == 50.0

    def test_an_empty_prices_list_falls_through_to_close(self, rsi):
        """The falsy-fallback semantics of the old ``or``, preserved on purpose.

        A mutation that made an empty list win instead of falling through
        survived the first draft of these tests. It is a behaviour change that
        matters: under it, ``{"prices": [], "close": [...]}`` would report
        ``rsi: None`` with no ``error`` key rather than reading the prices that
        are there.
        """
        out = rsi.analyze({"prices": [], "close": [2000.0] * 40})
        assert out["rsi"] == 50.0
        assert "error" not in out

    def test_an_empty_series_also_falls_through(self, rsi):
        out = rsi.analyze({"prices": pd.Series([], dtype=float), "close": [2000.0] * 40})
        assert out["rsi"] == 50.0

    def test_both_empty_is_refused_rather_than_reported_as_nothing(self, rsi):
        assert rsi.analyze({"prices": [], "close": []})["error"] == "no price data"


class TestBothAreCausal:
    """`backtesting-frameworks`: a signal at bar *i* must not depend on bar *i+1*."""

    @pytest.mark.parametrize("closes", [list(np.linspace(2100.0, 1900.0, 40)), [2000.0] * 25 + [1900.0]])
    def test_appending_future_bars_does_not_change_an_earlier_reversion_signal(self, reversion, closes):
        first = reversion.generate_signal(_frame(closes))
        second = reversion.generate_signal(_frame([*closes, 9000.0, 10.0]).iloc[: len(closes)])
        assert first["type"] == second["type"]
        assert first["reason"] == second["reason"]

    def test_appending_future_bars_does_not_change_an_earlier_rsi(self, rsi):
        closes = list(np.linspace(2100.0, 1900.0, 40))
        first = rsi.calculate_rsi(pd.Series(closes)).iloc[-1]
        second = rsi.calculate_rsi(pd.Series([*closes, 9000.0, 10.0])).iloc[len(closes) - 1]
        assert first == pytest.approx(second)
