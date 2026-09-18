# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_breakout_can_actually_break_out.py
===================================================
Two classes named ``BreakoutStrategy``. Neither could emit a signal.

Coverage-floor programme, Task 6c, applying ``backtesting-frameworks``. That
skill's first bias is look-ahead — using information the bar being tested could
not have had — and the grep-able constructs for it (``center=True``, a negative
``.shift()``, ``bfill``) appear nowhere in ``strategies/``. The sweep found
something adjacent and worse: a window that includes **the bar it is being
compared against**.

``strategies/breakout.py``::

    recent_high = high.tail(self.lookback_period).max()   # includes bar -1
    ...
    if current_high > resistance:                         # current_high IS in that max

``max`` over a window containing ``current_high`` is ``>= current_high``, so
the comparison is false for every input that has ever existed. The bearish
branch is the same identity with ``min``. Both breakout branches were
unreachable — the first dead-control shape, *a guard that can never open*,
except here it is the signal itself.

``strategies/manager.py:377`` defines a second, unrelated ``BreakoutStrategy``
with the identical defect and a multiplier that makes it stricter still::

    resistance = float(np.max([c.high for c in recent]))  # recent includes [-1]
    if current > resistance * (1 + self.breakout_threshold):

``current <= resistance``, so ``current > resistance * 1.001`` cannot hold for
any positive price. Its sell branch is the mirror.

**Measured before anything was changed.** 20 bars consolidating in [100, 110]
followed by a bar breaking to 130:

    UP BREAK   -> HOLD, "Consolidating: 100.00000 < 129.00000 < 130.00000"
    DOWN BREAK -> HOLD, "Consolidating: 70.00000 < 71.00000 < 110.00000"

The breakout bar is reported as consolidation, because the bar redefined the
level it was about to be measured against. Across 4,000 random OHLC frames
``strategies/breakout.py`` returned ``{'HOLD': 4000}`` and
``strategies/manager.py``'s returned ``{'none': 3000}`` across 3,000.

Both are live: ``strategies/registry.py:79`` maps ``"breakout"`` to the first,
``api/backtesting.py:203`` offers it by name to anyone running a backtest, and
``strategies/manager.py:473`` registers the second at construction. A user who
selected "Breakout" got a flat equity curve and no reason for it.

The fix is the one ``backtesting-frameworks`` prescribes for the whole family:
the level is computed from bars **strictly before** the bar being tested.

These tests fail on the pre-fix tree at ``6793da82``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


def _flat_then(last: dict, *, bars: int = 24) -> pd.DataFrame:
    """``bars`` candles ranging in [100, 110], then one candle of your choosing."""
    rows = [{"open": 105.0, "high": 110.0, "low": 100.0, "close": 105.0, "volume": 1000.0} for _ in range(bars)]
    rows.append(last)
    return pd.DataFrame(rows)


@pytest.fixture
def strategy():
    from strategies.breakout import BreakoutStrategy

    return BreakoutStrategy("bo", "XAUUSD", MagicMock(), lookback_period=20, breakout_threshold=0.02)


class TestTheLevelExcludesTheBarBeingTested:
    """The arithmetic, stated on its own so the reason survives the next edit."""

    def test_resistance_is_the_high_of_the_bars_before_this_one(self, strategy):
        frame = _flat_then({"open": 109.0, "high": 130.0, "low": 108.0, "close": 129.0, "volume": 5000.0})
        _support, resistance = strategy.identify_support_resistance(frame)
        assert resistance == 110.0, "the breaking bar's own high became the level it had to clear"

    def test_support_is_the_low_of_the_bars_before_this_one(self, strategy):
        frame = _flat_then({"open": 101.0, "high": 102.0, "low": 70.0, "close": 71.0, "volume": 5000.0})
        support, _resistance = strategy.identify_support_resistance(frame)
        assert support == 100.0

    def test_the_window_is_still_the_lookback_and_not_the_whole_frame(self, strategy):
        """Excluding the current bar must not quietly widen the lookback.

        A 60-bar frame with an old spike at bar 0 must not have that spike as
        its resistance when the lookback is 20.
        """
        rows = [{"open": 105.0, "high": 400.0, "low": 100.0, "close": 105.0, "volume": 1000.0}]
        rows += [{"open": 105.0, "high": 110.0, "low": 100.0, "close": 105.0, "volume": 1000.0} for _ in range(59)]
        _support, resistance = strategy.identify_support_resistance(pd.DataFrame(rows))
        assert resistance == 110.0


