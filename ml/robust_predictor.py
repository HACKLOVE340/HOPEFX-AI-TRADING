# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# ml/robust_predictor.py
"""
Production ML pipeline with walk-forward validation,
regime detection, and overfitting prevention.
"""

import logging
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
)
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


class Regime(Enum):
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


@dataclass
class ModelConfig:
    """Configuration for robust ML training"""

    # Validation
    min_train_samples: int = 5000
    min_test_samples: int = 1000
    n_splits: int = 5  # Walk-forward splits
    purge_length: int = 10  # Bars to purge between train/test
    embargo_length: int = 5  # Bars to embargo at end

    # Feature engineering
    max_features: int = 50  # Limit to prevent overfitting
    feature_selection_method: str = "mutual_info"  # or "lasso", "correlation"

    # Model constraints
    max_depth: int = 5  # Shallow trees to prevent overfitting
    min_samples_leaf: int = 100  # Require sufficient samples per leaf
    max_leaves: int = 32

    # Regularization
    reg_alpha: float = 0.1  # L1 regularization
    reg_lambda: float = 1.0  # L2 regularization
    learning_rate: float = 0.01  # Slow learning

    # Ensembling
    ensemble_methods: List[str] = None  # ['xgb', 'lgb', 'rf']
    meta_model: str = "logistic"  # Stacking meta-learner

    def __post_init__(self):
        if self.ensemble_methods is None:
            self.ensemble_methods = ["xgb", "lgb"]


@dataclass
class PredictionResult:
    """Structured prediction with uncertainty estimates"""

    direction: int  # -1, 0, 1
    probability: float
    confidence: str  # 'high', 'medium', 'low'
    expected_return: float
    uncertainty: float  # Prediction variance
    regime: Regime
    model_agreement: float  # Agreement across ensemble
    features_importance: Dict[str, float]
    timestamp: datetime
    # thresholds_calibrated=False means the confidence boundaries (high/medium/low)
    # were set by the default heuristic (0.3/0.4/0.6/0.7) rather than derived
    # from held-out OOS data.  Call RobustPredictor.calibrate_thresholds() with
    # OOS predictions and outcomes to replace the defaults.
    thresholds_calibrated: bool = False


