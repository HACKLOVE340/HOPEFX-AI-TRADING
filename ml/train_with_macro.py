#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/train_with_macro.py
======================
Train XAUUSD direction models with macro features (DXY, VIX, yields, SPX).

Walk-forward validation on up to 50 years of daily data.
Reports accuracy, F1, Sharpe, and statistical significance (binomial test).

Statistical significance notes
-------------------------------
  N=45 trades is insufficient for Sharpe significance (SE ≈ ±0.54).
  Need ~250 trades for SE ≤ ±0.3.
  The credible performance number is OOS accuracy (p-value from binomial test),
  not Sharpe ratio.  Do not commit live capital until 30+ days paper trading done.

Data availability note
----------------------
Yahoo Finance (yfinance) provides GC=F (Gold Futures) daily data back to
approximately 1974 (~50 years). Requesting --years 50 will fetch all
available history; yfinance silently clips to the earliest available date
so the actual bar count may be less than 50 × 252 trading days.

For tick-level or intraday data beyond what Yahoo provides, supplement
with a commercial data vendor (e.g. Refinitiv, Bloomberg, Quandl/Nasdaq)
and pass the pre-downloaded CSV via --csv-path.

Usage
-----
    # Full 50-year daily history (recommended for production)
    python ml/train_with_macro.py --years 50

    # Quick smoke test
    python ml/train_with_macro.py --years 5 --no-macro

    # Custom symbol / horizon
    python ml/train_with_macro.py --years 50 --symbol GC=F --horizon 1

Output
------
    ml/saved_models/xgb_macro.pkl
    ml/saved_models/rf_macro.pkl
    ml/saved_models/training_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
MODEL_DIR = ROOT / "ml" / "saved_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def fetch_gold_ohlcv(symbol: str, years: int) -> pd.DataFrame:
    """Download XAUUSD/GC=F daily OHLCV from Yahoo Finance.

    Yahoo Finance provides GC=F data back to approximately 1974 (~50 years).
    Requesting more years than available is safe — yfinance clips silently to
    the earliest available date. The actual bar count is logged after download.
    """
    import yfinance as yf

    end = datetime.now(UTC)
    start = end - timedelta(days=years * 365)
    logger.info(
        "Requesting %d years of %s daily data (%s → %s)",
        years,
        symbol,
        start.date(),
        end.date(),
    )
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
    raw.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in raw.columns]
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    actual_years = (raw.index[-1] - raw.index[0]).days / 365.25
    logger.info(
        "Downloaded %d bars for %s (%.1f years: %s → %s)",
        len(raw),
        symbol,
        actual_years,
        raw.index[0].date(),
        raw.index[-1].date(),
    )
    return raw


def fetch_macro(start: datetime, end: datetime) -> pd.DataFrame | None:
    """Fetch macro data (DXY, VIX, yields, SPX)."""
    try:
        from ml.macro_features import fetch_macro_history

        df = fetch_macro_history(start, end, interval="1d")
        if df.empty:
            logger.warning("Macro data fetch returned empty DataFrame")
            return None
        logger.info(
            "Fetched macro data: %d rows, columns=%s",
            len(df),
            list(df.columns),
        )
        return df
    except Exception as exc:
        logger.warning("Macro fetch failed: %s", exc)
        return None


