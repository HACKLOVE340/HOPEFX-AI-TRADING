#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/feature_stability_analysis.py
======================================
Walk-forward feature stability analysis across all CV folds.

Problem
-------
The production model uses 222 features across 6 walk-forward folds.
Features that appear in the top-N importance ranking in only 1-2 folds
are noise — they overfit to a specific market regime and degrade OOS
performance when that regime ends.

Method
------
1. Load the 50-year XAUUSD dataset (same pipeline as retrain_horizon5.py).
2. Run 6-fold TimeSeriesSplit walk-forward CV.
3. In each fold, train an XGBoost model and extract feature importances.
4. Compute per-feature stability score:
     stability = (folds_in_top_N) / total_folds
   where top_N = top 50 features by importance in each fold.
5. Classify features:
     stable   : stability >= STABLE_THRESHOLD (default 0.67 = 4/6 folds)
     marginal : stability >= MARGINAL_THRESHOLD (default 0.33 = 2/6 folds)
     unstable : stability < MARGINAL_THRESHOLD
6. Write ml/saved_models/feature_stability.json with:
     - stable_features   : list of feature names to keep
     - marginal_features : list to review
     - unstable_features : list to drop before next retrain
     - per_fold_top_N    : top-N features per fold for audit
     - stability_scores  : {feature: score} for all 222 features

Output
------
    ml/saved_models/feature_stability.json

Usage
-----
    python scripts/feature_stability_analysis.py
    python scripts/feature_stability_analysis.py --top-n 30 --stable-threshold 0.67
    python scripts/feature_stability_analysis.py --output path/to/report.json
    python scripts/feature_stability_analysis.py --smoke   # fast CI mode (2Y data)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("feature_stability")

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL_DIR = ROOT / "ml" / "saved_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_TOP_N = 50          # top-N features per fold to consider "important"
DEFAULT_STABLE_THRESHOLD = 0.67   # >= 4/6 folds → stable
DEFAULT_MARGINAL_THRESHOLD = 0.33  # >= 2/6 folds → marginal (review)
DEFAULT_N_SPLITS = 6
DEFAULT_YEARS = 50
DEFAULT_OOS_YEARS = 8
DEFAULT_HORIZON = 5
DEFAULT_MIN_MOVE_ATR = 0.25


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_data(years: int, smoke: bool) -> pd.DataFrame:
    """Load XAUUSD OHLCV via yfinance (same source as production retrain)."""
    import yfinance as yf

    if smoke:
        logger.info("Smoke mode: loading 2Y of GC=F data")
        df = yf.download("GC=F", period="2y", interval="1d", auto_adjust=True, progress=False)
    else:
        logger.info("Loading %dY of GC=F data via yfinance…", years)
        df = yf.download(
            "GC=F",
            period=f"{years}y",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )

    if df.empty:
        raise RuntimeError("yfinance returned no data for GC=F. Check network access.")

    # Flatten MultiIndex columns if present (yfinance ≥ 0.2.38)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    df = df.rename(columns={"adj close": "close"}) if "adj close" in df.columns else df
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    logger.info("Loaded %d bars  %s → %s", len(df), df.index[0].date(), df.index[-1].date())
    return df


# ── Feature matrix ────────────────────────────────────────────────────────────

def _build_features(df: pd.DataFrame, horizon: int, min_move_atr: float) -> tuple[pd.DataFrame, pd.Series]:
    """Build the full feature matrix using the production pipeline."""
    try:
        from ml.features_extended import build_extended_features
        logger.info("Building extended feature matrix…")
        X, y = build_extended_features(df, horizon=horizon, min_move_atr=min_move_atr)
        logger.info("Feature matrix: %d rows × %d features", len(X), X.shape[1])
        return X, y
    except Exception as exc:
        logger.warning("build_extended_features failed (%s) — falling back to advanced_features", exc)

    try:
        from ml.advanced_features import build_advanced_features
        logger.info("Building advanced feature matrix (fallback)…")
        X, y = build_advanced_features(df, horizon=horizon, min_move_atr=min_move_atr)
        logger.info("Feature matrix: %d rows × %d features", len(X), X.shape[1])
        return X, y
    except Exception as exc2:
        raise RuntimeError(f"Both feature builders failed: {exc2}") from exc2


