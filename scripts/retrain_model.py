#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/retrain_model.py
========================
Standalone ML retraining script.

Loads H1 OHLCV data, trains Random Forest + XGBoost (+ LSTM if TensorFlow
is available), saves weights to ml/saved_models/<SYMBOL>/, and writes a
manifest.json with accuracy metrics.

Usage
-----
    python scripts/retrain_model.py
    python scripts/retrain_model.py --symbol XAU_USD --timeframe H1 --years 8
    python scripts/retrain_model.py --symbol XAU_USD --model all
    python scripts/retrain_model.py --symbol XAU_USD --model rf,xgb
    python scripts/retrain_model.py --csv data/XAU_USD_H1.csv --symbol XAU_USD

Environment variables
---------------------
    ML_MODEL_DIR   — output directory (default: ml/saved_models)
    ML_SYMBOLS     — comma-separated symbols (default: XAU_USD)
    MLFLOW_TRACKING_URI — optional MLflow server for experiment tracking
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is on the path regardless of where the script is called from
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_DEFAULT_MODEL_DIR = os.getenv("ML_MODEL_DIR", "ml/saved_models")
_DEFAULT_SYMBOLS = os.getenv("ML_SYMBOLS", "XAU_USD").split(",")
_H1_CSV_DIR = os.getenv("ML_H1_CSV_DIR", "data")


# ── Data loading ──────────────────────────────────────────────────────────────


def _load_csv(symbol: str, csv_path: str | None, years: int) -> pd.DataFrame:
    """Load OHLCV data: explicit CSV > H1 CSV > yfinance fallback."""
    if csv_path:
        logger.info("Loading explicit CSV: %s", csv_path)
        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        for ts_col in ("timestamp", "datetime", "date", "time"):
            if ts_col in df.columns:
                df = df.rename(columns={ts_col: "datetime"})
                break
        if "volume" not in df.columns:
            df["volume"] = 0
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        logger.info("  %d bars loaded from %s", len(df), csv_path)
        return df

    # Try H1 CSV
    h1_path = Path(_H1_CSV_DIR) / f"{symbol}_H1.csv"
    if h1_path.exists():
        logger.info("Loading H1 CSV: %s", h1_path)
        df = pd.read_csv(h1_path)
        df.columns = [c.lower() for c in df.columns]
        if "volume" not in df.columns:
            df["volume"] = 0
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        # Trim to requested years
        if years and len(df) > years * 365 * 24:
            df = df.iloc[-(years * 365 * 24) :]
        logger.info("  %d H1 bars loaded for %s", len(df), symbol)
        return df

    # yfinance fallback
    logger.warning(
        "No H1 CSV found for %s — falling back to yfinance daily data. "
        "For better accuracy run the backfill first:\n"
        "  python -m data.scheduler --backfill --symbol %s --from %d-01-01",
        symbol,
        symbol,
        datetime.now().year - years,
    )
    try:
        import yfinance as yf

        _yf_map = {"XAU_USD": "GC=F", "XAUUSD": "GC=F", "EUR_USD": "EURUSD=X"}
        yf_sym = _yf_map.get(symbol, symbol)
        period = f"{min(years, 10)}y"
        df = yf.Ticker(yf_sym).history(period=period, interval="1d")
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        logger.info("  %d daily bars fetched from yfinance for %s", len(df), yf_sym)
        return df
    except Exception as exc:
        raise RuntimeError(
            f"Could not load data for {symbol}: {exc}\n"
            "Run the backfill first: python -m data.scheduler --backfill --symbol XAU_USD"
        ) from exc


# ── MLflow logging (optional) ─────────────────────────────────────────────────


def _log_to_mlflow(symbol: str, model_name: str, metrics: dict, params: dict) -> None:
    """Log metrics to MLflow if MLFLOW_TRACKING_URI is set."""
    uri = os.getenv("MLFLOW_TRACKING_URI", "")
    if not uri:
        return
    try:
        import mlflow

        mlflow.set_tracking_uri(uri)
        with mlflow.start_run(run_name=f"{symbol}_{model_name}_{datetime.now().strftime('%Y%m%d_%H%M')}"):
            mlflow.log_params(params)
            for k, v in metrics.items():
                if isinstance(v, int | float):
                    mlflow.log_metric(k, v)
        logger.info("MLflow: logged %s/%s to %s", symbol, model_name, uri)
    except Exception as exc:
        logger.warning("MLflow logging failed: %s", exc)


# ── Main pipeline ─────────────────────────────────────────────────────────────


