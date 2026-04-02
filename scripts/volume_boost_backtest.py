#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/volume_boost_backtest.py
=================================
GC=F (Gold Futures) volume-boosted backtest — 2022-2026 real data.

Timeframe strategy
------------------
yfinance caps 15m history at ~60 days. To cover 2022-2026 we use:
  - Daily bars (2022-01-01 → today) for the full historical run
  - 15m bars (last 60 days) for the recent high-resolution run
Both runs are reported. The daily run is the primary result.

Strategy
--------
- Signal: EMA(9) crosses EMA(21) with volume > 1.5× 20-bar avg volume
- Stop-loss:   1.5× ATR(14)
- Take-profit: 3.0× ATR(14)  →  2:1 R:R
- Risk per trade: 1% of running balance

Monte Carlo
-----------
1000 simulations (random trade-order shuffles) → worst-case DD distribution.
P&L is expressed as % of balance (normalised) so MC stats are meaningful.

Outputs
-------
- data/backtest_results_daily.csv   — per-trade log (daily run)
- data/backtest_results_15m.csv     — per-trade log (15m run)
- data/monte_carlo_results.json     — MC stats for both runs

Usage
-----
    python scripts/volume_boost_backtest.py
    python scripts/volume_boost_backtest.py --mc-runs 500 --no-15m
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("volume_backtest")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


# ── data download ─────────────────────────────────────────────────────────────


def download_data(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Download OHLCV data via yfinance.

    yfinance interval limits:
      1d  — unlimited history
      1h  — last 730 days
      15m — last 60 days (chunked automatically)
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    logger.info("Downloading %s %s  %s → %s …", symbol, interval, start, end)

    if interval in ("15m", "30m", "5m", "1m"):
        # Chunk into 50-day windows to stay within yfinance limits
        chunks: list[pd.DataFrame] = []
        cursor = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
        window = pd.Timedelta(days=50)
        while cursor < end_dt:
            chunk_end = min(cursor + window, end_dt)
            try:
                df = yf.download(
                    symbol,
                    start=cursor.strftime("%Y-%m-%d"),
                    end=chunk_end.strftime("%Y-%m-%d"),
                    interval=interval,
                    progress=False,
                    auto_adjust=True,
                )
                if not df.empty:
                    chunks.append(df)
            except Exception as exc:
                logger.warning("Chunk %s→%s failed: %s", cursor.date(), chunk_end.date(), exc)
            cursor = chunk_end
        data = pd.concat(chunks) if chunks else pd.DataFrame()
    else:
        data = yf.download(
            symbol,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )

    if data.empty:
        logger.error("No data downloaded for %s %s", symbol, interval)
        return data

    # Flatten MultiIndex columns (yfinance v0.2+)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] for col in data.columns]

    data = data[~data.index.duplicated(keep="first")].sort_index()
    data.dropna(inplace=True)
    logger.info("Downloaded %d bars  (%s → %s)", len(data), data.index[0], data.index[-1])
    return data


# ── indicators ────────────────────────────────────────────────────────────────


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["Close"].ewm(span=21, adjust=False).mean()

    # ATR(14)
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift(1)).abs()
    lc = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(span=14, adjust=False).mean()

    # Volume average (20-bar)
    df["vol_avg20"] = df["Volume"].rolling(20).mean()

    # EMA crossover: +1 BUY, -1 SELL
    df["cross"] = 0
    df.loc[
        (df["ema9"] > df["ema21"]) & (df["ema9"].shift(1) <= df["ema21"].shift(1)),
        "cross",
    ] = 1
    df.loc[
        (df["ema9"] < df["ema21"]) & (df["ema9"].shift(1) >= df["ema21"].shift(1)),
        "cross",
    ] = -1

    # Volume filter
    df["vol_ok"] = df["Volume"] > (df["vol_avg20"] * 1.5)

    df.dropna(inplace=True)
    return df


# ── backtest engine ───────────────────────────────────────────────────────────


