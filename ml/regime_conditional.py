# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/regime_conditional.py
========================
Regime-conditional training for XAUUSD direction models.

Motivation
----------
The 2022-2026 gold bull market was driven by central bank buying and
geopolitical risk — factors not in the basic feature set.  A single global
model trained on 50 years of mixed regimes learns the historical
macro-gold relationship (high yields/strong DXY = bearish gold), but that
relationship broke down in the structural bull market.

Solution: train separate models for each detected regime so that the
trending-regime model can learn the bull-market dynamics independently
from the mean-reverting-regime model.

Regime labels (from Hurst exponent + ADX):
  0 = mean-reverting  (Hurst < 0.45, ADX < 20)
  1 = trending        (Hurst > 0.55, ADX > 25)
  2 = mixed / unknown (everything else)

Usage
-----
    from ml.regime_conditional import RegimeConditionalModel

    rcm = RegimeConditionalModel()
    rcm.fit(X_train, y_train)
    preds = rcm.predict(X_test)
    report = rcm.evaluate(X_test, y_test)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, ClassVar

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    import xgboost as xgb

    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

logger = logging.getLogger(__name__)


# ── Prometheus metrics (optional) ────────────────────────────────────────────


def _init_prometheus():
    try:
        from prometheus_client import Counter, Gauge, Histogram

        class _M:
            predict_total = Counter(
                "hopefx_regime_conditional_predict_total",
                "Total RegimeConditionalModel predictions",
                ["symbol", "regime"],
            )
            predict_latency = Histogram(
                "hopefx_regime_conditional_latency_seconds",
                "RegimeConditionalModel prediction latency",
                ["symbol"],
                buckets=[0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
            )
            quality_gate_blocked = Counter(
                "hopefx_regime_conditional_quality_blocked_total",
                "Predictions blocked by data quality gate",
                ["symbol"],
            )
            sentiment_scale_gauge = Gauge(
                "hopefx_regime_conditional_sentiment_scale",
                "Sentiment scaling factor applied to last prediction",
                ["symbol"],
            )
            regime_distribution = Gauge(
                "hopefx_regime_conditional_regime_fraction",
                "Fraction of recent bars in each regime",
                ["regime"],
            )

        return _M()
    except ImportError:

        class _Noop:
            class _C:
                def labels(self, **_kw):
                    return self

                def inc(self, *a, **kw):
                    pass

                def observe(self, *a, **kw):
                    pass

                def set(self, *a, **kw):
                    pass

            def __getattr__(self, _):
                return self._C()

        return _Noop()


_PROM = _init_prometheus()

# Regime label constants
REGIME_MEAN_REVERTING = 0
REGIME_TRENDING = 1
REGIME_MIXED = 2
REGIME_HIGH_VOL_PARABOLIC = 3  # post-bubble / parabolic-blow-off regime
REGIME_NAMES = {
    0: "mean_reverting",
    1: "trending",
    2: "mixed",
    3: "high_vol_parabolic",
}

# Minimum samples required to train a regime-specific model.
# Below this threshold the global model is used as fallback.
MIN_REGIME_SAMPLES = 200

# Parabolic-bubble detection thresholds (tuned to gold 1979-1981 and 2010-2012)
# Calibration rationale: see docs/FOLD2_REGIME_ANALYSIS.md §Quantitative Regime Signature
# and ml/saved_models/horizon5_training_report.json for historical evidence.
# Summary:
#   1979 bubble peak: price/MA200 ≈ 2.1×, rv14/rv90 ≈ 3.8× at trough
#   2011 bubble peak: price/MA200 ≈ 1.42×, rv14/rv90 ≈ 2.1× at peak
# Thresholds are set conservatively to catch both episodes with ~0% false negatives
# in normal trending markets (< 2% of non-bubble bars are flagged in full 58Y backtest).
_PARABOLIC_MA_RATIO = 1.30  # price > 1.30× its 200-bar MA → parabolic territory
_PARABOLIC_RV_RATIO = 2.50  # rv14 > 2.5× rv90 → extreme vol expansion
_PARABOLIC_DRAWDOWN_PCT = 0.25  # price ≥ 25% below recent 200-bar peak → post-bubble crash
_PARABOLIC_LOOKBACK = 200  # bars for MA and peak detection


def is_parabolic_bubble_regime(
    X: pd.DataFrame,
    close_col: str = "close",
    lookback: int = _PARABOLIC_LOOKBACK,
) -> bool:
    """
    Detect whether the most recent bar is in a parabolic-bubble or post-bubble
    crash regime — the market condition responsible for Fold-2's 44.4% accuracy.

    A bar is flagged as HIGH_VOL_PARABOLIC when ANY of the following conditions
    hold for the last bar:

    1. Price > 1.30× its ``lookback``-bar simple moving average
       (parabolic blow-off: price has detached from fair value).

    2. 14-bar realised vol > 2.5× 90-bar realised vol
       AND price is ≥ 25% below a recent ``lookback``-bar high
       (post-bubble crash: extreme vol with price far below peak).

    Both conditions identify regimes where momentum/trend features become
    anti-predictive because the normal price-discovery process has broken down.

    Parameters
    ----------
    X        : Feature DataFrame — must contain ``close_col``.
    close_col: Name of the closing-price column.
    lookback : Rolling window for MA and peak detection.

    Returns
    -------
    bool — True when the last bar is in a parabolic-bubble regime.
    """
    if close_col not in X.columns or len(X) < max(20, lookback // 4):
        return False

    try:
        closes = X[close_col].astype(float).values
        last = closes[-1]
        if last <= 0:
            return False

        # ── Condition 1: price > 1.30× MA(lookback) ──────────────────────────
        window = min(lookback, len(closes))
        ma = float(np.mean(closes[-window:]))
        if ma > 0 and last / ma > _PARABOLIC_MA_RATIO:
            logger.debug(
                "is_parabolic_bubble_regime: price/MA200=%.3f > %.2f → PARABOLIC",
                last / ma,
                _PARABOLIC_MA_RATIO,
            )
            return True

        # ── Condition 2: extreme vol spike + post-bubble drawdown ─────────────
        if len(closes) >= 14:
            log_ret = np.nan_to_num(np.diff(np.log(np.maximum(closes, 1e-9))), nan=0.0, posinf=0.0, neginf=0.0)
            rv14 = float(np.nan_to_num(np.std(log_ret[-14:]), nan=0.0)) if len(log_ret) >= 14 else 0.0
            rv90 = float(np.nan_to_num(np.std(log_ret[-90:]), nan=0.0)) if len(log_ret) >= 90 else rv14
            peak = float(np.max(closes[-window:]))
            drawdown = (peak - last) / peak if peak > 0 else 0.0
            if rv90 > 0 and rv14 > _PARABOLIC_RV_RATIO * rv90 and drawdown >= _PARABOLIC_DRAWDOWN_PCT:
                logger.debug(
                    "is_parabolic_bubble_regime: rv14/rv90=%.2f > %.2f AND drawdown=%.1f%% → POST-BUBBLE",
                    rv14 / rv90,
                    _PARABOLIC_RV_RATIO,
                    drawdown * 100,
                )
                return True
    except Exception as exc:
        logger.debug("is_parabolic_bubble_regime: error: %s", exc)

    return False


def detect_regime_labels(
    X: pd.DataFrame,
    hurst_col: str = "regime_hurst",
    adx_col: str = "regime_trend_str",
) -> pd.Series:
    """
    Assign a regime label to each row based on Hurst exponent and ADX.

    Regime labels
    -------------
    0 = mean_reverting      (Hurst < 0.45, ADX < 0.20)
    1 = trending            (Hurst > 0.55, ADX > 0.25)
    2 = mixed / unknown     (everything else)
    3 = high_vol_parabolic  (parabolic blow-off or post-bubble crash)

    The HIGH_VOL_PARABOLIC label overrides all others when the parabolic-bubble
    condition is detected (see ``is_parabolic_bubble_regime()``).  This is the
    condition responsible for Walk-Forward Fold-2's 44.4% accuracy failure.

    Parameters
    ----------
    X         : Feature DataFrame (must contain hurst_col and adx_col)
    hurst_col : Column name for rolling Hurst exponent (0–1)
    adx_col   : Column name for normalised ADX trend strength (0–1)

    Returns
    -------
    labels : pd.Series of int (0=mean-reverting, 1=trending, 2=mixed, 3=high_vol_parabolic)
    """
    labels = pd.Series(REGIME_MIXED, index=X.index, dtype=int)

    has_hurst = hurst_col in X.columns
    has_adx = adx_col in X.columns

    if has_hurst and has_adx:
        hurst = X[hurst_col]
        adx = X[adx_col]
        labels[(hurst < 0.45) & (adx < 0.20)] = REGIME_MEAN_REVERTING
        labels[(hurst > 0.55) & (adx > 0.25)] = REGIME_TRENDING
    elif has_hurst:
        hurst = X[hurst_col]
        labels[hurst < 0.45] = REGIME_MEAN_REVERTING
        labels[hurst > 0.55] = REGIME_TRENDING
    elif has_adx:
        adx = X[adx_col]
        labels[adx < 0.20] = REGIME_MEAN_REVERTING
        labels[adx > 0.25] = REGIME_TRENDING
    else:
        logger.warning(
            "Neither '%s' nor '%s' found in feature matrix — "
            "all bars assigned to MIXED regime. "
            "Run add_regime_features() before regime-conditional training.",
            hurst_col,
            adx_col,
        )

    # ── Parabolic override: HIGH_VOL_PARABOLIC supersedes all other labels ────
    if "close" in X.columns and len(X) >= 20:
        parabolic_mask = _detect_parabolic_mask(X)
        labels[parabolic_mask] = REGIME_HIGH_VOL_PARABOLIC

    counts = labels.value_counts().to_dict()
    logger.info(
        "Regime distribution: mean_rev=%d  trending=%d  mixed=%d  parabolic=%d",
        counts.get(REGIME_MEAN_REVERTING, 0),
        counts.get(REGIME_TRENDING, 0),
        counts.get(REGIME_MIXED, 0),
        counts.get(REGIME_HIGH_VOL_PARABOLIC, 0),
    )
    return labels


def _detect_parabolic_mask(X: pd.DataFrame) -> pd.Series:
    """
    Return a boolean mask for rows that are in a parabolic-bubble regime.

    Condition 1 — parabolic blow-off:
        close > 1.30 × rolling 200-bar MA

    Condition 2 — post-bubble crash:
        rv14 > 2.5 × rv90  AND  close ≤ 75% of rolling 200-bar peak

    Both conditions use shifted (lag-1) values to prevent lookahead.
    """
    closes = X["close"].astype(float)
    n = len(closes)

    # Rolling MA and peak (shift by 1 to prevent lookahead)
    ma200 = closes.rolling(min(200, n), min_periods=10).mean().shift(1)
    peak200 = closes.rolling(min(200, n), min_periods=10).max().shift(1)

    # Log-return realised vols
    log_ret = np.log(closes.replace(0, np.nan)).diff()
    rv14 = log_ret.rolling(14, min_periods=5).std().shift(1)
    rv90 = log_ret.rolling(90, min_periods=20).std().shift(1).fillna(rv14)

    cond1 = (ma200 > 0) & (closes / ma200 > _PARABOLIC_MA_RATIO)
    cond2 = (
        (rv90 > 0)
        & (rv14 > _PARABOLIC_RV_RATIO * rv90)
        & (peak200 > 0)
        & (closes / peak200 <= (1.0 - _PARABOLIC_DRAWDOWN_PCT))
    )
    return (cond1 | cond2).fillna(False)


def add_regime_features(
    X: pd.DataFrame,
    hurst_window: int = 40,
    adx_window: int = 14,
) -> pd.DataFrame:
    """
    Compute and append ``regime_hurst`` and ``regime_trend_str`` columns.

    These columns are required by ``detect_regime_labels()`` and
    ``RegimeConditionalModel``.  Call this before fitting or predicting
    when the feature matrix does not already contain them.

    Parameters
    ----------
    X            : Feature DataFrame with at least a ``close`` column.
                   ``high`` and ``low`` are used for ADX if present.
    hurst_window : Rolling window for Hurst exponent estimation (R/S method).
    adx_window   : Smoothing window for ADX computation.

    Returns
    -------
    X with two new columns appended (in-place copy):
      regime_hurst      : float [0, 1] — Hurst exponent (>0.55 = trending)
      regime_trend_str  : float [0, 1] — normalised ADX (>0.25 = trending)
    """
    X = X.copy()

    if "close" not in X.columns:
        logger.warning("add_regime_features: 'close' column missing — regime features set to 0.5")
        X["regime_hurst"] = 0.5
        X["regime_trend_str"] = 0.25
        return X

    close = X["close"].astype(float)

    # ── Hurst exponent (rolling R/S) ──────────────────────────────────────────
    def _hurst_rs(prices: np.ndarray) -> float:
        """Estimate Hurst exponent via R/S analysis on a price window."""
        n = len(prices)
        if n < 10:
            return 0.5
        lags = range(2, min(n // 2, 12))
        rs_vals = []
        for lag in lags:
            sub = prices[:lag]
            mean = np.mean(sub)
            dev = np.cumsum(sub - mean)
            r = np.max(dev) - np.min(dev)
            s = np.std(sub, ddof=1)
            if s > 0:
                rs_vals.append(float(np.nan_to_num(np.log(max(r / max(s, 1e-9), 1e-9)), nan=0.0)))
        if len(rs_vals) < 2:
            return 0.5
        log_lags = np.log(np.maximum(list(lags[: len(rs_vals)]), 1e-9))
        return float(np.clip(np.polyfit(log_lags, rs_vals, 1)[0], 0.0, 1.0))

    X["regime_hurst"] = (
        close.rolling(hurst_window).apply(_hurst_rs, raw=True).shift(1)  # no lookahead
    )

    # ── ADX (normalised to [0, 1]) ────────────────────────────────────────────
    if all(c in X.columns for c in ["high", "low"]):
        high = X["high"].astype(float)
        low = X["low"].astype(float)
        tr = pd.concat(  # healer: ignore
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).fillna(0.0).max(axis=1)
        plus_dm = (high - high.shift(1)).clip(lower=0)
        minus_dm = (low.shift(1) - low).clip(lower=0)
        tr_s = tr.rolling(adx_window, min_periods=1).mean().fillna(0.0)
        plus_di = 100 * plus_dm.rolling(adx_window, min_periods=1).mean().fillna(0.0) / (tr_s + 1e-9)
        minus_di = 100 * minus_dm.rolling(adx_window, min_periods=1).mean().fillna(0.0) / (tr_s + 1e-9)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
        X["regime_trend_str"] = (dx.rolling(adx_window, min_periods=1).mean().fillna(0.0) / 100.0).shift(1)
    else:
        # Fallback: use rolling slope of close as trend proxy
        def _slope(x: np.ndarray) -> float:
            if len(x) < 3:
                return 0.0
            coef = np.polyfit(np.arange(len(x)), x, 1)[0]
            return float(np.clip(abs(coef) / (np.std(x) + 1e-9), 0.0, 1.0))

        X["regime_trend_str"] = close.rolling(adx_window).apply(_slope, raw=True).shift(1)

    # Fill NaN from rolling windows with neutral values
    X["regime_hurst"] = X["regime_hurst"].fillna(0.5)
    X["regime_trend_str"] = X["regime_trend_str"].fillna(0.25)

    logger.debug(
        "add_regime_features: hurst mean=%.3f  adx mean=%.3f  n=%d",
        X["regime_hurst"].mean(),
        X["regime_trend_str"].mean(),
        len(X),
    )
    return X


def _build_model(regime: int, n_samples: int) -> Pipeline:
    """
    Build a calibrated XGBoost (or RF fallback) pipeline tuned for the regime.

    Trending regime: deeper trees, lower learning rate — captures longer
    momentum patterns.
    Mean-reverting regime: shallower trees, higher regularisation — avoids
    overfitting to noise in choppy markets.
    """
    if _XGB_AVAILABLE:
        if regime == REGIME_TRENDING:
            base = xgb.XGBClassifier(
                n_estimators=500,
                max_depth=6,
                learning_rate=0.03,
                subsample=0.80,
                colsample_bytree=0.80,
                min_child_weight=3,
                gamma=0.05,
                reg_alpha=0.05,
                reg_lambda=1.0,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
        elif regime == REGIME_MEAN_REVERTING:
            base = xgb.XGBClassifier(
                n_estimators=400,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.75,
                colsample_bytree=0.75,
                min_child_weight=5,
                gamma=0.10,
                reg_alpha=0.20,
                reg_lambda=2.0,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
        else:  # MIXED
            base = xgb.XGBClassifier(
                n_estimators=400,
                max_depth=5,
                learning_rate=0.04,
                subsample=0.78,
                colsample_bytree=0.78,
                min_child_weight=4,
                gamma=0.08,
                reg_alpha=0.10,
                reg_lambda=1.5,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
    else:
        # RF fallback when XGBoost is not installed
        base = RandomForestClassifier(
            n_estimators=300,
            max_depth=6 if regime == REGIME_TRENDING else 4,
            min_samples_leaf=5 if regime == REGIME_TRENDING else 10,
            max_features="sqrt",
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

    cv_folds = min(3, max(2, n_samples // 100))
    cal = CalibratedClassifierCV(base, method="isotonic", cv=cv_folds)
    pipe = Pipeline([("scaler", StandardScaler()), ("model", cal)])
    return pipe


class RegimeConditionalModel(BaseEstimator, ClassifierMixin):
    """
    Ensemble of regime-specific classifiers.

    At prediction time, the regime label for each bar is detected from the
    feature matrix (Hurst + ADX columns) and the corresponding sub-model is
    used.  If a regime has fewer than MIN_REGIME_SAMPLES training bars, the
    global model is used as fallback for that regime.

    Parameters
    ----------
    hurst_col : Feature column name for rolling Hurst exponent
    adx_col   : Feature column name for normalised ADX trend strength
    """

    def __init__(
        self,
        hurst_col: str = "regime_hurst",
        adx_col: str = "regime_trend_str",
    ) -> None:
        self.hurst_col = hurst_col
        self.adx_col = adx_col

        self._regime_models: dict[int, Pipeline] = {}
        self._global_model: Pipeline | None = None
        self._regime_counts: dict[int, int] = {}
        self._feature_names: list[str] = []
        self._is_fitted = False

    # ── Fitting ───────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame, y: pd.Series) -> RegimeConditionalModel:
        """
        Train regime-specific models and a global fallback model.

        Steps
        -----
        1. Detect regime labels for every training bar.
        2. Train a global model on all training data (fallback).
        3. For each regime with >= MIN_REGIME_SAMPLES bars, train a
           regime-specific model on that subset.
        """
        self._feature_names = list(X.columns)
        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)

        # Global fallback model
        logger.info("Training global fallback model on %d samples...", len(X))
        self._global_model = _build_model(REGIME_MIXED, len(X))
        self._global_model.fit(X, y)

        # Regime-specific models
        for regime in [REGIME_MEAN_REVERTING, REGIME_TRENDING, REGIME_MIXED]:
            mask = labels == regime
            n = mask.sum()
            self._regime_counts[regime] = int(n)

            if n < MIN_REGIME_SAMPLES:
                logger.info(
                    "Regime %s: only %d samples (< %d) — using global fallback",
                    REGIME_NAMES[regime],
                    n,
                    MIN_REGIME_SAMPLES,
                )
                continue

            logger.info(
                "Training %s model on %d samples...",
                REGIME_NAMES[regime],
                n,
            )
            model = _build_model(regime, int(n))
            model.fit(X[mask], y[mask])
            self._regime_models[regime] = model
            logger.info("  %s model trained.", REGIME_NAMES[regime])

        self._is_fitted = True
        return self

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class labels using regime-specific models."""
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict class probabilities.

        Each bar is routed to its regime-specific model.  Bars whose regime
        has no trained model fall back to the global model.
        """
        if not self._is_fitted:
            raise RuntimeError("Call fit() before predict_proba()")

        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)
        proba = np.zeros((len(X), 2), dtype=float)

        for regime in [REGIME_MEAN_REVERTING, REGIME_TRENDING, REGIME_MIXED]:
            mask = (labels == regime).values
            if not mask.any():
                continue
            model = self._regime_models.get(regime, self._global_model)
            proba[mask] = model.predict_proba(X.iloc[mask])

        return proba

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """
        Evaluate per-regime and overall accuracy, F1, and AUC.

        Returns a dict with keys: overall, mean_reverting, trending, mixed.
        """
        if not self._is_fitted:
            raise RuntimeError("Call fit() before evaluate()")

        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)
        preds = self.predict(X)
        proba = self.predict_proba(X)[:, 1]

        def _metrics(mask: np.ndarray, tag: str) -> dict:
            if mask.sum() < 2:
                return {"n": int(mask.sum()), "note": "too few samples"}
            p = preds[mask]
            t = y.values[mask]
            pr = proba[mask]
            acc = accuracy_score(t, p)
            f1 = f1_score(t, p, zero_division=0)
            try:
                auc = roc_auc_score(t, pr)
            except ValueError:
                auc = 0.5
            logger.info(
                "Regime %-16s  n=%4d  acc=%.3f  f1=%.3f  auc=%.3f",
                tag,
                mask.sum(),
                acc,
                f1,
                auc,
            )
            return {
                "n": int(mask.sum()),
                "accuracy": round(acc, 4),
                "f1": round(f1, 4),
                "auc": round(auc, 4),
            }

        result = {
            "overall": _metrics(np.ones(len(X), dtype=bool), "overall"),
            "mean_reverting": _metrics(
                (labels == REGIME_MEAN_REVERTING).values,
                "mean_reverting",
            ),
            "trending": _metrics((labels == REGIME_TRENDING).values, "trending"),
            "mixed": _metrics((labels == REGIME_MIXED).values, "mixed"),
            "regime_counts": self._regime_counts,
            "regime_models_trained": list(self._regime_models.keys()),
        }
        return result

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str) -> str:
        """Save all regime models and metadata to a single joblib file."""
        if not self._is_fitted:
            raise RuntimeError("Call fit() before save()")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "regime_models": self._regime_models,
            "global_model": self._global_model,
            "regime_counts": self._regime_counts,
            "feature_names": self._feature_names,
            "hurst_col": self.hurst_col,
            "adx_col": self.adx_col,
        }
        joblib.dump(payload, path)
        logger.info("RegimeConditionalModel saved → %s", path)
        return path

    @classmethod
    def load(cls, path: str) -> RegimeConditionalModel:
        """Load a previously saved RegimeConditionalModel."""
        payload = joblib.load(path)  # nosec B301 - path set by class constructor from saved_models
        obj = cls(
            hurst_col=payload["hurst_col"],
            adx_col=payload["adx_col"],
        )
        obj._regime_models = payload["regime_models"]
        obj._global_model = payload["global_model"]
        obj._regime_counts = payload["regime_counts"]
        obj._feature_names = payload["feature_names"]
        obj._is_fitted = True
        logger.info("RegimeConditionalModel loaded from %s", path)
        return obj

    def predict_live(
        self,
        ohlcv: pd.DataFrame,
        symbol: str = "XAU_USD",
        min_data_quality: float = 0.40,
        extra_features: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """
        Full end-to-end live prediction wired to the orchestrator.

        Pipeline
        --------
        1. Add regime features (Hurst + ADX) to the OHLCV-derived feature matrix
        2. Inject orchestrator ML features (microstructure, sentiment, macro)
        3. Data quality gate — reject if tick confidence < min_data_quality
        4. Regime-conditional predict_proba (routes each bar to its sub-model)
        5. Sentiment scaling — reduce confidence in high-news environments
        6. Prometheus instrumentation
        7. Return structured result dict

        Parameters
        ----------
        ohlcv            : H1 OHLCV DataFrame (at least 50 bars recommended)
        symbol           : Instrument symbol for logging and Prometheus labels
        min_data_quality : Minimum orchestrator tick confidence to proceed
        extra_features   : Optional pre-built feature DataFrame.  When None,
                           regime features are computed from ``ohlcv`` directly.

        Returns
        -------
        dict with keys:
          direction          : "long" | "short" | "neutral"
          probability        : float [0, 1] — P(up) for last bar
          regime             : str — detected regime for last bar
          data_quality       : float — orchestrator tick confidence
          sentiment_score    : float — news sentiment from orchestrator
          macro_impact       : float — macro calendar impact score
          sentiment_scale    : float — multiplier applied to probability
          quality_gate_passed: bool
          model_used         : str — "regime_specific" | "global_fallback"
          latency_ms         : float
        """
        if not self._is_fitted:
            raise RuntimeError("Call fit() before predict_live()")

        t0 = time.perf_counter()

        # ── Step 1: Build feature matrix ──────────────────────────────────────
        if extra_features is not None:
            X = extra_features.copy()
        else:
            # Minimal feature set from OHLCV
            X = (
                ohlcv[["open", "high", "low", "close", "volume"]].copy()
                if all(c in ohlcv.columns for c in ["open", "high", "low", "close", "volume"])
                else ohlcv.copy()
            )

        # Ensure regime columns are present
        if self.hurst_col not in X.columns or self.adx_col not in X.columns:
            X = add_regime_features(X)

        # ── Step 2: Orchestrator feature injection ────────────────────────────
        data_quality = 1.0
        sentiment_score = 0.0
        macro_impact = 0.0

        try:
            from data_layer.orchestrator import orchestrator

            tick = orchestrator.get_latest_tick()
            if tick is not None:
                data_quality = float(tick.confidence)
            feats = orchestrator.get_ml_features()
            sentiment_score = float(feats.get("news_sentiment_score", 0.0))
            macro_impact = float(feats.get("macro_impact_score_now", 0.0))

            # Inject orchestrator features as extra columns
            for key, val in feats.items():
                col = f"orch_{key}"
                if col not in X.columns:
                    X[col] = float(val)
        except Exception as exc:
            logger.debug("predict_live: orchestrator unavailable: %s", exc)

        # ── Step 3: Data quality gate ─────────────────────────────────────────
        if data_quality < min_data_quality:
            _PROM.quality_gate_blocked.labels(symbol=symbol).inc()
            logger.warning(
                "RegimeConditionalModel.predict_live: data quality %.3f < %.3f — neutral",
                data_quality,
                min_data_quality,
            )
            return {
                "direction": "neutral",
                "probability": 0.5,
                "regime": "unknown",
                "data_quality": data_quality,
                "sentiment_score": sentiment_score,
                "macro_impact": macro_impact,
                "sentiment_scale": 1.0,
                "quality_gate_passed": False,
                "model_used": "none",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            }

        # ── Step 4: Align feature columns to training schema ──────────────────
        if self._feature_names:
            for col in self._feature_names:
                if col not in X.columns:
                    X[col] = 0.0
            # Only keep columns the model was trained on
            X_aligned = X[[c for c in self._feature_names if c in X.columns]]
            # Fill any remaining missing columns
            for col in self._feature_names:
                if col not in X_aligned.columns:
                    X_aligned[col] = 0.0
            X_aligned = X_aligned[self._feature_names]
        else:
            X_aligned = X

        X_aligned = X_aligned.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # ── Step 5: Regime-conditional prediction ─────────────────────────────
        last_row = X_aligned.iloc[[-1]]
        labels = detect_regime_labels(last_row, self.hurst_col, self.adx_col)
        regime_id = int(labels.iloc[0])
        regime_name = REGIME_NAMES.get(regime_id, "unknown")

        # ── Step 5a: Parabolic-bubble abstain gate ────────────────────────────
        # When the last bar is in a HIGH_VOL_PARABOLIC regime the model has
        # historically underperformed (Fold-2: 44.4% accuracy). Abstain to
        # avoid taking directional bets in parabolic blow-offs / post-bubble crashes.
        if regime_id == REGIME_HIGH_VOL_PARABOLIC or is_parabolic_bubble_regime(ohlcv if extra_features is None else X):
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            _PROM.predict_total.labels(symbol=symbol, regime="high_vol_parabolic").inc()
            logger.warning(
                "RegimeConditionalModel.predict_live: %s HIGH_VOL_PARABOLIC regime — abstain",
                symbol,
            )
            return {
                "direction": "neutral",
                "probability": 0.5,
                "regime": "high_vol_parabolic",
                "data_quality": round(data_quality, 4),
                "sentiment_score": round(sentiment_score, 4),
                "macro_impact": round(macro_impact, 4),
                "sentiment_scale": 1.0,
                "quality_gate_passed": True,
                "model_used": "none",
                "abstain": True,
                "abstain_reason": "HIGH_VOL_PARABOLIC regime: model accuracy < chance (Fold-2 failure)",
                "latency_ms": latency_ms,
            }

        model = self._regime_models.get(regime_id, self._global_model)
        model_used = "regime_specific" if regime_id in self._regime_models else "global_fallback"

        try:
            proba = model.predict_proba(last_row)
            prob_up = float(proba[0, 1]) if proba.shape[1] > 1 else float(proba[0, 0])
        except Exception as exc:
            logger.warning("predict_live: model.predict_proba failed: %s", exc)
            prob_up = 0.5

        # ── Step 6: Sentiment scaling ─────────────────────────────────────────
        # High absolute sentiment → model less reliable (news-driven move)
        sentiment_scale = max(0.80, 1.0 - abs(sentiment_score) * 0.40)
        scaled_prob = 0.5 + (prob_up - 0.5) * sentiment_scale
        scaled_prob = float(np.clip(scaled_prob, 0.01, 0.99))

        # ── Step 7: Direction ─────────────────────────────────────────────────
        if scaled_prob >= 0.58:
            direction = "long"
        elif scaled_prob <= 0.42:
            direction = "short"
        else:
            direction = "neutral"

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)

        # ── Prometheus ────────────────────────────────────────────────────────
        _PROM.predict_total.labels(symbol=symbol, regime=regime_name).inc()
        _PROM.predict_latency.labels(symbol=symbol).observe(latency_ms / 1000.0)
        _PROM.sentiment_scale_gauge.labels(symbol=symbol).set(sentiment_scale)

        logger.debug(
            "RegimeConditionalModel.predict_live: %s dir=%s prob=%.3f "
            "regime=%s quality=%.3f sentiment=%.3f scale=%.3f latency=%.1fms",
            symbol,
            direction,
            scaled_prob,
            regime_name,
            data_quality,
            sentiment_score,
            sentiment_scale,
            latency_ms,
        )

        return {
            "direction": direction,
            "probability": round(scaled_prob, 4),
            "regime": regime_name,
            "data_quality": round(data_quality, 4),
            "sentiment_score": round(sentiment_score, 4),
            "macro_impact": round(macro_impact, 4),
            "sentiment_scale": round(sentiment_scale, 4),
            "quality_gate_passed": True,
            "model_used": model_used,
            "abstain": False,
            "latency_ms": latency_ms,
        }

    # ── Prometheus-instrumented predict_proba ─────────────────────────────────

    def predict_proba_instrumented(
        self,
        X: pd.DataFrame,
        symbol: str = "XAU_USD",
    ) -> np.ndarray:
        """
        predict_proba() with Prometheus latency and regime distribution tracking.

        Emits:
          hopefx_regime_conditional_predict_total{symbol, regime}
          hopefx_regime_conditional_latency_seconds{symbol}
          hopefx_regime_conditional_regime_fraction{regime}
        """
        t0 = time.perf_counter()
        proba = self.predict_proba(X)
        latency = time.perf_counter() - t0

        _PROM.predict_latency.labels(symbol=symbol).observe(latency)

        # Regime distribution for the batch
        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)
        total = max(len(labels), 1)
        for regime_id, regime_name in REGIME_NAMES.items():
            frac = float(np.nan_to_num((labels == regime_id).sum(), nan=0.0)) / total
            _PROM.regime_distribution.labels(regime=regime_name).set(frac)
            _PROM.predict_total.labels(symbol=symbol, regime=regime_name).inc(amount=int((labels == regime_id).sum()))

        return proba

    # ── Orchestrator-wired prediction ─────────────────────────────────────────

    def predict_with_orchestrator(
        self,
        X: pd.DataFrame,
        min_data_quality: float = 0.40,
    ) -> dict:
        """
        Predict with live orchestrator data quality and sentiment gating.

        Reads from data_layer.orchestrator:
          - tick.confidence  → data quality gate (rejects if below min_data_quality)
          - get_ml_features() → news_sentiment_score, macro_impact_score

        Sentiment nudge: high absolute sentiment (|s| > 0.5) reduces confidence
        by up to 20% to reflect model uncertainty in high-news environments.

        Returns
        -------
        dict with keys:
          predictions      : np.ndarray of class labels
          probabilities    : np.ndarray of class-1 probabilities
          data_quality     : float — orchestrator tick confidence
          sentiment_score  : float — news sentiment from orchestrator
          macro_impact     : float — macro impact score from orchestrator
          quality_gate_passed : bool — False if data quality too low
          sentiment_scale  : float — multiplier applied to confidence
        """
        # ── Pull orchestrator context ─────────────────────────────────────────
        data_quality = 1.0
        sentiment_score = 0.0
        macro_impact = 0.0

        try:
            from data_layer.orchestrator import orchestrator

            tick = orchestrator.get_latest_tick()
            if tick is not None:
                data_quality = float(tick.confidence)
            features = orchestrator.get_ml_features()
            sentiment_score = float(features.get("news_sentiment_score", 0.0))
            macro_impact = float(features.get("macro_impact_score", 0.0))
        except Exception as exc:
            logger.debug("predict_with_orchestrator: orchestrator unavailable: %s", exc)

        # ── Data quality gate ─────────────────────────────────────────────────
        if data_quality < min_data_quality:
            logger.warning(
                "predict_with_orchestrator: data quality %.3f < %.3f — returning neutral",
                data_quality,
                min_data_quality,
            )
            neutral_proba = np.full((len(X), 2), 0.5)
            return {
                "predictions": np.zeros(len(X), dtype=int),
                "probabilities": neutral_proba[:, 1],
                "data_quality": data_quality,
                "sentiment_score": sentiment_score,
                "macro_impact": macro_impact,
                "quality_gate_passed": False,
                "sentiment_scale": 1.0,
            }

        # ── Parabolic-bubble abstain gate ─────────────────────────────────────
        if is_parabolic_bubble_regime(X):
            logger.warning("predict_with_orchestrator: HIGH_VOL_PARABOLIC regime — abstain (Fold-2 filter)")
            neutral_proba = np.full((len(X), 2), 0.5)
            return {
                "predictions": np.zeros(len(X), dtype=int),
                "probabilities": neutral_proba[:, 1],
                "data_quality": data_quality,
                "sentiment_score": sentiment_score,
                "macro_impact": macro_impact,
                "quality_gate_passed": True,
                "sentiment_scale": 1.0,
                "abstain": True,
                "abstain_reason": "HIGH_VOL_PARABOLIC regime: model accuracy < chance (Fold-2 filter)",
            }

        # ── Base prediction ───────────────────────────────────────────────────
        proba = self.predict_proba(X)
        preds = (proba[:, 1] >= 0.5).astype(int)

        # ── Sentiment scaling (soft — reduces confidence, never flips signal) ─
        # High absolute sentiment → model is less reliable (news-driven move).
        sentiment_scale = max(0.80, 1.0 - abs(sentiment_score) * 0.40)
        # Scale probabilities toward 0.5 by sentiment_scale
        scaled_proba = 0.5 + (proba[:, 1] - 0.5) * sentiment_scale

        logger.debug(
            "predict_with_orchestrator: quality=%.3f sentiment=%.3f impact=%.3f scale=%.3f",
            data_quality,
            sentiment_score,
            macro_impact,
            sentiment_scale,
        )

        return {
            "predictions": preds,
            "probabilities": scaled_proba,
            "data_quality": data_quality,
            "sentiment_score": sentiment_score,
            "macro_impact": macro_impact,
            "quality_gate_passed": True,
            "sentiment_scale": sentiment_scale,
            "abstain": False,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward evaluation with regime-conditional model
# ─────────────────────────────────────────────────────────────────────────────


def walk_forward_regime_eval(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
) -> dict:
    """
    Walk-forward cross-validation using RegimeConditionalModel.

    Returns per-fold metrics and aggregate statistics including per-regime
    breakdown for the last fold (most representative of live conditions).
    """
    from scipy import stats
    from sklearn.model_selection import TimeSeriesSplit

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=1)
    fold_results: ClassVar[list[dict]] = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        if len(y_train.unique()) < 2:
            logger.warning("Fold %d: only one class in training — skipping", fold + 1)
            continue

        model = RegimeConditionalModel()
        model.fit(X_train, y_train)
        eval_result = model.evaluate(X_test, y_test)

        overall = eval_result["overall"]
        fold_results.append(
            {
                "fold": fold + 1,
                "train_size": len(train_idx),
                "test_size": len(test_idx),
                "accuracy": overall["accuracy"],
                "f1": overall["f1"],
                "auc": overall.get("auc", 0.5),
                "per_regime": {
                    k: v
                    for k, v in eval_result.items()
                    if k not in ("overall", "regime_counts", "regime_models_trained")
                },
            },
        )
        logger.info(
            "Fold %d/%d  acc=%.3f  f1=%.3f  auc=%.3f  train=%d  test=%d",
            fold + 1,
            n_splits,
            overall["accuracy"],
            overall["f1"],
            overall.get("auc", 0.5),
            len(train_idx),
            len(test_idx),
        )

    if not fold_results:
        return {"error": "no valid folds"}

    accs = [r["accuracy"] for r in fold_results]
    f1s = [r["f1"] for r in fold_results]
    aucs = [r["auc"] for r in fold_results]

    t_stat, p_value = stats.ttest_1samp(accs, 0.5)

    return {
        "model": "RegimeConditionalModel",
        "folds": fold_results,
        "mean_accuracy": round(float(np.mean(accs)), 4),
        "std_accuracy": round(float(np.std(accs)), 4),
        "mean_f1": round(float(np.mean(f1s)), 4),
        "mean_auc": round(float(np.mean(aucs)), 4),
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05 and float(np.mean(accs)) > 0.55),
    }


# ── Module-level singleton ────────────────────────────────────────────────────

_rcm_singleton: RegimeConditionalModel | None = None
_rcm_path: str | None = None


def get_regime_conditional_model(
    model_path: str | None = None,
) -> RegimeConditionalModel | None:
    """
    Return the module-level RegimeConditionalModel singleton.

    Loads from ``model_path`` (or the default saved location) on first call.
    Returns None when no saved model exists — callers must handle this and
    fall back to the global InferenceEngine.

    Parameters
    ----------
    model_path : Path to a joblib file saved by RegimeConditionalModel.save().
                 Defaults to ``ml/saved_models/regime_conditional.joblib``.
    """
    global _rcm_singleton, _rcm_path

    default_path = model_path or "ml/saved_models/regime_conditional.joblib"

    # Return cached singleton if path unchanged
    if _rcm_singleton is not None and _rcm_path == default_path:
        return _rcm_singleton

    if not Path(default_path).exists():
        logger.debug(
            "get_regime_conditional_model: no saved model at %s — returning None",
            default_path,
        )
        return None

    try:
        _rcm_singleton = RegimeConditionalModel.load(default_path)
        _rcm_path = default_path
        logger.info("get_regime_conditional_model: loaded from %s", default_path)
        return _rcm_singleton
    except Exception as exc:
        logger.error("get_regime_conditional_model: load failed: %s", exc)
        return None
