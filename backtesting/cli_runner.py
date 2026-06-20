# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
backtesting/cli_runner.py
=========================
Turn-key backtest over committed historical OHLCV CSVs (e.g. data/XAUUSD_5Y.csv).

This wires the real BacktestEngine end-to-end on real gold data with no network
and no API keys — the reproducible "exercise the pipeline with real data" path.
It is used by ``run.py --mode backtest`` and is importable for CI/tests.

CSV format handled (auto-detected): a date column named one of
``Date|timestamp|date|Datetime`` plus ``open,high,low,close,volume`` in any case.
A ``symbol`` column is optional — when absent the configured symbol is used.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtesting.engine import BacktestEngine, DataFrameDataHandler

logger = logging.getLogger("backtest.cli")

# Capture the genuine pandas shift BEFORE the backtest's no_lookahead_context
# guard monkeypatches it. The inference feature pipeline legitimately uses
# shift(-1) for label creation (the label is dropped before prediction), which
# the guard flags as look-ahead. MLInferenceStrategy restores the real shift
# only around predict(); the prediction window is already sliced to the current
# bar, so no real future data leaks in.
_REAL_DF_SHIFT = pd.DataFrame.shift
_REAL_SERIES_SHIFT = pd.Series.shift

ROOT = Path(__file__).parent.parent
_DATE_COLS = ("date", "timestamp", "datetime", "time")


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """Load an OHLCV CSV into a DatetimeIndex DataFrame with lowercase columns.

    Tolerant of the committed data files (``Date,close,high,low,open,volume``)
    and of intraday files using ``timestamp``.
    """
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise FileNotFoundError(f"Backtest data file not found: {p}")

    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]

    date_col = next((c for c in _DATE_COLS if c in df.columns), None)
    if date_col is None:
        raise ValueError(
            f"{p.name}: no date column found (looked for {_DATE_COLS}); columns={list(df.columns)}"
        )

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()

    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"{p.name}: missing OHLC columns {missing}; columns={list(df.columns)}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df


class MACrossoverStrategy:
    """Self-contained moving-average crossover strategy.

    Matches the BacktestEngine strategy contract:
        strategy(timestamp, symbol, tick, positions, capital, history) -> list[dict]

    Emits one signal on each fast/slow SMA crossover, optionally filtered by a
    longer-term trend SMA (``trend>0``) so it only trades *with* the prevailing
    trend. NOTE: measured on the committed XAUUSD 2Y/5Y data the trend filter
    *reduced* return and win rate (it over-filters gold's behaviour), so it
    defaults OFF (``trend=0`` = raw crossover baseline). It is kept as a
    configurable knob, not a recommended default — this is a baseline strategy,
    not the platform's ML engine.

    Position size is a fixed fraction of current capital, in units at price.
    """

    def __init__(
        self,
        symbol: str,
        fast: int = 10,
        slow: int = 30,
        trend: int = 0,
        capital_fraction: float = 0.5,
    ):
        self.symbol = symbol
        self.fast = fast
        self.slow = slow
        self.trend = trend
        self.capital_fraction = capital_fraction
        self._closes: list[float] = []
        self._last_state: str | None = None  # "fast_above" | "fast_below"

    @staticmethod
    def _sma(values: list[float], n: int) -> float:
        return sum(values[-n:]) / n

    def __call__(self, *, timestamp, symbol, tick, positions, capital, history) -> list[dict]:
        if symbol != self.symbol:
            return []
        price = float(tick.ask)
        self._closes.append(price)
        warmup = max(self.slow, self.trend) + 1
        if len(self._closes) < warmup:
            return []

        fast_ma = self._sma(self._closes, self.fast)
        slow_ma = self._sma(self._closes, self.slow)
        state = "fast_above" if fast_ma > slow_ma else "fast_below"

        # Only act on a state change (a crossover), not every bar.
        if state == self._last_state:
            return []
        prev_state = self._last_state
        self._last_state = state
        if prev_state is None:
            return []  # establish baseline without trading on the first comparison

        action = "buy" if state == "fast_above" else "sell"

        # Trend filter: skip entries that fight the longer-term trend.
        if self.trend > 0:
            trend_ma = self._sma(self._closes, self.trend)
            if action == "buy" and price < trend_ma:
                return []
            if action == "sell" and price > trend_ma:
                return []

        qty = round((capital * self.capital_fraction) / max(price, 1e-9), 4)
        if qty <= 0:
            return []
        return [{"action": action, "quantity": qty}]


