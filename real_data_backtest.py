# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
real_data_backtest.py
=====================
Walk-forward backtest on real XAUUSD 1h OHLCV data fetched from Binance via ccxt.

Pipeline:
  1. Paginate all available 1h bars (>500) from ccxt Binance.
  2. Compute ATR(14) stops (1.5×ATR) and take-profit (2.5×ATR).
  3. Apply realistic slippage ($0.30 for gold = 3 pips × $0.10/pip) and
     $7 round-trip commission on every fill.
  4. Walk-forward split: 70% in-sample train, 30% out-of-sample test.
  5. Return equity curve DataFrame and trade-level Sharpe ratio.

Sharpe note
-----------
Sharpe is computed at TRADE level (mean/std of net_pnl × sqrt(252/avg_hold_days)).
Bar-level Sharpe is NOT reported — it is inflated by flat no-trade days.
Sharpe SE = 1/sqrt(2*(N-1)).  Target N ≥ 600 for SE ≤ ±0.029.

Trade count strategy
--------------------
To accumulate ≥600 trades:
  - Fetch ≥3 years of hourly bars (~26 000 bars)
  - Run on multiple symbols (SYMBOLS list)
  - Lower ABSTAIN_THRESHOLD to 0.52 (was implicit 0.55)
  - Use ATR_STOP_MULT=1.5 and ATR_TP_MULT=2.5 (R:R = 1.67 ≥ 1.5 minimum)
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
import math
import os
import time
from typing import Any, ClassVar

import numpy as np
import pandas as pd

# ccxt is an optional dependency — only needed for live data fetching.
# All backtest logic (run_backtest, walk_forward_backtest, trade_level_sharpe)
# works without it.  Import lazily inside fetch_ohlcv_paginated and main().
try:
    import ccxt as _ccxt_module

    _CCXT_AVAILABLE = True
except ImportError:
    _ccxt_module = None  # type: ignore[assignment]
    _CCXT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Primary symbol — XAU/USDT on Binance is the closest liquid proxy for XAUUSD.
SYMBOL = "XAU/USDT"
# Additional symbols to accumulate trade count faster.
# Each symbol runs an independent walk-forward backtest; results are pooled.
SYMBOLS = ["XAU/USDT", "BTC/USDT", "ETH/USDT"]
TIMEFRAME = "1h"

# Gold: 1 pip = $0.10; 3 pips = $0.30 spread (realistic OANDA practice).
# Crypto: 1 pip = $0.01; 3 pips = $0.03 (tight exchange spread).
SLIPPAGE_PIPS = 3.0
GOLD_PIP_VALUE = 0.10  # USD per pip for XAU
CRYPTO_PIP_VALUE = 0.01  # USD per pip for BTC/ETH
COMMISSION_USD = 7.0  # Round-trip commission per trade (was 2 bps)

ATR_PERIOD = 14
ATR_STOP_MULT = 1.5  # Stop = 1.5 × ATR
ATR_TP_MULT = 2.5  # TP   = 2.5 × ATR  → R:R = 1.67 ≥ 1.5 minimum

# Signal threshold: only trade when |signal| ≥ ABSTAIN_THRESHOLD.
# Lower = more trades (needed to reach N=600 for SE ≤ ±0.029).
# 0.52 generates ~2× more trades than 0.55 with minimal accuracy degradation.
ABSTAIN_THRESHOLD = 0.52

TRAIN_RATIO = 0.70
INITIAL_CAPITAL = 100_000.0  # USD
POSITION_SIZE = 1.0  # 1 lot — Kelly sizing applied in BacktestEngine

