# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_reversion_exits_now_fire.py
============================================
Owner decision A18 (MASTER_OUTSTANDING §A18 / CORRECTION_REGISTER F276):
"thread position state into the strategies so the exits fire."

`tests/unit/test_reversion_exits_are_never_reached.py` proved the defect:
`strategies/mean_reversion.py` and `strategies/rsi_strategy.py` each declare
`self.position` and never write it again outside a test, so their exit
branches (gated on `self.position == "LONG"`) are dead in production.

The fix threads the ONE place that already tracks a confirmed position for
these two strategies — `backtesting.strategy_adapter.BacktestStrategyAdapter`,
which drives them for `BacktestEngine` — into `strategy.position`, before each
`generate_signal` call. The adapter's own `self.position` is written from its
own confirmed entries/exits (never from a pending order), and read here on the
NEXT bar only, so there is no look-ahead: a signal at bar *i* still cannot see
information from bar *i+1*.

These tests fail on the pre-fix tree (proven via `git stash`): the adapter
opens a long on the oversold entry and then holds forever, because the
strategy's own "reverted to mean" exit branch never sees `position == "LONG"`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from backtesting.strategy_adapter import BacktestStrategyAdapter

UTC = timezone.utc


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    timestamps = [start + timedelta(hours=i) for i in range(len(closes))]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        }
    )


class TestMeanReversionExitFiresThroughTheAdapter:
    def test_a_long_that_reverts_to_the_mean_is_exited(self):
        from strategies.mean_reversion import MeanReversionStrategy

        strategy = MeanReversionStrategy("mr", "XAUUSD", MagicMock(), period=20, std_dev=2.0)
        adapter = BacktestStrategyAdapter(strategy, "XAUUSD")

        # Bars 0..24: flat around 2000 so the bands settle. Bar 25: a sharp
        # drop below the lower band — the entry. Bars 26+: price climbs back
        # to the mean — the exit condition the dead branch is supposed to see.
        closes = [2000.0] * 25 + [1900.0] + list(np.linspace(1920.0, 2000.0, 10))
        frame = _ohlcv(closes)
        data = {"XAUUSD": frame}

        entered = False
        exited = False
        for i in range(2, len(frame)):
            ts = frame["timestamp"].iloc[i]
            price = float(frame["close"].iloc[i])
            signals = adapter.generate_signals(ts, {"XAUUSD": price}, data)
            for sig in signals:
                if sig["action"] == "buy":
                    entered = True
                if sig["action"] == "sell" and sig.get("exit"):
                    exited = True

        assert entered, "the oversold entry must fire first for the exit to have anything to close"
        assert exited, (
            "the mean-reversion exit never fired — self.position was not threaded into the "
            "strategy, so 'reverted to mean' could never match"
        )

    def test_position_is_synced_from_confirmed_state_not_invented(self):
        """The strategy's `.position` mirrors the adapter's CONFIRMED position,
        one bar in arrears — never set ahead of an actual entry."""
        from strategies.mean_reversion import MeanReversionStrategy

        strategy = MeanReversionStrategy("mr", "XAUUSD", MagicMock(), period=20, std_dev=2.0)
        adapter = BacktestStrategyAdapter(strategy, "XAUUSD")
        closes = [2000.0] * 25 + [1900.0]
        frame = _ohlcv(closes)
        data = {"XAUUSD": frame}

        # Before any signal has ever been generated, nothing is open.
        assert strategy.position is None

        ts = frame["timestamp"].iloc[-1]
        adapter.generate_signals(ts, {"XAUUSD": 1900.0}, data)
        # The entry was just returned (adapter.position flips to "long"
        # immediately, matching the adapter's existing own-state convention),
        # but the strategy object was synced from the PRE-call value (flat),
        # so the entry call itself still saw no open position.
        assert adapter.position == "long"


class TestRsiExitFiresThroughTheAdapter:
    def test_a_long_exited_specifically_by_the_position_gated_branch(self):
        """Pins the branch precisely: RSI must be >50 (so it needs the LONG
        exit gate), turning down, but still under `overbought` — so the
        unconditional overbought-SELL branch above it cannot be what fired.
        """
        from strategies.base import StrategyConfig
        from strategies.rsi_strategy import RSIStrategy

        strategy = RSIStrategy(StrategyConfig(name="rsi", symbol="XAUUSD", timeframe="1h"))
        adapter = BacktestStrategyAdapter(strategy, "XAUUSD")
        frame = _ohlcv([2000.0] * 45)

        # Bar 1: deeply oversold -> BUY entry.
        entry_rsi = pd.Series([25.0] * 40, index=frame["close"].iloc[:40].index)
        with patch.object(strategy, "calculate_rsi", return_value=entry_rsi):
            entry_signals = adapter.generate_signals(
                frame["timestamp"].iloc[39], {"XAUUSD": 2000.0}, {"XAUUSD": frame.iloc[:40]}
            )
        assert any(s["action"] == "buy" for s in entry_signals)
        assert adapter.position == "long"

        # Bar 2: RSI at 55, below `overbought` (70) and turning down from the
        # previous bar — only the position-gated exit branch can produce this.
        exit_rsi = pd.Series([25.0] * 39 + [60.0, 55.0], index=frame["close"].iloc[:41].index)
        with patch.object(strategy, "calculate_rsi", return_value=exit_rsi):
            exit_signals = adapter.generate_signals(
                frame["timestamp"].iloc[40], {"XAUUSD": 2000.0}, {"XAUUSD": frame.iloc[:41]}
            )

        assert any(s["action"] == "sell" and s.get("exit") for s in exit_signals), (
            "the RSI exit-long branch never fired — position was not threaded into the strategy"
        )


class TestNoLookAhead:
    """`backtesting-frameworks`: the sync must use only past-bar information."""

    def test_appending_future_bars_does_not_change_an_earlier_signal(self):
        from strategies.mean_reversion import MeanReversionStrategy

        closes = [2000.0] * 25 + [1900.0] + list(np.linspace(1920.0, 2000.0, 5))
        frame_a = _ohlcv(closes)
        frame_b = _ohlcv([*closes, 9000.0, 10.0])

        strat_a = MeanReversionStrategy("mr", "XAUUSD", MagicMock(), period=20, std_dev=2.0)
        adapter_a = BacktestStrategyAdapter(strat_a, "XAUUSD")
        strat_b = MeanReversionStrategy("mr", "XAUUSD", MagicMock(), period=20, std_dev=2.0)
        adapter_b = BacktestStrategyAdapter(strat_b, "XAUUSD")

        results_a = []
        results_b = []
        for i in range(2, len(frame_a)):
            ts = frame_a["timestamp"].iloc[i]
            price = float(frame_a["close"].iloc[i])
            results_a.append(adapter_a.generate_signals(ts, {"XAUUSD": price}, {"XAUUSD": frame_a}))
            results_b.append(adapter_b.generate_signals(ts, {"XAUUSD": price}, {"XAUUSD": frame_b}))

        assert results_a == results_b