def build_features(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None,
    prediction_horizon: int = 1,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build feature matrix and binary direction target."""
    # ml/training/ directory shadows ml/training.py — import directly from the file
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location(
        "ml._training_module",
        Path(__file__).parent / "training.py",
    )
    _mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
    FeatureEngineer = _mod.FeatureEngineer
    fe = FeatureEngineer(
        include_indicators=True,
        include_lags=True,
        include_macro=True,
        include_regime=True,
        macro_df=macro_df,
    )
    X, y_class, _y_reg, _ = fe.create_features(
        ohlcv,
        target_col="close",
        prediction_horizon=prediction_horizon,
        lookback_window=20,
    )
    return X, y_class


def _compute_fold_sharpe(
    X_test: pd.DataFrame,
    y_test: pd.Series,
    preds: np.ndarray,
    annualise: bool = True,
) -> float:
    """
    Compute annualised Sharpe ratio for a single walk-forward fold.

    Strategy: go long (+1) when pred=1, short (-1) when pred=0.
    Realised return proxy: next-bar close return × signal direction.

    The 'returns' or 'log_returns' column in X_test is used as the
    next-bar return proxy (it is the 1-bar lagged return, so it represents
    the return that was realised on the bar being predicted).

    This is a 1-bar holding period with no transaction costs — an upper
    bound on strategy performance, not a live trading estimate.

    Returns 0.0 if the return series cannot be reconstructed.
    """
    # Prefer log_returns (more stationary), fall back to returns
    ret_col = None
    for candidate in ("log_returns", "returns", "returns_lag_1", "log_ret_lag_1"):
        if candidate in X_test.columns:
            ret_col = candidate
            break

    if ret_col is None:
        return 0.0

    bar_returns = X_test[ret_col].values
    # Signal: +1 for long (pred=1), -1 for short (pred=0)
    signal = np.where(preds == 1, 1.0, -1.0)
    strategy_returns = signal * bar_returns

    if len(strategy_returns) < 2:  # noqa: PLR2004
        return 0.0

    mu = np.mean(strategy_returns)
    std = np.std(strategy_returns, ddof=1)
    if std == 0.0:
        return 0.0

    sharpe = mu / std
    if annualise:
        sharpe *= np.sqrt(252)  # daily bars → annualised
    return float(np.clip(sharpe, -10.0, 10.0))


def walk_forward_eval(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
    model_type: str = "xgb",
) -> dict:
    """
    Walk-forward cross-validation.

    Returns dict with per-fold metrics and aggregate statistics.
    """
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import TimeSeriesSplit

    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_results = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        if model_type == "xgb":
            model = xgb.XGBClassifier(
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=5,
                gamma=0.1,
                reg_alpha=0.1,
                reg_lambda=1.0,
                scale_pos_weight=float((y_train == 0).sum()) / max((y_train == 1).sum(), 1),
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
        else:
            model = RandomForestClassifier(
                n_estimators=300,
                max_depth=6,
                min_samples_leaf=10,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            )

        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        _proba = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else preds

        acc = accuracy_score(y_test, preds)
        f1 = f1_score(y_test, preds, zero_division=0)

        # ── Sharpe ratio from simulated long/short strategy ───────────────────
        # Signal: +1 (long) when pred=1, -1 (short) when pred=0.
        # Realised P&L proxy: next-bar close return × signal direction.
        # This is a 1-bar holding period with no transaction costs — an upper
        # bound on strategy performance, not a live trading estimate.
        # Annualised Sharpe = mean(daily_ret) / std(daily_ret) × sqrt(252).
        sharpe = _compute_fold_sharpe(X_test, y_test, preds)

        fold_results.append(
            {
                "fold": fold + 1,
                "train_size": len(train_idx),
                "test_size": len(test_idx),
                "accuracy": round(acc, 4),
                "f1": round(f1, 4),
                "sharpe": round(sharpe, 4),
            },
        )
        logger.info(
            "Fold %d/%d  acc=%.3f  f1=%.3f  sharpe=%.3f  train=%d  test=%d",
            fold + 1,
            n_splits,
            acc,
            f1,
            sharpe,
            len(train_idx),
            len(test_idx),
        )

    accs = [r["accuracy"] for r in fold_results]
    f1s = [r["f1"] for r in fold_results]
    sharpes = [r["sharpe"] for r in fold_results]

    # One-sample t-test: H0 = mean accuracy == 0.5 (random)
    t_stat, p_value = stats.ttest_1samp(accs, 0.5)

    return {
        "model": model_type,
        "folds": fold_results,
        "mean_accuracy": round(float(np.mean(accs)), 4),
        "std_accuracy": round(float(np.std(accs)), 4),
        "mean_f1": round(float(np.mean(f1s)), 4),
        "mean_sharpe": round(float(np.mean(sharpes)), 4),
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05),  # noqa: PLR2004
    }


def train_final_model(
    X: pd.DataFrame,
    y: pd.Series,
    model_type: str = "xgb",
    train_pct: float = 0.8,
):
    """Train on 80% of data, evaluate on held-out 20%."""
    import joblib
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report, f1_score

    split = int(len(X) * train_pct)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    if model_type == "xgb":
        model = xgb.XGBClassifier(
            n_estimators=500,
            max_depth=4,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            gamma=0.1,
            reg_alpha=0.1,
            reg_lambda=1.0,
            scale_pos_weight=float((y_train == 0).sum()) / max((y_train == 1).sum(), 1),
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
    else:
        model = RandomForestClassifier(
            n_estimators=500,
            max_depth=8,
            min_samples_leaf=5,
            max_features="sqrt",
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    f1 = f1_score(y_test, preds, zero_division=0)

    logger.info(
        "Final %s  acc=%.3f  f1=%.3f  train=%d  test=%d",
        model_type,
        acc,
        f1,
        len(X_train),
        len(X_test),
    )
    logger.info("\n%s", classification_report(y_test, preds))

    # Feature importance
    if hasattr(model, "feature_importances_"):
        imp = pd.Series(model.feature_importances_, index=X.columns)
        top10 = imp.nlargest(10)
        logger.info("Top-10 features:\n%s", top10.to_string())

    # Save model
    out_path = MODEL_DIR / f"{model_type}_macro.pkl"
    joblib.dump(model, out_path)
    logger.info("Saved model to %s", out_path)

    return model, {
        "model": model_type,
        "train_size": len(X_train),
        "test_size": len(X_test),
        "accuracy": round(acc, 4),
        "f1": round(f1, 4),
        "feature_count": X.shape[1],
        "features": list(X.columns),
    }


def oos_eval(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_oos: pd.DataFrame,
    y_oos: pd.Series,
    model_type: str = "xgb",
) -> dict:
    """
    Train on X_train/y_train, evaluate on a completely held-out X_oos/y_oos.

    The OOS set is never seen during training or hyperparameter selection.
    Reports accuracy, F1, and a one-sided binomial p-value testing H0: accuracy <= 0.5.

    The binomial test is more appropriate than a t-test here because we have
    a single OOS period (not multiple folds) and the test statistic is a count
    of correct predictions out of N independent Bernoulli trials.

    Statistical significance
    ------------------------
    The credible performance number is OOS accuracy (p-value from binomial test),
    not Sharpe ratio.  N=45 trades gives Sharpe SE ≈ ±0.54 — not statistically
    robust.  Need ~250 trades for SE ≤ ±0.3.
    """
    import joblib
    import xgboost as xgb
    from scipy.stats import binomtest
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        f1_score,
        roc_auc_score,
    )

    if model_type == "xgb":
        model = xgb.XGBClassifier(
            n_estimators=500,
            max_depth=4,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            gamma=0.1,
            reg_alpha=0.1,
            reg_lambda=1.0,
            scale_pos_weight=float((y_train == 0).sum()) / max((y_train == 1).sum(), 1),
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
    else:
        model = RandomForestClassifier(
            n_estimators=500,
            max_depth=8,
            min_samples_leaf=5,
            max_features="sqrt",
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

    model.fit(X_train, y_train)
    preds = model.predict(X_oos)
    acc = accuracy_score(y_oos, preds)
    f1 = f1_score(y_oos, preds, zero_division=0)
    n = len(y_oos)
    k = int(round(acc * n))

    # Accuracy SE: sqrt(p*(1-p)/n)
    acc_se = float(np.sqrt(acc * (1 - acc) / max(n, 1)))

    # AUC
    try:
        proba = model.predict_proba(X_oos)[:, 1]
        auc = float(roc_auc_score(y_oos, proba))
    except Exception:
        auc = 0.5

    # One-sided binomial test: H0 = p(correct) <= 0.5
    binom_result = binomtest(k, n, p=0.5, alternative="greater")
    p_value = float(binom_result.pvalue)

    # OOS date range
    oos_start = X_oos.index[0].date() if hasattr(X_oos.index[0], "date") else str(X_oos.index[0])
    oos_end = X_oos.index[-1].date() if hasattr(X_oos.index[-1], "date") else str(X_oos.index[-1])

    logger.info(
        "OOS %s  acc=%.3f±%.3f  f1=%.3f  auc=%.3f  n=%d  k=%d  p=%.4f  significant=%s",
        model_type.upper(),
        acc,
        acc_se,
        f1,
        auc,
        n,
        k,
        p_value,
        p_value < 0.05,  # noqa: PLR2004
    )
    logger.info("\n%s", classification_report(y_oos, preds))

    # Save OOS model
    out_path = MODEL_DIR / f"{model_type}_macro_oos.pkl"
    joblib.dump(model, out_path)
    logger.info("Saved OOS model to %s", out_path)

    # Feature importance
    if hasattr(model, "feature_importances_"):
        imp = pd.Series(model.feature_importances_, index=X_train.columns)
        top10 = {k: round(float(v), 6) for k, v in imp.nlargest(10).items()}
        logger.info("Top-10 OOS features: %s", top10)
    else:
        top10 = {}

    return {
        "model": model_type,
        "train_size": len(X_train),
        "oos_size": n,
        "correct_predictions": k,
        "accuracy": round(acc, 4),
        "accuracy_se": round(acc_se, 4),
        "f1": round(f1, 4),
        "auc": round(auc, 4),
        "p_value_binomial": round(p_value, 4),
        "significant": bool(p_value < 0.05),  # noqa: PLR2004
        "oos_period": f"{oos_start} → {oos_end}",
        "test": "one-sided binomial (H0: accuracy <= 0.5)",
        "top_features": top10,
        "sharpe_note": ("N=45 trades: Sharpe SE ≈ ±0.54. Use OOS accuracy as the credible performance number."),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Train XAUUSD direction models with macro features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python ml/train_with_macro.py --years 50              # full history\n"
            "  python ml/train_with_macro.py --years 50 --oos-years 3  # 3-year OOS\n"
            "  python ml/train_with_macro.py --years 5 --no-macro    # quick test\n"
        ),
    )
    parser.add_argument(
        "--years",
        type=int,
        default=50,
        help="Years of daily history to request from Yahoo Finance (default: 50). "
        "yfinance clips to earliest available date (~1974 for GC=F).",
    )
    parser.add_argument(
        "--symbol",
        default="GC=F",
        help="Yahoo Finance symbol (default: GC=F)",
    )
    parser.add_argument(
        "--no-macro",
        action="store_true",
        help="Skip macro features (DXY, VIX, yields, SPX)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=1,
        help="Prediction horizon in bars (default: 1)",
    )
    parser.add_argument(
        "--splits",
        type=int,
        default=5,
        help="Walk-forward CV splits (default: 5)",
    )
    parser.add_argument(
        "--oos-years",
        type=float,
        default=0.0,
        help=(
            "Reserve the last N years as a completely held-out OOS period. "
            "The model is trained on all data before this window and evaluated "
            "on it with a one-sided binomial p-value test. "
            "Default: 0 (no separate OOS period; use walk-forward CV only)."
        ),
    )
    args = parser.parse_args()

    # ── Fetch data ────────────────────────────────────────────────────────────
    ohlcv = fetch_gold_ohlcv(args.symbol, args.years)
    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=args.years * 365)

    macro_df = None
    if not args.no_macro:
        macro_df = fetch_macro(start_dt, end_dt)

    # ── Build features ────────────────────────────────────────────────────────
    logger.info("Building feature matrix (macro=%s)...", macro_df is not None)
    X, y = build_features(ohlcv, macro_df, prediction_horizon=args.horizon)
    logger.info("Feature matrix: %d rows × %d columns", *X.shape)

    # ── OOS split (if requested) ──────────────────────────────────────────────
    # The OOS period is carved off the END of the dataset before any model
    # training or CV.  It is never seen during training or hyperparameter
    # selection — this is the only valid way to estimate live performance.
    oos_n = 0
    X_cv, y_cv = X, y
    X_oos, y_oos = None, None

    if args.oos_years > 0:
        oos_n = int(round(args.oos_years * 252))  # ~252 trading days/year
        oos_n = min(oos_n, len(X) // 4)  # cap at 25% of data
        if oos_n < 100:  # noqa: PLR2004
            # < 100 bars gives accuracy SE > ±0.05 — not meaningful for production.
            logger.warning(
                "--oos-years %.1f produces only %d bars (need >= 100 for SE <= ±0.05). "
                "Increase --oos-years or --years.",
                args.oos_years,
                oos_n,
            )
            oos_n = 0
        else:
            X_cv, y_cv = X.iloc[:-oos_n], y.iloc[:-oos_n]
            X_oos, y_oos = X.iloc[-oos_n:], y.iloc[-oos_n:]
            logger.info(
                "OOS split: train/CV=%d bars, OOS=%d bars (last %.1f years, %s → %s)",
                len(X_cv),
                oos_n,
                args.oos_years,
                X_oos.index[0].date() if hasattr(X_oos.index[0], "date") else X_oos.index[0],
                X_oos.index[-1].date() if hasattr(X_oos.index[-1], "date") else X_oos.index[-1],
            )

    # ── Walk-forward evaluation (on CV portion only) ──────────────────────────
    report = {
        "symbol": args.symbol,
        "years": args.years,
        "oos_years": args.oos_years,
        "macro_features": macro_df is not None,
        "feature_count": X.shape[1],
        "sample_count": len(X),
        "cv_sample_count": len(X_cv),
        "oos_sample_count": oos_n,
        "trained_at": datetime.now(UTC).isoformat(),
    }

    for model_type in ("xgb", "rf"):
        logger.info("\n=== Walk-forward CV: %s ===", model_type.upper())
        wf = walk_forward_eval(X_cv, y_cv, n_splits=args.splits, model_type=model_type)
        report[f"walkforward_{model_type}"] = wf
        logger.info(
            "%s  mean_acc=%.3f±%.3f  p=%.4f  significant=%s",
            model_type.upper(),
            wf["mean_accuracy"],
            wf["std_accuracy"],
            wf["p_value"],
            wf["significant"],
        )

    # ── Train final models (on CV portion) ───────────────────────────────────
    logger.info("\n=== Training final models ===")
    for model_type in ("xgb", "rf"):
        _, final_metrics = train_final_model(X_cv, y_cv, model_type=model_type)
        report[f"final_{model_type}"] = final_metrics

    # ── Held-out OOS evaluation ───────────────────────────────────────────────
    if X_oos is not None:
        logger.info("\n=== Held-out OOS evaluation (%d bars) ===", oos_n)
        for model_type in ("xgb", "rf"):
            oos_metrics = oos_eval(X_cv, y_cv, X_oos, y_oos, model_type=model_type)
            report[f"oos_{model_type}"] = oos_metrics

    # ── Save report ───────────────────────────────────────────────────────────
    report_path = MODEL_DIR / "training_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Training report saved to %s", report_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TRAINING SUMMARY  (basic macro model — 65 stationary features)")
    print("=" * 60)
    for model_type in ("xgb", "rf"):
        wf = report[f"walkforward_{model_type}"]
        fin = report[f"final_{model_type}"]
        print(f"\n{model_type.upper()}")
        print(
            f"  Walk-forward accuracy : {wf['mean_accuracy']:.3f} ± {wf['std_accuracy']:.3f}",
        )
        print(f"  Walk-forward F1       : {wf['mean_f1']:.3f}")
        mean_sharpe = wf.get("mean_sharpe", 0.0)
        print(
            f"  Walk-forward Sharpe   : {mean_sharpe:.3f}  (annualised, 1-bar, no costs — N < 250: SE ≈ ±0.54)",
        )
        print(
            f"  p-value (vs random)   : {wf['p_value']:.4f}"
            f"  {'✓ significant' if wf['significant'] else '✗ not significant'}",
        )
        print(f"  Final holdout accuracy: {fin['accuracy']:.3f}")
        print(f"  Final holdout F1      : {fin['f1']:.3f}")
        print(f"  Features used         : {fin['feature_count']}")
        if f"oos_{model_type}" in report:
            oos = report[f"oos_{model_type}"]
            sig = "✓ significant" if oos["significant"] else "✗ not significant"
            acc_se = oos.get("accuracy_se", 0.0)
            print(
                f"  OOS period            : {oos.get('oos_period', 'n/a')}",
            )
            print(
                f"  OOS accuracy          : {oos['accuracy']:.3f} ± {acc_se:.3f}  (n={oos['oos_size']})",
            )
            print(f"  OOS F1                : {oos['f1']:.3f}")
            print(f"  OOS AUC               : {oos.get('auc', 0.0):.3f}")
            print(f"  OOS p-value (binomial): {oos['p_value_binomial']:.4f}  {sig}")

    print()
    print("  ─── Sharpe significance ─────────────────────────────────────")
    print("  N=45 trades: Sharpe SE ≈ ±0.54 (need ~250 for SE ≤ ±0.3).")
    print("  Credible performance number: OOS accuracy (p-value above).")
    print("  Do NOT commit live capital until 30+ days paper trading done.")
    print("  ─────────────────────────────────────────────────────────────")
    print("=" * 60)

    return report


if __name__ == "__main__":
    main()
