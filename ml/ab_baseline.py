# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/ab_baseline.py
=================
A/B measurement: does the ML model actually beat the rule baseline?

The decision engine runs a rule-based signal (Phase 1) and then an ML
"enrichment" (Phase 2). Nobody had measured whether Phase 2 adds anything over
Phase 1 on the SAME out-of-sample bars — so this harness answers exactly that.

It builds the production feature matrix and target, carves a leakage-safe OOS
window (purging the label horizon at the boundary), then on that identical OOS
set computes:

  * baseline  — a transparent EMA20-vs-EMA50 trend rule (the kind of indicator
                Phase 1's StrategyBrain votes on),
  * ml        — a calibrated XGBoost trained on the in-sample window (same
                pipeline as oos_eval_advanced),
  * ml_filter — baseline trades taken only when the ML agrees (ML as a filter).

For each it reports directional accuracy and a trade-level Sharpe on the actual
forward returns, plus the ML "lift" (ml_acc - baseline_acc). The verdict is
printed and written to ml/saved_models/ab_baseline_report.json.

Usage
-----
    python ml/ab_baseline.py --csv data/XAUUSD_clean.csv --horizon 5 --oos-years 3
    python ml/ab_baseline.py --smoke      # synthetic data, ~5s, for CI/tests

This is a *measurement* tool — it never writes or promotes a model.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Allow `python ml/ab_baseline.py` to resolve top-level packages (ml.*), matching
# ml/train_advanced.py's bootstrap.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent / "saved_models"
REPORT_PATH = MODEL_DIR / "ab_baseline_report.json"


# ─────────────────────────────────────────────────────────────────────────────
# Rule baseline — the Phase-1-style signal
# ─────────────────────────────────────────────────────────────────────────────


def rule_baseline_signal(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """EMA(fast) > EMA(slow) → predict up (1), else down (0).

    A deliberately simple, transparent trend rule — representative of the
    technical-indicator consensus the rule engine (StrategyBrain) produces, so
    the comparison isolates the ML's marginal value rather than baseline tuning.
    """
    close = df["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return (ema_fast > ema_slow).astype(int)


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────


def _trade_sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float:
    """Annualised Sharpe of a per-trade return series (0.0 if < 2 or flat)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd < 1e-12:
        return 0.0
    return float(np.mean(r) / sd * np.sqrt(periods_per_year))


def _directional_pnl(pred: np.ndarray, fwd_ret: np.ndarray) -> np.ndarray:
    """Long when pred==1, short when pred==0; PnL = position * forward return."""
    position = np.where(np.asarray(pred) == 1, 1.0, -1.0)
    return position * np.asarray(fwd_ret, dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# A/B run
# ─────────────────────────────────────────────────────────────────────────────


def run_ab(
    df: pd.DataFrame,
    horizon: int = 5,
    oos_years: float = 3.0,
    min_move_atr: float = 0.25,
    n_estimators: int = 300,
) -> dict[str, Any]:
    """Run the baseline-vs-ML A/B on a single OHLCV frame. Returns a report dict."""
    import xgboost as xgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import accuracy_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    from ml.advanced_features import build_advanced_features

    horizon = max(int(horizon), 1)

    # 1. Production feature matrix + target (same builder as training).
    X, y = build_advanced_features(
        df, macro_df=None, horizon=horizon, use_filtered_target=True, min_move_atr=min_move_atr
    )
    if len(X) < 120:
        raise ValueError(f"Too few samples after feature build ({len(X)}); need >= 120.")

    # 2. Forward returns aligned to the feature index (for trade-level PnL).
    close = df["close"].astype(float)
    fwd = (close.shift(-horizon) / close - 1.0)
    fwd = fwd.reindex(X.index)

    # 3. Leakage-safe OOS split: carve the tail, then purge `horizon` boundary
    #    bars whose labels reach into the OOS window.
    oos_n = int(round(oos_years * 252))
    oos_n = min(oos_n, int(len(X) * 0.40))
    if oos_n < 60:
        oos_n = max(int(len(X) * 0.25), 30)
    X_cv, y_cv = X.iloc[:-oos_n], y.iloc[:-oos_n]
    X_oos, y_oos = X.iloc[-oos_n:], y.iloc[-oos_n:]
    if len(X_cv) > horizon:
        X_cv, y_cv = X_cv.iloc[:-horizon], y_cv.iloc[:-horizon]
    fwd_oos = fwd.reindex(X_oos.index).to_numpy()
    y_oos_arr = y_oos.to_numpy()

    if len(np.unique(y_cv)) < 2:
        raise ValueError("Training window has a single class — cannot fit ML.")

    # 4. ML predictions on OOS (same calibrated-XGB pipeline as oos_eval_advanced).
    base = xgb.XGBClassifier(
        n_estimators=n_estimators, max_depth=5, learning_rate=0.05,
        subsample=0.75, colsample_bytree=0.75, min_child_weight=3,
        eval_metric="logloss", random_state=42, n_jobs=1,
    )
    model = Pipeline([("scaler", StandardScaler()),
                      ("model", CalibratedClassifierCV(base, method="isotonic", cv=3))])
    model.fit(X_cv, y_cv)
    ml_pred = model.predict(X_oos)
    ml_proba = model.predict_proba(X_oos)[:, 1]

    # 5. Baseline predictions on the same OOS bars.
    base_pred = rule_baseline_signal(df).reindex(X_oos.index).fillna(0).astype(int).to_numpy()

    # 6. Metrics.
    base_acc = float(accuracy_score(y_oos_arr, base_pred))
    ml_acc = float(accuracy_score(y_oos_arr, ml_pred))

    base_pnl = _directional_pnl(base_pred, fwd_oos)
    ml_pnl = _directional_pnl(ml_pred, fwd_oos)

    # ML-as-filter: only take the baseline trade when ML agrees with it.
    agree = ml_pred == base_pred
    n_agree = int(agree.sum())
    filt_pnl = base_pnl[agree]
    filt_acc = (
        float(accuracy_score(y_oos_arr[agree], base_pred[agree])) if n_agree > 0 else 0.0
    )

    lift = ml_acc - base_acc
    report: dict[str, Any] = {
        "oos_bars": int(len(y_oos_arr)),
        "horizon": horizon,
        "baseline": {
            "accuracy": round(base_acc, 4),
            "sharpe": round(_trade_sharpe(base_pnl), 4),
            "mean_return": round(float(np.nanmean(base_pnl)), 6),
            "trades": int(len(base_pnl)),
        },
        "ml": {
            "accuracy": round(ml_acc, 4),
            "sharpe": round(_trade_sharpe(ml_pnl), 4),
            "mean_return": round(float(np.nanmean(ml_pnl)), 6),
            "trades": int(len(ml_pnl)),
            "mean_confidence": round(float(np.mean(np.abs(ml_proba - 0.5)) * 2), 4),
        },
        "ml_as_filter": {
            "accuracy": round(filt_acc, 4),
            "sharpe": round(_trade_sharpe(filt_pnl), 4),
            "mean_return": round(float(np.nanmean(filt_pnl)) if n_agree else 0.0, 6),
            "trades": n_agree,
            "agreement_rate": round(n_agree / max(len(base_pred), 1), 4),
        },
        "ml_accuracy_lift": round(lift, 4),
        "ml_beats_baseline": bool(ml_acc > base_acc),
        "verdict": _verdict(base_acc, ml_acc, lift),
    }
    return report


def _verdict(base_acc: float, ml_acc: float, lift: float) -> str:
    if lift >= 0.03:
        return f"ML adds real value (+{lift * 100:.1f}pp directional accuracy over the rule baseline)."
    if lift > 0.005:
        return f"ML edges out the baseline (+{lift * 100:.1f}pp) — marginal; verify on more OOS bars."
    if lift >= -0.005:
        return "ML ties the rule baseline — Phase 2 is not adding directional value; fix the model or features before investing further."
    return f"ML UNDERPERFORMS the rule baseline ({lift * 100:.1f}pp) — investigate before trusting Phase 2."


# ─────────────────────────────────────────────────────────────────────────────
# Data loading / CLI
# ─────────────────────────────────────────────────────────────────────────────


def _synthetic_ohlcv(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    """Deterministic synthetic gold-like series for smoke runs / tests."""
    rng = np.random.default_rng(seed)
    drift = np.linspace(0, 0.4, n)
    price = 1800.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)) + drift)
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    high = price * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = price * (1 - np.abs(rng.normal(0, 0.004, n)))
    return pd.DataFrame(
        {"open": price, "high": high, "low": low, "close": price,
         "volume": rng.integers(1000, 5000, n)},
        index=idx,
    )


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    ts = cols.get("timestamp") or cols.get("date") or cols.get("time")
    if ts:
        dt = pd.to_datetime(df[ts], errors="coerce", utc=True)
        df.index = dt.dt.tz_localize(None)
        df = df.drop(columns=[ts])
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="A/B: ML model vs rule baseline on OOS")
    ap.add_argument("--csv", type=str, default=None, help="OHLCV CSV path")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--oos-years", type=float, default=3.0)
    ap.add_argument("--min-move", type=float, default=0.25)
    ap.add_argument("--smoke", action="store_true", help="synthetic data, fast")
    args = ap.parse_args()

    if args.smoke or not args.csv:
        logger.info("Running A/B on synthetic data (smoke)")
        df = _synthetic_ohlcv()
        n_est = 120
    else:
        logger.info("Loading %s", args.csv)
        df = _load_csv(args.csv)
        n_est = 300

    report = run_ab(
        df, horizon=args.horizon, oos_years=args.oos_years,
        min_move_atr=args.min_move, n_estimators=n_est,
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))

    logger.info("\n%s", "=" * 64)
    logger.info("A/B — ML vs RULE BASELINE  (OOS bars: %d, horizon: %d)",
                report["oos_bars"], report["horizon"])
    logger.info("=" * 64)
    logger.info("  baseline   acc=%.3f  sharpe=%.2f  (n=%d)",
                report["baseline"]["accuracy"], report["baseline"]["sharpe"], report["baseline"]["trades"])
    logger.info("  ml         acc=%.3f  sharpe=%.2f  (n=%d)",
                report["ml"]["accuracy"], report["ml"]["sharpe"], report["ml"]["trades"])
    logger.info("  ml_filter  acc=%.3f  sharpe=%.2f  (n=%d, agree=%.0f%%)",
                report["ml_as_filter"]["accuracy"], report["ml_as_filter"]["sharpe"],
                report["ml_as_filter"]["trades"], report["ml_as_filter"]["agreement_rate"] * 100)
    logger.info("  ML lift    %+.1fpp", report["ml_accuracy_lift"] * 100)
    logger.info("  VERDICT: %s", report["verdict"])
    logger.info("=" * 64)
    logger.info("Report → %s", REPORT_PATH)


if __name__ == "__main__":
    main()