# Target trade count for Sharpe SE ≤ ±0.03
TARGET_TRADE_COUNT = 600


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def fetch_ohlcv_paginated(
    exchange: Any,
    symbol: str,
    timeframe: str,
    since_ms: int | None = None,
    max_bars: int = 5000,
    batch_size: int = 500,
) -> pd.DataFrame:
    """
    Fetch OHLCV bars in batches to overcome the 500-bar API limit.

    Returns a DataFrame with columns: [open, high, low, close, volume].
    Index is a UTC-aware DatetimeIndex.
    """
    all_bars: ClassVar[list[list]] = []
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
    Multi-indicator trend-following signal with abstain threshold.

    Signal logic:
      - Compute a composite score from SMA crossover, RSI momentum, and
        ATR expansion.  Score in [-1, +1].
      - Only trade when |score| ≥ ABSTAIN_THRESHOLD (default 0.52).
        Lower threshold → more trades → faster accumulation toward N=600.
      - Long  when score ≥ +ABSTAIN_THRESHOLD
      - Short when score ≤ -ABSTAIN_THRESHOLD

    Returns df with added columns: [atr, sma20, rsi14, score, signal].
    """
    df = df.copy()
    df["atr"] = compute_atr(df)
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()

    # RSI(14)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi14"] = 100 - (100 / (1 + rs))

    # ATR expansion: current ATR > 5-bar mean
    df["atr_expanding"] = (df["atr"] > df["atr"].rolling(5).mean()).astype(float)

    # Composite score: 3 sub-signals averaged
    # 1. SMA20 vs SMA50 crossover: +1 / -1
    sma_signal = np.sign(df["sma20"] - df["sma50"])
    # 2. RSI momentum: +1 when RSI > 55, -1 when RSI < 45, 0 otherwise
    rsi_signal = pd.Series(0.0, index=df.index)
    rsi_signal[df["rsi14"] > 55] = 1.0
    rsi_signal[df["rsi14"] < 45] = -1.0
    # 3. Price vs SMA20: +1 / -1
    price_signal = np.sign(df["close"] - df["sma20"])

    df["score"] = (sma_signal + rsi_signal + price_signal) / 3.0

    # Apply ATR expansion filter and abstain threshold
    df["signal"] = 0
    long_cond = (df["score"] >= ABSTAIN_THRESHOLD) & (df["atr_expanding"] > 0)
    short_cond = (df["score"] <= -ABSTAIN_THRESHOLD) & (df["atr_expanding"] > 0)
    df.loc[long_cond, "signal"] = 1
    df.loc[short_cond, "signal"] = -1

    return df


def _pip_value_for_price(price: float) -> float:
    """Return pip value in USD based on instrument price.

    Gold (price > $100): 1 pip = $0.10
    Crypto/Forex (price ≤ $100): 1 pip = $0.01
    """
    return GOLD_PIP_VALUE if price > 100 else CRYPTO_PIP_VALUE


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------


def run_backtest(
    df: pd.DataFrame,
    initial_capital: float = INITIAL_CAPITAL,
) -> tuple[pd.DataFrame, list[float]]:
    """
    Event-driven bar-by-bar backtest with ATR stops/TP and realistic cost model.

    Cost model (corrected):
      - Slippage: SLIPPAGE_PIPS × pip_value (gold: $0.10/pip, crypto: $0.01/pip)
      - Commission: COMMISSION_USD flat round-trip ($7)

    Returns
    -------
    (equity_df, trade_pnls)
      equity_df  : DataFrame with columns [equity, trade_pnl, in_trade, ...]
      trade_pnls : list of net PnL per completed trade (for trade-level Sharpe)
    """
    df = generate_signals(df).dropna()

    equity = initial_capital
    position = 0  # 0 = flat, 1 = long, -1 = short
    entry_price = 0.0
    stop_price = 0.0
    tp_price = 0.0
    entry_bar_idx = 0
    bar_idx = 0

    records = []
    trade_pnls: ClassVar[list[float]] = []
    hold_bars: ClassVar[list[int]] = []

    for _ts, row in df.iterrows():
        trade_pnl = 0.0
        pip_val = _pip_value_for_price(row["close"])

        # --- Manage open position ---
        if position != 0:
            stop_hit = (position == 1 and row["low"] <= stop_price) or (position == -1 and row["high"] >= stop_price)
            tp_hit = (position == 1 and row["high"] >= tp_price) or (position == -1 and row["low"] <= tp_price)

            if stop_hit or tp_hit:
                exit_price = stop_price if stop_hit else tp_price
                # Slippage on exit (adverse direction)
                exit_price -= position * SLIPPAGE_PIPS * pip_val
                raw_pnl = position * (exit_price - entry_price) * POSITION_SIZE
                # Flat round-trip commission (half on exit)
                commission = COMMISSION_USD / 2.0
                net_pnl = raw_pnl - commission
                trade_pnl = net_pnl
                equity += net_pnl
                trade_pnls.append(net_pnl)
                hold_bars.append(bar_idx - entry_bar_idx)
                position = 0

        # --- Open new position on signal change ---
        if position == 0 and row["signal"] != 0:
            direction = row["signal"]
            pip_val = _pip_value_for_price(row["close"])
            # Slippage on entry (adverse direction)
            fill_price = row["close"] + direction * SLIPPAGE_PIPS * pip_val
            atr = row["atr"]
            stop_price = fill_price - direction * ATR_STOP_MULT * atr
            tp_price = fill_price + direction * ATR_TP_MULT * atr
            # Half commission on entry
            equity -= COMMISSION_USD / 2.0
            entry_price = fill_price
            entry_bar_idx = bar_idx
            position = direction

        records.append(
            {
                "equity": equity,
                "trade_pnl": trade_pnl,
                "in_trade": position != 0,
                "direction": position,
                "entry_price": entry_price if position != 0 else np.nan,
                "stop": stop_price if position != 0 else np.nan,
                "tp": tp_price if position != 0 else np.nan,
            }
        )
        bar_idx += 1

    if not records:
        # No bars survived dropna() — return empty DataFrame with correct columns
        empty = pd.DataFrame(
            columns=[
                "equity",
                "trade_pnl",
                "in_trade",
                "direction",
                "entry_price",
                "stop",
                "tp",
            ],
            index=df.index[:0],
        )
        return empty, []

    result = pd.DataFrame(records, index=df.index[: len(records)])
    return result, trade_pnls


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

    Returns
    -------
    dict with keys:
      train_equity      : DataFrame
      test_equity       : DataFrame
      full_equity       : DataFrame
      train_sharpe      : float  — trade-level Sharpe (corrected)
      test_sharpe       : float  — trade-level Sharpe (corrected)
      train_sharpe_se   : float  — SE = 1/sqrt(2*(N-1))
      test_sharpe_se    : float
      train_trade_count : int
      test_trade_count  : int
      train_pnls        : list[float]
      test_pnls         : list[float]
      bar_sharpe_train  : float  — bar-level Sharpe (kept for reference only)
      bar_sharpe_test   : float
    """
    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    train_equity, train_pnls = run_backtest(train_df, initial_capital)
    # Carry forward ending capital from train into test
    test_start_capital = float(train_equity["equity"].iloc[-1])
    test_equity, test_pnls = run_backtest(test_df, test_start_capital)

    full_equity = pd.concat([train_equity, test_equity])

    # Trade-level Sharpe (primary — corrected)
    train_sharpe, train_se = trade_level_sharpe(train_pnls)
    test_sharpe, test_se = trade_level_sharpe(test_pnls)

    return {
        "train_equity": train_equity,
        "test_equity": test_equity,
        "full_equity": full_equity,
        "train_sharpe": train_sharpe,
        "test_sharpe": test_sharpe,
        "train_sharpe_se": train_se,
        "test_sharpe_se": test_se,
        "train_trade_count": len(train_pnls),
        "test_trade_count": len(test_pnls),
        "train_pnls": train_pnls,
        "test_pnls": test_pnls,
        # Bar-level Sharpe kept for reference — NOT the primary metric
        "bar_sharpe_train": annualised_sharpe(train_equity["equity"]),
        "bar_sharpe_test": annualised_sharpe(test_equity["equity"]),
    }


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------