class TestItCanBreakOut:
    def test_a_break_above_the_range_is_a_buy(self, strategy):
        frame = _flat_then({"open": 109.0, "high": 130.0, "low": 108.0, "close": 129.0, "volume": 5000.0})
        signal = strategy.generate_signal(frame)
        assert signal["type"] == "BUY", signal["reason"]
        assert signal["confidence"] >= 0.70

    def test_a_break_below_the_range_is_a_sell(self, strategy):
        frame = _flat_then({"open": 101.0, "high": 102.0, "low": 70.0, "close": 71.0, "volume": 5000.0})
        signal = strategy.generate_signal(frame)
        assert signal["type"] == "SELL", signal["reason"]
        assert signal["confidence"] >= 0.70

    def test_it_is_capable_of_selling_at_all(self, strategy):
        """The test that would have caught this, written as the question to ask.

        Before the fix this strategy returned HOLD for all 4,000 random frames
        it was given. A strategy that has never produced one of its two
        directions is not a strategy with a quiet week.
        """
        rng = np.random.default_rng(0)
        seen = set()
        for _ in range(400):
            base = rng.uniform(50, 500)
            highs = base + rng.uniform(0, 40, 30)
            lows = base - rng.uniform(0, 40, 30)
            closes = (highs + lows) / 2 + rng.normal(0, 5, 30)
            frame = pd.DataFrame(
                {
                    "open": closes,
                    "high": np.maximum(highs, closes),
                    "low": np.minimum(lows, closes),
                    "close": closes,
                    "volume": rng.uniform(100, 10_000, 30),
                }
            )
            seen.add(strategy.generate_signal(frame)["type"])
        assert {"BUY", "SELL"} <= seen, f"only ever produced {sorted(seen)}"


class TestItStillRefusesWhatItShould:
    def test_a_bar_inside_the_range_is_not_a_breakout(self, strategy):
        frame = _flat_then({"open": 105.0, "high": 108.0, "low": 102.0, "close": 106.0, "volume": 1000.0})
        assert strategy.generate_signal(frame)["type"] != "SELL"
        assert "breakout" not in strategy.generate_signal(frame)["reason"].lower()

    def test_a_break_smaller_than_the_threshold_is_not_taken(self, strategy):
        """range is 10, threshold 2% -> 0.2 of price must be cleared."""
        frame = _flat_then({"open": 109.0, "high": 110.05, "low": 108.0, "close": 110.02, "volume": 1000.0})
        signal = strategy.generate_signal(frame)
        assert signal["type"] != "SELL"
        assert "Bullish breakout" not in signal["reason"]

    def test_too_little_history_holds(self, strategy):
        frame = pd.DataFrame(
            [{"open": 105.0, "high": 110.0, "low": 100.0, "close": 105.0, "volume": 1000.0} for _ in range(5)]
        )
        signal = strategy.generate_signal(frame)
        assert signal["type"] == "HOLD"
        assert signal["reason"] == "Insufficient data"

    def test_a_frame_with_exactly_the_lookback_does_not_divide_by_an_empty_window(self, strategy):
        """Excluding the current bar leaves ``lookback - 1`` bars at the boundary.

        The off-by-one that the fix could introduce: at exactly ``lookback``
        rows the window must still be non-empty, or ``max()`` of nothing raises
        into the blanket ``except`` and the strategy silently holds again.
        """
        frame = pd.DataFrame(
            [{"open": 105.0, "high": 110.0, "low": 100.0, "close": 105.0, "volume": 1000.0} for _ in range(20)]
        )
        signal = strategy.generate_signal(frame)
        assert not signal["reason"].startswith("Error:"), signal["reason"]