def run_backtest(
    df: pd.DataFrame,
    initial_balance: float = 100_000.0,
    risk_pct: float = 0.01,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
    commission_pct: float = 0.0002,  # 0.02% round-trip (realistic for futures)
) -> tuple[pd.DataFrame, dict]:
    """
    Event-driven backtest.

    P&L is expressed as a fraction of balance (normalised) so that
    Monte Carlo simulations produce meaningful drawdown estimates.
    """
    balance = initial_balance
    peak_bal = initial_balance
    max_dd = 0.0
    trades: list[dict] = []

    in_trade = False
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    trade_side = 0
    entry_time = None
    risk_amount = 0.0  # $ risked on this trade

    for ts, row in df.iterrows():
        if in_trade:
            if trade_side == 1:
                hit_sl = row["Low"] <= sl_price
                hit_tp = row["High"] >= tp_price
            else:
                hit_sl = row["High"] >= sl_price
                hit_tp = row["Low"] <= tp_price

            if hit_tp or hit_sl:
                exit_price = tp_price if hit_tp else sl_price
                # R-multiple: +2 for TP (2:1 R:R), -1 for SL
                r_mult = tp_atr_mult / sl_atr_mult if hit_tp else -1.0
                pnl = risk_amount * r_mult - balance * commission_pct
                balance += pnl
                peak_bal = max(peak_bal, balance)
                dd = (peak_bal - balance) / peak_bal if peak_bal > 0 else 0.0
                max_dd = max(max_dd, dd)

                trades.append(
                    {
                        "entry_time": entry_time,
                        "exit_time": ts,
                        "side": "BUY" if trade_side == 1 else "SELL",
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "sl_price": sl_price,
                        "tp_price": tp_price,
                        "pnl_usd": round(pnl, 4),
                        "pnl_pct": round(pnl / (balance - pnl) * 100, 4),
                        "win": int(hit_tp),
                        "balance": round(balance, 2),
                        "drawdown_pct": round(dd * 100, 4),
                    }
                )
                in_trade = False

        if not in_trade and row["cross"] != 0 and row["vol_ok"]:
            atr = row["atr14"]
            if atr == 0:
                continue
            trade_side = int(row["cross"])
            entry_price = row["Close"]
            entry_time = ts
            risk_amount = balance * risk_pct  # 1% of current balance

            if trade_side == 1:
                sl_price = entry_price - sl_atr_mult * atr
                tp_price = entry_price + tp_atr_mult * atr
            else:
                sl_price = entry_price + sl_atr_mult * atr
                tp_price = entry_price - tp_atr_mult * atr

            in_trade = True

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return trades_df, {}

    wins = trades_df["win"].sum()
    total = len(trades_df)
    win_rate = wins / total if total > 0 else 0

    # Sharpe on daily P&L
    try:
        daily_pnl = trades_df.set_index("exit_time")["pnl_usd"].resample("D").sum()
        sharpe = (daily_pnl.mean() / daily_pnl.std() * (252**0.5)) if daily_pnl.std() > 0 else 0.0
    except Exception:
        sharpe = 0.0

    summary = {
        "symbol": "GC=F",
        "timeframe": "varies",
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "total_bars": len(df),
        "total_trades": total,
        "win_rate_pct": round(win_rate * 100, 2),
        "total_pnl_usd": round(trades_df["pnl_usd"].sum(), 2),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "sharpe_ratio": round(float(sharpe), 4),
        "final_balance": round(balance, 2),
        "initial_balance": initial_balance,
        "return_pct": round((balance - initial_balance) / initial_balance * 100, 4),
    }
    return trades_df, summary


# ── Monte Carlo ───────────────────────────────────────────────────────────────


def monte_carlo(trades_df: pd.DataFrame, n_runs: int = 1000, seed: int = 42) -> dict:
    """
    Shuffle trade P&L (as % of balance) n_runs times.
    Returns worst-case drawdown distribution.
    """
    if trades_df.empty:
        return {}

    rng = np.random.default_rng(seed)
    # Use pnl_pct (normalised) so DD is meaningful regardless of balance scale
    pnls = trades_df["pnl_pct"].values / 100.0  # convert to fraction

    max_dds: list[float] = []
    for _ in range(n_runs):
        shuffled = rng.permutation(pnls)
        equity = np.cumprod(1 + shuffled)  # compound returns
        peak = np.maximum.accumulate(equity)
        dd_series = (peak - equity) / peak
        max_dds.append(float(dd_series.max()))

    arr = np.array(max_dds)
    result = {
        "n_runs": n_runs,
        "worst_case_dd_pct": round(float(arr.max()) * 100, 4),
        "p99_dd_pct": round(float(np.percentile(arr, 99)) * 100, 4),
        "p95_dd_pct": round(float(np.percentile(arr, 95)) * 100, 4),
        "median_dd_pct": round(float(np.median(arr)) * 100, 4),
        "mean_dd_pct": round(float(arr.mean()) * 100, 4),
    }
    logger.info(
        "Monte Carlo (%d runs) | worst=%.2f%% | p95=%.2f%% | p99=%.2f%%",
        n_runs,
        result["worst_case_dd_pct"],
        result["p95_dd_pct"],
        result["p99_dd_pct"],
    )
    return result


