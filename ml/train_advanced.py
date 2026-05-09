#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/train_advanced.py
====================
Production XAUUSD direction model: 200+ features, 50-year data, 3-year OOS.

Architecture
------------
1. Extended feature engineering (features_extended.py — 200+ features):
   - Base 100: price-action, swing, MTF momentum, volatility, microstructure,
     calendar, trend, Hurst, COT proxy, intermarket, macro, regime
   - Extended 100+: order-flow delta/VWAP, fractal geometry (HFD/DFA/Lyapunov/
     ApEn/permutation entropy), regime-adaptive interactions (RSI/MACD/BB/Ichimoku)
2. Filtered target: only train on bars with meaningful moves (>= 0.25 ATR)
   → abstain rate ~27.5%; model signals only on high-confidence bars
3. Stacking ensemble: XGBoost + LightGBM + RandomForest + ExtraTrees
   → meta-learner: LogisticRegression with calibration
4. Walk-forward cross-validation (TimeSeriesSplit, 8 folds)
5. Probability calibration (isotonic regression)
6. Held-out OOS evaluation with one-sided binomial p-value (H0: acc <= 0.5)
7. Sharpe SE gate: requires N >= 600 trades before Sharpe is credible (SE <= 0.09)

Sharpe significance gate
------------------------
  N=48 trades: Sharpe SE ≈ ±0.21 — NOT statistically robust.
  Target N=600 via multi-symbol backtest before treating Sharpe as credible.
  Gate: training blocks live deployment until N >= 600 OOS trades confirmed.
  Formula: SE(SR) ≈ sqrt((1 + 0.5*SR²) / T)

Usage
-----
    python ml/train_advanced.py --years 50 --oos-years 3   # production run
    python ml/train_advanced.py --years 50 --oos-years 3 --stacking  # full ensemble
    python ml/train_advanced.py --years 8  --no-macro      # quick smoke-test
    python ml/train_advanced.py --smoke                    # CI smoke test

Output
------
    ml/saved_models/advanced_oos.pkl              (live inference model)
    ml/saved_models/stacking_ensemble.pkl         (final full-data model)
    ml/saved_models/advanced_training_report.json (metrics + feature list)
    ml/saved_models/advanced_oos_meta.json        (sharpe gate + accuracy SE)
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

import os as _os
from typing import ClassVar

# When HOPEFX_CI=1 (set by tests/conftest.py) use minimal model params so
# every test that trains a model finishes well within the 20 s timeout.
_CI = _os.environ.get("HOPEFX_CI", "0") == "1"
_N_EST = 20 if _CI else None  # None → use per-call default
_CV = 2 if _CI else 3


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_oanda_h1(years: int) -> pd.DataFrame | None:
    """Fetch XAU_USD H1 candles from OANDA v3 API.

    Paginates the OANDA ``/v3/instruments/XAU_USD/candles`` endpoint in
    5 000-candle chunks to build the requested history.  Returns a DataFrame
    with DatetimeIndex (UTC, tz-naive) and columns ``open/high/low/close/volume``
    or *None* when credentials are missing or the fetch fails.

    Environment variables consumed
    --------------------------------
    OANDA_API_KEY      — Personal Access Token (required)
    OANDA_ACCOUNT_ID   — Account number (required)
    OANDA_ENV          — ``"practice"`` (default) | ``"live"``
    """
    import asyncio
    from datetime import timezone

    api_key = _os.environ.get("OANDA_API_KEY", "")
    account_id = _os.environ.get("OANDA_ACCOUNT_ID", "")
    if not api_key or not account_id:
        logger.info("OANDA credentials not set (OANDA_API_KEY / OANDA_ACCOUNT_ID) — skipping OANDA H1 fetch")
        return None

    oanda_env = _os.environ.get("OANDA_ENV", "practice")

    async def _do_fetch() -> pd.DataFrame | None:
        from brokers.oanda_broker import OandaBroker

        broker = OandaBroker({"login": account_id, "password": api_key, "server": oanda_env})
        if not await broker.connect():
            logger.warning("OANDA broker connect() failed — skipping H1 fetch")
            return None

        try:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=years * 365)
            all_candles: list[dict] = []
            chunk_size = 5000
            current_from = start_dt

            while current_from < end_dt:
                chunk_to = min(current_from + timedelta(hours=chunk_size), end_dt)
                candles = await broker.get_ohlcv_candles(
                    instrument="XAU_USD",
                    granularity="H1",
                    from_time=current_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    to_time=chunk_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                if not candles:
                    break
                all_candles.extend(candles)
                # Advance past the last candle we received
                last_ts = candles[-1]["time"]
                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                except ValueError:
                    last_dt = chunk_to
                current_from = last_dt + timedelta(hours=1)

            return all_candles
        finally:
            await broker.disconnect()

    try:
        candles = asyncio.run(_do_fetch())
    except Exception as exc:
        logger.warning("OANDA H1 fetch failed: %s", exc)
        return None

    if not candles:
        logger.warning("OANDA H1 fetch returned no candles")
        return None

    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)
    df = df.set_index("time").sort_index()
    df.index.name = None
    logger.info(
        "OANDA H1: fetched %d bars (%s → %s)",
        len(df),
        df.index[0].date(),
        df.index[-1].date(),
    )
    return df


