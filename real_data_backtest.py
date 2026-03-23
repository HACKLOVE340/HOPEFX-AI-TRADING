"""
real_data_backtest.py
=====================
Walk-forward backtest on real XAUUSD 1h OHLCV data fetched from Binance via ccxt.

Pipeline:
  1. Paginate all available 1h bars (>500) from ccxt Binance.
  2. Compute ATR(14) stops (1.5×ATR) and take-profit (2.5×ATR).
  3. Apply 1-pip slippage and 2 bps commission on every fill.
  4. Walk-forward split: 70% in-sample train, 30% out-of-sample test.
  5. Return equity curve DataFrame and annualised Sharpe ratio.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import ccxt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SYMBOL = "XAU/USDT"          # Binance uses XAU/USDT; closest proxy for XAUUSD
TIMEFRAME = "1h"
SLIPPAGE_PIPS = 1.0           # 1 pip = $0.01 for gold on most brokers
PIP_VALUE = 0.01              # USD per pip per unit
COMMISSION_BPS = 2.0          # 2 basis points per side
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TP_MULT = 2.5
TRAIN_RATIO = 0.70
INITIAL_CAPITAL = 100_000.0   # USD
POSITION_SIZE = 1.0           # 1 lot (100 oz) — adjust for risk sizing


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_ohlcv_paginated(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: Optional[int] = None,
    max_bars: int = 5000,
    batch_size: int = 500,
) -> pd.DataFrame:
    """
    Fetch OHLCV bars in batches to overcome the 500-bar API limit.

    Returns a DataFrame with columns: [open, high, low, close, volume].
    Index is a UTC-aware DatetimeIndex.
    """
    all_bars: list[list] = []
    fetch_since = since_ms

    while len(all_bars) < max_bars:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=fetch_since, limit=batch_size)
        if not batch:
            break

        # Deduplicate: skip bars already collected
        if all_bars and batch[0][0] <= all_bars[-1][0]:
            batch = [b for b in batch if b[0] > all_bars[-1][0]]
        if not batch:
            break

        all_bars.extend(batch)
        fetch_since = batch[-1][0] + 1  # advance cursor past last bar

        # Respect rate limits
        time.sleep(exchange.rateLimit / 1000)

        if len(batch) < batch_size:
            # Exchange returned fewer bars than requested — we've hit the end
            break

    if not all_bars:
        raise RuntimeError(f"No OHLCV data returned for {symbol} {timeframe}")

    df = pd.DataFrame(all_bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """True Range → EMA-smoothed ATR."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simple trend-following signal:
      - Long  when close > 20-bar SMA and ATR is expanding (momentum filter).
      - Short when close < 20-bar SMA and ATR is expanding.

    Returns df with added columns: [atr, sma20, signal].
    """
    df = df.copy()
    df["atr"] = compute_atr(df)
    df["sma20"] = df["close"].rolling(20).mean()
    df["atr_expanding"] = df["atr"] > df["atr"].rolling(5).mean()

    df["signal"] = 0
    long_cond = (df["close"] > df["sma20"]) & df["atr_expanding"]
    short_cond = (df["close"] < df["sma20"]) & df["atr_expanding"]
    df.loc[long_cond, "signal"] = 1
    df.loc[short_cond, "signal"] = -1

    return df


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, initial_capital: float = INITIAL_CAPITAL) -> pd.DataFrame:
    """
    Event-driven bar-by-bar backtest with ATR stops/TP and cost model.

    Returns a DataFrame with columns:
      [equity, trade_pnl, in_trade, direction, entry_price, stop, tp]
    """
    df = generate_signals(df).dropna()

    equity = initial_capital
    position = 0          # 0 = flat, 1 = long, -1 = short
    entry_price = 0.0
    stop_price = 0.0
    tp_price = 0.0

    records = []

    for ts, row in df.iterrows():
        trade_pnl = 0.0

        # --- Manage open position ---
        if position != 0:
            # Check stop-loss (use low/high for intra-bar touch)
            stop_hit = (position == 1 and row["low"] <= stop_price) or \
                       (position == -1 and row["high"] >= stop_price)
            tp_hit = (position == 1 and row["high"] >= tp_price) or \
                     (position == -1 and row["low"] <= tp_price)

            if stop_hit or tp_hit:
                exit_price = stop_price if stop_hit else tp_price
                # Apply slippage against the trade direction
                exit_price -= position * SLIPPAGE_PIPS * PIP_VALUE
                raw_pnl = position * (exit_price - entry_price) * POSITION_SIZE
                commission = abs(exit_price) * COMMISSION_BPS / 10_000 * POSITION_SIZE
                trade_pnl = raw_pnl - commission
                equity += trade_pnl
                position = 0

        # --- Open new position on signal change ---
        if position == 0 and row["signal"] != 0:
            direction = row["signal"]
            # Slippage on entry
            fill_price = row["close"] + direction * SLIPPAGE_PIPS * PIP_VALUE
            atr = row["atr"]
            stop_price = fill_price - direction * ATR_STOP_MULT * atr
            tp_price = fill_price + direction * ATR_TP_MULT * atr
            commission = abs(fill_price) * COMMISSION_BPS / 10_000 * POSITION_SIZE
            equity -= commission  # entry commission
            entry_price = fill_price
            position = direction

        records.append(
            {
                "timestamp": ts,
                "equity": equity,
                "trade_pnl": trade_pnl,
                "in_trade": position != 0,
                "direction": position,
                "entry_price": entry_price if position != 0 else np.nan,
                "stop": stop_price if position != 0 else np.nan,
                "tp": tp_price if position != 0 else np.nan,
            }
        )

    result = pd.DataFrame(records).set_index("timestamp")
    return result


# ---------------------------------------------------------------------------
# Walk-forward wrapper
# ---------------------------------------------------------------------------

def walk_forward_backtest(
    df: pd.DataFrame,
    train_ratio: float = TRAIN_RATIO,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    """
    Single walk-forward split: train on first `train_ratio` of data,
    evaluate on the remaining out-of-sample window.

    Returns:
        {
          "train_equity": DataFrame,
          "test_equity":  DataFrame,
          "train_sharpe": float,
          "test_sharpe":  float,
          "full_equity":  DataFrame,
        }
    """
    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    train_equity = run_backtest(train_df, initial_capital)
    # Carry forward ending capital from train into test
    test_start_capital = train_equity["equity"].iloc[-1]
    test_equity = run_backtest(test_df, test_start_capital)

    full_equity = pd.concat([train_equity, test_equity])

    return {
        "train_equity": train_equity,
        "test_equity": test_equity,
        "train_sharpe": annualised_sharpe(train_equity["equity"]),
        "test_sharpe": annualised_sharpe(test_equity["equity"]),
        "full_equity": full_equity,
    }


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

def annualised_sharpe(equity: pd.Series, periods_per_year: int = 8760) -> float:
    """
    Annualised Sharpe ratio from an equity curve.

    Assumes hourly bars (8760 periods/year). Risk-free rate = 0.
    """
    returns = equity.pct_change().dropna()
    if returns.std() == 0:
        return 0.0
    return float((returns.mean() / returns.std()) * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a fraction."""
    roll_max = equity.cummax()
    drawdown = (equity - roll_max) / roll_max
    return float(drawdown.min())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> dict:
    """
    Fetch data, run walk-forward backtest, print summary, return results dict.
    """
    exchange = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )

    # Fetch ~3 years of hourly bars (≈26 280 bars)
    since_ms = exchange.parse8601("2021-01-01T00:00:00Z")
    print(f"Fetching {SYMBOL} {TIMEFRAME} bars from Binance …")
    df = fetch_ohlcv_paginated(exchange, SYMBOL, TIMEFRAME, since_ms=since_ms, max_bars=30_000)
    print(f"  Fetched {len(df)} bars  ({df.index[0]} → {df.index[-1]})")

    results = walk_forward_backtest(df)

    train_eq = results["train_equity"]
    test_eq = results["test_equity"]
    full_eq = results["full_equity"]

    print("\n=== Walk-Forward Results ===")
    print(f"  Train bars : {len(train_eq)}")
    print(f"  Test  bars : {len(test_eq)}")
    print(f"  Train Sharpe : {results['train_sharpe']:.3f}")
    print(f"  Test  Sharpe : {results['test_sharpe']:.3f}")
    print(f"  Train start equity : ${train_eq['equity'].iloc[0]:,.2f}")
    print(f"  Train end   equity : ${train_eq['equity'].iloc[-1]:,.2f}")
    print(f"  Test  end   equity : ${test_eq['equity'].iloc[-1]:,.2f}")
    print(f"  Full  max drawdown : {max_drawdown(full_eq['equity']):.2%}")

    return results


if __name__ == "__main__":
    main()