# ── reporting ─────────────────────────────────────────────────────────────────


def print_summary(label: str, summary: dict, mc: dict) -> None:
    print(f"\n{'=' * 62}")
    print(f"  HOPEFX Volume-Boost Backtest — {label}")
    print(f"{'=' * 62}")
    for k, v in summary.items():
        print(f"  {k:<28} {v}")
    if mc:
        print(f"\n  Monte Carlo worst-case drawdown ({mc['n_runs']} runs)")
        for k, v in mc.items():
            print(f"  {k:<28} {v}")
    print(f"{'=' * 62}")
    if summary.get("total_trades", 0) < 200:  # noqa: PLR2004
        logger.warning(
            "Trade count %d < 200 target (expected for daily bars — "
            "use --interval 1h or run 15m mode for higher frequency)",
            summary["total_trades"],
        )


# ── CLI ───────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    p = argparse.ArgumentParser(description="Volume-boost GC=F backtest 2022-2026")
    p.add_argument("--symbol", default="GC=F")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default=today)
    p.add_argument("--balance", type=float, default=100_000.0)
    p.add_argument("--risk", type=float, default=0.01)
    p.add_argument("--mc-runs", type=int, default=1000)
    p.add_argument("--no-mc", action="store_true")
    p.add_argument("--no-15m", action="store_true", help="Skip 15m recent run")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    all_results: dict = {}

    # ── Run 1: Daily bars 2022 → today (full history) ────────────────────────
    logger.info("=== Run 1: Daily bars 2022-2026 ===")
    df_daily = download_data(args.symbol, args.start, args.end, "1d")
    if not df_daily.empty:
        df_daily = add_indicators(df_daily)
        trades_daily, summary_daily = run_backtest(df_daily, args.balance, args.risk)
        summary_daily["timeframe"] = "1d"
        if not trades_daily.empty:
            trades_daily.to_csv(DATA_DIR / "backtest_results_daily.csv", index=False)
            mc_daily = {} if args.no_mc else monte_carlo(trades_daily, args.mc_runs)
            print_summary("GC=F Daily 2022-2026", summary_daily, mc_daily)
            all_results["daily"] = {**summary_daily, "monte_carlo": mc_daily}

    # ── Run 2: 15m bars last 60 days ─────────────────────────────────────────
    if not args.no_15m:
        logger.info("=== Run 2: 15m bars (last 60 days) ===")
        from datetime import timedelta

        start_15m = (datetime.now(UTC) - timedelta(days=58)).strftime("%Y-%m-%d")
        df_15m = download_data(args.symbol, start_15m, args.end, "15m")
        if not df_15m.empty:
            df_15m = add_indicators(df_15m)
            trades_15m, summary_15m = run_backtest(df_15m, args.balance, args.risk)
            summary_15m["timeframe"] = "15m"
            if not trades_15m.empty:
                trades_15m.to_csv(DATA_DIR / "backtest_results_15m.csv", index=False)
                mc_15m = {} if args.no_mc else monte_carlo(trades_15m, args.mc_runs)
                print_summary("GC=F 15m (last 60 days)", summary_15m, mc_15m)
                all_results["15m"] = {**summary_15m, "monte_carlo": mc_15m}

    # ── Save combined results ─────────────────────────────────────────────────
    if all_results:
        mc_json = DATA_DIR / "monte_carlo_results.json"
        mc_json.write_text(json.dumps(all_results, indent=2, default=str))
        logger.info("Combined results saved → %s", mc_json)


if __name__ == "__main__":
    main()
