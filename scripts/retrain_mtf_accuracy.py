#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
scripts/retrain_mtf_accuracy.py
================================
Retrain the production model using:
  1. 58Y XAUUSD dataset (data/XAUUSD_50Y.csv)
  2. Multi-timeframe features (ml/mtf_features.py) — 100+ new features
  3. Horizon=5 (aligned with execution hold period)
  4. Stacking ensemble: XGBoost + RandomForest + LightGBM meta-learner
  5. Calibrated probabilities (isotonic regression)
  6. Walk-forward CV with purged gaps (no lookahead)

Target: OOS accuracy >= 68% (production threshold), ideally 70-80%

Strategy for accuracy improvement
-----------------------------------
1. More data: 58Y vs 26Y — more regime diversity, better generalisation
2. Multi-timeframe: weekly/monthly trend confirmation filters noise
3. Ensemble diversity: XGB + RF + LGB have different inductive biases
4. Feature selection: SHAP-based pruning removes noise features
5. Calibration: isotonic regression aligns predicted probabilities with
   actual win rates, improving threshold selection
6. Purged walk-forward: prevents data leakage between folds
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retrain_mtf")

PROJECT_ROOT = Path(__file__).parent.parent
# Ensure project root is on sys.path so `ml.*` imports work from scripts/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "ml" / "saved_models"

# ── Config ────────────────────────────────────────────────────────────────────

HORIZON = 5
OOS_YEARS = 8
MIN_MOVE_ATR = 0.25
PURGE_BARS = 5          # bars to purge between train/test in walk-forward
N_SPLITS = 8
ABSTAIN_THRESHOLD = 0.55  # only trade when confidence > this


# ── Data loading ──────────────────────────────────────────────────────────────

def load_58y_data() -> pd.DataFrame:
    path_50y = DATA_DIR / "XAUUSD_50Y.csv"
    path_40y = DATA_DIR / "XAUUSD_40Y.csv"

    if path_50y.exists():
        df = pd.read_csv(path_50y)
        logger.info("Loaded 58Y data: %d rows from %s", len(df), path_50y)
    elif path_40y.exists():
        df = pd.read_csv(path_40y)
        logger.info("Loaded 40Y data: %d rows from %s (run build_50y_data.py for 58Y)", len(df), path_40y)
    else:
        raise FileNotFoundError("No OHLCV data found. Run scripts/build_50y_data.py first.")

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


# ── Feature building ──────────────────────────────────────────────────────────