class TestVolumeConfirmation:
    def test_a_breakout_on_heavy_volume_is_held_with_more_confidence(self, strategy):
        quiet = strategy.generate_signal(
            _flat_then({"open": 109.0, "high": 130.0, "low": 108.0, "close": 129.0, "volume": 1000.0})
        )
        heavy = strategy.generate_signal(
            _flat_then({"open": 109.0, "high": 130.0, "low": 108.0, "close": 129.0, "volume": 5000.0})
        )
        assert heavy["confidence"] > quiet["confidence"]
        assert "high volume" in heavy["reason"]

    def test_the_average_volume_also_excludes_the_breaking_bar(self, strategy):
        """Otherwise a volume spike raises the bar it is supposed to clear.

        Same defect as the price level, one field over: a 5,000-lot bar inside
        its own 20-bar mean pulls the mean up by 200 and can disqualify itself.
        """
        signal = strategy.generate_signal(
            _flat_then({"open": 109.0, "high": 130.0, "low": 108.0, "close": 129.0, "volume": 5000.0})
        )
        assert signal["metadata"]["avg_volume"] == 1000.0

    def test_a_close_back_inside_the_range_is_a_weaker_breakout(self, strategy):
        """High pierced the level, close did not hold it — a failed breakout."""
        pierced = strategy.generate_signal(
            _flat_then({"open": 105.0, "high": 130.0, "low": 104.0, "close": 106.0, "volume": 1000.0})
        )
        held = strategy.generate_signal(
            _flat_then({"open": 109.0, "high": 130.0, "low": 108.0, "close": 129.0, "volume": 1000.0})
        )
        assert pierced["type"] == held["type"] == "BUY"
        assert held["confidence"] > pierced["confidence"]
        assert "strong close" in held["reason"]


class TestTheBranchesThatDoFire:
    """The three that were reachable all along, and the snapshot method.

    With both breakout branches dead, these were the only outputs this
    strategy could produce — which is why a user watching it saw a mixture of
    "Approaching resistance" and "Consolidating" and nothing else, forever.
    They are worth pinning now that they are no longer the whole story.
    """

    def test_a_close_just_under_resistance_is_a_weak_buy(self, strategy):
        frame = _flat_then({"open": 105.0, "high": 109.9, "low": 104.0, "close": 109.8, "volume": 1000.0})
        signal = strategy.generate_signal(frame)
        assert signal["type"] == "BUY"
        assert signal["confidence"] == 0.50
        assert "Approaching resistance" in signal["reason"]

    def test_a_close_just_above_support_is_also_a_buy(self, strategy):
        """Labelled "Near support level" and it buys — the dip, not the break.

        Asserted rather than corrected: a mean-reversion entry at support is a
        defensible thing for a breakout strategy to also do, and changing it
        would be a strategy decision rather than a defect fix.
        """
        frame = _flat_then({"open": 101.0, "high": 102.0, "low": 100.2, "close": 100.3, "volume": 1000.0})
        signal = strategy.generate_signal(frame)
        assert signal["type"] == "BUY"
        assert signal["confidence"] == 0.55
        assert "Near support" in signal["reason"]

    def test_the_middle_of_the_range_is_consolidation(self, strategy):
        frame = _flat_then({"open": 105.0, "high": 106.0, "low": 104.0, "close": 105.0, "volume": 1000.0})
        signal = strategy.generate_signal(frame)
        assert signal["type"] == "HOLD"
        assert "Consolidating" in signal["reason"]

    def test_a_broken_frame_is_held_rather_than_raised(self, strategy):
        """The blanket ``except`` is the reason this defect survived: every
        failure inside ``generate_signal`` becomes a HOLD with a reason
        string, which reads exactly like a quiet market."""
        signal = strategy.generate_signal(pd.DataFrame({"nonsense": range(40)}))
        assert signal["type"] == "HOLD"
        assert signal["reason"].startswith("Error:")


class TestTheSnapshot:
    def test_analyze_reports_the_levels_and_the_volatility(self, strategy):
        out = strategy.analyze(
            _flat_then({"open": 105.0, "high": 108.0, "low": 102.0, "close": 106.0, "volume": 1000.0})
        )
        assert out["support"] == 100.0
        assert out["resistance"] == 110.0
        assert out["price"] == 106.0
        assert out["atr"] > 0

    def test_analyze_accepts_a_dict_of_columns(self, strategy):
        out = strategy.analyze({"high": [110.0] * 25, "low": [100.0] * 25, "close": [105.0] * 25})
        assert out["resistance"] == 110.0

    def test_analyze_refuses_a_frame_without_ohlc(self, strategy):
        assert strategy.analyze(pd.DataFrame({"close": [1.0]}))["error"] == "insufficient OHLC data"

    def test_analyze_refuses_an_empty_frame(self, strategy):
        assert strategy.analyze(pd.DataFrame())["error"] == "insufficient OHLC data"