class RobustPredictor:
    """
    Production-grade predictor with regime awareness and overfitting protection.

    Key features:
    - Purged k-fold cross-validation for time series
    - Regime detection with model switching
    - Feature importance stability checks
    - Prediction uncertainty quantification
    - Automated model retraining triggers
    """

    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.meta_model = None
        self.selected_features: List[str] = []
        self.feature_importance_history: List[Dict] = []
        self.regime_detector = RegimeDetector()

        # Performance tracking
        self.oos_predictions: List[Dict] = []
        self.model_performance: Dict[str, List[float]] = {}
        self.last_retrain: Optional[datetime] = None

        # Stability checks
        self.feature_stability_threshold = (
            0.6  # Pearson correlation of importance across folds
        )

        # ── Confidence thresholds ─────────────────────────────────────────────
        # Default heuristic thresholds (uncalibrated).
        # Replace by calling calibrate_thresholds() with OOS predictions.
        #
        # Interpretation:
        #   prob > bullish_high_threshold  → direction=+1, confidence='high'
        #   prob > bullish_med_threshold   → direction=+1, confidence='medium'
        #   prob < bearish_high_threshold  → direction=-1, confidence='high'
        #   prob < bearish_med_threshold   → direction=-1, confidence='medium'
        #   otherwise                      → direction=0,  confidence='low'
        self._thresholds_calibrated: bool = False
        self._bullish_high_threshold: float = 0.70  # was hardcoded 0.7
        self._bullish_med_threshold: float = 0.60  # was hardcoded 0.6
        self._bearish_high_threshold: float = 0.30  # was hardcoded 0.3
        self._bearish_med_threshold: float = 0.40  # was hardcoded 0.4
        self._agreement_threshold: float = 0.60  # was hardcoded 0.6

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weights: Optional[np.ndarray] = None,
    ) -> Dict:
        """
        Train with walk-forward validation and overfitting checks.

        Returns training metrics and validation statistics.
        """
        logger.info(f"Starting robust training with {len(X)} samples")

        # 1. Feature engineering and selection
        X_features = self._engineer_features(X)
        self.selected_features = self._select_features(X_features, y)
        X_selected = X_features[self.selected_features]

        logger.info(f"Selected {len(self.selected_features)} features")

        # 2. Regime detection
        regimes = self.regime_detector.detect(X)
        logger.info(f"Detected regimes: {pd.Series(regimes).value_counts().to_dict()}")

        # 3. Walk-forward validation with purging
        cv_results = self._walk_forward_validation(
            X_selected,
            y,
            regimes,
            sample_weights,
        )

        # 4. Check for overfitting
        overfitting_score = self._calculate_overfitting(cv_results)
        if overfitting_score > 0.3:  # Train vs test performance gap
            logger.warning(f"High overfitting detected: {overfitting_score:.2f}")
            self._apply_stronger_regularization()

        # 5. Train final models on all data (with embargo)
        X_train, y_train = self._apply_embargo(X_selected, y)
        self._train_final_models(X_train, y_train, sample_weights)

        # 6. Feature stability check
        stability = self._check_feature_stability()
        logger.info(f"Feature stability: {stability:.2f}")

        self.last_retrain = datetime.now(timezone.utc)

        return {
            "cv_results": cv_results,
            "overfitting_score": overfitting_score,
            "feature_stability": stability,
            "selected_features": self.selected_features,
            "regime_distribution": pd.Series(regimes).value_counts().to_dict(),
        }

    def _walk_forward_validation(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        regimes: np.ndarray,
        sample_weights: Optional[np.ndarray],
    ) -> Dict:
        """Perform purged walk-forward cross-validation"""
        n_samples = len(X)
        fold_size = n_samples // self.config.n_splits

        results = {
            "train_scores": [],
            "test_scores": [],
            "feature_importances": [],
            "predictions": [],
            "probabilities": [],
        }

        for i in range(self.config.n_splits):
            # Define splits with purging
            test_start = i * fold_size
            test_end = min((i + 1) * fold_size, n_samples)

            # Purge: remove samples between train and test
            train_end = max(0, test_start - self.config.purge_length)

            X_train = X.iloc[:train_end]
            y_train = y.iloc[:train_end]
            X_test = X.iloc[test_end:]
            y_test = y.iloc[test_end:]

            if len(X_test) < self.config.min_test_samples:
                continue

            # Train ensemble for this fold
            fold_models = self._train_ensemble(
                X_train,
                y_train,
                sample_weights[:train_end] if sample_weights is not None else None,
            )

            # Evaluate
            preds, probs = self._ensemble_predict(fold_models, X_test)

            train_preds, _ = self._ensemble_predict(fold_models, X_train)

            results["train_scores"].append(accuracy_score(y_train, train_preds))
            results["test_scores"].append(accuracy_score(y_test, preds))
            results["predictions"].extend(preds)
            results["probabilities"].extend(probs)

            # Store feature importance
            fold_importance = self._aggregate_feature_importance(fold_models)
            results["feature_importances"].append(fold_importance)
            self.feature_importance_history.append(fold_importance)

        return results

    def _train_ensemble(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weights: Optional[np.ndarray],
    ) -> Dict[str, Any]:
        """Train diverse models for ensemble"""
        models = {}

        if "xgb" in self.config.ensemble_methods:
            models["xgb"] = xgb.XGBClassifier(
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                n_estimators=100,
                reg_alpha=self.config.reg_alpha,
                reg_lambda=self.config.reg_lambda,
                min_child_weight=self.config.min_samples_leaf,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                eval_metric="logloss",
            )
            models["xgb"].fit(X, y, sample_weight=sample_weights)

        if "lgb" in self.config.ensemble_methods:
            models["lgb"] = lgb.LGBMClassifier(
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                n_estimators=100,
                reg_alpha=self.config.reg_alpha,
                reg_lambda=self.config.reg_lambda,
                min_child_samples=self.config.min_samples_leaf,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbose=-1,
            )
            models["lgb"].fit(X, y, sample_weight=sample_weights)

        if "rf" in self.config.ensemble_methods:
            models["rf"] = RandomForestClassifier(
                n_estimators=100,
                max_depth=self.config.max_depth,
                min_samples_leaf=self.config.min_samples_leaf,
                max_leaf_nodes=self.config.max_leaves,
                random_state=42,
            )
            models["rf"].fit(X, y, sample_weight=sample_weights)

        return models

    def predict(
        self,
        X: pd.DataFrame,
        regime: Optional[Regime] = None,
    ) -> PredictionResult:
        """
        Make prediction with uncertainty quantification.
        """
        if not self.models:
            raise ValueError("Model not trained")

        # Feature engineering
        X_features = self._engineer_features(X)
        X_selected = X_features[self.selected_features]

        # Detect regime if not provided
        if regime is None:
            regime = self.regime_detector.detect_single(X_selected.iloc[-1:])

        # Get predictions from all models
        predictions = []
        probabilities = []

        for name, model in self.models.items():
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X_selected.iloc[-1:])[0]
                pred = np.argmax(proba)
                prob = proba[pred] if pred == 1 else proba[0]
            else:
                pred = model.predict(X_selected.iloc[-1:])[0]
                prob = 0.5

            predictions.append(pred)
            probabilities.append(prob)

        # Ensemble aggregation
        predictions = np.array(predictions)
        probabilities = np.array(probabilities)

        # Direction based on majority vote with confidence threshold
        mean_prob = np.mean(probabilities)
        std_prob = np.std(probabilities)

        # Model agreement
        agreement = np.mean(predictions == stats.mode(predictions)[0])

        # Uncertainty quantification
        uncertainty = std_prob + (1 - agreement) * 0.5

        # ── Determine direction and confidence using (possibly calibrated) thresholds ──
        # Thresholds are set by calibrate_thresholds() if OOS data is available,
        # otherwise the defaults (0.3/0.4/0.6/0.7) are used.
        if (
            mean_prob > self._bullish_med_threshold
            and agreement > self._agreement_threshold
        ):
            direction = 1
            confidence = (
                "high" if mean_prob > self._bullish_high_threshold else "medium"
            )
        elif (
            mean_prob < self._bearish_med_threshold
            and agreement > self._agreement_threshold
        ):
            direction = -1
            confidence = (
                "high" if mean_prob < self._bearish_high_threshold else "medium"
            )
        else:
            direction = 0  # No trade — uncertainty too high
            confidence = "low"

        # Expected return estimate (calibrated)
        expected_return = self._estimate_return(direction, mean_prob, regime)

        # Feature importance for this prediction
        current_importance = self._get_current_feature_importance(X_selected.iloc[-1])

        return PredictionResult(
            direction=direction,
            probability=float(mean_prob),
            confidence=confidence,
            expected_return=expected_return,
            uncertainty=float(uncertainty),
            regime=regime,
            model_agreement=float(agreement),
            features_importance=current_importance,
            timestamp=datetime.now(timezone.utc),
            thresholds_calibrated=self._thresholds_calibrated,
        )

    def calibrate_thresholds(
        self,
        oos_probabilities: np.ndarray,
        oos_outcomes: np.ndarray,
        n_bins: int = 10,
        min_precision: float = 0.55,
    ) -> Dict[str, float]:
        """
        Derive confidence thresholds from held-out OOS predictions.

        Replaces the default heuristic thresholds (0.3/0.4/0.6/0.7) with
        data-driven boundaries calibrated to achieve at least `min_precision`
        precision on the OOS set.

        Algorithm
        ---------
        1. Bin OOS probabilities into `n_bins` equal-width buckets.
        2. For each bin compute precision (fraction of correct direction calls).
        3. Find the lowest probability bin where precision >= min_precision
           for bullish calls, and the highest bin for bearish calls.
        4. Set thresholds to the bin boundaries.

        If fewer than 30 OOS samples are available the method logs a warning
        and leaves the default thresholds unchanged.

        Args:
            oos_probabilities : 1-D array of predicted probabilities (0–1)
            oos_outcomes      : 1-D array of true labels (1=up, 0=down)
            n_bins            : Number of probability bins
            min_precision     : Minimum precision required for a 'medium' signal

        Returns:
            Dict with the calibrated threshold values and calibration stats.
        """
        oos_probabilities = np.asarray(oos_probabilities, dtype=float)
        oos_outcomes = np.asarray(oos_outcomes, dtype=float)

        if len(oos_probabilities) < 30:
            logger.warning(
                "calibrate_thresholds: only %d OOS samples — need ≥30 for reliable "
                "calibration. Default thresholds unchanged.",
                len(oos_probabilities),
            )
            return {
                "calibrated": False,
                "reason": f"insufficient OOS samples ({len(oos_probabilities)} < 30)",
                "thresholds": self._current_thresholds(),
            }

        bins = np.linspace(0.0, 1.0, n_bins + 1)
        bin_stats = []
        for i in range(n_bins):
            lo, hi = bins[i], bins[i + 1]
            mask = (oos_probabilities >= lo) & (oos_probabilities < hi)
            if mask.sum() == 0:
                bin_stats.append({"lo": lo, "hi": hi, "n": 0, "precision": np.nan})
                continue
            precision = float(oos_outcomes[mask].mean())
            bin_stats.append(
                {"lo": lo, "hi": hi, "n": int(mask.sum()), "precision": precision},
            )

        # Bullish threshold: lowest bin mid-point where precision >= min_precision
        bullish_med = self._bullish_med_threshold  # fallback
        bullish_high = self._bullish_high_threshold
        for b in bin_stats:
            if (
                b["n"] >= 5
                and not np.isnan(b["precision"])
                and b["precision"] >= min_precision
            ):
                bullish_med = b["lo"]
                break
        for b in bin_stats:
            if (
                b["n"] >= 5
                and not np.isnan(b["precision"])
                and b["precision"] >= min(min_precision + 0.10, 0.70)
            ):
                bullish_high = b["lo"]
                break

        # Bearish threshold: highest bin mid-point where (1-precision) >= min_precision
        bearish_med = self._bearish_med_threshold
        bearish_high = self._bearish_high_threshold
        for b in reversed(bin_stats):
            if (
                b["n"] >= 5
                and not np.isnan(b["precision"])
                and (1.0 - b["precision"]) >= min_precision
            ):
                bearish_med = b["hi"]
                break
        for b in reversed(bin_stats):
            if (
                b["n"] >= 5
                and not np.isnan(b["precision"])
                and (1.0 - b["precision"]) >= min(min_precision + 0.10, 0.70)
            ):
                bearish_high = b["hi"]
                break

        # Sanity: bullish must be > 0.5, bearish must be < 0.5
        bullish_med = max(bullish_med, 0.50)
        bullish_high = max(bullish_high, bullish_med)
        bearish_med = min(bearish_med, 0.50)
        bearish_high = min(bearish_high, bearish_med)

        self._bullish_med_threshold = bullish_med
        self._bullish_high_threshold = bullish_high
        self._bearish_med_threshold = bearish_med
        self._bearish_high_threshold = bearish_high
        self._thresholds_calibrated = True

        result = {
            "calibrated": True,
            "n_oos_samples": len(oos_probabilities),
            "min_precision_target": min_precision,
            "thresholds": self._current_thresholds(),
            "bin_stats": bin_stats,
        }
        logger.info(
            "calibrate_thresholds: calibrated on %d OOS samples. "
            "bullish_med=%.3f bullish_high=%.3f bearish_med=%.3f bearish_high=%.3f",
            len(oos_probabilities),
            bullish_med,
            bullish_high,
            bearish_med,
            bearish_high,
        )
        return result

    def _current_thresholds(self) -> Dict[str, float]:
        """Return the current threshold values as a dict."""
        return {
            "bullish_high": self._bullish_high_threshold,
            "bullish_med": self._bullish_med_threshold,
            "bearish_high": self._bearish_high_threshold,
            "bearish_med": self._bearish_med_threshold,
            "agreement": self._agreement_threshold,
            "calibrated": self._thresholds_calibrated,
        }

    def _estimate_return(
        self,
        direction: int,
        probability: float,
        regime: Regime,
    ) -> float:
        """
        Expected return estimate scaled by regime multiplier.

        Base return is 10 bps per unit of probability edge above 0.5.
        Regime multipliers reflect empirical XAUUSD regime characteristics:
          - TRENDING:        1.5× (momentum persists)
          - MEAN_REVERTING:  0.8× (smaller moves, faster reversals)
          - HIGH_VOLATILITY: 0.5× (wide spreads, unpredictable fills)
          - LOW_VOLATILITY:  1.2× (tight spreads, cleaner signals)
          - UNKNOWN:         0.0× (no trade — regime unclear)

        Note: these multipliers are heuristic defaults. Replace with
        regime-stratified backtested returns once sufficient OOS data exists.
        """
        base_return = 0.001 * direction  # 10 bps base

        regime_multipliers = {
            Regime.TRENDING: 1.5,
            Regime.MEAN_REVERTING: 0.8,
            Regime.HIGH_VOLATILITY: 0.5,
            Regime.LOW_VOLATILITY: 1.2,
            Regime.UNKNOWN: 0.0,
        }

        return (
            base_return * regime_multipliers.get(regime, 1.0) * (probability - 0.5) * 2
        )

    def _engineer_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Create features with strict constraints to prevent lookahead bias"""
        features = pd.DataFrame(index=X.index)

        # Price-based features (lagged)
        for lag in [1, 2, 5, 10, 20]:
            features[f"return_lag_{lag}"] = X["close"].pct_change(lag).shift(1)
            features[f"volatility_{lag}"] = (
                X["close"].pct_change().rolling(lag).std().shift(1)
            )

        # Technical indicators (only using past data)
        features["sma_ratio"] = (
            X["close"].rolling(10).mean() / X["close"].rolling(30).mean()
        ).shift(1)

        features["rsi"] = self._calculate_rsi(X["close"], 14).shift(1)

        # Volume features
        if "volume" in X.columns:
            features["volume_sma_ratio"] = (
                X["volume"] / X["volume"].rolling(20).mean()
            ).shift(1)

        # Time features
        features["hour"] = X.index.hour
        features["day_of_week"] = X.index.dayofweek

        return features.dropna()

    def _select_features(self, X: pd.DataFrame, y: pd.Series) -> List[str]:
        """Select stable features using mutual information"""
        from sklearn.feature_selection import SelectKBest, mutual_info_classif

        # Remove highly correlated features first
        corr_matrix = X.corr().abs()
        upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
        to_drop = [column for column in upper.columns if any(upper[column] > 0.95)]
        X_filtered = X.drop(columns=to_drop)

        # Select top k by mutual information
        selector = SelectKBest(
            mutual_info_classif,
            k=min(self.config.max_features, len(X_filtered.columns)),
        )
        selector.fit(X_filtered, y)

        selected = X_filtered.columns[selector.get_support()].tolist()
        return selected

    def _calculate_overfitting(self, cv_results: Dict) -> float:
        """Calculate overfitting score as train-test performance gap"""
        train_mean = np.mean(cv_results["train_scores"])
        test_mean = np.mean(cv_results["test_scores"])
        return max(0, train_mean - test_mean)

    def _apply_stronger_regularization(self):
        """Increase regularization if overfitting detected"""
        self.config.reg_alpha *= 2
        self.config.reg_lambda *= 2
        self.config.max_depth = max(3, self.config.max_depth - 1)
        logger.info(
            f"Increased regularization: alpha={self.config.reg_alpha}, depth={self.config.max_depth}",
        )

    def _check_feature_stability(self) -> float:
        """Check if feature importance is stable across folds"""
        if len(self.feature_importance_history) < 2:
            return 1.0

        # Calculate correlation of importance rankings across folds
        correlations = []
        for i in range(len(self.feature_importance_history) - 1):
            imp1 = self.feature_importance_history[i]
            imp2 = self.feature_importance_history[i + 1]

            # Align features
            all_features = set(imp1.keys()) & set(imp2.keys())
            v1 = [imp1.get(f, 0) for f in all_features]
            v2 = [imp2.get(f, 0) for f in all_features]

            if len(v1) > 1:
                corr, _ = stats.pearsonr(v1, v2)
                correlations.append(corr)

        return np.mean(correlations) if correlations else 0.0

    def _apply_embargo(
        self,
        X: pd.DataFrame,
        y: pd.Series,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Remove recent data to prevent information leakage"""
        embargo_idx = len(X) - self.config.embargo_length
        return X.iloc[:embargo_idx], y.iloc[:embargo_idx]

    def _train_final_models(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weights: Optional[np.ndarray],
    ):
        """Train final models on all available data"""
        self.models = self._train_ensemble(X, y, sample_weights)

        # Train meta-model for stacking
        if self.config.meta_model == "logistic":
            # Generate meta-features
            meta_features = []
            for name, model in self.models.items():
                if hasattr(model, "predict_proba"):
                    probs = model.predict_proba(X)[:, 1]
                else:
                    probs = model.predict(X).astype(float)
                meta_features.append(probs)

            meta_X = np.column_stack(meta_features)
            self.meta_model = LogisticRegression(random_state=42)
            self.meta_model.fit(meta_X, y)

    def _ensemble_predict(
        self,
        models: Dict,
        X: pd.DataFrame,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generate ensemble predictions"""
        predictions = []
        probabilities = []

        for name, model in models.items():
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X)
                predictions.append(np.argmax(proba, axis=1))
                probabilities.append(proba[:, 1])
            else:
                pred = model.predict(X)
                predictions.append(pred)
                probabilities.append(pred.astype(float))

        # Average probabilities
        avg_proba = np.mean(probabilities, axis=0)
        final_pred = (avg_proba > 0.5).astype(int)

        return final_pred, avg_proba

    def _aggregate_feature_importance(self, models: Dict) -> Dict[str, float]:
        """Aggregate feature importance across ensemble"""
        importance = {}

        for name, model in models.items():
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
                for i, feat in enumerate(self.selected_features):
                    importance[feat] = importance.get(feat, 0) + imp[i] / len(models)

        return importance

    def _get_current_feature_importance(self, X_row: pd.Series) -> Dict[str, float]:
        """Get feature importance for current prediction using SHAP-like approximation"""
        # Simplified - implement actual SHAP for production
        base_importance = self._aggregate_feature_importance(self.models)

        # Weight by feature value deviation from mean
        weighted = {}
        for feat, imp in base_importance.items():
            if feat in X_row.index:
                # Normalize importance by feature value
                weighted[feat] = imp * abs(X_row[feat])

        return dict(sorted(weighted.items(), key=lambda x: x[1], reverse=True)[:10])

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI without lookahead bias"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def should_retrain(self, recent_performance: List[float]) -> bool:
        """Determine if model needs retraining based on performance decay"""
        if len(recent_performance) < 30:
            return False

        # Check for significant performance decay
        recent_mean = np.mean(recent_performance[-30:])
        historical_mean = (
            np.mean(recent_performance[-90:])
            if len(recent_performance) >= 90
            else np.mean(recent_performance)
        )

        if recent_mean < historical_mean * 0.7:  # 30% decay
            logger.warning(
                f"Performance decay detected: {recent_mean:.3f} vs {historical_mean:.3f}",
            )
            return True

        # Check time since last train
        if (
            self.last_retrain
            and (datetime.now(timezone.utc) - self.last_retrain).days > 7
        ):
            return True

        return False

    def save(self, path: str):
        """Save model state"""
        state = {
            "models": {
                k: joblib.dump(v, f"{path}/{k}.joblib") for k, v in self.models.items()
            },
            "config": self.config,
            "selected_features": self.selected_features,
            "feature_importance_history": self.feature_importance_history,
            "last_retrain": self.last_retrain,
        }
        joblib.dump(state, f"{path}/state.joblib")

    def load(self, path: str):
        """Load model state"""
        state = joblib.load(f"{path}/state.joblib")
        self.config = state["config"]
        self.selected_features = state["selected_features"]
        self.feature_importance_history = state["feature_importance_history"]
        self.last_retrain = state["last_retrain"]

        for name in self.config.ensemble_methods:
            self.models[name] = joblib.load(f"{path}/{name}.joblib")


class RegimeDetector:
    """Detect market regime using unsupervised learning"""

    def __init__(self):
        self.lookback = 50
        self.volatility_threshold = 0.02
        self.trend_threshold = 0.001

    def detect(self, X: pd.DataFrame) -> np.ndarray:
        """Detect regime for each time point"""
        returns = X["close"].pct_change()
        volatility = returns.rolling(self.lookback).std()
        trend = (
            X["close"]
            .rolling(self.lookback)
            .apply(lambda x: np.polyfit(range(len(x)), x, 1)[0])
        )

        regimes = []
        for i in range(len(X)):
            if i < self.lookback:
                regimes.append(Regime.UNKNOWN)
                continue

            vol = volatility.iloc[i]
            tr = trend.iloc[i]

            if vol > self.volatility_threshold * 2:
                regimes.append(Regime.HIGH_VOLATILITY)
            elif vol < self.volatility_threshold * 0.5:
                regimes.append(Regime.LOW_VOLATILITY)
            elif abs(tr) > self.trend_threshold:
                regimes.append(Regime.TRENDING)
            else:
                regimes.append(Regime.MEAN_REVERTING)

        return np.array(regimes)

    def detect_single(self, X: pd.DataFrame) -> Regime:
        """Detect current regime"""
        regimes = self.detect(X)
        return regimes[-1] if len(regimes) > 0 else Regime.UNKNOWN
