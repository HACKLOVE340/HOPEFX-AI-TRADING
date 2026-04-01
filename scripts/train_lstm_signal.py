#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/train_lstm_signal.py
==============================
Train the LSTM signal layer on existing XAUUSD OHLCV data.

Prerequisites
-------------
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    # or for GPU:
    pip install torch --index-url https://download.pytorch.org/whl/cu121

Usage
-----
    # Quick smoke test (~2 min, CPU)
    python scripts/train_lstm_signal.py --smoke

    # Full training on all available OHLCV data (~10-30 min, CPU)
    python scripts/train_lstm_signal.py

    # Custom output path
    python scripts/train_lstm_signal.py --output ml/saved_models/lstm_signal.pt

What it does
------------
1. Loads XAUUSD OHLCV from data/XAU_USD_H1.csv (hourly bars)
2. Builds 176-feature matrix using ml/advanced_features.py
3. Creates sequences of length SEQ_LEN (default 60 bars)
4. Trains DeepPredictor(architecture='lstm') with early stopping
5. Saves model to LSTM_MODEL_PATH (default: ml/saved_models/lstm_signal.pt)
6. Prints OOS accuracy and val loss

After training
--------------
Set in .env:
    LSTM_SIGNAL_WEIGHT=0.2
    LSTM_MODEL_PATH=ml/saved_models/lstm_signal.pt

The signal engine will blend: final_prob = 0.8 * xgb_prob + 0.2 * lstm_prob
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
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
logger = logging.getLogger("train_lstm")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train LSTM signal layer")
    p.add_argument("--smoke", action="store_true", help="Quick smoke test (50 bars, 3 epochs)")
    p.add_argument("--seq-len", type=int, default=60, help="Sequence length (default: 60)")
    p.add_argument("--epochs", type=int, default=50, help="Max epochs (default: 50)")
    p.add_argument("--batch-size", type=int, default=64, help="Batch size (default: 64)")
    p.add_argument("--val-frac", type=float, default=0.2, help="Validation fraction (default: 0.2)")
    p.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "ml" / "saved_models" / "lstm_signal.pt"),
        help="Output model path",
    )
    p.add_argument(
        "--data",
        type=str,
        default=str(ROOT / "data" / "XAU_USD_H1.csv"),
        help="OHLCV CSV path (default: data/XAU_USD_H1.csv)",
    )
    return p.parse_args()


def load_ohlcv(path: str) -> "pd.DataFrame":
    import pandas as pd
    df = pd.read_csv(path)
    # Normalise column names
    df.columns = [c.lower() for c in df.columns]
    ts_col = next((c for c in df.columns if "time" in c or "date" in c), None)
    if ts_col:
        df = df.rename(columns={ts_col: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.set_index("timestamp").sort_index()
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in {path}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    logger.info("Loaded %d H1 bars from %s", len(df), path)
    return df


def build_features(ohlcv: "pd.DataFrame", smoke: bool) -> "tuple[np.ndarray, np.ndarray]":
    import numpy as np
    from ml.advanced_features import build_advanced_features

    if smoke:
        ohlcv = ohlcv.tail(500)

    logger.info("Building features for %d bars...", len(ohlcv))
    X, y = build_advanced_features(ohlcv, horizon=1)

    # Drop rows with NaN (feature warm-up period)
    mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
    X, y = X[mask], y[mask]
    logger.info("Feature matrix: %d rows × %d features", X.shape[0], X.shape[1])
    return X.values if hasattr(X, "values") else X, y.values if hasattr(y, "values") else y


def train(args: argparse.Namespace) -> None:
    import numpy as np

    # ── Check PyTorch ─────────────────────────────────────────────────────────
    try:
        import torch
        logger.info("PyTorch %s available (device: %s)",
                    torch.__version__,
                    "cuda" if torch.cuda.is_available() else "cpu")
    except ImportError:
        logger.error(
            "PyTorch not installed.\n"
            "Install with:\n"
            "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            "Then re-run this script."
        )
        sys.exit(1)

    # ── Load data ─────────────────────────────────────────────────────────────
    data_path = args.data
    if not Path(data_path).exists():
        # Fallback to daily data
        daily = ROOT / "data" / "XAUUSD_40Y.csv"
        if daily.exists():
            logger.warning("%s not found — falling back to %s", data_path, daily)
            data_path = str(daily)
        else:
            logger.error("No OHLCV data found at %s", data_path)
            sys.exit(1)

    ohlcv = load_ohlcv(data_path)

    # ── Build features ────────────────────────────────────────────────────────
    X, y = build_features(ohlcv, smoke=args.smoke)

    if len(X) < args.seq_len + 50:
        logger.error("Not enough data (%d rows) for seq_len=%d", len(X), args.seq_len)
        sys.exit(1)

    # ── Make sequences ────────────────────────────────────────────────────────
    from research.pipeline.models_deep import make_sequences, DeepPredictor

    X_seq, y_seq = make_sequences(X, y, seq_len=args.seq_len)
    logger.info("Sequences: %d × %d × %d", *X_seq.shape)

    # Train/val split (time-ordered — no shuffle)
    split = int(len(X_seq) * (1 - args.val_frac))
    X_train, X_val = X_seq[:split], X_seq[split:]
    y_train, y_val = y_seq[:split], y_seq[split:]
    logger.info("Train: %d  Val: %d", len(X_train), len(X_val))

    # ── Train ─────────────────────────────────────────────────────────────────
    n_features = X_seq.shape[2]
    epochs = 3 if args.smoke else args.epochs

    predictor = DeepPredictor(
        architecture="lstm",
        n_features=n_features,
        seq_len=args.seq_len,
        task="binary",
        device="auto",
        lr=1e-3,
        batch_size=args.batch_size,
        max_epochs=epochs,
        patience=7,
        label_smoothing=0.05,
    )

    logger.info("Training LSTM (epochs=%d, features=%d, seq_len=%d)...",
                epochs, n_features, args.seq_len)
    t0 = time.time()
    history = predictor.fit(X_train, y_train, X_val, y_val)
    elapsed = time.time() - t0

    # ── Evaluate ──────────────────────────────────────────────────────────────
    val_preds = predictor.predict_proba(X_val)
    val_binary = (val_preds >= 0.5).astype(int)
    accuracy = float(np.mean(val_binary == y_val))
    logger.info("Val accuracy: %.4f  (%.1f s training)", accuracy, elapsed)

    if accuracy < 0.50 and not args.smoke:
        logger.warning(
            "Val accuracy %.4f < 0.50 — model may not be adding signal. "
            "Consider more data or tuning hyperparameters before enabling.",
            accuracy,
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    predictor.save(str(out_path))
    logger.info("Model saved → %s", out_path)

    print("\n" + "=" * 60)
    print("LSTM training complete")
    print(f"  Val accuracy : {accuracy:.4f}")
    print(f"  Features     : {n_features}")
    print(f"  Seq len      : {args.seq_len}")
    print(f"  Saved to     : {out_path}")
    print("\nNext steps:")
    print("  1. Add to .env:")
    print(f"       LSTM_MODEL_PATH={out_path}")
    print("       LSTM_SIGNAL_WEIGHT=0.2")
    print("  2. Restart the app — LSTM will blend at 20% weight")
    print("=" * 60)


if __name__ == "__main__":
    args = parse_args()
    train(args)