def retrain(
    symbol: str,
    model_types: list[str],
    model_dir: str,
    csv_path: str | None,
    years: int,
) -> dict:
    """Load data, train models, save weights, return results dict."""
    df = _load_csv(symbol, csv_path, years)

    if len(df) < 100:
        raise ValueError(f"Only {len(df)} bars available for {symbol} — need at least 100. Run the backfill first.")

    # Resolve ml/training.py directly (avoids ml/training/ package shadowing)
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location(
        "ml_training_module",
        str(_ROOT / "ml" / "training.py"),
    )
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    train_ml_pipeline = _mod.train_ml_pipeline

    safe_sym = symbol.replace("=", "").replace("/", "")
    out_dir = Path(model_dir) / safe_sym
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Training %s for %s (%d bars) → %s", model_types, symbol, len(df), out_dir)
    logger.info("=" * 60)

    results = train_ml_pipeline(
        df=df,
        model_types=model_types,
        prediction_horizon=1,
        test_size=0.2,
        model_dir=str(out_dir),
    )

    # Write manifest
    manifest = {
        "symbol": symbol,
        "trained_at": datetime.now(UTC).isoformat(),
        "data_rows": len(df),
        "years_requested": years,
        "models": {},
    }
    for name, info in results.items():
        m = info.get("metrics") or {}
        manifest["models"][name] = {
            "path": info.get("model_path", ""),
            "accuracy": m.get("accuracy"),
            "f1": m.get("f1"),
            "rmse": m.get("rmse"),
        }
        _log_to_mlflow(
            symbol,
            name,
            {k: v for k, v in m.items() if isinstance(v, int | float)},
            {"symbol": symbol, "model": name, "bars": len(df), "years": years},
        )

    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Manifest written: %s", manifest_path)

    # Also update the regime router manifest with new accuracy data
    try:
        from strategies.regime_router import detect_regime, update_regime_performance

        regime, _ = detect_regime(df)
        for name, info in results.items():
            m = info.get("metrics") or {}
            acc = m.get("accuracy", 0.0)
            f1 = m.get("f1", 0.0)
            update_regime_performance(
                strategy_name=name,
                regime=regime,
                sharpe=acc * 2 - 1,  # rough proxy until real backtest
                win_rate=acc,
                total_trades=int(len(df) * 0.2),
                avg_return_pct=f1,
            )
        logger.info("Regime manifest updated for regime=%s", regime)
    except Exception as exc:
        logger.debug("Regime manifest update skipped: %s", exc)

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HOPEFX ML retraining script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/retrain_model.py
  python scripts/retrain_model.py --symbol XAU_USD --timeframe H1 --years 8 --model all
  python scripts/retrain_model.py --symbol XAU_USD --model rf,xgb
  python scripts/retrain_model.py --csv data/XAU_USD_H1.csv --symbol XAU_USD
        """,
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Symbol to train (default: ML_SYMBOLS env or XAU_USD)",
    )
    parser.add_argument(
        "--timeframe",
        default="H1",
        help="Timeframe hint for logging (default: H1)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=8,
        help="Years of history to use (default: 8)",
    )
    parser.add_argument(
        "--model",
        default="rf,xgb",
        help=("Comma-separated model types or 'all'. Options: rf, xgb, lstm, random_forest, xgboost (default: rf,xgb)"),
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Explicit path to OHLCV CSV file (overrides auto-discovery)",
    )
    parser.add_argument(
        "--model-dir",
        default=_DEFAULT_MODEL_DIR,
        help=f"Output directory for saved weights (default: {_DEFAULT_MODEL_DIR})",
    )
    parser.add_argument(
        "--advanced",
        action="store_true",
        help=(
            "Run the advanced 122-feature stacking ensemble (ml/train_advanced.py). "
            "Equivalent to: python ml/train_advanced.py --years <years> --oos-years 8 "
            "--use-cached. Produces advanced_oos.pkl for live inference."
        ),
    )
    parser.add_argument(
        "--oos-years",
        type=float,
        default=8.0,
        help="OOS years for --advanced mode (default: 8.0)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke-test mode for --advanced: 2 years, no OOS, no macro, 2 splits (~30 s)",
    )
    args = parser.parse_args()

    # ── Advanced mode: delegate to train_advanced.py ──────────────────────────
    if args.advanced or args.smoke:
        import subprocess  # nosec B404 - list-form call with sys.executable; no shell=True, no user input

        cmd = [
            sys.executable,
            str(_ROOT / "ml" / "train_advanced.py"),
            "--years",
            str(args.years),
            "--oos-years",
            str(args.oos_years),
            "--use-cached",
        ]
        if args.smoke:
            cmd.append("--smoke")
        if args.symbol and args.symbol not in ("XAU_USD", "XAUUSD"):
            # Map OANDA symbol to yfinance ticker
            _yf_map = {"XAU_USD": "GC=F", "XAUUSD": "GC=F", "EUR_USD": "EURUSD=X"}
            yf_sym = _yf_map.get(args.symbol, args.symbol)
            cmd += ["--symbol", yf_sym]
        logger.info("Running advanced training: %s", " ".join(cmd))
        result = subprocess.run(  # nosec B603 B607 - list-form call with sys.executable; no shell=True, no user input
            cmd, check=False
        )
        sys.exit(result.returncode)

    symbols = [args.symbol] if args.symbol else _DEFAULT_SYMBOLS
    symbols = [s.strip() for s in symbols]

    # Normalise model type aliases
    _ALIASES = {"rf": "random_forest", "xgb": "xgboost"}
    if args.model.lower() == "all":
        model_types = ["random_forest", "xgboost", "lstm"]
    else:
        model_types = [_ALIASES.get(m.strip().lower(), m.strip().lower()) for m in args.model.split(",")]

    logger.info("Symbols:   %s", symbols)
    logger.info("Models:    %s", model_types)
    logger.info("Years:     %d", args.years)
    logger.info("Model dir: %s", args.model_dir)

    all_ok = True
    for sym in symbols:
        try:
            results = retrain(
                symbol=sym,
                model_types=model_types,
                model_dir=args.model_dir,
                csv_path=args.csv,
                years=args.years,
            )
            print(f"\n{'=' * 50}")
            print(f"Results for {sym}:")
            for name, info in results.items():
                m = info.get("metrics") or {}
                acc = m.get("accuracy", m.get("rmse", "n/a"))
                f1 = m.get("f1", "n/a")
                path = info.get("model_path", "")
                print(f"  {name:<20} accuracy={acc}  f1={f1}")
                print(f"  {'':20} saved → {path}")
        except Exception as exc:
            logger.exception("Failed for %s: %s", sym)
            all_ok = False

    if not all_ok:
        sys.exit(1)

    print(f"\nAll models saved to {args.model_dir}/")
    print("Next steps:")
    print("  1. Review manifest.json in each symbol directory")
    print("  2. Restart the app to load new weights")
    print("  3. Check /api/trading/regime for updated regime performance")


if __name__ == "__main__":
    main()