# ─────────────────────────────────────────────────────────────────────────────
# The second class, in strategies/manager.py
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _Candle:
    high: float
    low: float
    close: float


def _candles(last: _Candle, *, bars: int = 24) -> list[_Candle]:
    return [_Candle(110.0, 100.0, 105.0) for _ in range(bars)] + [last]


@pytest.fixture
def manager_strategy():
    from strategies.manager import BreakoutStrategy

    return BreakoutStrategy({"lookback_period": 20, "breakout_threshold": 0.001})


class TestTheManagersOwnBreakoutStrategy:
    def test_a_break_above_the_range_produces_a_buy(self, manager_strategy):
        out = asyncio.run(
            manager_strategy.generate_signals("XAUUSD", _candles(_Candle(130.0, 108.0, 129.0)), "ranging")
        )
        assert [s.action for s in out] == ["buy"]

    def test_a_break_below_the_range_produces_a_sell(self, manager_strategy):
        out = asyncio.run(manager_strategy.generate_signals("XAUUSD", _candles(_Candle(102.0, 70.0, 71.0)), "ranging"))
        assert [s.action for s in out] == ["sell"]

    def test_the_stop_sits_on_the_other_side_of_the_range(self, manager_strategy):
        (sig,) = asyncio.run(
            manager_strategy.generate_signals("XAUUSD", _candles(_Candle(130.0, 108.0, 129.0)), "ranging")
        )
        assert sig.stop_loss == 100.0
        assert sig.entry_price == 129.0
        # 2R on the measured range.
        assert sig.take_profit == pytest.approx(129.0 + (129.0 - 100.0) * 2)

    def test_a_bar_inside_the_range_produces_nothing(self, manager_strategy):
        assert (
            asyncio.run(manager_strategy.generate_signals("XAUUSD", _candles(_Candle(108.0, 102.0, 106.0)), "ranging"))
            == []
        )

    def test_it_stays_out_of_a_trending_market(self, manager_strategy):
        """Deliberate and unchanged: this one only trades ranges."""
        assert (
            asyncio.run(manager_strategy.generate_signals("XAUUSD", _candles(_Candle(130.0, 108.0, 129.0)), "trending"))
            == []
        )

    def test_too_little_history_produces_nothing(self, manager_strategy):
        assert (
            asyncio.run(
                manager_strategy.generate_signals("XAUUSD", _candles(_Candle(130.0, 108.0, 129.0), bars=3), "ranging")
            )
            == []
        )

    def test_a_signal_is_counted_where_the_dashboard_reads_it(self, manager_strategy):
        before = manager_strategy.performance_metrics["signals_generated"]
        asyncio.run(manager_strategy.generate_signals("XAUUSD", _candles(_Candle(130.0, 108.0, 129.0)), "ranging"))
        assert manager_strategy.performance_metrics["signals_generated"] == before + 1
        assert manager_strategy.performance_metrics["last_signal_at"] is not None

    def test_it_is_capable_of_both_directions(self, manager_strategy):
        """Deliberate breaks in both directions, at a range of price levels.

        The first draft of this test sampled random OHLC and asserted both
        actions appeared. It failed — not because a branch was dead, but
        because this class's threshold is a fraction of the **level**
        (``resistance * 1.001``) rather than of the range, so a random walk
        clears it about 0.1% of the time and 300 frames was an underpowered
        sample. Measured over 3,000: 3 buys, 2 sells. A test that needs a
        one-in-a-thousand event to pass is a flake with a seed on it, so this
        asks the question directly instead.
        """
        seen = set()
        for base in (50.0, 137.5, 500.0, 2400.0):
            span = base * 0.05
            flat = [_Candle(base + span, base - span, base) for _ in range(24)]
            up = asyncio.run(
                manager_strategy.generate_signals(
                    "XAUUSD", [*flat, _Candle(base + span * 3, base, base + span * 2)], "ranging"
                )
            )
            down = asyncio.run(
                manager_strategy.generate_signals(
                    "XAUUSD", [*flat, _Candle(base, base - span * 3, base - span * 2)], "ranging"
                )
            )
            seen.update(s.action for s in (*up, *down))
        assert seen == {"buy", "sell"}, f"only ever produced {sorted(seen)}"
