#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/run_tick_backtest.py
==============================
Download Dukascopy XAUUSD tick data and run a tick-level backtest.

This validates the ML model on real intraday tick data — not just daily bars.
Tick data is free from Dukascopy (no account required).

Usage
-----
    # Default: last 30 days of tick data
    python scripts/run_tick_backtest.py

    # Custom date range
    python scripts/run_tick_backtest.py --start 2024-01-01 --end 2024-03-31

    # Quick smoke test (last 3 days)
    python scripts/run_tick_backtest.py --smoke

    # Save results to CSV
    python scripts/run_tick_backtest.py --output data/tick_backtest_results.csv

What it does
------------
1. Downloads XAUUSD bi5 tick files from datafeed.dukascopy.com (cached locally)
2. Aggregates ticks into H1 OHLCV bars
3. Runs the production ML model (advanced_oos.pkl) on each bar
4. Simulates fills using AlmgrenChriss market impact model
5. Reports: accuracy, win rate, Sharpe, max drawdown, trade count

Cache
-----
Downloaded bi5 files are cached in data/dukascopy_cache/ — subsequent runs
for the same date range are instant (no re-download).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("tick_backtest")

UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dukascopy tick-level backtest")
    p.add_argument("--smoke", action="store_true", help="Quick test: last 3 days only")
    p.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (default: 30 days ago)")
    p.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (default: yesterday)")
    p.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol (default: XAUUSD)")
    p.add_argument("--output", type=str, default=None, help="Save trade log to CSV")
    p.add_argument("--capital", type=float, default=100_000.0, help="Starting capital (default: 100000)")
    return p.parse_args()


async def download_and_aggregate(
    symbol: str,
    start: datetime,
    end: datetime,
) -> "pd.DataFrame":
    """Download Dukascopy ticks and aggregate to H1 OHLCV."""
    from data_layer.replay.engine import MarketReplayEngine
    from data_layer.replay.dukascopy import DukascopyFetcher

    fetcher = DukascopyFetcher()
    engine = MarketReplayEngine(fetcher=fetcher)

    logger.info("Downloading %s ticks %s → %s...", symbol, start.date(), end.date())
    ohlcv = await engine.build_ohlcv_dataframe(
        start=start,
        end=end,
        symbol=symbol,
        timeframe_minutes=60,
        normalize=False,
    )
    await fetcher.close()

    if ohlcv.empty:
        logger.error("No tick data returned — check network or try a different date range")
        sys.exit(1)

    logger.info("Aggregated %d H1 bars from tick data", len(ohlcv))
    return ohlcv