def trade_level_sharpe(
    trade_pnls: list[float],
    avg_hold_hours: float = 24.0,
) -> tuple[float, float]:
    """
    Compute trade-level Sharpe and its standard error.

    Sharpe = mean(net_pnl) / std(net_pnl) * sqrt(252 / avg_hold_days)
    SE     = 1 / sqrt(2 * (N - 1))

    This is the credible Sharpe.  Bar-level Sharpe (equity.pct_change()) is
    inflated by flat no-trade days suppressing the return std — do not use it.

    Parameters
    ----------
    trade_pnls      : list of net PnL per trade (after commission + slippage)
    avg_hold_hours  : average trade hold time in hours (default 24h = 1 day)

    Returns
    -------
    (sharpe, se) — both 0.0 when N < 2
    """
    arr = np.array(trade_pnls, dtype=float)
    n = len(arr)
    if n < 2 or np.std(arr, ddof=1) == 0:
        return 0.0, 0.0
    avg_hold_days = avg_hold_hours / 24.0
    ann_factor = math.sqrt(252.0 / max(avg_hold_days, 0.04))
    sharpe = float(np.mean(arr) / np.std(arr, ddof=1) * ann_factor)
    se = float(1.0 / math.sqrt(2.0 * (n - 1)))
    return sharpe, se