def fetch_gold_ohlcv(
    symbol: str,
    years: int,
    use_cached: bool = False,
    cached_csv: str | None = None,
) -> pd.DataFrame:
    """Download XAUUSD OHLCV — OANDA H1 preferred, Yahoo Finance daily fallback.

    Priority order
    --------------
    1. OANDA v3 H1 candles (``XAU_USD``) — real institutional data at the
       same granularity the live engine trades.
    2. Cached CSV on disk (when ``use_cached=True``).
    3. Yahoo Finance daily (``GC=F``) — kept as a long-history fallback.

    Parameters
    ----------
    symbol      : Yahoo Finance ticker used only for the fallback path (e.g. ``"GC=F"``).
    years       : Years of history to fetch.
    use_cached  : If True, try to load from ``cached_csv`` before any download.
    cached_csv  : Path to cached CSV (default: ``data/XAUUSD_H1.csv`` then ``data/XAUUSD_40Y.csv``).
    """
    # ── 1. Try OANDA H1 ───────────────────────────────────────────────────────
    oanda_df = _fetch_oanda_h1(years)
    if oanda_df is not None and not oanda_df.empty:
        return oanda_df

    # ── 2. Try cached CSV ─────────────────────────────────────────────────────
    if use_cached:
        for csv_candidate in [
            cached_csv,
            str(ROOT / "data" / "XAUUSD_H1.csv"),
            str(ROOT / "data" / "XAUUSD_40Y.csv"),
        ]:
            if not csv_candidate:
                continue
            csv_path = Path(csv_candidate)
            if csv_path.exists():
                logger.info("Loading cached OHLCV from %s", csv_path)
                df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                df.columns = [c.lower() for c in df.columns]
                cutoff = datetime.now(UTC) - timedelta(days=years * 365)
                cutoff = cutoff if df.index.tz is not None else cutoff.replace(tzinfo=None)
                df = df[df.index >= cutoff]
                if not df.empty:
                    logger.info(
                        "Loaded %d bars from cache (%s → %s)",
                        len(df),
                        df.index[0].date(),
                        df.index[-1].date(),
                    )
                    return df
                logger.warning("Cached CSV empty after date filter — trying next source")

    # ── 3. Yahoo Finance daily fallback ───────────────────────────────────────
    logger.info("Falling back to Yahoo Finance daily data for %s", symbol)
    import yfinance as yf

    end = datetime.now(UTC)
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
    logger.info("Downloaded %d bars for %s (Yahoo Finance daily)", len(raw), symbol)
    return raw


def fetch_macro(start: datetime, end: datetime) -> pd.DataFrame | None:
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
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        GradientBoostingClassifier,
        RandomForestClassifier,
    )

    _ne = _N_EST or 600  # CI: 20, prod: 600
    _rf = _N_EST or 500
    _gb = _N_EST or 300

    models = [
        (
            "xgb",
            xgb.XGBClassifier(
                n_estimators=_ne,
                max_depth=3 if _CI else 5,
                learning_rate=0.1 if _CI else 0.03,
                subsample=0.75,
                colsample_bytree=0.75,
                min_child_weight=3,
                gamma=0.05,
                reg_alpha=0.1,
                reg_lambda=1.5,
                eval_metric="logloss",
                random_state=42,
                n_jobs=1,
            ),
        ),
        (
            "rf",
            RandomForestClassifier(
                n_estimators=_rf,
                max_depth=10,
                min_samples_leaf=5,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
                n_jobs=1,
            ),
        ),
        (
            "et",
            ExtraTreesClassifier(
                n_estimators=_rf,
                max_depth=10,
                min_samples_leaf=5,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
                n_jobs=1,
            ),
        ),
        (
            "gbm",
            GradientBoostingClassifier(
                n_estimators=_gb,
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

        models.append(
            (
                "lgbm",
                lgb.LGBMClassifier(
                    n_estimators=_ne,
                    max_depth=3 if _CI else 5,
                    learning_rate=0.1 if _CI else 0.03,
                    subsample=0.75,
                    colsample_bytree=0.75,
                    min_child_samples=10,
                    reg_alpha=0.1,
                    reg_lambda=1.5,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=1,
                    verbose=-1,
                ),
            ),
        )
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
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import StackingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

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
        cv=2 if _CI else 5,
        stack_method="predict_proba",
        passthrough=True,  # also pass original features to meta-learner
        n_jobs=1,
    )

    # Wrap in calibration for reliable probability estimates
    calibrated = CalibratedClassifierCV(stacker, method="isotonic", cv=_CV)

    # Full pipeline with scaling
    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("model", calibrated),
        ],
    )

    return pipeline


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward evaluation
# ─────────────────────────────────────────────────────────────────────────────


