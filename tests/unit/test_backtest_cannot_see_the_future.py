# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A backtest must not hand a strategy a bar that has not happened.

`backtesting/engine_config.py` built its price snapshot correctly — masked with
``df["timestamp"] <= timestamp`` — and then passed the strategy the complete,
unsliced frame for every symbol:

    signals = strategy.generate_signals(timestamp=timestamp, prices=current_prices, data=all_data)

Thirty lines above that loop it constructed the control designed to catch
exactly this:

    # Initialise the BacktestBarGuard to catch any strategy that tries to
    # peek at future bars during the simulation loop.
    _bar_guard = BacktestBarGuard(_all_ts)
    logger.debug("BacktestBarGuard active: %d timestamps", len(_all_ts))

``_bar_guard`` was never referenced again — the F176 shape, a control that
exists, reads correctly, logs that it is active, and never runs. Its failure
path logged at DEBUG, so a run where the guard could not even be built looked
identical to one where it could.

Measured before the fix, against a live harness (the first two harnesses were
themselves broken — one never awaited the coroutine, one let the engine load
its own empty data — so this file asserts the harness ran before it asserts
what the harness found):

    engine actually ran      : True
    strategy was called      : 120 times
    times it read a FUTURE bar: 119
    first peek: at 2024-01-01 00:00 it read close=1997.94 from the next hour
    guard raised: NO

Look-ahead is the one backtest defect that makes every other number on the
report meaningless, because a strategy that can see the next bar can be
arbitrarily profitable. These tests pin that it cannot.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


def _frame(n: int = 60) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(3)
    close = 2000 + np.cumsum(rng.normal(0, 4, n))
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(hours=i) for i in range(n)],
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000.0,
        }
    )


class _RecordingStrategy:
    """Records what it was handed. Trades nothing, so it cannot skew results."""

    name = "recorder"

    def __init__(self) -> None:
        self.calls = 0
        self.future_bars_seen = 0
        self.rows_seen: list[int] = []

    def generate_signals(self, timestamp, prices, data):
        self.calls += 1
        frame = data["XAUUSD"]
        self.rows_seen.append(len(frame))
        stamps = frame.get("timestamp", frame.index)
        if (pd.Series(stamps) > timestamp).any():
            self.future_bars_seen += 1
        return []


def _run(strategy, frame: pd.DataFrame):
    """Run the real engine over *frame*, and prove the run happened."""
    from backtesting.engine_config import BacktestConfig, BacktestEngine

    cfg = BacktestConfig(
        start_date=frame["timestamp"].iloc[0],
        end_date=frame["timestamp"].iloc[-1],
        symbols=["XAUUSD"],
        initial_capital=100_000.0,
    )
    engine = BacktestEngine(cfg)
    engine.strategies = [strategy]

    class _Loader:
        async def load_data(self, symbol, tf, start, end):
            return frame

    engine.data_loader = _Loader()
    result = asyncio.run(engine.run())

    # Harness liveness, asserted before anything reads the strategy's counters.
    # A run that never called the strategy reports zero peeks and looks like a
    # pass; that is how the first two versions of this harness "proved" the
    # engine safe while exercising nothing.
    assert strategy.calls > 0, "the engine never called the strategy — no conclusion is available"
    return result


class TestStrategiesSeeOnlyThePast:
    def test_no_future_bar_reaches_the_strategy(self):
        frame = _frame()
        strat = _RecordingStrategy()
        _run(strat, frame)

        assert strat.future_bars_seen == 0, (
            f"the strategy was handed a not-yet-happened bar on {strat.future_bars_seen} of {strat.calls} bars"
        )

    def test_the_visible_history_grows_one_bar_at_a_time(self):
        """A point-in-time view is not just 'no future' — it is the right past.

        Handing the strategy an empty frame every bar would also satisfy the
        test above while destroying every strategy that needs history.
        """
        frame = _frame()
        strat = _RecordingStrategy()
        _run(strat, frame)

        assert strat.rows_seen == sorted(strat.rows_seen), "visible history must never shrink"
        assert strat.rows_seen[0] >= 1, "the first bar must be visible on the first call"
        assert strat.rows_seen[-1] == len(frame), "by the last bar the whole history must be visible"
        assert len(set(strat.rows_seen)) > 1, "the view must actually advance, not be frozen"

    def test_the_strategy_still_sees_the_current_bar(self):
        """Slicing must be inclusive of `timestamp`, or every strategy is blind."""
        frame = _frame()
        seen: list[tuple] = []

        class _CurrentBar:
            name = "current"
            calls = 0

            def generate_signals(self, timestamp, prices, data):
                type(self).calls += 1
                f = data["XAUUSD"]
                seen.append((timestamp, f["timestamp"].iloc[-1]))
                return []

        _run(_CurrentBar(), frame)
        assert seen, "no observations recorded"
        for ts, last_visible in seen:
            assert last_visible == ts, f"at {ts} the newest visible bar was {last_visible}"


class TestTheGuardIsWiredNotJustBuilt:
    def test_a_strategy_that_reaches_past_its_view_is_refused(self):
        """The control must be able to say no, not merely exist.

        The engine used to construct `BacktestBarGuard` and never consult it.
        A guard nothing calls is indistinguishable from no guard, so this
        asserts a peek is actively refused rather than merely unavailable.
        """
        from risk.lookahead_guard import BacktestBarGuard, LookAheadBiasError

        frame = _frame(20)
        guard = BacktestBarGuard(frame, strict=True)
        # Walk it forward two bars, then reach for a bar beyond the cursor.
        it = iter(guard)
        next(it)
        next(it)
        with pytest.raises(LookAheadBiasError):
            guard.get(len(frame) - 1)

    def test_the_engine_reports_whether_the_guard_is_active(self):
        """A run must be able to say whether it was policed.

        The construction failure used to log at DEBUG, so a backtest that ran
        entirely unguarded produced the same visible output as a guarded one.
        """
        from backtesting.engine_config import BacktestEngine

        assert hasattr(BacktestEngine, "lookahead_protection"), (
            "the engine must expose whether look-ahead protection was in force for a run"
        )
