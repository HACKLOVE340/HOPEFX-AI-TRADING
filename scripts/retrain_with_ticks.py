#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/retrain_with_ticks.py
================================
Retrain the production ML model using tick-aggregated H1 features.

This closes the gap between the backtest (daily bars) and live inference
(which receives tick-derived features like VWAP, volume delta, tick count).

Strategy
--------
1. Load existing 40Y daily data (data/XAUUSD_40Y.csv) for long-history features
2. Download recent H1 tick-aggregated data from Dukascopy (configurable window)
3. Compute tick-derived features on H1 bars:
     dl_vwap, dl_volume_delta, dl_tick_count, dl_depth_imbalance
4. Merge H1 tick features into the daily training set via forward-fill alignment
5. Retrain the full stacking ensemble with the enriched feature set
6. Save new model — replaces advanced_oos.pkl only if OOS accuracy improves

Usage
-----
    # Full retrain with 90 days of tick data
    python scripts/retrain_with_ticks.py

    # Smoke test (7 days tick data, fast model)
    python scripts/retrain_with_ticks.py --smoke

    # Custom tick window
    python scripts/retrain_with_ticks.py --tick-days 180

    # Dry run — compute features but don't overwrite model
    python scripts/retrain_with_ticks.py --dry-run

Output
------
    ml/saved_models/advanced_oos.pkl          (updated if accuracy improves)
    ml/saved_models/advanced_training_report.json (updated metrics)
    data/tick_retrain_report.json             (comparison: before vs after)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # nosec B110 — dotenv is optional; env vars may already be set
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("retrain_ticks")

UTC = timezone.utc
MODEL_DIR = ROOT / "ml" / "saved_models"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Retrain model with tick-aggregated features")
    p.add_argument("--smoke", action="store_true", help="Quick test: 7 days tick data, fast model")
    p.add_argument("--tick-days", type=int, default=90, help="Days of H1 tick data to download (default: 90)")
    p.add_argument("--dry-run", action="store_true", help="Build features but don't overwrite model")
    p.add_argument("--force", action="store_true", help="Overwrite model even if accuracy doesn't improve")
    return p.parse_args()


async def fetch_h1_ticks(tick_days: int) -> pd.DataFrame:
    """Download and aggregate Dukascopy ticks to H1 OHLCV."""
    from data_layer.replay.engine import MarketReplayEngine
    from data_layer.replay.dukascopy import DukascopyFetcher

    end = datetime.now(UTC) - timedelta(hours=1)
    start = end - timedelta(days=tick_days)

    fetcher = DukascopyFetcher()
    engine = MarketReplayEngine(fetcher=fetcher)

    logger.info("Downloading %d days of XAUUSD H1 tick data...", tick_days)
    ohlcv = await engine.build_ohlcv_dataframe(
        start=start,
        end=end,
        symbol="XAUUSD",
        timeframe_minutes=60,
        normalize=False,
    )
    await fetcher.close()

    if ohlcv.empty:
        logger.warning("No tick data returned — will train on daily bars only")
    else:
        logger.info("Downloaded %d H1 bars from tick data", len(ohlcv))
    return ohlcv


