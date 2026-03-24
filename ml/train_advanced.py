#!/usr/bin/env python3
"""
ml/train_advanced.py
====================
High-accuracy XAUUSD direction model targeting 85-90% accuracy.

Architecture
------------
1. Advanced feature engineering (price-action, swing levels, MTF momentum,
   volatility regime, microstructure, calendar, trend strength, macro)
2. Filtered target: only train on bars with meaningful moves (>= 0.25 ATR)
3. Stacking ensemble: XGBoost + LightGBM + RandomForest + ExtraTrees
   → meta-learner: LogisticRegression with calibration
4. Walk-forward cross-validation (TimeSeriesSplit, 8 folds)
5. Probability calibration (Platt scaling / isotonic regression)
6. Statistical significance test (t-test vs 0.5 baseline)

Usage
-----
    python ml/train_advanced.py [--years 8] [--symbol GC=F] [--no-macro]

Output
------
    ml/saved_models/stacking_ensemble.pkl
    ml/saved_models/feature_scaler.pkl
    ml/saved_models/advanced_training_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
MODEL_DIR = ROOT / "ml" / "saved_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_gold_ohlcv(symbol: str, years: int) -> pd.DataFrame:
    """Download XAUUSD/GC=F daily OHLCV from Yahoo Finance."""
    import yfinance as yf

    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=years * 365)
    logger.info("Downloading %s  %s → %s", symbol, start.date(), end.date())

    raw = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if raw.empty:
        raise ValueError(f"No data returned for {symbol}")

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]

    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    logger.info("Downloaded %d bars for %s", len(raw), symbol)
    return raw


def fetch_macro(start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    """Fetch macro data (DXY, VIX, yields, SPX)."""
    try:
        from ml.macro_features import fetch_macro_history
        df = fetch_macro_history(start, end, interval="1d")
        if df.empty:
            logger.warning("Macro data returned empty — skipping")
            return None
        logger.info("Macro data: %d rows, %d columns", len(df), df.shape[1])
        return df
    except Exception as exc:
        logger.warning("Macro fetch failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Model building
# ─────────────────────────────────────────────────────────────────────────────

def _build_base_models():
    """Return list of (name, estimator) base learners."""
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier

    models = [
        (
            "xgb",
            xgb.XGBClassifier(
                n_estimators=600,
                max_depth=5,
                learning_rate=0.03,
                subsample=0.75,
                colsample_bytree=0.75,
                min_child_weight=3,
                gamma=0.05,
                reg_alpha=0.1,
                reg_lambda=1.5,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            ),
        ),
        (
            "rf",
            RandomForestClassifier(
                n_estimators=500,
                max_depth=10,
                min_samples_leaf=5,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        ),
        (
            "et",
            ExtraTreesClassifier(
                n_estimators=500,
                max_depth=10,
                min_samples_leaf=5,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        ),
        (
            "gbm",
            GradientBoostingClassifier(
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                min_samples_leaf=5,
                random_state=42,
            ),
        ),
    ]

    # LightGBM if available
    try:
        import lightgbm as lgb
        models.append((
            "lgbm",
            lgb.LGBMClassifier(
                n_estimators=600,
                max_depth=5,
                learning_rate=0.03,
                subsample=0.75,
                colsample_bytree=0.75,
                min_child_samples=10,
                reg_alpha=0.1,
                reg_lambda=1.5,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            ),
        ))
        logger.info("LightGBM available — added to ensemble")
    except ImportError:
        logger.info("LightGBM not installed — using 4-model ensemble")

    return models


def build_stacking_ensemble():
    """
    Build a stacking classifier:
      Base: XGBoost + RF + ExtraTrees + GBM [+ LightGBM]
      Meta: Calibrated LogisticRegression
    """
    from sklearn.ensemble import StackingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    base_models = _build_base_models()

    meta = LogisticRegression(
        C=0.5,
        max_iter=1000,
        solver="lbfgs",
        random_state=42,
    )

    stacker = StackingClassifier(
        estimators=base_models,
        final_estimator=meta,
        cv=5,
        stack_method="predict_proba",
        passthrough=True,   # also pass original features to meta-learner
        n_jobs=-1,
    )

    # Wrap in calibration for reliable probability estimates
    calibrated = CalibratedClassifierCV(stacker, method="isotonic", cv=3)

    # Full pipeline with scaling
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model",  calibrated),
    ])

    return pipeline


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward evaluation
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward_eval(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 8,
) -> Dict:
    """
    Walk-forward cross-validation with the stacking ensemble.
    Uses a simpler (faster) model for CV to avoid O(n²) fitting time.
    """
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.calibration import CalibratedClassifierCV
    import xgboost as xgb

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=1)
    fold_results = []

    # Use XGBoost + calibration for CV (fast, representative)
    def _cv_model():
        base = xgb.XGBClassifier(
            n_estimators=400,
            max_depth=5,
            learning_rate=0.04,
            subsample=0.75,
            colsample_bytree=0.75,
            min_child_weight=3,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
        cal = CalibratedClassifierCV(base, method="isotonic", cv=3)
        return Pipeline([("scaler", StandardScaler()), ("model", cal)])

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        if len(y_train.unique()) < 2:
            logger.warning("Fold %d: only one class in training — skipping", fold + 1)
            continue

        model = _cv_model()
        model.fit(X_train, y_train)

        preds = model.predict(X_test)
        proba = model.predict_proba(X_test)[:, 1]

        acc  = accuracy_score(y_test, preds)
        f1   = f1_score(y_test, preds, zero_division=0)
        try:
            auc = roc_auc_score(y_test, proba)
        except Exception:
            auc = 0.5

        fold_results.append({
            "fold":       fold + 1,
            "train_size": len(train_idx),
            "test_size":  len(test_idx),
            "accuracy":   round(acc, 4),
            "f1":         round(f1, 4),
            "auc":        round(auc, 4),
        })
        logger.info(
            "Fold %d/%d  acc=%.3f  f1=%.3f  auc=%.3f  train=%d  test=%d",
            fold + 1, n_splits, acc, f1, auc, len(train_idx), len(test_idx),
        )

    if not fold_results:
        return {"error": "no valid folds"}

    accs = [r["accuracy"] for r in fold_results]
    f1s  = [r["f1"]       for r in fold_results]
    aucs = [r["auc"]      for r in fold_results]

    t_stat, p_value = stats.ttest_1samp(accs, 0.5)

    return {
        "folds":         fold_results,
        "mean_accuracy": round(float(np.mean(accs)), 4),
        "std_accuracy":  round(float(np.std(accs)),  4),
        "mean_f1":       round(float(np.mean(f1s)),  4),
        "mean_auc":      round(float(np.mean(aucs)), 4),
        "t_stat":        round(float(t_stat),        4),
        "p_value":       round(float(p_value),       4),
        "significant":   bool(p_value < 0.05 and np.mean(accs) > 0.55),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Final model training
# ─────────────────────────────────────────────────────────────────────────────

def train_final_model(
    X: pd.DataFrame,
    y: pd.Series,
    train_pct: float = 0.8,
) -> Tuple[object, Dict]:
    """Train stacking ensemble on 80% of data; evaluate on held-out 20%."""
    from sklearn.metrics import (
        accuracy_score, f1_score, roc_auc_score,
        classification_report, confusion_matrix,
    )

    split = int(len(X) * train_pct)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    logger.info("Training stacking ensemble on %d samples...", len(X_train))
    model = build_stacking_ensemble()
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]

    acc  = accuracy_score(y_test, preds)
    f1   = f1_score(y_test, preds, zero_division=0)
    try:
        auc = roc_auc_score(y_test, proba)
    except Exception:
        auc = 0.5

    logger.info("Final model  acc=%.3f  f1=%.3f  auc=%.3f", acc, f1, auc)
    logger.info("\n%s", classification_report(y_test, preds))
    logger.info("Confusion matrix:\n%s", confusion_matrix(y_test, preds))

    # Save
    model_path = MODEL_DIR / "stacking_ensemble.pkl"
    joblib.dump(model, model_path)
    logger.info("Saved stacking ensemble → %s", model_path)

    return model, {
        "train_size":    len(X_train),
        "test_size":     len(X_test),
        "accuracy":      round(acc, 4),
        "f1":            round(f1, 4),
        "auc":           round(auc, 4),
        "feature_count": X.shape[1],
        "features":      list(X.columns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Feature importance
# ─────────────────────────────────────────────────────────────────────────────

def extract_feature_importance(model, feature_names: List[str]) -> Dict:
    """Extract feature importance from the stacking ensemble."""
    try:
        # Try to get importance from the XGBoost base model inside the pipeline
        pipeline = model
        cal_model = pipeline.named_steps["model"]
        stacker   = cal_model.calibrated_classifiers_[0].estimator
        xgb_model = dict(stacker.estimators_).get("xgb")
        if xgb_model and hasattr(xgb_model, "feature_importances_"):
            imp = pd.Series(xgb_model.feature_importances_, index=feature_names)
            top20 = imp.nlargest(20).to_dict()
            return {k: round(float(v), 6) for k, v in top20.items()}
    except Exception:
        pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train advanced XAUUSD stacking ensemble")
    parser.add_argument("--years",     type=int,   default=8,     help="Years of history")
    parser.add_argument("--symbol",    default="GC=F",            help="Yahoo Finance symbol")
    parser.add_argument("--no-macro",  action="store_true",       help="Skip macro features")
    parser.add_argument("--horizon",   type=int,   default=1,     help="Prediction horizon (bars)")
    parser.add_argument("--splits",    type=int,   default=8,     help="Walk-forward CV splits")
    parser.add_argument("--min-move",  type=float, default=0.25,  help="Min ATR move for filtered target")
    parser.add_argument("--no-filter", action="store_true",       help="Disable filtered target")
    args = parser.parse_args()

    from ml.advanced_features import build_advanced_features

    # ── Fetch data ────────────────────────────────────────────────────────────
    ohlcv = fetch_gold_ohlcv(args.symbol, args.years)
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.years * 365)

    macro_df = None
    if not args.no_macro:
        macro_df = fetch_macro(start_dt, end_dt)

    # ── Build features ────────────────────────────────────────────────────────
    logger.info("Building advanced feature matrix (macro=%s, filtered=%s)...",
                macro_df is not None, not args.no_filter)

    X, y = build_advanced_features(
        ohlcv,
        macro_df=macro_df,
        horizon=args.horizon,
        use_filtered_target=not args.no_filter,
        min_move_atr=args.min_move,
    )
    logger.info("Feature matrix: %d rows × %d columns", *X.shape)
    logger.info("Class balance: %s", y.value_counts().to_dict())

    if len(X) < 100:
        logger.error("Too few samples (%d) after filtering — reduce --min-move", len(X))
        sys.exit(1)

    # ── Walk-forward evaluation ───────────────────────────────────────────────
    logger.info("\n=== Walk-forward CV (XGBoost + calibration, %d folds) ===", args.splits)
    wf = walk_forward_eval(X, y, n_splits=args.splits)

    logger.info(
        "Walk-forward  acc=%.3f±%.3f  f1=%.3f  auc=%.3f  p=%.4f  significant=%s",
        wf.get("mean_accuracy", 0),
        wf.get("std_accuracy",  0),
        wf.get("mean_f1",       0),
        wf.get("mean_auc",      0),
        wf.get("p_value",       1),
        wf.get("significant",   False),
    )

    # ── Train final stacking ensemble ─────────────────────────────────────────
    logger.info("\n=== Training final stacking ensemble ===")
    final_model, final_metrics = train_final_model(X, y)

    # Feature importance
    importance = extract_feature_importance(final_model, list(X.columns))
    if importance:
        logger.info("Top features: %s", list(importance.keys())[:10])

    # ── Save report ───────────────────────────────────────────────────────────
    report = {
        "symbol":          args.symbol,
        "years":           args.years,
        "macro_features":  macro_df is not None,
        "filtered_target": not args.no_filter,
        "min_move_atr":    args.min_move,
        "horizon":         args.horizon,
        "sample_count":    len(X),
        "feature_count":   X.shape[1],
        "trained_at":      datetime.now(timezone.utc).isoformat(),
        "walkforward":     wf,
        "final":           final_metrics,
        "top_features":    importance,
    }

    report_path = MODEL_DIR / "advanced_training_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Report saved → %s", report_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("ADVANCED TRAINING SUMMARY")
    print("=" * 65)
    print(f"  Symbol          : {args.symbol}  ({args.years} years)")
    print(f"  Samples         : {len(X)}  (after filtered-target)")
    print(f"  Features        : {X.shape[1]}")
    print(f"  Macro features  : {macro_df is not None}")
    print()
    print(f"  Walk-forward accuracy : {wf.get('mean_accuracy', 0):.3f} ± {wf.get('std_accuracy', 0):.3f}")
    print(f"  Walk-forward F1       : {wf.get('mean_f1', 0):.3f}")
    print(f"  Walk-forward AUC      : {wf.get('mean_auc', 0):.3f}")
    print(f"  p-value (vs random)   : {wf.get('p_value', 1):.4f}  "
          f"{'✓ significant' if wf.get('significant') else '✗ not significant'}")
    print()
    print(f"  Final holdout accuracy: {final_metrics['accuracy']:.3f}")
    print(f"  Final holdout F1      : {final_metrics['f1']:.3f}")
    print(f"  Final holdout AUC     : {final_metrics['auc']:.3f}")
    print()

    acc = final_metrics["accuracy"]
    if acc >= 0.85:
        print("  ✓ TARGET MET: accuracy >= 85%")
    elif acc >= 0.70:
        print("  ⚠ Partial: accuracy >= 70% — increase --years or reduce --min-move")
    else:
        print("  ✗ Below target — check feature quality and data volume")

    print("=" * 65)

    return report


if __name__ == "__main__":
    main()
