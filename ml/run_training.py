#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ML training pipeline runner.

Loads H1 OHLCV data from local CSV files (preferred) or falls back to
yfinance daily data. Trains Random Forest + XGBoost (+ LSTM if TensorFlow
is available) with class-balanced settings and saves weights to
ml/saved_models/.

Usage:
    python3 ml/run_training.py [--symbol XAU_USD] [--models rf,xgb,lstm]
    python3 ml/run_training.py --csv data/XAU_USD_H1.csv --symbol XAU_USD

Environment:
    ML_MODEL_DIR   — output directory (default: ml/saved_models)
    ML_SYMBOLS     — comma-separated symbols (default: XAU_USD)
    ML_H1_CSV_DIR  — directory containing <SYMBOL>_H1.csv files (default: data)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = os.getenv("ML_MODEL_DIR", "ml/saved_models")
DEFAULT_SYMBOLS = os.getenv("ML_SYMBOLS", "XAU_USD").split(",")
H1_CSV_DIR = os.getenv("ML_H1_CSV_DIR", "data")


def load_h1_csv(symbol: str, csv_dir: str = H1_CSV_DIR) -> pd.DataFrame | None:
    """Load H1 OHLCV data from a local CSV file.

    Looks for <csv_dir>/<SYMBOL>_H1.csv (e.g. data/XAU_USD_H1.csv).
    Returns None if the file does not exist.
    """
    path = Path(csv_dir) / f"{symbol}_H1.csv"
    if not path.exists():
        return None

    logger.info("Loading H1 data from %s ...", path)
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.rename(columns={"timestamp": "datetime"})
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        logger.warning(
            "CSV missing required columns %s — skipping",
            required - set(df.columns),
        )
        return None
    if "volume" not in df.columns:
        df["volume"] = 0
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    logger.info("  %d H1 bars loaded for %s", len(df), symbol)
    return df


def fetch_ohlcv_yfinance(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fallback: download OHLCV data from Yahoo Finance (daily bars)."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed — run: pip install yfinance") from None

    logger.info("Fetching %s from yfinance (%s, %s)...", symbol, period, interval)
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    logger.info("  %d daily bars fetched for %s", len(df), symbol)
    return df


def load_data(symbol: str, csv_path: str | None, period: str) -> pd.DataFrame:
    """Load training data: explicit CSV > H1 CSV > yfinance fallback."""
    if csv_path:
        logger.info("Loading explicit CSV: %s", csv_path)
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df.columns = [c.lower() for c in df.columns]
        if "timestamp" in df.columns:
            df = df.rename(columns={"timestamp": "datetime"})
        if "volume" not in df.columns:
            df["volume"] = 0
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        logger.info("  %d bars loaded from %s", len(df), csv_path)
        return df

    h1 = load_h1_csv(symbol)
    if h1 is not None:
        return h1

    # Last resort: yfinance (daily bars, less data)
    logger.warning(
        "No H1 CSV found for %s — falling back to yfinance daily data. "
        "For better accuracy place data/%s_H1.csv in the data/ directory.",
        symbol,
        symbol,
    )
    return fetch_ohlcv_yfinance(symbol, period=period)


def run_pipeline(
    symbol: str,
    model_types: list[str],
    model_dir: str,
    csv_path: str | None = None,
    period: str = "2y",
) -> dict:
    """Load data and run the full training pipeline for one symbol."""
    # ml/training.py is shadowed by ml/training/ package — load directly
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location(
        "ml_training_module",
        os.path.join(Path(__file__).parent, "training.py"),
    )
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    train_ml_pipeline = _mod.train_ml_pipeline

    df = load_data(symbol, csv_path, period)

    # Sanitise symbol for directory name (e.g. XAU_USD → XAU_USD)
    safe_sym = symbol.replace("=", "").replace("/", "").replace("\\", "")
    out_dir = Path(model_dir) / safe_sym
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Training models for %s → %s (%d bars)", symbol, out_dir, len(df))
    results = train_ml_pipeline(
        df=df,
        model_types=model_types,
        prediction_horizon=1,
        test_size=0.2,
        model_dir=out_dir,
    )

    # Write a manifest so the app knows which weights are available
    manifest = {
        "symbol": symbol,
        "trained_at": datetime.now(UTC).isoformat(),
        "data_source": csv_path or f"data/{symbol}_H1.csv",
        "rows": len(df),
        "models": {},
    }
    for name, info in results.items():
        manifest["models"][name] = {
            "path": info.get("model_path", ""),
            "metrics": {k: v for k, v in (info.get("metrics") or {}).items() if isinstance(v, int | float)},
        }

    manifest_path = Path(out_dir) / "manifest.json"
    with Path(manifest_path).open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Manifest written: %s", manifest_path)

    return results


def main():
    parser = argparse.ArgumentParser(description="HOPEFX ML training pipeline")
    parser.add_argument(
        "--symbol",
        default=None,
        help="Single symbol to train (overrides ML_SYMBOLS)",
    )
    parser.add_argument("--csv", default=None, help="Explicit path to OHLCV CSV file")
    parser.add_argument(
        "--period",
        default="2y",
        help="yfinance fallback period (default: 2y)",
    )
    parser.add_argument(
        "--models",
        default="random_forest,xgboost",
        help="Comma-separated model types: random_forest,xgboost,lstm",
    )
    parser.add_argument(
        "--model-dir",
        default=MODEL_DIR,
        help="Output directory for saved weights",
    )
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else DEFAULT_SYMBOLS
    model_types = [m.strip() for m in args.models.split(",")]

    logger.info("=" * 60)
    logger.info("HOPEFX ML Training Pipeline")
    logger.info("Symbols: %s", symbols)
    logger.info("Models:  %s", model_types)
    logger.info("Data:    H1 CSV (data/<SYMBOL>_H1.csv) or yfinance fallback")
    logger.info("Output:  %s", args.model_dir)
    logger.info("=" * 60)

    all_ok = True
    for sym in symbols:
        try:
            results = run_pipeline(
                sym,
                model_types,
                args.model_dir,
                csv_path=args.csv,
                period=args.period,
            )
            for name, info in results.items():
                m = info.get("metrics") or {}
                acc = m.get("accuracy", m.get("rmse", "n/a"))
                logger.info("  %-20s %-15s metric=%s", sym, name, acc)
        except Exception:
            logger.exception("Failed for %s: %s", sym)
            all_ok = False

    if not all_ok:
        sys.exit(1)
    logger.info("Training complete. Weights saved to %s", args.model_dir)


if __name__ == "__main__":
    main()
