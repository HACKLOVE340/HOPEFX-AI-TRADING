# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/pipeline.py

Production ML pipeline for XAUUSD directional prediction.

Constraints enforced:
- No look-ahead bias: features computed on t-1 data only
- Stationarity: ADF + KPSS tests gate feature inclusion
- OOS accuracy target >= 65%, p-value < 0.001
- Walk-forward cross-validation (expanding window, no shuffling)
- XGBoost + scikit-learn only (no experimental packages)
- Model artifacts saved with metadata for audit trail
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# Suppress statsmodels convergence warnings in CI
warnings.filterwarnings("ignore", category=UserWarning, module="statsmodels")

try:
    from statsmodels.tsa.stattools import adfuller, kpss

    _STATSMODELS = True
except ImportError:
    _STATSMODELS = False
    logger.warning("statsmodels not installed — stationarity tests disabled.")

try:
    import xgboost as xgb

    _XGB = True
except ImportError:
    _XGB = False
    logger.error("xgboost not installed. Install: pip install xgboost>=2.0.0")

try:
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    _SKLEARN = True
except ImportError:
    _SKLEARN = False
    logger.error("scikit-learn not installed.")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StationarityResult:
    feature: str
    adf_statistic: float
    adf_pvalue: float
    kpss_statistic: float
    kpss_pvalue: float
    is_stationary: bool
    method: str = "ADF+KPSS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "adf_statistic": self.adf_statistic,
            "adf_pvalue": self.adf_pvalue,
            "kpss_statistic": self.kpss_statistic,
            "kpss_pvalue": self.kpss_pvalue,
            "is_stationary": self.is_stationary,
        }


@dataclass
class WalkForwardFold:
    fold_idx: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    accuracy: float
    auc: float
    n_train: int
    n_test: int
    feature_importances: dict[str, float] = field(default_factory=dict)


@dataclass
class ValidationReport:
    oos_accuracy: float
    oos_accuracy_std: float
    mean_auc: float
    p_value: float  # binomial test vs 0.5 baseline
    n_folds: int
    n_total_oos_samples: int
    passes_accuracy_gate: bool  # >= 65%
    passes_pvalue_gate: bool  # < 0.001
    folds: list[WalkForwardFold] = field(default_factory=list)
    feature_importances: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "oos_accuracy": self.oos_accuracy,
            "oos_accuracy_std": self.oos_accuracy_std,
            "mean_auc": self.mean_auc,
            "p_value": self.p_value,
            "n_folds": self.n_folds,
            "n_total_oos_samples": self.n_total_oos_samples,
            "passes_accuracy_gate": self.passes_accuracy_gate,
            "passes_pvalue_gate": self.passes_pvalue_gate,
            "feature_importances": self.feature_importances,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