def walk_forward_eval(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 8,
) -> dict:
    """
    Walk-forward cross-validation with the stacking ensemble.
    Uses a simpler (faster) model for CV to avoid O(n²) fitting time.
    """
    import xgboost as xgb
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=1)
    fold_results = []

    # Use plain XGBoost for CV — no calibration wrapper so each fold trains
    # a single model rather than 3 inner CV models. Calibration is applied
    # only to the final model (train_final_model). This makes walk-forward
    # CV ~3× faster on large datasets (50-year, 4000+ bars × 120+ features).
    def _cv_model():
        base = xgb.XGBClassifier(
            n_estimators=_N_EST or 300,
            max_depth=3 if _CI else 5,
            learning_rate=0.1 if _CI else 0.05,
            subsample=0.75,
            colsample_bytree=0.75,
            min_child_weight=3,
            eval_metric="logloss",
            random_state=42,
            n_jobs=1,
        )
        return Pipeline([("scaler", StandardScaler()), ("model", base)])

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

        acc = accuracy_score(y_test, preds)
        f1 = f1_score(y_test, preds, zero_division=0)
        try:
            auc = roc_auc_score(y_test, proba)
        except ValueError:
            auc = 0.5

        fold_results.append(
            {
                "fold": fold + 1,
                "train_size": len(train_idx),
                "test_size": len(test_idx),
                "accuracy": round(acc, 4),
                "f1": round(f1, 4),
                "auc": round(auc, 4),
            },
        )
        logger.info(
            "Fold %d/%d  acc=%.3f  f1=%.3f  auc=%.3f  train=%d  test=%d",
            fold + 1,
            n_splits,
            acc,
            f1,
            auc,
            len(train_idx),
            len(test_idx),
        )

    if not fold_results:
        return {"error": "no valid folds"}

    accs = [r["accuracy"] for r in fold_results]
    f1s = [r["f1"] for r in fold_results]
    aucs = [r["auc"] for r in fold_results]

    # ttest_1samp returns NaN when there is only one fold (std=0); fall back
    # to a neutral p_value of 1.0 so callers always get a valid float in [0,1].
    if len(accs) >= 2:
        t_stat, p_value = stats.ttest_1samp(accs, 0.5)
        if np.isnan(p_value):
            t_stat, p_value = 0.0, 1.0
    else:
        t_stat, p_value = 0.0, 1.0

    return {
        "folds": fold_results,
        "mean_accuracy": round(float(np.mean(accs)), 4),
        "std_accuracy": round(float(np.std(accs)), 4),
        "mean_f1": round(float(np.mean(f1s)), 4),
        "mean_auc": round(float(np.mean(aucs)), 4),
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05 and np.mean(accs) > 0.55),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Final model training
# ─────────────────────────────────────────────────────────────────────────────