def run_backtest(
    ohlcv: "pd.DataFrame",
    capital: float,
) -> dict:
    """Run the production ML model on tick-aggregated H1 bars."""
    import numpy as np
    import pandas as pd
    import joblib

    # Load production model
    model_path = ROOT / "ml" / "saved_models" / "advanced_oos.pkl"
    if not model_path.exists():
        logger.error("Model not found at %s — run ml/train_advanced.py first", model_path)
        sys.exit(1)

    model = joblib.load(model_path)
    logger.info("Loaded model from %s", model_path)

    # Build features
    from ml.advanced_features import build_advanced_features
    try:
        X, y = build_advanced_features(ohlcv, horizon=1)
    except Exception as exc:
        logger.error("Feature build failed: %s", exc)
        sys.exit(1)

    # Drop NaN warm-up rows
    mask = ~(np.isnan(X.values if hasattr(X, 'values') else X).any(axis=1))
    X_clean = X[mask] if hasattr(X, '__getitem__') else X[mask]
    y_clean = y[mask] if hasattr(y, '__getitem__') else y[mask]

    if len(X_clean) < 10:
        logger.error("Not enough clean bars (%d) for backtest", len(X_clean))
        sys.exit(1)

    logger.info("Running model on %d bars...", len(X_clean))

    # Get probabilities
    X_vals = X_clean.values if hasattr(X_clean, 'values') else X_clean
    probs = model.predict_proba(X_vals)[:, 1]

    # Signal thresholds
    threshold_long = float(__import__('os').getenv("SIGNAL_THRESHOLD_LONG", "0.60"))
    threshold_short = float(__import__('os').getenv("SIGNAL_THRESHOLD_SHORT", "0.40"))

    # Simulate trades with AlmgrenChriss fills
    from execution.market_impact import FillSimulator
    fill_sim = FillSimulator()

    trades = []
    equity = capital
    peak_equity = capital
    max_dd = 0.0
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0.0
    entry_bar = None

    closes = ohlcv["close"].values if hasattr(ohlcv, 'values') else ohlcv["close"]
    highs = ohlcv["high"].values if hasattr(ohlcv, 'values') else ohlcv["high"]
    lows = ohlcv["low"].values if hasattr(ohlcv, 'values') else ohlcv["low"]
    volumes = ohlcv["volume"].values if hasattr(ohlcv, 'values') else ohlcv["volume"]

    # Align indices
    n = len(probs)
    closes_aligned = closes[-n:]
    highs_aligned = highs[-n:]
    lows_aligned = lows[-n:]
    volumes_aligned = volumes[-n:]
    y_vals = y_clean.values if hasattr(y_clean, 'values') else y_clean

    adv = float(np.mean(volumes_aligned[volumes_aligned > 0])) if np.any(volumes_aligned > 0) else 50_000.0
    vol_daily = float(np.std(np.diff(np.log(closes_aligned + 1e-9)))) * np.sqrt(24)

    for i, (prob, actual) in enumerate(zip(probs, y_vals)):
        price = float(closes_aligned[i])
        bar_high = float(highs_aligned[i])
        bar_low = float(lows_aligned[i])
        bar_vol = float(volumes_aligned[i])

        # Exit existing position first
        if position != 0:
            side = "SELL" if position == 1 else "BUY"
            fill = fill_sim.simulate_fill(
                signal_price=price, side=side, quantity=1.0,
                bar_high=bar_high, bar_low=bar_low, bar_volume=bar_vol,
                adv=adv, volatility_daily=vol_daily,
            )
            pnl = (fill.fill_price - entry_price) * position
            equity += pnl
            peak_equity = max(peak_equity, equity)
            dd = (peak_equity - equity) / peak_equity
            max_dd = max(max_dd, dd)
            trades.append({
                "bar": i, "side": "exit", "entry": entry_price,
                "exit": fill.fill_price, "pnl": pnl,
                "slippage_bps": fill.slippage_bps, "equity": equity,
            })
            position = 0

        # Enter new position
        if prob >= threshold_long:
            side = "BUY"
            new_pos = 1
        elif prob <= threshold_short:
            side = "SELL"
            new_pos = -1
        else:
            continue  # abstain

        fill = fill_sim.simulate_fill(
            signal_price=price, side=side, quantity=1.0,
            bar_high=bar_high, bar_low=bar_low, bar_volume=bar_vol,
            adv=adv, volatility_daily=vol_daily,
        )
        position = new_pos
        entry_price = fill.fill_price

    # Compute metrics
    if not trades:
        logger.warning("No trades generated — check signal thresholds")
        return {"trades": 0, "accuracy": 0.0, "sharpe": 0.0, "max_dd": 0.0}

    exit_trades = [t for t in trades if t["side"] == "exit"]
    pnls = [t["pnl"] for t in exit_trades]
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / len(pnls) if pnls else 0.0

    # Accuracy: did signal direction match actual next-bar direction?
    correct = int(np.sum(
        ((probs >= threshold_long) & (y_vals == 1)) |
        ((probs <= threshold_short) & (y_vals == 0))
    ))
    signals = int(np.sum((probs >= threshold_long) | (probs <= threshold_short)))
    accuracy = correct / signals if signals > 0 else 0.0

    # Sharpe (annualised from H1 bars)
    if len(pnls) > 1:
        pnl_arr = np.array(pnls)
        sharpe = float(np.mean(pnl_arr) / (np.std(pnl_arr) + 1e-9) * np.sqrt(24 * 252))
    else:
        sharpe = 0.0

    total_pnl = sum(pnls)
    avg_slippage = float(np.mean([t["slippage_bps"] for t in exit_trades]))

    return {
        "trades": len(exit_trades),
        "signals": signals,
        "accuracy": accuracy,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "final_equity": equity,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "avg_slippage_bps": avg_slippage,
        "trade_log": trades,
    }


def save_results(results: dict, output_path: str) -> None:
    import csv
    trades = results.get("trade_log", [])
    if not trades:
        return
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["bar", "side", "entry", "exit", "pnl", "slippage_bps", "equity"])
        writer.writeheader()
        for t in trades:
            writer.writerow(t)
    logger.info("Trade log saved → %s", output_path)


async def main() -> None:
    args = parse_args()

    now = datetime.now(UTC)
    if args.smoke:
        start = now - timedelta(days=3)
        end = now - timedelta(hours=1)
    else:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC) if args.start else now - timedelta(days=30)
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC) if args.end else now - timedelta(hours=1)

    logger.info("Tick backtest: %s  %s → %s", args.symbol, start.date(), end.date())

    ohlcv = await download_and_aggregate(args.symbol, start, end)
    results = run_backtest(ohlcv, capital=args.capital)

    print("\n" + "=" * 60)
    print(f"TICK BACKTEST RESULTS — {args.symbol}  {start.date()} → {end.date()}")
    print("=" * 60)
    print(f"  Bars analysed  : {len(ohlcv)}")
    print(f"  Signals fired  : {results.get('signals', 0)}")
    print(f"  Trades         : {results['trades']}")
    print(f"  Accuracy       : {results['accuracy']:.1%}")
    print(f"  Win rate       : {results['win_rate']:.1%}")
    print(f"  Total P&L      : ${results.get('total_pnl', 0):+,.2f}")
    print(f"  Final equity   : ${results.get('final_equity', args.capital):,.2f}")
    print(f"  Max drawdown   : {results['max_drawdown']:.1%}")
    print(f"  Sharpe (ann.)  : {results['sharpe']:.3f}")
    print(f"  Avg slippage   : {results.get('avg_slippage_bps', 0):.2f} bps")
    print("=" * 60)

    if args.output:
        save_results(results, args.output)

    # Save summary to data/
    import json
    summary_path = ROOT / "data" / "tick_backtest_results.json"
    summary = {k: v for k, v in results.items() if k != "trade_log"}
    summary["symbol"] = args.symbol
    summary["start"] = start.isoformat()
    summary["end"] = end.isoformat()
    summary["bars"] = len(ohlcv)
    summary_path.write_text(json.dumps(summary, indent=2))
    logger.info("Summary saved → %s", summary_path)


if __name__ == "__main__":
    asyncio.run(main())