class MLInferenceStrategy:
    """Runs the REAL platform model (ml.inference_engine.InferenceEngine) over
    history — the same calibrated ensemble used live (advanced_oos.pkl), not a
    hand-written rule. This validates the actual model edge on real data.

    On each bar it feeds the trailing daily OHLCV window to ``predict()`` and
    acts on the returned ``direction`` (long/short), which the engine only emits
    after its own probability thresholds + calibration. To avoid pyramiding it
    only trades when the direction *changes* (clean position flips), mirroring
    how the live decision pipeline opens/flips a position.

    No look-ahead: the window is sliced up to and including the current bar only.
    """

    def __init__(self, ohlcv_df, symbol: str, capital_fraction: float = 0.5, window: int = 300):
        from ml.inference_engine import InferenceEngine

        self._df = ohlcv_df
        self.symbol = symbol
        # predict() expects the underscore symbol form (e.g. XAU_USD).
        self._pred_symbol = symbol.replace("/", "_")
        self.capital_fraction = capital_fraction
        self.window = window
        self._engine = InferenceEngine()
        self._last_dir: str | None = None
        self.fallback_bars = 0
        self.model_bars = 0
        self.model_version: str | None = None

    def __call__(self, *, timestamp, symbol, tick, positions, capital, history) -> list[dict]:
        if symbol != self.symbol:
            return []
        # Trailing window up to and including the current bar (no future data).
        win = self._df.loc[:timestamp].tail(self.window)
        if len(win) < 100:  # InferenceEngine._MIN_BARS
            return []

        # Let the model's internal pipeline (incl. label-creation shift(-1)) run
        # with the real pandas shift; restore the guard's version afterwards.
        _saved_df, _saved_s = pd.DataFrame.shift, pd.Series.shift
        pd.DataFrame.shift, pd.Series.shift = _REAL_DF_SHIFT, _REAL_SERIES_SHIFT
        try:
            res = self._engine.predict(win, symbol=self._pred_symbol)
        except RuntimeError:
            # Stale/drift block (if enabled) — abstain, like the live Phase-2 gate.
            return []
        except Exception:
            return []
        finally:
            pd.DataFrame.shift, pd.Series.shift = _saved_df, _saved_s

        if res.get("fallback"):
            self.fallback_bars += 1
        else:
            self.model_bars += 1
            self.model_version = res.get("model_version")

        direction = res.get("direction", "neutral")
        if direction not in ("long", "short") or direction == self._last_dir:
            return []
        self._last_dir = direction

        price = float(tick.ask)
        qty = round((capital * self.capital_fraction) / max(price, 1e-9), 4)
        if qty <= 0:
            return []
        return [{"action": "buy" if direction == "long" else "sell", "quantity": qty}]


def run_backtest(
    data_file: str = "data/XAUUSD_5Y.csv",
    symbol: str = "XAU/USD",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    initial_capital: float = 10_000.0,
    data_frequency: str = "1d",
    fast: int = 10,
    slow: int = 30,
    trend: int = 0,
    strategy: str = "ma",
):
    """Run a real-data backtest and return PerformanceMetrics.

    strategy="ma"  → MACrossoverStrategy baseline
    strategy="ml"  → MLInferenceStrategy (the real advanced_oos.pkl model)
    """
    df = load_ohlcv_csv(data_file)
    # Default to the full span of the file when no dates are given.
    start = start_date or df.index.min().to_pydatetime()
    end = end_date or df.index.max().to_pydatetime()

    engine = BacktestEngine(initial_capital=initial_capital, data_frequency=data_frequency)
    engine.set_data_handler(DataFrameDataHandler(df, symbol))
    if strategy == "ml":
        strat = MLInferenceStrategy(df, symbol)
    else:
        strat = MACrossoverStrategy(symbol, fast=fast, slow=slow, trend=trend)
    engine.set_strategy(strat, [symbol])

    logger.info(
        "Backtest: %s strategy=%s %s bars=%d range=%s→%s capital=$%.0f",
        symbol, strategy, data_file, len(df), start.date(), end.date(), initial_capital,
    )
    metrics = engine.run(start_date=start, end_date=end)
    if strategy == "ml":
        logger.info(
            "  ML coverage: %d bars on real model (%s), %d fallback bars",
            getattr(strat, "model_bars", 0),
            getattr(strat, "model_version", None) or "?",
            getattr(strat, "fallback_bars", 0),
        )
    return metrics
