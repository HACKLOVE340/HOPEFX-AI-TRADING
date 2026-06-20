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

    Emits one signal on each fast/slow SMA crossover. Position size is a fixed
    fraction of current capital converted to units at the current price.
    """

    def __init__(self, symbol: str, fast: int = 10, slow: int = 30, capital_fraction: float = 0.5):
        self.symbol = symbol
        self.fast = fast
        self.slow = slow
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
        if len(self._closes) < self.slow + 1:
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

        qty = round((capital * self.capital_fraction) / max(price, 1e-9), 4)
        if qty <= 0:
            return []
        action = "buy" if state == "fast_above" else "sell"
        return [{"action": action, "quantity": qty}]


def run_backtest(
    data_file: str = "data/XAUUSD_5Y.csv",
    symbol: str = "XAU/USD",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    initial_capital: float = 10_000.0,
    data_frequency: str = "1d",
    fast: int = 10,
    slow: int = 30,
):
    """Run a real-data backtest and return PerformanceMetrics."""
    df = load_ohlcv_csv(data_file)
    # Default to the full span of the file when no dates are given.
    start = start_date or df.index.min().to_pydatetime()
    end = end_date or df.index.max().to_pydatetime()

    engine = BacktestEngine(initial_capital=initial_capital, data_frequency=data_frequency)
    engine.set_data_handler(DataFrameDataHandler(df, symbol))
    engine.set_strategy(MACrossoverStrategy(symbol, fast=fast, slow=slow), [symbol])

    logger.info(
        "Backtest: %s %s bars=%d range=%s→%s capital=$%.0f",
        symbol, data_file, len(df), start.date(), end.date(), initial_capital,
    )
    metrics = engine.run(start_date=start, end_date=end)
    return metrics