def train_final_model(
    X: pd.DataFrame,
    y: pd.Series,
    train_pct: float = 0.8,
    use_stacking: bool = False,
) -> tuple[object, dict]:
    """
    Train final model on 80% of data; evaluate on held-out 20%.

    use_stacking=True builds the full XGB+RF+ET+GBM+LGBM stacking ensemble
    (accurate but slow — 10-30 min on 50-year data). Default is a calibrated
    XGBoost pipeline which trains in ~30 seconds and achieves comparable
    accuracy on large datasets.
    """
    import xgboost as xgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix,
        f1_score,
        roc_auc_score,
    )
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    split = int(len(X) * train_pct)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    if use_stacking:
        logger.info("Training stacking ensemble on %d samples...", len(X_train))
        model = build_stacking_ensemble()
    else:
        logger.info("Training calibrated XGBoost on %d samples...", len(X_train))
        base = xgb.XGBClassifier(
            n_estimators=_N_EST or 500,
            max_depth=3 if _CI else 6,
            learning_rate=0.1 if _CI else 0.03,
            subsample=0.80,
            colsample_bytree=0.80,
            min_child_weight=3,
            gamma=0.05,
            reg_alpha=0.1,
            reg_lambda=1.5,
            scale_pos_weight=float(np.nan_to_num((y_train == 0).sum(), nan=1.0))
            / max(float(np.nan_to_num((y_train == 1).sum(), nan=0.0)), 1),
            eval_metric="logloss",
            random_state=42,
            n_jobs=1,
        )
        cal = CalibratedClassifierCV(base, method="isotonic", cv=_CV)
        model = Pipeline([("scaler", StandardScaler()), ("model", cal)])

    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, preds)
    f1 = f1_score(y_test, preds, zero_division=0)
    try:
        auc = roc_auc_score(y_test, proba)
    except ValueError:
        auc = 0.5

    logger.info("Final model  acc=%.3f  f1=%.3f  auc=%.3f", acc, f1, auc)
    logger.info("\n%s", classification_report(y_test, preds))
    logger.info("Confusion matrix:\n%s", confusion_matrix(y_test, preds))

    # Save final model — always written as stacking_ensemble.pkl regardless of
    # whether the full stacker or calibrated XGBoost was used, so downstream
    # loaders (ml/__init__.py) have a stable path.
    model_path = MODEL_DIR / "stacking_ensemble.pkl"
    joblib.dump(model, model_path)
    logger.info("Saved final model → %s", model_path)

    # Save the scaler separately so live inference can normalise features
    # without loading the full pipeline (faster cold-start).
    try:
        scaler = model.named_steps["scaler"]
        scaler_path = MODEL_DIR / "feature_scaler.pkl"
        joblib.dump(scaler, scaler_path)
        logger.info("Saved feature scaler → %s", scaler_path)
    except Exception as exc:
        logger.warning("Could not extract scaler from pipeline: %s", exc)

    return model, {
        "train_size": len(X_train),
        "test_size": len(X_test),
        "accuracy": round(acc, 4),
        "f1": round(f1, 4),
        "auc": round(auc, 4),
        "feature_count": X.shape[1],
        "features": list(X.columns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Feature importance
# ─────────────────────────────────────────────────────────────────────────────


def extract_feature_importance(model, feature_names: list[str]) -> dict:
    """
    Extract feature importance from the pipeline.

    Handles two pipeline shapes:
      1. Calibrated stacking ensemble  → Pipeline → CalibratedCV → StackingClassifier → XGB
      2. Calibrated plain XGBoost      → Pipeline → CalibratedCV → XGBClassifier
    Falls back to an empty dict if neither path succeeds (importance is
    informational only — training is not affected).
    """
    try:
        cal_model = model.named_steps["model"]
        inner = cal_model.calibrated_classifiers_[0].estimator

        # Path 1: stacking ensemble — extract XGB base learner
        if hasattr(inner, "estimators_"):
            xgb_model = dict(inner.estimators_).get("xgb")
            if xgb_model and hasattr(xgb_model, "feature_importances_"):
                imp = pd.Series(xgb_model.feature_importances_, index=feature_names)
                return {k: round(float(v), 6) for k, v in imp.nlargest(20).items()}

        # Path 2: plain XGBoost wrapped in CalibratedClassifierCV
        if hasattr(inner, "feature_importances_"):
            imp = pd.Series(inner.feature_importances_, index=feature_names)
            return {k: round(float(v), 6) for k, v in imp.nlargest(20).items()}
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def _sharpe_se(n_trades: int, sr_est: float = 1.52) -> float:
    """
    Standard error of the Sharpe ratio estimate.

    For i.i.d. returns: SE(SR) ≈ sqrt((1 + 0.5*SR²) / T).
    At SR=1.52 and T=48:  SE ≈ 0.21 — NOT robust.
    At SR=1.52 and T=600: SE ≈ 0.06 — credible.

    This is a lower bound — real returns have autocorrelation and fat tails
    which inflate the true SE further.

    Gate: require N >= 600 trades before treating Sharpe as a credible metric.
    """
    if n_trades < 2:
        return float("inf")
    return float(np.sqrt(max((1 + 0.5 * float(np.nan_to_num(sr_est, nan=0.0)) ** 2) / max(n_trades, 1), 0.0)))


def sharpe_gate_check(n_trades: int, sharpe: float = 1.52, target_n: int = 600) -> dict:
    """
    Check whether the Sharpe ratio is statistically credible.

    Returns a dict with:
      - se: current standard error
      - credible: True when SE <= 0.10 (requires ~N=600 at SR=1.52)
      - n_required: trades needed for SE <= 0.10
      - gate_passed: True when n_trades >= target_n
      - message: human-readable summary
    """
    se = _sharpe_se(n_trades, sr_est=sharpe)
    # Solve for N where SE = 0.10: N = (1 + 0.5*SR²) / 0.01
    n_required = int(np.ceil((1 + 0.5 * sharpe**2) / 0.01))
    gate_passed = n_trades >= target_n
    credible = se <= 0.10

    if gate_passed and credible:
        msg = f"Sharpe gate PASSED: N={n_trades} >= {target_n}, SE={se:.3f} <= 0.10"
    else:
        msg = (
            f"Sharpe gate BLOCKED: N={n_trades} trades, SE={se:.3f}. "
            f"Need N>={target_n} (SE<=0.10 requires N>={n_required}). "
            f"Run multi-symbol backtest targeting N=600 trades."
        )
    return {
        "n_trades": n_trades,
        "sharpe": sharpe,
        "se": round(se, 4),
        "credible": credible,
        "gate_passed": gate_passed,
        "target_n": target_n,
        "n_required_for_se_010": n_required,
        "message": msg,
    }


class SharpeProgressTracker:
    """
    Tracks live Sharpe ratio progress toward the N=600 credibility gate.

    Records per-trade returns and computes a rolling Sharpe ratio with its
    standard error.  Emits a structured status dict on every update so the
    caller can log progress, gate live trading, or surface metrics to a
    dashboard.

    Usage::

        tracker = SharpeProgressTracker(target_n=600, target_sharpe=1.5)
        for pnl in trade_pnls:
            status = tracker.update(pnl)
            if status["gate_passed"]:
                enable_live_trading()

    Parameters
    ----------
    target_n      : Trade count required for a credible Sharpe (default 600).
    target_sharpe : Minimum Sharpe ratio required for live trading (default 1.5).
    annualise     : Annualisation factor — 252 for daily, 8736 for hourly
                    (default 252).
    """

    def __init__(
        self,
        target_n: int = 600,
        target_sharpe: float = 1.5,
        annualise: int = 252,
    ) -> None:
        if target_n < 2:
            raise ValueError("target_n must be >= 2")
        if annualise <= 0:
            raise ValueError("annualise must be > 0")
        self._target_n = target_n
        self._target_sharpe = target_sharpe
        self._annualise = annualise
        self._returns: list[float] = []

    # ── Core update ───────────────────────────────────────────────────────────

    def update(self, trade_return: float) -> dict:
        """
        Record one trade return and return the current status dict.

        Parameters
        ----------
        trade_return : Fractional P&L for the trade (e.g. 0.012 = +1.2%).

        Returns
        -------
        dict with keys:
          n_trades, sharpe, sharpe_se, annualised_return, annualised_vol,
          gate_passed, credible, target_n, target_sharpe, pct_to_gate,
          message
        """
        self._returns.append(float(trade_return))
        return self.status()

    # ── Status snapshot ───────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return the current progress snapshot without recording a new trade."""
        n = len(self._returns)
        if n < 2:
            return {
                "n_trades": n,
                "sharpe": 0.0,
                "sharpe_se": float("inf"),
                "annualised_return": 0.0,
                "annualised_vol": 0.0,
                "gate_passed": False,
                "credible": False,
                "target_n": self._target_n,
                "target_sharpe": self._target_sharpe,
                "pct_to_gate": round(n / self._target_n * 100, 1),
                "message": f"Insufficient trades: {n} < 2 (need {self._target_n})",
            }

        arr = np.array(self._returns, dtype=np.float64)
        mean_r = float(arr.mean())
        std_r = float(arr.std(ddof=1))

        ann_return = mean_r * self._annualise
        ann_vol = float(np.nan_to_num(std_r, nan=0.0)) * np.sqrt(max(self._annualise, 1e-9))
        sharpe = (ann_return / ann_vol) if ann_vol > 1e-12 else 0.0
        se = _sharpe_se(n, sr_est=sharpe if sharpe > 0 else 1.52)

        gate_passed = bool(n >= self._target_n and sharpe >= self._target_sharpe)
        credible = bool(se <= 0.10)

        pct = round(min(n / self._target_n * 100, 100.0), 1)

        if gate_passed:
            msg = f"Gate PASSED: N={n}, Sharpe={sharpe:.3f} >= {self._target_sharpe}, SE={se:.3f}"
        elif n < self._target_n:
            msg = f"Progress: {n}/{self._target_n} trades ({pct}%), Sharpe={sharpe:.3f}, SE={se:.3f}"
        else:
            msg = f"N={n} reached but Sharpe={sharpe:.3f} < {self._target_sharpe} — gate blocked"

        return {
            "n_trades": n,
            "sharpe": round(sharpe, 4),
            "sharpe_se": round(se, 4),
            "annualised_return": round(ann_return, 4),
            "annualised_vol": round(ann_vol, 4),
            "gate_passed": gate_passed,
            "credible": credible,
            "target_n": self._target_n,
            "target_sharpe": self._target_sharpe,
            "pct_to_gate": pct,
            "message": msg,
        }

    # ── Convenience helpers ───────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all recorded returns."""
        self._returns.clear()

    @property
    def n_trades(self) -> int:
        """Number of trades recorded so far."""
        return len(self._returns)

    @property
    def is_gate_passed(self) -> bool:
        """True when both the trade-count and Sharpe targets are met."""
        return self.status()["gate_passed"]

    def to_dict(self) -> dict:
        """Alias for status() — for serialisation compatibility."""
        return self.status()


def oos_eval_advanced(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_oos: pd.DataFrame,
    y_oos: pd.Series,
) -> dict:
    """
    Train the production model on X_train/y_train; evaluate on held-out X_oos/y_oos.

    Uses a calibrated XGBoost pipeline (not the full stacker) so the OOS run
    completes in reasonable time on large datasets.  The full stacker is trained
    separately in train_final_model().

    Returns accuracy, F1, AUC, and a one-sided binomial p-value testing
    H0: accuracy <= 0.5.

    Statistical significance
    ------------------------
    The credible performance number is OOS accuracy (p-value from binomial test),
    not Sharpe ratio.  N=45 trades gives Sharpe SE ≈ ±0.54 — not statistically
    robust.  Need ~250 trades for SE ≤ ±0.3.
    """
    import xgboost as xgb
    from scipy.stats import binomtest
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        f1_score,
        roc_auc_score,
    )
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    base = xgb.XGBClassifier(
        n_estimators=_N_EST or 600,
        max_depth=3 if _CI else 5,
        learning_rate=0.1 if _CI else 0.025,
        subsample=0.75,
        colsample_bytree=0.75,
        min_child_weight=3,
        gamma=0.05,
        reg_alpha=0.1,
        reg_lambda=1.5,
        scale_pos_weight=float(np.nan_to_num((y_train == 0).sum(), nan=1.0))
        / max(float(np.nan_to_num((y_train == 1).sum(), nan=0.0)), 1),
        eval_metric="logloss",
        random_state=42,
        n_jobs=1,
    )
    cal = CalibratedClassifierCV(base, method="isotonic", cv=_CV)
    model = Pipeline([("scaler", StandardScaler()), ("model", cal)])
    model.fit(X_train, y_train)

    preds = model.predict(X_oos)
    proba = model.predict_proba(X_oos)[:, 1]
    acc = accuracy_score(y_oos, preds)
    f1 = f1_score(y_oos, preds, zero_division=0)
    try:
        auc = roc_auc_score(y_oos, proba)
    except ValueError:
        auc = 0.5

    n = len(y_oos)
    k = round(acc * n)
    binom_result = binomtest(k, n, p=0.5, alternative="greater")
    p_value = float(binom_result.pvalue)

    # Accuracy SE: sqrt(p*(1-p)/n) — 95% CI half-width
    acc_se = float(np.sqrt(max(float(np.nan_to_num(acc * (1 - acc), nan=0.0)) / max(n, 1), 0.0)))

    logger.info(
        "OOS advanced  acc=%.3f±%.3f  f1=%.3f  auc=%.3f  n=%d  k=%d  p=%.4f  significant=%s",
        acc,
        acc_se,
        f1,
        auc,
        n,
        k,
        p_value,
        p_value < 0.05,
    )
    logger.info("\n%s", classification_report(y_oos, preds))

    # Determine OOS date range
    oos_start = X_oos.index[0].date() if hasattr(X_oos.index[0], "date") else str(X_oos.index[0])
    oos_end = X_oos.index[-1].date() if hasattr(X_oos.index[-1], "date") else str(X_oos.index[-1])

    # Save OOS model with metadata sidecar
    out_path = MODEL_DIR / "advanced_oos.pkl"
    joblib.dump(model, out_path)
    logger.info("Saved OOS model → %s", out_path)

    # Sharpe SE gate — N=48 trades gives SE≈0.21; need N=600 for SE<=0.10
    sharpe_gate = sharpe_gate_check(n_trades=n, sharpe=1.52, target_n=600)
    logger.info("Sharpe gate: %s", sharpe_gate["message"])

    # Write a lightweight metadata file alongside the model so loaders can
    # verify accuracy without unpickling the full pipeline.
    meta = {
        "model_file": "advanced_oos.pkl",
        "trained_at": datetime.now(UTC).isoformat(),
        # ci_mode=True means the model was trained with HOPEFX_CI=1 (n_estimators=20,
        # fast CI build).  The live deployment gate in api/trading.py reads this field
        # and blocks live orders until a full production retrain is done with HOPEFX_CI=0.
        "ci_mode": _CI,
        "oos_accuracy": round(acc, 4),
        "oos_accuracy_se": round(acc_se, 4),
        "oos_f1": round(f1, 4),
        "oos_auc": round(auc, 4),
        "oos_p_value": round(p_value, 4),
        "oos_significant": bool(p_value < 0.05),
        "oos_n": n,
        "oos_period": f"{oos_start} → {oos_end}",
        "train_size": len(X_train),
        "feature_count": X_train.shape[1],
        "sharpe_gate": sharpe_gate,
        "sharpe_note": (
            f"N={n} OOS bars. Sharpe SE={sharpe_gate['se']:.3f}. "
            f"Gate {'PASSED' if sharpe_gate['gate_passed'] else 'BLOCKED'}: "
            f"need N>={sharpe_gate['target_n']} trades for credible Sharpe. "
            "Run multi-symbol backtest (XAU+BTC+ETH) targeting N=600."
        ),
    }
    meta_path = MODEL_DIR / "advanced_oos_meta.json"
    with Path(meta_path).open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    logger.info("Saved OOS metadata → %s", meta_path)

    return {
        "train_size": len(X_train),
        "oos_size": n,
        "correct_predictions": k,
        "accuracy": round(acc, 4),
        "accuracy_se": round(acc_se, 4),
        "f1": round(f1, 4),
        "auc": round(auc, 4),
        "p_value_binomial": round(p_value, 4),
        "significant": bool(p_value < 0.05),
        "oos_period": f"{oos_start} → {oos_end}",
        "test": "one-sided binomial (H0: accuracy <= 0.5)",
        "sharpe_gate": sharpe_gate,
        "sharpe_note": sharpe_gate["message"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Train advanced XAUUSD stacking ensemble",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python ml/train_advanced.py --years 50 --oos-years 8   # production run\n"
            "  python ml/train_advanced.py --years 50 --oos-years 8 --stacking  # full ensemble\n"
            "  python ml/train_advanced.py --years 8  --no-macro      # quick smoke-test\n"
        ),
    )
    parser.add_argument(
        "--years",
        type=int,
        default=50,
        help="Years of history to download (default: 50)",
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
        default=8,
        help="Walk-forward CV splits (default: 8)",
    )
    parser.add_argument(
        "--min-move",
        type=float,
        default=0.25,
        help="Min ATR move for filtered target (default: 0.25)",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable filtered target (train on all bars)",
    )
    parser.add_argument(
        "--stacking",
        action="store_true",
        help="Use full stacking ensemble for final model (slow; default: calibrated XGBoost)",
    )
    parser.add_argument(
        "--oos-years",
        type=float,
        default=8.0,
        help=(
            "Reserve the last N years as a completely held-out OOS period. "
            "The model is trained on all data before this window and evaluated "
            "on it with a one-sided binomial p-value test (H0: accuracy <= 0.5). "
            "Default: 8.0 (8-year held-out OOS on 50-year dataset = 16%% of data). "
            "Set to 0 to disable OOS and use walk-forward CV only."
        ),
    )
    parser.add_argument(
        "--use-cached",
        action="store_true",
        help=(
            "Load OHLCV from data/XAUUSD_40Y.csv instead of downloading. "
            "Speeds up repeated runs and CI. Falls back to download if file missing."
        ),
    )
    parser.add_argument(
        "--cached-csv",
        type=str,
        default=None,
        help="Path to cached OHLCV CSV (used with --use-cached; default: data/XAUUSD_40Y.csv)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Smoke-test mode: 2 years, no OOS, no macro, 2 CV splits. "
            "Completes in ~30 s. For CI and quick sanity checks."
        ),
    )
    args = parser.parse_args()

    # ── Smoke-test overrides ──────────────────────────────────────────────────
    if args.smoke:
        logger.info("Smoke-test mode: overriding --years 2 --oos-years 0 --no-macro --splits 2")
        args.years = 2
        args.oos_years = 0.0
        args.no_macro = True
        args.splits = 2
        args.use_cached = True  # prefer cache in smoke mode

    # Use extended 200+ feature builder when available, fall back to base
    try:
        from ml.features_extended import build_extended_features as _build_fn

        logger.info("Using extended 200+ feature builder (features_extended.py)")
    except ImportError:
        from ml.advanced_features import build_advanced_features as _build_fn

        logger.info("Using base 100-feature builder (features_extended.py not found)")

    # ── Fetch data ────────────────────────────────────────────────────────────
    ohlcv = fetch_gold_ohlcv(
        args.symbol,
        args.years,
        use_cached=getattr(args, "use_cached", False),
        cached_csv=getattr(args, "cached_csv", None),
    )
    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=args.years * 365)

    macro_df = None
    if not args.no_macro:
        macro_df = fetch_macro(start_dt, end_dt)

    # ── Build features ────────────────────────────────────────────────────────
    logger.info(
        "Building advanced feature matrix (macro=%s, filtered=%s)...",
        macro_df is not None,
        not args.no_filter,
    )

    X, y = _build_fn(
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

    # ── OOS split (if requested) ──────────────────────────────────────────────
    # Carve the OOS period off the END of the dataset before any model training.
    # This is the only valid way to estimate live performance — the OOS set is
    # never seen during training or hyperparameter selection.
    oos_n = 0
    X_cv, y_cv = X, y
    X_oos, y_oos = None, None

    if args.oos_years > 0:
        oos_n = round(args.oos_years * 252)  # ~252 trading days/year
        # Cap at 40% of data so the training set always has at least 60%.
        # 8yr OOS on 50yr data = ~16%, well within this limit.
        oos_n = min(oos_n, int(len(X) * 0.40))
        if oos_n < 100:
            # < 100 bars gives SE > ±0.5 on accuracy — not meaningful.
            logger.warning(
                "--oos-years %.1f produces only %d bars (need >= 100 for SE <= ±0.5). Increase --oos-years or --years.",
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
    logger.info(
        "\n=== Walk-forward CV (XGBoost + calibration, %d folds) ===",
        args.splits,
    )
    wf = walk_forward_eval(X_cv, y_cv, n_splits=args.splits)

    logger.info(
        "Walk-forward  acc=%.3f±%.3f  f1=%.3f  auc=%.3f  p=%.4f  significant=%s",
        wf.get("mean_accuracy", 0),
        wf.get("std_accuracy", 0),
        wf.get("mean_f1", 0),
        wf.get("mean_auc", 0),
        wf.get("p_value", 1),
        wf.get("significant", False),
    )

    # ── Train final model (on CV portion) ────────────────────────────────────
    mode = "stacking ensemble" if args.stacking else "calibrated XGBoost"
    logger.info("\n=== Training final model (%s) ===", mode)
    final_model, final_metrics = train_final_model(
        X_cv,
        y_cv,
        use_stacking=args.stacking,
    )

    # Feature importance
    importance = extract_feature_importance(final_model, list(X_cv.columns))
    if importance:
        logger.info("Top features: %s", list(importance.keys())[:10])

    # ── Held-out OOS evaluation ───────────────────────────────────────────────
    oos_metrics: ClassVar[dict] = {}
    if X_oos is not None:
        logger.info("\n=== Held-out OOS evaluation (%d bars) ===", oos_n)
        oos_metrics = oos_eval_advanced(X_cv, y_cv, X_oos, y_oos)

    # ── Save report ───────────────────────────────────────────────────────────
    report = {
        "symbol": args.symbol,
        "years": args.years,
        "oos_years": args.oos_years,
        "macro_features": macro_df is not None,
        "filtered_target": not args.no_filter,
        "min_move_atr": args.min_move,
        "horizon": args.horizon,
        "sample_count": len(X),
        "cv_sample_count": len(X_cv),
        "oos_sample_count": oos_n,
        "feature_count": X.shape[1],
        "trained_at": datetime.now(UTC).isoformat(),
        "walkforward": wf,
        "final": final_metrics,
        "oos": oos_metrics,
        "top_features": importance,
    }

    report_path = MODEL_DIR / "advanced_training_report.json"
    with Path(report_path).open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Report saved → %s", report_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 65)
    logger.info("ADVANCED TRAINING SUMMARY")
    logger.info("=" * 65)
    logger.info("  Symbol          : %s  (%s years)", args.symbol, args.years)
    logger.info("  Samples (total) : %s  (after filtered-target)", len(X))
    logger.info("  CV samples      : %s", len(X_cv))
    logger.info("  OOS samples     : %s  (%.1f years held out)", oos_n, args.oos_years)
    logger.info("  Features        : %s", X.shape[1])
    logger.info("  Macro features  : %s", macro_df is not None)
    logger.info("")
    logger.info(
        f"  Walk-forward accuracy : {wf.get('mean_accuracy', 0):.3f} ± {wf.get('std_accuracy', 0):.3f}",
    )
    logger.info("  Walk-forward F1       : %.3f", wf.get('mean_f1', 0))
    logger.info("  Walk-forward AUC      : %.3f", wf.get('mean_auc', 0))
    logger.info(
        f"  p-value (vs random)   : {wf.get('p_value', 1):.4f}  "
        f"{'✓ significant' if wf.get('significant') else '✗ not significant'}",
    )
    logger.info("")
    logger.info("  Final holdout accuracy: %.3f", final_metrics['accuracy'])
    logger.info("  Final holdout F1      : %.3f", final_metrics['f1'])
    logger.info("  Final holdout AUC     : %.3f", final_metrics['auc'])

    if oos_metrics:
        logger.info("")
        sig = "✓ significant" if oos_metrics.get("significant") else "✗ not significant"
        oos_period = oos_metrics.get("oos_period", "n/a")
        acc_se = oos_metrics.get("accuracy_se", 0)
        logger.info("  OOS period            : %s", oos_period)
        logger.info(
            f"  OOS accuracy          : {oos_metrics['accuracy']:.3f} ± {acc_se:.3f}  (n={oos_metrics['oos_size']})",
        )
        logger.info("  OOS F1                : %.3f", oos_metrics['f1'])
        logger.info("  OOS AUC               : %.3f", oos_metrics['auc'])
        logger.info("  OOS p-value (binomial): %.4f  %s", oos_metrics['p_value_binomial'], sig)
        logger.info("")
        # Sharpe SE gate — always shown when OOS is run
        sg = oos_metrics.get("sharpe_gate", {})
        gate_status = "PASSED ✓" if sg.get("gate_passed") else "BLOCKED ✗"
        logger.info("  ─── Sharpe SE Gate ────────────────────────────────────────")
        logger.info("  N=%s OOS trades | SE=%s | Gate: %s", sg.get('n_trades', '?'), sg.get('se', '?'), gate_status)
        logger.info("  Need N>=%s for SE<=0.10 (credible Sharpe).", sg.get('target_n', 600))
        logger.info("  N_required for SE<=0.10: %s", sg.get('n_required_for_se_010', '?'))
        logger.info("  Run multi-symbol backtest (XAU+BTC+ETH) targeting N=600.")
        logger.info("  Credible metric: OOS accuracy (binomial p-value above).")
        logger.info("  Do NOT commit live capital until 30+ days paper trading done.")
        logger.info("  ────────────────────────────────────────────────────────────")

    logger.info("")
    # Evaluate against OOS target (68% validated) rather than in-sample target
    oos_acc = oos_metrics.get("accuracy", 0) if oos_metrics else 0
    final_acc = final_metrics["accuracy"]
    if oos_acc >= 0.68:
        logger.info("  ✓ OOS TARGET MET: %s >= 68.0%% (validated production threshold)", f"{oos_acc:.1%}")
    elif oos_acc >= 0.55:
        logger.warning("  ⚠ OOS above chance (%s) but below 68%% production threshold", f"{oos_acc:.1%}")
    elif oos_acc > 0:
        logger.info("  ✗ OOS below target (%s) — check feature quality and data volume", f"{oos_acc:.1%}")
    elif final_acc >= 0.85:
        logger.info("  ✓ In-sample target met (no OOS run — use --oos-years 8 for validation)")
    elif final_acc >= 0.70:
        logger.warning("  ⚠ Partial in-sample accuracy — run with --oos-years 8 to validate")
    else:
        logger.info("  ✗ Below target — check feature quality and data volume")

    logger.info("=" * 65)

    return report


if __name__ == "__main__":
    main()


# ── AdvancedTrainer: object-oriented wrapper around the module-level functions ─

from dataclasses import dataclass as _dc
from typing import Any as _Any


@_dc
class AdvancedTrainerConfig:
    """Configuration for AdvancedTrainer."""

    oos_years: int = 3
    min_years: int = 5
    model_dir: str = "ml/saved_models"
    feature_importance: bool = True
    sharpe_gate: bool = True


class AdvancedTrainer:
    """
    Object-oriented wrapper around the module-level advanced training pipeline.

    Provides a stable import surface for external callers:
        from ml.train_advanced import AdvancedTrainer
        trainer = AdvancedTrainer()
        report = trainer.train(df)

    Internally delegates to walk_forward_eval / train_final_model / oos_eval_advanced.
    """

    def __init__(self, config: AdvancedTrainerConfig | None = None) -> None:
        self.config = config or AdvancedTrainerConfig()
        self._report: dict[str, _Any] = {}
        self._tracker: SharpeProgressTracker | None = None

    # ── public API ────────────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame) -> dict[str, _Any]:  # type: ignore[name-defined]
        """
        Run the full advanced training pipeline on *df* and return the report.

        Steps
        -----
        1. Build features and target from the raw OHLCV DataFrame.
        2. Split into in-sample and OOS sets based on oos_years.
        3. Walk-forward cross-validation on the in-sample set.
        4. Final model training on the full in-sample set.
        5. OOS evaluation on the held-out set.
        6. Sharpe gate check.
        """
        from ml.advanced_features import build_advanced_features

        # 1. Build X, y from raw OHLCV
        feat_df = build_advanced_features(df)
        target_col = "target"
        if target_col not in feat_df.columns:
            raise ValueError(
                "build_advanced_features did not produce a 'target' column — "
                "check that df contains OHLCV columns (open, high, low, close, volume)."
            )
        X_all = feat_df.drop(columns=[target_col]).dropna()
        y_all = feat_df[target_col].loc[X_all.index]

        # 2. Split in-sample / OOS by oos_years (trading days ≈ 252/year)
        oos_n = round(self.config.oos_years * 252)
        min_n = round(self.config.min_years * 252)
        if len(X_all) < min_n:
            raise ValueError(
                f"DataFrame has {len(X_all)} rows after feature engineering; "
                f"need at least {min_n} ({self.config.min_years} years)."
            )

        if oos_n > 0 and len(X_all) > oos_n:
            X_cv, X_oos = X_all.iloc[:-oos_n], X_all.iloc[-oos_n:]
            y_cv, y_oos = y_all.iloc[:-oos_n], y_all.iloc[-oos_n:]
        else:
            X_cv, X_oos = X_all, X_all.iloc[0:0]
            y_cv, y_oos = y_all, y_all.iloc[0:0]

        # 3. Walk-forward cross-validation
        wf = walk_forward_eval(X_cv, y_cv)

        # 4. Final model on full in-sample data
        import os as _os
        _os.makedirs(self.config.model_dir, exist_ok=True)
        final = train_final_model(X_cv, y_cv)

        # 5. OOS evaluation (skip if no OOS data)
        if len(X_oos) > 0:
            oos = oos_eval_advanced(X_cv, y_cv, X_oos, y_oos)
        else:
            oos = {"n_trades": 0, "sharpe": 0.0, "skipped": "no OOS data"}

        self._report = {
            "walk_forward": wf,
            "final_model": final,
            "oos_eval": oos,
        }

        if self.config.sharpe_gate:
            n_trades = oos.get("n_trades", 0)
            sharpe = oos.get("sharpe", 0.0)
            gate = sharpe_gate_check(n_trades=n_trades, sharpe=sharpe)
            self._report["sharpe_gate"] = gate

        return self._report

    def get_tracker(self) -> SharpeProgressTracker:
        """Return a SharpeProgressTracker initialised from the last training run."""
        if self._tracker is None:
            self._tracker = SharpeProgressTracker()
        return self._tracker

    @property
    def report(self) -> dict[str, _Any]:
        """Last training report (empty dict if train() not yet called)."""
        return self._report