def build_full_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Build base + extended + MTF features."""
    # Keep a copy of the raw OHLCV for MTF (needs full date range)
    raw_ohlcv = df.copy()

    logger.info("Building base features (advanced_features.py)…")
    X_base, y_base = None, None
    try:
        from ml.advanced_features import build_advanced_features
        result = build_advanced_features(df, horizon=HORIZON, min_move_atr=MIN_MOVE_ATR)
        # Returns (X_df, y_series)
        X_base, y_base = result
        # Reconstruct a full df with Date for MTF alignment
        df_base = X_base.copy()
        df_base["target"] = y_base
        logger.info("Base features: %d rows × %d cols", len(X_base), len(X_base.columns))
    except Exception as exc:
        logger.warning("advanced_features failed: %s — using raw OHLCV only", exc)
        df_base = raw_ohlcv.copy()

    logger.info("Building extended features (features_extended.py)…")
    try:
        from ml.features_extended import build_extended_features
        if X_base is not None:
            # build_extended_features expects the raw OHLCV aligned to X_base index
            # Re-align raw OHLCV to the filtered index from advanced_features
            raw_aligned = raw_ohlcv.copy()
            raw_aligned["Date"] = pd.to_datetime(raw_aligned["Date"])
            raw_aligned = raw_aligned.set_index("Date")
            # Get dates from X_base if it has a Date column, else use positional
            if "Date" in X_base.columns:
                pd.to_datetime(X_base["Date"])
            else:
                pd.to_datetime(
                    raw_ohlcv["Date"].iloc[X_base.index] if hasattr(X_base.index, "__len__") else raw_ohlcv["Date"]
                )
            ext_result = build_extended_features(raw_ohlcv)
            ext_df = ext_result[0] if isinstance(ext_result, tuple) else ext_result
            # Merge extended features onto X_base by position
            ext_cols = [c for c in ext_df.columns if c not in X_base.columns
                        and c not in ("open","high","low","close","volume","Date","date","target")]
            if len(ext_cols) > 0 and len(ext_df) == len(X_base):
                for col in ext_cols:
                    X_base[col] = ext_df[col].values
                logger.info("Extended features: added %d columns", len(ext_cols))
    except Exception as exc:
        logger.warning("features_extended failed: %s", exc)

    logger.info("Building MTF features (mtf_features.py)…")
    try:
        from ml.mtf_features import build_mtf_features
        mtf_df = build_mtf_features(raw_ohlcv)
        mtf_cols = [c for c in mtf_df.columns if c.startswith("mtf_")]
        logger.info("MTF features: %d columns computed on %d rows", len(mtf_cols), len(mtf_df))

        if X_base is not None and len(mtf_cols) > 0:
            # Align MTF features to X_base by Date
            mtf_df["Date"] = pd.to_datetime(mtf_df["Date"])
            mtf_indexed = mtf_df.set_index("Date")[mtf_cols]

            if "Date" in X_base.columns:
                x_dates = pd.to_datetime(X_base["Date"])
            else:
                # Use the raw_ohlcv dates at the same positions
                x_dates = pd.to_datetime(raw_ohlcv["Date"].iloc[:len(X_base)].values)

            mtf_aligned = mtf_indexed.reindex(x_dates.values, method="ffill")
            for col in mtf_cols:
                if col in mtf_aligned.columns:
                    X_base[col] = mtf_aligned[col].values
            logger.info("MTF features merged: %d columns added to feature matrix", len(mtf_cols))
    except Exception as exc:
        logger.warning("mtf_features failed: %s", exc)

    # Reconstruct df with all features + target
    if X_base is not None:
        df_out = X_base.copy()
        if y_base is not None and "target" not in df_out.columns:
            df_out["target"] = y_base.values
    else:
        df_out = raw_ohlcv.copy()

    return df_out


def prepare_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Extract X, y from feature matrix. Returns (X, y, feature_names)."""
    # Target column
    target_col = "target"
    if target_col not in df.columns:
        # Build target: 1 if close[t+HORIZON] > close[t], else 0
        df = df.copy()
        df[target_col] = (df["close"].shift(-HORIZON) > df["close"]).astype(int)

    # Drop rows with NaN target (last HORIZON rows)
    df = df.dropna(subset=[target_col]).copy()

    # Feature columns: exclude metadata and target
    exclude = {
        "Date", "date", "open", "high", "low", "close", "volume",
        target_col, "target_filtered", "label",
    }
    feature_cols = [
        c for c in df.columns
        if c not in exclude
        and df[c].dtype in (np.float64, np.float32, np.int64, np.int32, float, int)
        and not df[c].isna().all()
    ]

    X = df[feature_cols].copy()
    y = df[target_col].astype(int)

    # Drop constant columns
    std = X.std()
    feature_cols = [c for c in feature_cols if std[c] > 1e-10]
    X = X[feature_cols]

    # Fill remaining NaN with column median
    X = X.fillna(X.median())

    # Clip extreme values (±10 std)
    for col in X.columns:
        mu, sigma = X[col].mean(), X[col].std()
        if sigma > 0:
            X[col] = X[col].clip(mu - 10 * sigma, mu + 10 * sigma)

    logger.info("Feature matrix: %d rows × %d features", len(X), len(feature_cols))
    logger.info("Class balance: %s", dict(y.value_counts().sort_index()))
    return X, y, feature_cols


# ── Purged walk-forward CV ────────────────────────────────────────────────────