# ── Per-fold importance extraction ────────────────────────────────────────────

def _train_fold_and_extract_importance(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    fold: int,
    ci_mode: bool,
) -> dict:
    """
    Train XGBoost on one fold and return feature importances + fold metrics.

    Uses gain-based importance (sum of information gain across all splits
    where the feature is used) rather than frequency-based importance.
    Gain is more robust to feature cardinality differences.
    """
    import xgboost as xgb
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    n_est = 50 if ci_mode else 300
    lr = 0.1 if ci_mode else 0.05

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", xgb.XGBClassifier(
            n_estimators=n_est,
            max_depth=3 if ci_mode else 5,
            learning_rate=lr,
            subsample=0.75,
            colsample_bytree=0.75,
            min_child_weight=3,
            gamma=0.05,
            reg_alpha=0.1,
            reg_lambda=1.5,
            importance_type="gain",   # gain > frequency for stability analysis
            eval_metric="logloss",
            random_state=42,
            n_jobs=1,
        )),
    ])

    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, preds)
    f1 = f1_score(y_test, preds, zero_division=0)
    try:
        auc = roc_auc_score(y_test, proba)
    except ValueError:
        auc = 0.5

    # Extract gain-based importances
    xgb_model = model.named_steps["xgb"]
    raw_imp = xgb_model.feature_importances_
    feature_names = list(X_train.columns)

    # Normalise to sum=1 so folds with different scales are comparable
    total = float(raw_imp.sum()) or 1.0
    importance = {name: float(raw_imp[i]) / total for i, name in enumerate(feature_names)}

    logger.info(
        "Fold %d  acc=%.3f  f1=%.3f  auc=%.3f  train=%d  test=%d",
        fold, acc, f1, auc, len(X_train), len(X_test),
    )

    return {
        "fold": fold,
        "accuracy": round(acc, 4),
        "f1": round(f1, 4),
        "auc": round(auc, 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "importance": importance,  # {feature: normalised_gain}
    }


# ── Stability computation ─────────────────────────────────────────────────────

def compute_stability(
    fold_results: list[dict],
    top_n: int,
    stable_threshold: float,
    marginal_threshold: float,
) -> dict:
    """
    Compute per-feature stability scores from fold importance dicts.

    stability_score(f) = (number of folds where f is in top-N) / total_folds

    Also computes mean and std of importance across folds where the feature
    appears, and a coefficient of variation (CV = std/mean) as a secondary
    instability signal.
    """
    n_folds = len(fold_results)
    all_features: set[str] = set()
    for r in fold_results:
        all_features.update(r["importance"].keys())

    # Per-fold top-N sets
    fold_top_n: list[list[str]] = []
    for r in fold_results:
        imp = r["importance"]
        top = sorted(imp, key=lambda f: imp[f], reverse=True)[:top_n]
        fold_top_n.append(top)

    # Stability scores
    stability_scores: dict[str, float] = {}
    mean_importance: dict[str, float] = {}
    std_importance: dict[str, float] = {}
    cv_importance: dict[str, float] = {}

    for feat in all_features:
        appearances = sum(1 for top in fold_top_n if feat in top)
        stability_scores[feat] = round(appearances / n_folds, 4)

        # Importance values across all folds (0 if absent)
        vals = [r["importance"].get(feat, 0.0) for r in fold_results]
        mean_imp = float(np.mean(vals))
        std_imp = float(np.std(vals))
        mean_importance[feat] = round(mean_imp, 6)
        std_importance[feat] = round(std_imp, 6)
        cv_importance[feat] = round(std_imp / mean_imp if mean_imp > 1e-10 else float("inf"), 4)

    # Classify
    stable = sorted(
        [f for f, s in stability_scores.items() if s >= stable_threshold],
        key=lambda f: stability_scores[f], reverse=True,
    )
    marginal = sorted(
        [f for f, s in stability_scores.items()
         if marginal_threshold <= s < stable_threshold],
        key=lambda f: stability_scores[f], reverse=True,
    )
    unstable = sorted(
        [f for f, s in stability_scores.items() if s < marginal_threshold],
        key=lambda f: stability_scores[f], reverse=True,
    )

    logger.info(
        "Feature stability: %d stable  %d marginal  %d unstable  (top-%d, threshold=%.2f)",
        len(stable), len(marginal), len(unstable), top_n, stable_threshold,
    )
    if stable:
        logger.info("Top 10 stable features: %s", stable[:10])
    if unstable:
        logger.info("Top 10 unstable features (to drop): %s", unstable[:10])

    return {
        "stable_features": stable,
        "marginal_features": marginal,
        "unstable_features": unstable,
        "stability_scores": stability_scores,
        "mean_importance": mean_importance,
        "std_importance": std_importance,
        "cv_importance": cv_importance,
        "per_fold_top_n": fold_top_n,
    }


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_stability_analysis(
    years: int = DEFAULT_YEARS,
    n_splits: int = DEFAULT_N_SPLITS,
    top_n: int = DEFAULT_TOP_N,
    stable_threshold: float = DEFAULT_STABLE_THRESHOLD,
    marginal_threshold: float = DEFAULT_MARGINAL_THRESHOLD,
    horizon: int = DEFAULT_HORIZON,
    min_move_atr: float = DEFAULT_MIN_MOVE_ATR,
    smoke: bool = False,
    output_path: Path | None = None,
) -> dict:
    """
    Full feature stability analysis pipeline.

    Returns the stability report dict and writes it to output_path.
    """
    from sklearn.model_selection import TimeSeriesSplit

    import os
    ci_mode = smoke or bool(os.getenv("CI_FAST") or os.getenv("HOPEFX_CI"))

    if ci_mode:
        years = 2
        n_splits = 2
        logger.info("CI/smoke mode: years=2, n_splits=2")

    # 1. Load data
    df = _load_data(years=years, smoke=smoke)

    # 2. Build feature matrix
    X, y = _build_features(df, horizon=horizon, min_move_atr=min_move_atr)

    if len(X) < 200:
        raise RuntimeError(
            f"Insufficient data for stability analysis: {len(X)} samples "
            f"(need >= 200). Increase --years or check data source."
        )

    # 3. Walk-forward CV
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=horizon)
    fold_results: list[dict] = []

    logger.info("Running %d-fold walk-forward stability analysis…", n_splits)
    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X), start=1):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        if len(y_train.unique()) < 2:
            logger.warning("Fold %d: single class in training — skipping", fold_idx)
            continue
        if len(y_test.unique()) < 2:
            logger.warning("Fold %d: single class in test — skipping", fold_idx)
            continue

        result = _train_fold_and_extract_importance(
            X_train, y_train, X_test, y_test,
            fold=fold_idx, ci_mode=ci_mode,
        )
        fold_results.append(result)

    if not fold_results:
        raise RuntimeError("No valid folds produced. Check data quality.")

    # 4. Compute stability
    stability = compute_stability(
        fold_results=fold_results,
        top_n=top_n,
        stable_threshold=stable_threshold,
        marginal_threshold=marginal_threshold,
    )

    # 5. Fold-level accuracy summary
    fold_accs = [r["accuracy"] for r in fold_results]
    fold_summary = [
        {k: v for k, v in r.items() if k != "importance"}
        for r in fold_results
    ]

    # 6. Assemble report
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "years": years,
            "n_splits": n_splits,
            "top_n": top_n,
            "stable_threshold": stable_threshold,
            "marginal_threshold": marginal_threshold,
            "horizon": horizon,
            "min_move_atr": min_move_atr,
            "ci_mode": ci_mode,
            "total_features": X.shape[1],
            "total_samples": len(X),
        },
        "summary": {
            "n_stable": len(stability["stable_features"]),
            "n_marginal": len(stability["marginal_features"]),
            "n_unstable": len(stability["unstable_features"]),
            "mean_fold_accuracy": round(float(np.mean(fold_accs)), 4),
            "std_fold_accuracy": round(float(np.std(fold_accs)), 4),
            "recommendation": (
                f"Drop {len(stability['unstable_features'])} unstable features before next retrain. "
                f"Keep {len(stability['stable_features'])} stable features. "
                f"Review {len(stability['marginal_features'])} marginal features."
            ),
        },
        "stable_features": stability["stable_features"],
        "marginal_features": stability["marginal_features"],
        "unstable_features": stability["unstable_features"],
        "stability_scores": stability["stability_scores"],
        "mean_importance": stability["mean_importance"],
        "cv_importance": stability["cv_importance"],
        "per_fold_top_n": stability["per_fold_top_n"],
        "fold_results": fold_summary,
    }

    # 7. Write output
    out = output_path or (MODEL_DIR / "feature_stability.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    logger.info("Feature stability report written → %s", out)

    # 8. Print summary
    print("\n" + "=" * 60)
    print("FEATURE STABILITY ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"  Total features   : {X.shape[1]}")
    print(f"  Stable (>= {stable_threshold:.0%}) : {len(stability['stable_features'])}")
    print(f"  Marginal         : {len(stability['marginal_features'])}")
    print(f"  Unstable (drop)  : {len(stability['unstable_features'])}")
    print(f"  Mean fold acc    : {np.mean(fold_accs):.4f} ± {np.std(fold_accs):.4f}")
    print("\n  Top 15 stable features:")
    for feat in stability["stable_features"][:15]:
        score = stability["stability_scores"][feat]
        mean_imp = stability["mean_importance"][feat]
        print(f"    {feat:<40s}  stability={score:.2f}  mean_gain={mean_imp:.6f}")
    if stability["unstable_features"]:
        print("\n  Top 10 unstable features (recommend dropping):")
        for feat in stability["unstable_features"][:10]:
            score = stability["stability_scores"][feat]
            cv = stability["cv_importance"].get(feat, float("inf"))
            print(f"    {feat:<40s}  stability={score:.2f}  CV={cv:.2f}")
    print("=" * 60)

    return report


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Walk-forward feature stability analysis for HOPEFX ML models.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--years", type=int, default=DEFAULT_YEARS,
                   help="Years of XAUUSD history to use")
    p.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS,
                   help="Number of walk-forward CV folds")
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                   help="Top-N features per fold to consider 'important'")
    p.add_argument("--stable-threshold", type=float, default=DEFAULT_STABLE_THRESHOLD,
                   help="Fraction of folds a feature must appear in to be 'stable'")
    p.add_argument("--marginal-threshold", type=float, default=DEFAULT_MARGINAL_THRESHOLD,
                   help="Fraction of folds below which a feature is 'unstable'")
    p.add_argument("--horizon", type=int, default=DEFAULT_HORIZON,
                   help="Prediction horizon in bars (must match production model)")
    p.add_argument("--min-move-atr", type=float, default=DEFAULT_MIN_MOVE_ATR,
                   help="Minimum move (ATR multiples) to include a bar as a training sample")
    p.add_argument("--output", type=Path, default=MODEL_DIR / "feature_stability.json",
                   help="Output path for the stability report JSON")
    p.add_argument("--smoke", action="store_true",
                   help="Smoke-test mode: 2Y data, 2 folds (fast CI validation)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    run_stability_analysis(
        years=args.years,
        n_splits=args.n_splits,
        top_n=args.top_n,
        stable_threshold=args.stable_threshold,
        marginal_threshold=args.marginal_threshold,
        horizon=args.horizon,
        min_move_atr=args.min_move_atr,
        smoke=args.smoke,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