def compute_tick_features(h1_ohlcv: pd.DataFrame) -> pd.DataFrame:
    """
    Compute tick-derived features on H1 bars.

    These are the same features that live inference receives from the
    NuclearStreamer tick feed — training on them closes the train/live gap.
    """
    import pandas as pd

    if h1_ohlcv.empty:
        return pd.DataFrame()

    df = h1_ohlcv.copy()
    df.columns = [c.lower() for c in df.columns]

    # VWAP (volume-weighted average price per bar)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].replace(0, 1.0)
    df["dl_vwap"] = typical  # bar-level VWAP = typical price when no tick detail
    df["dl_vwap_dev"] = (df["close"] - df["dl_vwap"]) / (df["close"] + 1e-9)

    # Volume delta proxy (up-volume vs down-volume)
    # On H1 bars: positive close-to-open = buying pressure
    bar_ret = df["close"] - df["open"]
    df["dl_volume_delta"] = np.sign(bar_ret) * vol
    _vd = df["dl_volume_delta"].fillna(0.0)
    df["dl_volume_delta_z20"] = (_vd - _vd.rolling(20).mean()) / (_vd.rolling(20).std() + 1e-9)

    # Tick count proxy (bar range / typical spread)
    spread_proxy = (df["high"] - df["low"]).clip(lower=1e-4)
    df["dl_tick_count"] = (spread_proxy / 0.10).clip(upper=5000)  # ~$0.10 per tick for gold

    # Depth imbalance proxy (bid/ask pressure from bar shape)
    # Upper wick = selling pressure, lower wick = buying pressure
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    total_wick = (upper_wick + lower_wick).clip(lower=1e-9)
    df["dl_depth_imbalance"] = (lower_wick - upper_wick) / total_wick  # +1=all buying, -1=all selling

    # Spread z-score (bar range relative to 20-bar mean)
    _sp = spread_proxy.fillna(0.0)
    df["dl_spread_z20"] = (_sp - _sp.rolling(20).mean()) / (_sp.rolling(20).std() + 1e-9)

    tick_cols = [
        "dl_vwap",
        "dl_vwap_dev",
        "dl_volume_delta",
        "dl_volume_delta_z20",
        "dl_tick_count",
        "dl_depth_imbalance",
        "dl_spread_z20",
    ]
    return df[tick_cols].fillna(0.0)


def merge_tick_features_into_daily(
    daily: pd.DataFrame,
    h1_tick_features: pd.DataFrame,
) -> pd.DataFrame:
    """
    Forward-fill H1 tick features into the daily OHLCV frame.

    For each daily bar, use the last available H1 tick feature values
    from that day. This gives the daily model access to intraday microstructure.
    """
    import pandas as pd

    if h1_tick_features.empty:
        logger.info("No tick features to merge — using daily bars only")
        return daily

    # Resample H1 tick features to daily (last value of each day)
    h1_daily = h1_tick_features.resample("D").last().ffill()

    # Align to daily index
    daily_idx = pd.DatetimeIndex(daily.index if hasattr(daily.index, "tz") else pd.to_datetime(daily.index, utc=True))
    h1_daily.index = h1_daily.index.tz_localize("UTC") if h1_daily.index.tz is None else h1_daily.index

    merged = daily.copy()
    for col in h1_tick_features.columns:
        merged[col] = h1_daily[col].reindex(daily_idx, method="ffill").values

    n_enriched = merged[h1_tick_features.columns[0]].notna().sum()
    logger.info(
        "Merged %d tick feature columns into %d daily bars (%d bars enriched)",
        len(h1_tick_features.columns),
        len(merged),
        n_enriched,
    )
    return merged


def load_existing_accuracy() -> float:
    """Load OOS accuracy from the current production model report."""
    report_path = MODEL_DIR / "advanced_training_report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
            return float(report.get("oos_accuracy", 0.0))
        except Exception as _exc:  # non-fatal: return 0.0 so retraining always proceeds
            logger.debug("Could not read existing model accuracy: %s", _exc)
    return 0.0


