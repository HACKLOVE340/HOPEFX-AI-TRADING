#!/usr/bin/env python3
"""
ML training pipeline runner.

Fetches OHLCV data via yfinance, trains Random Forest + XGBoost (+ LSTM if
TensorFlow is available), and saves model weights to ml/saved_models/.

Usage:
    python3 ml/run_training.py [--symbol XAUUSD=X] [--period 2y] [--models rf,xgb,lstm]

Environment:
    ML_MODEL_DIR   — output directory (default: ml/saved_models)
    ML_SYMBOLS     — comma-separated symbols (default: XAUUSD=X,EURUSD=X)
    ML_PERIOD      — yfinance period string (default: 2y)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = os.getenv("ML_MODEL_DIR", "ml/saved_models")
DEFAULT_SYMBOLS = os.getenv("ML_SYMBOLS", "GC=F,EURUSD=X").split(",")  # GC=F = Gold futures
DEFAULT_PERIOD = os.getenv("ML_PERIOD", "2y")


def fetch_ohlcv(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Download OHLCV data from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed — run: pip install yfinance")

    logger.info("Fetching %s (%s, %s)...", symbol, period, interval)
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    logger.info("  %d rows fetched for %s", len(df), symbol)
    return df


def run_pipeline(symbol: str, period: str, model_types: list[str], model_dir: str) -> dict:
    """Fetch data and run the full training pipeline for one symbol."""
    # ml/training.py is shadowed by ml/training/ package — load directly
    import importlib.util, os as _os
    _spec = importlib.util.spec_from_file_location(
        "ml_training_module",
        _os.path.join(_os.path.dirname(__file__), "training.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    train_ml_pipeline = _mod.train_ml_pipeline

    df = fetch_ohlcv(symbol, period=period)

    # Sanitise symbol for directory name (e.g. XAUUSD=X → XAUUSD)
    safe_sym = symbol.replace("=", "").replace("/", "").replace("\\", "")
    out_dir = os.path.join(model_dir, safe_sym)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Training models for %s → %s", symbol, out_dir)
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
        "trained_at": datetime.utcnow().isoformat(),
        "period": period,
        "rows": len(df),
        "models": {},
    }
    for name, info in results.items():
        manifest["models"][name] = {
            "path": info.get("model_path", ""),
            "metrics": {k: v for k, v in (info.get("metrics") or {}).items()
                        if isinstance(v, (int, float))},
        }

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Manifest written: %s", manifest_path)

    return results


def main():
    parser = argparse.ArgumentParser(description="HOPEFX ML training pipeline")
    parser.add_argument("--symbol", default=None, help="Single symbol to train (overrides ML_SYMBOLS)")
    parser.add_argument("--period", default=DEFAULT_PERIOD, help="yfinance period (default: 2y)")
    parser.add_argument(
        "--models",
        default="random_forest,xgboost",
        help="Comma-separated model types: random_forest,xgboost,lstm",
    )
    parser.add_argument("--model-dir", default=MODEL_DIR, help="Output directory for saved weights")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else DEFAULT_SYMBOLS
    model_types = [m.strip() for m in args.models.split(",")]

    logger.info("=" * 60)
    logger.info("HOPEFX ML Training Pipeline")
    logger.info("Symbols: %s", symbols)
    logger.info("Models:  %s", model_types)
    logger.info("Period:  %s", args.period)
    logger.info("Output:  %s", args.model_dir)
    logger.info("=" * 60)

    all_ok = True
    for sym in symbols:
        try:
            results = run_pipeline(sym, args.period, model_types, args.model_dir)
            for name, info in results.items():
                m = info.get("metrics") or {}
                acc = m.get("accuracy", m.get("rmse", "n/a"))
                logger.info("  %-20s %-15s metric=%s", sym, name, acc)
        except Exception as exc:
            logger.error("Failed for %s: %s", sym, exc)
            all_ok = False

    if not all_ok:
        sys.exit(1)
    logger.info("Training complete. Weights saved to %s", args.model_dir)


if __name__ == "__main__":
    main()