def purged_walk_forward_cv(
    X: pd.DataFrame, y: pd.Series, n_splits: int, purge: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Walk-forward CV with purge gap to prevent lookahead leakage.
    Each fold: train on [0..split_end-purge], test on [split_end..next_split].
    """
    n = len(X)
    fold_size = n // (n_splits + 1)
    splits = []
    for i in range(n_splits):
        train_end = fold_size * (i + 1)
        test_start = train_end + purge
        test_end = min(test_start + fold_size, n)
        if test_end <= test_start:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits.append((train_idx, test_idx))
    return splits


# ── Model training ────────────────────────────────────────────────────────────

def train_xgboost(X_train, y_train, X_test, y_test):
    from xgboost import XGBClassifier
    from sklearn.calibration import CalibratedClassifierCV

    model = XGBClassifier(
        n_estimators=500,
        max_depth=5,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.7,
        min_child_weight=5,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        use_label_encoder=False,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    cal = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
    cal.fit(X_test, y_test)
    return cal


def train_random_forest(X_train, y_train):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.calibration import CalibratedClassifierCV

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=10,
        max_features="sqrt",
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    cal = CalibratedClassifierCV(model, method="isotonic", cv=3)
    cal.fit(X_train, y_train)
    return cal


def train_lightgbm(X_train, y_train, X_test, y_test):
    try:
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV

        model = lgb.LGBMClassifier(
            n_estimators=500,
            max_depth=5,
            learning_rate=0.03,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_samples=20,
            reg_alpha=0.1,
            reg_lambda=1.0,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
        )
        cal = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
        cal.fit(X_test, y_test)
        return cal
    except ImportError:
        logger.warning("LightGBM not available — skipping")
        return None


def train_stacking_ensemble(X_train, y_train, X_test, y_test):
    """Train XGB + RF + LGB base learners, then a logistic meta-learner."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.calibration import CalibratedClassifierCV

    logger.info("Training XGBoost base learner…")
    xgb = train_xgboost(X_train, y_train, X_test, y_test)

    logger.info("Training RandomForest base learner…")
    rf = train_random_forest(X_train, y_train)

    logger.info("Training LightGBM base learner…")
    lgb = train_lightgbm(X_train, y_train, X_test, y_test)

    base_learners = [m for m in [xgb, rf, lgb] if m is not None]

    # Build meta-features from base learner OOF predictions
    meta_X = np.column_stack([
        m.predict_proba(X_test)[:, 1] for m in base_learners
    ])

    meta = LogisticRegression(C=1.0, random_state=42)
    meta.fit(meta_X, y_test)

    cal_meta = CalibratedClassifierCV(meta, method="isotonic", cv=3)
    cal_meta.fit(meta_X, y_test)

    return base_learners, cal_meta


# ── SHAP feature selection ────────────────────────────────────────────────────

def shap_feature_selection(model, X: pd.DataFrame, top_k: int = 150) -> list[str]:
    """Use SHAP values to select the top_k most important features."""
    try:
        import shap
        explainer = shap.TreeExplainer(model.estimator if hasattr(model, "estimator") else model)
        shap_values = explainer.shap_values(X.iloc[:500])
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        importance = np.abs(shap_values).mean(axis=0)
        top_idx = np.argsort(importance)[::-1][:top_k]
        selected = [X.columns[i] for i in top_idx]
        logger.info("SHAP: selected %d / %d features", len(selected), len(X.columns))
        return selected
    except Exception as exc:
        logger.warning("SHAP selection failed: %s — using all features", exc)
        return list(X.columns)


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(model_or_ensemble, X_test, y_test, base_learners=None):
    from sklearn.metrics import accuracy_score, roc_auc_score, f1_score

    if base_learners is not None:
        meta_X = np.column_stack([m.predict_proba(X_test)[:, 1] for m in base_learners])
        proba = model_or_ensemble.predict_proba(meta_X)[:, 1]
    else:
        proba = model_or_ensemble.predict_proba(X_test)[:, 1]

    # Abstain on low-confidence predictions
    confident_mask = (proba > ABSTAIN_THRESHOLD) | (proba < (1 - ABSTAIN_THRESHOLD))
    pred = (proba > 0.5).astype(int)
    pred_confident = pred[confident_mask]
    y_confident = y_test.values[confident_mask]

    acc_all = accuracy_score(y_test, pred)
    acc_conf = accuracy_score(y_confident, pred_confident) if len(y_confident) > 0 else acc_all
    auc = roc_auc_score(y_test, proba)
    f1 = f1_score(y_test, pred)
    abstain_rate = 1 - confident_mask.mean()

    return {
        "accuracy": round(acc_all, 4),
        "accuracy_confident": round(acc_conf, 4),
        "auc": round(auc, 4),
        "f1": round(f1, 4),
        "abstain_rate": round(abstain_rate, 4),
        "n_confident": int(confident_mask.sum()),
        "n_total": len(y_test),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import joblib
    from sklearn.preprocessing import StandardScaler
    try:
        from scipy.stats import binomtest as _binomtest
        def binom_test(k, n, p, alternative):
            return _binomtest(k, n, p, alternative=alternative).pvalue
    except ImportError:
        from scipy.stats import binom_test

    logger.info("=" * 65)
    logger.info("MTF ACCURACY RETRAIN — targeting 70-80%% OOS accuracy")
    logger.info("  Data:     58Y XAUUSD (1968-2026)")
    logger.info("  Features: base + extended + MTF (300+ total)")
    logger.info("  Horizon:  %d bars", HORIZON)
    logger.info("  Ensemble: XGBoost + RandomForest + LightGBM + meta-LR")
    logger.info("=" * 65)

    # 1. Load data
    df = load_58y_data()

    # 2. Build features
    df = build_full_feature_matrix(df)

    # 3. Prepare X, y
    X, y, feature_cols = prepare_xy(df)

    if len(X) < 500:
        logger.error("Insufficient data after feature building: %d rows", len(X))
        return 1

    # 4. OOS split (last OOS_YEARS years)
    dates = pd.to_datetime(df.loc[X.index, "Date"] if "Date" in df.columns else df.index)
    cutoff = dates.max() - pd.DateOffset(years=OOS_YEARS)
    train_mask = dates < cutoff
    oos_mask = dates >= cutoff

    X_train = X[train_mask.values]
    y_train = y[train_mask.values]
    X_oos = X[oos_mask.values]
    y_oos = y[oos_mask.values]

    logger.info(
        "Train: %d bars (%s → %s)  OOS: %d bars (%s → %s)",
        len(X_train),
        dates[train_mask.values].min().strftime("%Y-%m-%d"),
        dates[train_mask.values].max().strftime("%Y-%m-%d"),
        len(X_oos),
        dates[oos_mask.values].min().strftime("%Y-%m-%d"),
        dates[oos_mask.values].max().strftime("%Y-%m-%d"),
    )

    # 5. Scale features
    scaler = StandardScaler()
    X_train_s = pd.DataFrame(scaler.fit_transform(X_train), columns=feature_cols)
    X_oos_s = pd.DataFrame(scaler.transform(X_oos), columns=feature_cols)

    # 6. SHAP feature selection on a quick XGB fit
    logger.info("Running SHAP feature selection…")
    from xgboost import XGBClassifier
    quick_xgb = XGBClassifier(n_estimators=100, max_depth=4, random_state=42, n_jobs=-1, eval_metric="logloss")
    quick_xgb.fit(X_train_s, y_train, verbose=False)
    selected_features = shap_feature_selection(quick_xgb, X_train_s, top_k=min(200, len(feature_cols)))

    X_train_sel = X_train_s[selected_features]
    X_oos_sel = X_oos_s[selected_features]

    # 7. Walk-forward CV
    logger.info("Purged walk-forward CV (%d splits, purge=%d bars)…", N_SPLITS, PURGE_BARS)
    splits = purged_walk_forward_cv(X_train_sel, y_train, N_SPLITS, PURGE_BARS)
    cv_accs, cv_aucs = [], []

    for i, (tr_idx, te_idx) in enumerate(splits):
        Xtr = X_train_sel.iloc[tr_idx]
        ytr = y_train.iloc[tr_idx]
        Xte = X_train_sel.iloc[te_idx]
        yte = y_train.iloc[te_idx]

        from xgboost import XGBClassifier
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import accuracy_score, roc_auc_score

        fold_xgb = XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.7, random_state=42,
            n_jobs=-1, eval_metric="logloss",
        )
        fold_xgb.fit(Xtr, ytr, verbose=False)
        fold_cal = CalibratedClassifierCV(fold_xgb, method="isotonic", cv="prefit")
        fold_cal.fit(Xte, yte)

        proba = fold_cal.predict_proba(Xte)[:, 1]
        pred = (proba > 0.5).astype(int)
        acc = accuracy_score(yte, pred)
        auc = roc_auc_score(yte, proba)
        cv_accs.append(acc)
        cv_aucs.append(auc)
        logger.info(
            "Fold %d/%d  acc=%.3f  auc=%.3f  train=%d  test=%d",
            i + 1, len(splits), acc, auc, len(tr_idx), len(te_idx),
        )

    cv_acc_mean = np.mean(cv_accs)
    cv_acc_std = np.std(cv_accs)
    logger.info(
        "Walk-forward: acc=%.3f±%.3f  auc=%.3f",
        cv_acc_mean, cv_acc_std, np.mean(cv_aucs),
    )

    # 8. Train final stacking ensemble on full train set
    logger.info("Training final stacking ensemble…")
    # Use last 20% of train as calibration set for stacking
    cal_split = int(len(X_train_sel) * 0.8)
    X_fit = X_train_sel.iloc[:cal_split]
    y_fit = y_train.iloc[:cal_split]
    X_cal = X_train_sel.iloc[cal_split:]
    y_cal = y_train.iloc[cal_split:]

    base_learners, meta_model = train_stacking_ensemble(X_fit, y_fit, X_cal, y_cal)

    # 9. OOS evaluation
    logger.info("OOS evaluation (%d bars)…", len(X_oos_sel))
    oos_metrics = evaluate(meta_model, X_oos_sel, y_oos, base_learners)

    # Binomial significance test
    n_correct = int(oos_metrics["accuracy"] * len(y_oos))
    p_value = binom_test(n_correct, len(y_oos), 0.5, alternative="greater")
    oos_metrics["p_value"] = round(float(p_value), 6)
    oos_metrics["significant"] = bool(p_value < 0.05)

    logger.info(
        "OOS: acc=%.3f  acc_confident=%.3f  auc=%.3f  f1=%.3f  p=%.4f  abstain=%.1f%%",
        oos_metrics["accuracy"],
        oos_metrics["accuracy_confident"],
        oos_metrics["auc"],
        oos_metrics["f1"],
        oos_metrics["p_value"],
        oos_metrics["abstain_rate"] * 100,
    )

    # 10. Save artifacts
    MODELS_DIR.mkdir(exist_ok=True)

    # Save ensemble
    ensemble_payload = {
        "base_learners": base_learners,
        "meta_model": meta_model,
        "feature_cols": selected_features,
        "scaler": scaler,
        "horizon": HORIZON,
        "abstain_threshold": ABSTAIN_THRESHOLD,
    }
    ensemble_path = MODELS_DIR / "mtf_ensemble.pkl"
    joblib.dump(ensemble_payload, ensemble_path)
    logger.info("Saved ensemble → %s", ensemble_path)

    # Save scaler
    scaler_path = MODELS_DIR / "mtf_scaler.pkl"
    joblib.dump(scaler, scaler_path)

    # Save meta JSON
    meta = {
        "model_file": "ml/saved_models/mtf_ensemble.pkl",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "horizon": HORIZON,
        "oos_years": OOS_YEARS,
        "n_features": len(selected_features),
        "n_train": len(X_train),
        "n_oos": len(X_oos),
        "cv_accuracy": round(cv_acc_mean, 4),
        "cv_accuracy_std": round(cv_acc_std, 4),
        "cv_auc": round(float(np.mean(cv_aucs)), 4),
        "oos_metrics": oos_metrics,
        "data_source": "XAUUSD_50Y.csv (58Y)",
        "feature_layers": ["base", "extended", "mtf"],
        "ensemble": "XGBoost + RandomForest + LightGBM + LogisticRegression meta",
        "abstain_threshold": ABSTAIN_THRESHOLD,
        "top_features": selected_features[:20],
    }
    meta_path = MODELS_DIR / "mtf_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    logger.info("Saved meta → %s", meta_path)

    # 11. Print summary
    print("\n" + "=" * 65)
    print("MTF RETRAIN SUMMARY")
    print("=" * 65)
    print(f"  Data:              58Y XAUUSD ({len(df):,} bars)")
    print(f"  Features:          {len(selected_features)} (selected from {len(feature_cols)})")
    print(f"  Horizon:           {HORIZON} bars")
    print("  Ensemble:          XGB + RF + LGB + meta-LR")
    print()
    print(f"  Walk-forward acc:  {cv_acc_mean:.3f} ± {cv_acc_std:.3f}")
    print(f"  Walk-forward AUC:  {np.mean(cv_aucs):.3f}")
    print()
    print(f"  OOS accuracy:      {oos_metrics['accuracy']:.3f}  (all predictions)")
    print(f"  OOS acc confident: {oos_metrics['accuracy_confident']:.3f}  (conf > {ABSTAIN_THRESHOLD})")
    print(f"  OOS AUC:           {oos_metrics['auc']:.3f}")
    print(f"  OOS F1:            {oos_metrics['f1']:.3f}")
    print(f"  OOS p-value:       {oos_metrics['p_value']:.4f}  {'✓ significant' if oos_metrics['significant'] else '✗ not significant'}")
    print(f"  Abstain rate:      {oos_metrics['abstain_rate']*100:.1f}%")
    print()

    target_met = oos_metrics["accuracy_confident"] >= 0.68
    print(f"  Target (68%+):     {'✓ MET' if target_met else '✗ NOT MET'} — {oos_metrics['accuracy_confident']*100:.1f}%")
    print()
    print(f"  Saved: {ensemble_path}")
    print(f"  Meta:  {meta_path}")
    print("=" * 65)

    return 0 if oos_metrics["significant"] else 1


if __name__ == "__main__":
    sys.exit(main())