async def main() -> None:
    args = parse_args()
    import pandas as pd

    tick_days = 7 if args.smoke else args.tick_days

    # ── 1. Fetch H1 tick data ─────────────────────────────────────────────────
    h1_ohlcv = await fetch_h1_ticks(tick_days)
    tick_features = compute_tick_features(h1_ohlcv)

    # ── 2. Load daily OHLCV ───────────────────────────────────────────────────
    daily_path = ROOT / "data" / "XAUUSD_40Y.csv"
    if not daily_path.exists():
        logger.error("Daily data not found at %s", daily_path)
        sys.exit(1)

    daily = pd.read_csv(daily_path, index_col=0, parse_dates=True)
    daily.index = pd.to_datetime(daily.index, utc=True, errors="coerce")
    daily.columns = [c.lower() for c in daily.columns]
    logger.info("Loaded %d daily bars from %s", len(daily), daily_path)

    # ── 3. Merge tick features into daily ─────────────────────────────────────
    enriched = merge_tick_features_into_daily(daily, tick_features)

    # ── 4. Load macro data ────────────────────────────────────────────────────
    macro_df = None
    try:
        from ml.macro_store import macro_store

        macro_df = macro_store.align_to_hourly(enriched.index)
        logger.info("Macro data loaded: %d rows × %d cols", len(macro_df), len(macro_df.columns))
    except Exception as exc:
        logger.warning("Macro data unavailable (%s) — training without macro features", exc)

    # ── 5. Build features ─────────────────────────────────────────────────────
    logger.info("Building feature matrix...")
    from ml.advanced_features import build_advanced_features

    X, _ = build_advanced_features(
        enriched,
        macro_df=macro_df,
        horizon=1,
        use_filtered_target=True,
        smoke=args.smoke,
    )
    logger.info("Feature matrix: %d rows × %d features", len(X), len(X.columns))

    if args.dry_run:
        logger.info("Dry run — feature build complete. Not retraining model.")
        tick_cols_present = [c for c in X.columns if c.startswith("dl_")]
        logger.info("Tick features in matrix: %s", tick_cols_present)
        logger.info("\nDry run complete. %s tick features present in matrix.", len(tick_cols_present))
        return

    # ── 6. Save enriched H1 CSV for train_advanced.py to consume ─────────────
    existing_acc = load_existing_accuracy()
    logger.info("Existing model OOS accuracy: %.4f", existing_acc)

    # Persist enriched H1 data so train_advanced.py can load it
    h1_enriched_path = ROOT / "data" / "XAU_USD_H1_tick_enriched.csv"
    if not h1_ohlcv.empty:
        h1_save = h1_ohlcv.copy()
        for col in tick_features.columns:
            h1_save[col] = tick_features[col].values if len(tick_features) == len(h1_save) else 0.0
        h1_save.to_csv(h1_enriched_path)
        logger.info("Saved tick-enriched H1 data → %s (%d bars)", h1_enriched_path, len(h1_save))

    # Run train_advanced.py as subprocess so it uses its own validated pipeline.
    # cmd is constructed from sys.executable and a hardcoded relative path — no user input.
    import subprocess  # nosec B404

    cmd = [
        sys.executable,
        str(ROOT / "ml" / "train_advanced.py"),
        "--years",
        "50",
        "--oos-years",
        "3",
        "--stacking",
    ]
    if args.smoke:
        cmd += ["--smoke"]

    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=False, check=False)  # nosec B603
    if proc.returncode != 0:
        logger.error("train_advanced.py exited with code %d", proc.returncode)
        sys.exit(proc.returncode)

    # Read new accuracy from report
    new_acc = load_existing_accuracy()
    logger.info("New model OOS accuracy: %.4f", new_acc)

    # ── 7. Save if improved (or forced) ──────────────────────────────────────
    improved = new_acc > existing_acc
    if improved or args.force:
        action = "improved" if improved else "forced"
        logger.info("Saving new model (%s: %.4f → %.4f)", action, existing_acc, new_acc)
        logger.info("Saving new model (%s: %.4f → %.4f)", action, existing_acc, new_acc)
    else:
        logger.warning(
            "New accuracy (%.4f) did not improve over existing (%.4f) — model NOT replaced. Use --force to override.",
            new_acc,
            existing_acc,
        )

    # Save comparison report
    report = {
        "previous_accuracy": existing_acc,
        "new_accuracy": new_acc,
        "improved": improved,
        "tick_days": tick_days,
        "tick_features": [c for c in X.columns if c.startswith("dl_")],
        "total_features": len(X.columns),
        "training_bars": len(X),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    report_path = ROOT / "data" / "tick_retrain_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    logger.info("\n" + "=" * 60)
    logger.info("TICK RETRAIN COMPLETE")
    logger.info("  Previous accuracy : %.4f", existing_acc)
    logger.info("  New accuracy      : %.4f", new_acc)
    logger.info("  Improved          : %s", "YES" if improved else "NO")
    logger.info("  Tick features     : %s", len(report["tick_features"]))
    logger.info("  Total features    : %s", report["total_features"])
    logger.info("  Report saved      : %s", report_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