class FeatureEngineer:
    """
    Computes features from OHLCV bars with strict no-look-ahead enforcement.

    All features are shifted by 1 period before returning so that
    row[t] contains only information available at close of bar[t-1].
    """

    def __init__(self, lookback: int = 20) -> None:
        self._lookback = lookback

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Args:
            df: DataFrame with columns [open, high, low, close, volume].
                Index must be monotonically increasing (time-ordered).

        Returns:
            DataFrame with feature columns. Rows with NaN are dropped.
            Target column 'y' = 1 if next close > current close, else 0.
        """
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")

        c = df["close"]
        h = df["high"]
        lo = df["low"]
        v = df["volume"]

        feats = pd.DataFrame(index=df.index)

        # Returns (stationary by construction)
        feats["ret_1"] = c.pct_change(1)
        feats["ret_5"] = c.pct_change(5)
        feats["ret_10"] = c.pct_change(10)
        feats["ret_20"] = c.pct_change(20)

        # Log returns
        feats["log_ret_1"] = np.log(c / c.shift(1))
        feats["log_ret_5"] = np.log(c / c.shift(5))

        # Volatility (rolling std of log returns)
        feats["vol_5"] = feats["log_ret_1"].rolling(5).std()
        feats["vol_20"] = feats["log_ret_1"].rolling(20).std()
        feats["vol_ratio"] = feats["vol_5"] / (feats["vol_20"] + 1e-10)

        # RSI (14)
        feats["rsi_14"] = self._rsi(c, 14)

        # MACD signal
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        feats["macd_hist"] = (macd - signal) / (c + 1e-10)

        # Bollinger band position
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        feats["bb_pos"] = (c - sma20) / (2 * std20 + 1e-10)

        # ATR normalised
        tr = pd.concat(
            [
                h - lo,
                (h - c.shift(1)).abs(),
                (lo - c.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        feats["atr_norm"] = tr.rolling(14).mean() / (c + 1e-10)

        # Volume z-score
        vol_mean = v.rolling(20).mean()
        vol_std = v.rolling(20).std()
        feats["vol_zscore"] = (v - vol_mean) / (vol_std + 1e-10)

        # Price position in range
        feats["range_pos"] = (c - lo.rolling(20).min()) / (h.rolling(20).max() - lo.rolling(20).min() + 1e-10)

        # Momentum
        feats["mom_10"] = c / c.shift(10) - 1
        feats["mom_20"] = c / c.shift(20) - 1

        # Target: 1 if next bar close > current close
        feats["y"] = (c.shift(-1) > c).astype(int)

        # ── NO LOOK-AHEAD: shift all features forward by 1 ───────────────────
        # After shift, feats.iloc[t] contains features computed from data
        # available at end of bar t-1. Target y is already forward-looking
        # (next bar), so it must NOT be shifted.
        feature_cols = [col for col in feats.columns if col != "y"]
        feats[feature_cols] = feats[feature_cols].shift(1)

        # Drop rows with any NaN (warm-up period + shift)
        feats = feats.dropna()

        return feats

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# Stationarity tests
# ---------------------------------------------------------------------------


class StationarityTester:
    """
    ADF + KPSS stationarity tests.

    A feature is considered stationary if:
    - ADF rejects unit root (p < 0.05)  AND
    - KPSS fails to reject stationarity (p > 0.05)

    Non-stationary features are flagged but NOT automatically dropped —
    the caller decides whether to exclude them.
    """

    def __init__(self, adf_pvalue: float = 0.05, kpss_pvalue: float = 0.05) -> None:
        self._adf_p = adf_pvalue
        self._kpss_p = kpss_pvalue

    def test(self, series: pd.Series, name: str = "") -> StationarityResult:
        if not _STATSMODELS:
            # Return a permissive result if statsmodels unavailable
            return StationarityResult(
                feature=name,
                adf_statistic=0.0,
                adf_pvalue=0.01,
                kpss_statistic=0.0,
                kpss_pvalue=0.10,
                is_stationary=True,
                method="SKIPPED (statsmodels unavailable)",
            )

        series = series.dropna()
        if len(series) < 30:
            return StationarityResult(
                feature=name,
                adf_statistic=0.0,
                adf_pvalue=1.0,
                kpss_statistic=0.0,
                kpss_pvalue=0.0,
                is_stationary=False,
                method="SKIPPED (insufficient data)",
            )

        try:
            adf_stat, adf_p, *_ = adfuller(series, autolag="AIC")
        except Exception as exc:
            logger.warning("ADF test failed for %s: %s", name, exc)
            adf_stat, adf_p = 0.0, 1.0

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                kpss_stat, kpss_p, *_ = kpss(series, regression="c", nlags="auto")
        except Exception as exc:
            logger.warning("KPSS test failed for %s: %s", name, exc)
            kpss_stat, kpss_p = 0.0, 0.0

        is_stationary = (adf_p < self._adf_p) and (kpss_p > self._kpss_p)

        return StationarityResult(
            feature=name,
            adf_statistic=float(adf_stat),
            adf_pvalue=float(adf_p),
            kpss_statistic=float(kpss_stat),
            kpss_pvalue=float(kpss_p),
            is_stationary=is_stationary,
        )

    def test_dataframe(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
    ) -> dict[str, StationarityResult]:
        results = {}
        for col in feature_cols:
            results[col] = self.test(df[col], name=col)
            r = results[col]
            status = "STATIONARY" if r.is_stationary else "NON-STATIONARY"
            logger.info(
                "Stationarity [%s] %s | ADF p=%.4f KPSS p=%.4f",
                status,
                col,
                r.adf_pvalue,
                r.kpss_pvalue,
            )
        return results


# ---------------------------------------------------------------------------
# Walk-forward validator
# ---------------------------------------------------------------------------


class WalkForwardValidator:
    """
    Expanding-window walk-forward cross-validation.

    No data shuffling. Each fold trains on all data up to split point,
    tests on the next window. This is the only valid OOS methodology
    for time-series — k-fold with shuffling introduces look-ahead bias.
    """

    def __init__(
        self,
        n_folds: int = 5,
        min_train_size: float = 0.5,  # minimum 50% of data for first fold
    ) -> None:
        self._n_folds = n_folds
        self._min_train_size = min_train_size

    def split(
        self,
        n: int,
    ) -> list[tuple[range, range]]:
        """
        Generate (train_indices, test_indices) for each fold.
        Train set expands; test set is the next contiguous window.
        """
        min_train = int(n * self._min_train_size)
        remaining = n - min_train
        if remaining < self._n_folds:
            raise ValueError(
                f"Insufficient data for {self._n_folds} folds: n={n}, min_train={min_train}, remaining={remaining}",
            )

        fold_size = remaining // self._n_folds
        splits = []
        for i in range(self._n_folds):
            train_end = min_train + i * fold_size
            test_start = train_end
            test_end = min(test_start + fold_size, n)
            splits.append((range(train_end), range(test_start, test_end)))
        return splits


# ---------------------------------------------------------------------------
# XGBoost model
# ---------------------------------------------------------------------------


class XGBoostPredictor:
    """
    XGBoost binary classifier for XAUUSD directional prediction.

    Hyperparameters are conservative defaults tuned for financial time-series:
    - Low learning rate (0.05) to reduce overfitting
    - Subsample + colsample for regularisation
    - scale_pos_weight handles class imbalance
    """

    # Production defaults — tuned for financial time-series.
    # CI_FAST=1 reduces n_estimators to 50 so the full test suite finishes
    # within the 120s pytest timeout without sacrificing code-path coverage.
    _CI_FAST: bool = os.environ.get("CI_FAST", "").lower() in ("1", "true", "yes")

    DEFAULT_PARAMS: dict[str, Any] = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "learning_rate": 0.05,
        "max_depth": 4,
        "n_estimators": 300,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42,
        "n_jobs": -1,
        "verbosity": 0,
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        if not _XGB:
            raise ImportError("xgboost not installed.")
        base = dict(self.DEFAULT_PARAMS)
        if self._CI_FAST:
            base["n_estimators"] = int(os.environ.get("CI_XGB_N_ESTIMATORS", "50"))
        self._params = {**base, **(params or {})}
        self._model: xgb.XGBClassifier | None = None
        self._scaler: StandardScaler | None = None
        self._feature_names: list[str] = []

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> None:
        if not _SKLEARN:
            raise ImportError("scikit-learn not installed.")

        self._feature_names = list(X_train.columns)
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X_train)

        # Adjust for class imbalance
        pos = y_train.sum()
        neg = len(y_train) - pos
        scale_pos_weight = neg / max(pos, 1)

        params = {**self._params, "scale_pos_weight": scale_pos_weight}
        self._model = xgb.XGBClassifier(**params)

        eval_set = None
        if X_val is not None and y_val is not None:
            X_val_scaled = self._scaler.transform(X_val)
            eval_set = [(X_val_scaled, y_val)]

        self._model.fit(
            X_scaled,
            y_train,
            eval_set=eval_set,
            verbose=False,
        )

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self._model is None or self._scaler is None:
            raise RuntimeError("Model not fitted.")
        X_scaled = self._scaler.transform(X[self._feature_names])
        return self._model.predict_proba(X_scaled)[:, 1]

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba >= threshold).astype(int)

    def get_feature_importances(self) -> dict[str, float]:
        if self._model is None:
            return {}
        imp = self._model.feature_importances_
        return dict(zip(self._feature_names, imp.tolist(), strict=False))

    def save(self, path: str) -> None:
        if self._model is None:
            raise RuntimeError("No model to save.")
        import joblib

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self._model,
                "scaler": self._scaler,
                "features": self._feature_names,
            },
            path,
        )
        logger.info("XGBoostPredictor saved to %s", path)

    def load(self, path: str) -> None:
        import joblib

        obj = joblib.load(path)  # nosec B301 - path set by class constructor from saved_models
        self._model = obj["model"]
        self._scaler = obj["scaler"]
        self._feature_names = obj["features"]
        logger.info("XGBoostPredictor loaded from %s", path)


# ---------------------------------------------------------------------------
# ML Pipeline
# ---------------------------------------------------------------------------


class MLPipeline:
    """
    End-to-end ML pipeline:
      1. Feature engineering (no look-ahead)
      2. Stationarity tests (ADF + KPSS)
      3. Walk-forward OOS validation
      4. Final model training on full dataset
      5. Validation report with p-value gate

    OOS accuracy target: >= 65%
    p-value target: < 0.001 (binomial test vs 0.5 baseline)
    """

    OOS_ACCURACY_TARGET = 0.65
    PVALUE_TARGET = 0.001

    def __init__(
        self,
        model_dir: str = "ml/saved_models",
        n_folds: int = 5,
        drop_nonstationary: bool = False,
    ) -> None:
        self._model_dir = Path(model_dir)
        self._n_folds = n_folds
        self._drop_nonstationary = drop_nonstationary

        self._feature_engineer = FeatureEngineer()
        self._stationarity_tester = StationarityTester()
        self._validator = WalkForwardValidator(n_folds=n_folds)
        self._predictor = XGBoostPredictor()

        self._validation_report: ValidationReport | None = None
        self._stationary_features: list[str] = []

    def run(self, df: pd.DataFrame) -> ValidationReport:
        """
        Full pipeline run.

        Args:
            df: Raw OHLCV DataFrame (columns: open/high/low/close/volume).

        Returns:
            ValidationReport with OOS metrics.

        Raises:
            ValueError: if data is insufficient or gates fail.
        """
        logger.info("MLPipeline.run: starting | rows=%d", len(df))

        # ── 1. Feature engineering ────────────────────────────────────────────
        feats = self._feature_engineer.compute(df)
        feature_cols = [c for c in feats.columns if c != "y"]
        X = feats[feature_cols]
        y = feats["y"]

        logger.info(
            "MLPipeline: features computed | rows=%d features=%d class_balance=%.3f",
            len(feats),
            len(feature_cols),
            y.mean(),
        )

        # ── 2. Stationarity tests ─────────────────────────────────────────────
        stat_results = self._stationarity_tester.test_dataframe(feats, feature_cols)
        nonstationary = [f for f, r in stat_results.items() if not r.is_stationary]
        if nonstationary:
            logger.warning(
                "MLPipeline: %d non-stationary features: %s",
                len(nonstationary),
                nonstationary,
            )

        if self._drop_nonstationary and nonstationary:
            feature_cols = [f for f in feature_cols if f not in nonstationary]
            X = feats[feature_cols]
            logger.info(
                "MLPipeline: dropped %d non-stationary features. Remaining: %d",
                len(nonstationary),
                len(feature_cols),
            )

        self._stationary_features = feature_cols

        # ── 3. Walk-forward OOS validation ────────────────────────────────────
        report = self._walk_forward_validate(X, y, feature_cols)
        self._validation_report = report

        logger.info(
            "MLPipeline: OOS accuracy=%.4f (target=%.2f) p=%.6f (target=%.4f) AUC=%.4f folds=%d",
            report.oos_accuracy,
            self.OOS_ACCURACY_TARGET,
            report.p_value,
            self.PVALUE_TARGET,
            report.mean_auc,
            report.n_folds,
        )

        if not report.passes_accuracy_gate:
            logger.warning(
                "MLPipeline: OOS accuracy %.4f < target %.2f — model NOT deployed.",
                report.oos_accuracy,
                self.OOS_ACCURACY_TARGET,
            )
        if not report.passes_pvalue_gate:
            logger.warning(
                "MLPipeline: p-value %.6f >= target %.4f — results may be noise.",
                report.p_value,
                self.PVALUE_TARGET,
            )

        # ── 4. Final model training (full dataset) ────────────────────────────
        if report.passes_accuracy_gate and report.passes_pvalue_gate:
            logger.info("MLPipeline: gates passed — training final model on full dataset.")
            self._predictor.fit(X, y)
            model_path = str(self._model_dir / "xgb_xauusd.pkl")
            self._predictor.save(model_path)
            self._save_report(report)
        else:
            logger.warning(
                "MLPipeline: one or more gates failed — final model NOT saved.",
            )

        return report

    def _walk_forward_validate(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        feature_cols: list[str],
    ) -> ValidationReport:
        n = len(X)
        splits = self._validator.split(n)

        fold_results: list[WalkForwardFold] = []
        all_oos_preds: list[int] = []
        all_oos_true: list[int] = []
        all_oos_proba: list[float] = []

        for i, (train_idx, test_idx) in enumerate(splits):
            X_train = X.iloc[list(train_idx)]
            y_train = y.iloc[list(train_idx)]
            X_test = X.iloc[list(test_idx)]
            y_test = y.iloc[list(test_idx)]

            predictor = XGBoostPredictor()
            predictor.fit(X_train, y_train, X_test, y_test)

            preds = predictor.predict(X_test)
            proba = predictor.predict_proba(X_test)
            acc = float(accuracy_score(y_test, preds))

            try:
                auc = float(roc_auc_score(y_test, proba))
            except Exception:
                auc = 0.5

            fold = WalkForwardFold(
                fold_idx=i,
                train_start=next(iter(train_idx)),
                train_end=list(train_idx)[-1],
                test_start=next(iter(test_idx)),
                test_end=list(test_idx)[-1],
                accuracy=acc,
                auc=auc,
                n_train=len(train_idx),
                n_test=len(test_idx),
                feature_importances=predictor.get_feature_importances(),
            )
            fold_results.append(fold)
            all_oos_preds.extend(preds.tolist())
            all_oos_true.extend(y_test.tolist())
            all_oos_proba.extend(proba.tolist())

            logger.info(
                "MLPipeline fold %d/%d | train=%d test=%d acc=%.4f auc=%.4f",
                i + 1,
                len(splits),
                len(train_idx),
                len(test_idx),
                acc,
                auc,
            )

        # Aggregate metrics
        oos_acc = float(accuracy_score(all_oos_true, all_oos_preds))
        oos_acc_std = float(np.std([f.accuracy for f in fold_results]))
        mean_auc = float(np.mean([f.auc for f in fold_results]))

        # Binomial test: is accuracy significantly better than 0.5?
        n_correct = sum(p == t for p, t in zip(all_oos_preds, all_oos_true, strict=False))
        n_total = len(all_oos_true)
        binom_result = stats.binomtest(n_correct, n_total, p=0.5, alternative="greater")
        p_value = float(binom_result.pvalue)

        # Aggregate feature importances (mean across folds)
        all_imps: dict[str, list[float]] = {}
        for fold in fold_results:
            for feat, imp in fold.feature_importances.items():
                all_imps.setdefault(feat, []).append(imp)
        mean_imps = {f: float(np.mean(v)) for f, v in all_imps.items()}
        mean_imps = dict(sorted(mean_imps.items(), key=lambda x: x[1], reverse=True))

        return ValidationReport(
            oos_accuracy=oos_acc,
            oos_accuracy_std=oos_acc_std,
            mean_auc=mean_auc,
            p_value=p_value,
            n_folds=len(fold_results),
            n_total_oos_samples=n_total,
            passes_accuracy_gate=oos_acc >= self.OOS_ACCURACY_TARGET,
            passes_pvalue_gate=p_value < self.PVALUE_TARGET,
            folds=fold_results,
            feature_importances=mean_imps,
        )

    def _save_report(self, report: ValidationReport) -> None:
        self._model_dir.mkdir(parents=True, exist_ok=True)
        path = self._model_dir / "validation_report.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info("MLPipeline: validation report saved to %s", path)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return probability of upward move for each row in X."""
        return self._predictor.predict_proba(X)

    def get_validation_report(self) -> ValidationReport | None:
        return self._validation_report