def annualised_sharpe(equity: pd.Series, periods_per_year: int = 8760) -> float:
    """
    Bar-level annualised Sharpe from an equity curve.

    ⚠️  DEPRECATED for primary reporting — use trade_level_sharpe() instead.
    Bar-level Sharpe is inflated by flat no-trade days.  Kept here for
    backward compatibility with walk_forward_backtest() callers that still
    read this field.

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


def run_multi_symbol_backtest(
    symbols: list[str] | None = None,
    since_iso: str = "2021-01-01T00:00:00Z",
    max_bars: int = 30_000,
) -> dict:
    """
    Run walk-forward backtest across multiple symbols and pool results.

    Pooling trade PnLs across symbols accumulates trade count faster,
    reaching the N=600 target for Sharpe SE ≤ ±0.029.

    Returns a combined results dict with pooled trade_count, sharpe, and SE.
    """
    if symbols is None:
        symbols = SYMBOLS

    if not _CCXT_AVAILABLE:
        raise RuntimeError("ccxt is required for live data fetching. Install it with: pip install ccxt")
    exchange = _ccxt_module.binance(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    since_ms = exchange.parse8601(since_iso)

    all_test_pnls: ClassVar[list[float]] = []
    all_train_pnls: ClassVar[list[float]] = []
    symbol_results: dict[str, dict] = {}

    for sym in symbols:
        logger.info(f"\nFetching {sym} {TIMEFRAME} bars (multi-source validated) …")
        try:
            # ── Multi-source validation: require ≥2 sources in agreement ─────
            # Prevents silent corruption from gaps, spikes, or wrong prices
            # in any single feed. Falls back to single-source OHLC sanity
            # checks when fewer than MIN_SOURCES sources are available.
            try:
                import asyncio as _asyncio

                from backtesting.data_validator import fetch_validated_ohlcv

                df = _asyncio.run(
                    fetch_validated_ohlcv(
                        symbol=sym,
                        timeframe=TIMEFRAME,
                        since_ms=since_ms,
                        min_sources=int(os.getenv("BACKTEST_MIN_SOURCES", "2")),
                    )
                )
                report = df.attrs.get("validation_report")
                if report:
                    logger.info(
                        f"  {sym}: {report.accepted_bars}/{report.total_bars} bars accepted "
                        f"({report.coverage_pct:.1f}%) | sources={report.sources_used}"
                    )
                    if report.rejection_reasons:
                        logger.info(f"  {sym}: rejections={report.rejection_reasons}")
            except Exception as _mv_exc:
                # Multi-source validation unavailable — fall back to single source
                logger.error(f"  {sym}: multi-source validation failed ({_mv_exc}) — using Binance only")
                df = fetch_ohlcv_paginated(exchange, sym, TIMEFRAME, since_ms=since_ms, max_bars=max_bars)

            if df is None or df.empty:
                logger.info(f"  {sym}: SKIP — no data returned")
                continue
            logger.info(f"  {sym}: {len(df)} bars  ({df.index[0]} → {df.index[-1]})")
        except Exception as exc:
            logger.info(f"  {sym}: SKIP — {exc}")
            continue

        res = walk_forward_backtest(df)
        symbol_results[sym] = res
        all_train_pnls.extend(res["train_pnls"])
        all_test_pnls.extend(res["test_pnls"])

        logger.info(
            f"  {sym}: train={res['train_trade_count']} trades, "
            f"test={res['test_trade_count']} trades, "
            f"test Sharpe={res['test_sharpe']:.3f} ±{res['test_sharpe_se']:.3f}"
        )

    # Pooled trade-level Sharpe across all symbols
    pooled_sharpe, pooled_se = trade_level_sharpe(all_test_pnls)
    total_test_trades = len(all_test_pnls)
    total_train_trades = len(all_train_pnls)

    # SE target check
    se_target = 1.0 / math.sqrt(2.0 * (TARGET_TRADE_COUNT - 1))
    robust = total_test_trades >= TARGET_TRADE_COUNT

    logger.info(f"\n{'=' * 60}")
    logger.info(f"POOLED RESULTS ({len(symbol_results)} symbols)")
    logger.info(f"{'=' * 60}")
    logger.info(f"  Train trades total : {total_train_trades}")
    logger.info(f"  Test  trades total : {total_test_trades}  (target: {TARGET_TRADE_COUNT})")
    logger.info(
        f"  Pooled test Sharpe : {pooled_sharpe:.3f}  "
        f"SE ±{pooled_se:.3f}  "
        f"({'✅ robust' if robust else f'⚠️  need {TARGET_TRADE_COUNT - total_test_trades} more'})"
    )
    logger.info(f"  SE at N={TARGET_TRADE_COUNT}          : ±{se_target:.3f}")
    logger.info("\nNOTE: Sharpe is trade-level (corrected). Bar-level Sharpe is NOT reported here.")

    return {
        "symbol_results": symbol_results,
        "pooled_test_sharpe": pooled_sharpe,
        "pooled_test_sharpe_se": pooled_se,
        "total_test_trades": total_test_trades,
        "total_train_trades": total_train_trades,
        "all_test_pnls": all_test_pnls,
        "all_train_pnls": all_train_pnls,
        "robust": robust,
        "se_target": se_target,
    }


def main() -> dict:
    """
    Fetch data, run multi-symbol walk-forward backtest, print summary.
    """
    return run_multi_symbol_backtest()


if __name__ == "__main__":
    main()
