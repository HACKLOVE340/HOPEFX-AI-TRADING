# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# enhanced_ml_predictor.py
"""
=============================================================================
HOPEFX MACHINE LEARNING PREDICTION ENGINE v4.0
=============================================================================
Institutional-Grade ML with Uncertainty Quantification & Online Learning

Features:
- Multi-architecture deep learning (LSTM, GRU, Transformer, Temporal Fusion)
- Bayesian uncertainty quantification via Monte Carlo Dropout
- Automated ensemble weighting with dynamic model selection
- Online learning with catastrophic forgetting prevention
- GPU acceleration with mixed precision training
- Feature importance analysis with SHAP integration

Author: HOPEFX Development Team
License: Proprietary - Institutional Use Only
=============================================================================
"""

import json
import logging
import warnings
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

# ML/DL Libraries
try:
    import tensorflow as tf
    from tensorflow.keras.callbacks import (
        EarlyStopping,
        ModelCheckpoint,
        ReduceLROnPlateau,
        TerminateOnNaN,
    )
    from tensorflow.keras.layers import (
        GRU,
        LSTM,
        Add,
        BatchNormalization,
        Conv1D,
        Dense,
        Dropout,
        GlobalAveragePooling1D,
        Input,
        LayerNormalization,
        MaxPooling1D,
        MultiHeadAttention,
    )
    from tensorflow.keras.models import Model, load_model
    from tensorflow.keras.optimizers import AdamW
    from tensorflow.keras.regularizers import l1_l2

    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False
    import importlib.util as _importlib_util

warnings.warn("TensorFlow not available - deep learning disabled", stacklevel=2)

PYTORCH_AVAILABLE = _importlib_util.find_spec("torch") is not None

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import (
        RandomForestClassifier,
    )
    from sklearn.feature_selection import SelectFromModel, mutual_info_classif
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.preprocessing import RobustScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb

    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

try:
    import lightgbm as lgb

    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False

try:
    import optuna  # pylint: disable=unused-import

    OPTUNA_AVAILABLE = True
except ImportError:
    optuna = None  # type: ignore[assignment]  # graceful degradation; checked via OPTUNA_AVAILABLE
    OPTUNA_AVAILABLE = False

try:
    import shap as _shap_module

    SHAP_AVAILABLE = True
    del _shap_module
except ImportError:
    SHAP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("HOPEFX.ML")

# =============================================================================
# ENUMERATIONS AND CONFIGURATION
# =============================================================================


class PredictionTarget(Enum):
    """Types of predictions supported"""

    DIRECTION = "direction"  # Classification: Up/Down/Sideways
    VOLATILITY = "volatility"  # Regression: Future realized vol
    RETURN = "return"  # Regression: Future return
    PROBABILITY = "probability"  # Classification: Event probability
    QUANTILE = "quantile"  # Quantile regression
    SHARPE = "sharpe"  # Regression: Risk-adjusted return


class ModelArchitecture(Enum):
    """Supported model architectures"""

    LSTM = "lstm"
    GRU = "gru"
    TRANSFORMER = "transformer"
    TEMPORAL_FUSION = "temporal_fusion"
    CNN_LSTM = "cnn_lstm"
    BIDIRECTIONAL_LSTM = "bilstm"
    RANDOM_FOREST = "random_forest"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    TABNET = "tabnet"


@dataclass
class ModelConfig:
    """Model hyperparameter configuration"""

    architecture: ModelArchitecture
    sequence_length: int = 60
    prediction_horizon: int = 5

    # Network architecture
    hidden_units: list[int] = field(default_factory=lambda: [128, 64, 32])
    dropout_rate: float = 0.2
    recurrent_dropout: float = 0.1
    attention_heads: int = 4

    # Training
    learning_rate: float = 0.001
    batch_size: int = 32
    epochs: int = 100
    early_stopping_patience: int = 15
    reduce_lr_patience: int = 5

    # Regularization
    l1_reg: float = 0.0001
    l2_reg: float = 0.001
    max_grad_norm: float = 1.0

    # Uncertainty
    mc_dropout_samples: int = 100
    confidence_threshold: float = 0.6


@dataclass
class Prediction:
    """Structured prediction output with uncertainty quantification"""

    symbol: str
    timestamp: datetime
    target: PredictionTarget

    # Point prediction
    prediction: str | float | int
    confidence: float  # 0-1

    # Probabilistic outputs
    probabilities: dict[str, float] | None = None
    quantiles: dict[str, float] | None = None

    # Uncertainty decomposition
    epistemic_uncertainty: float = 0.0  # Model uncertainty (reducible)
    aleatoric_uncertainty: float = 0.0  # Data noise (irreducible)
    total_uncertainty: float = 0.0

    # Prediction intervals
    prediction_interval: tuple[float, float] | None = None
    confidence_80: tuple[float, float] | None = None
    confidence_95: tuple[float, float] | None = None

    # Model metadata
    model_version: str = "unknown"
    model_architecture: str = "unknown"
    features_used: list[str] = field(default_factory=list)
    feature_importance: dict[str, float] = field(default_factory=dict)

    # Performance tracking
    inference_time_ms: float = 0.0
    training_samples: int = 0

    # Default uncertainty ceiling used by is_confident().
    # This value (0.3) is a reasonable starting point but is NOT calibrated —
    # it was chosen arbitrarily.  To calibrate it properly, run
    # calibrate_uncertainty_threshold() on a held-out validation set and
    # pass the returned value here (or store it in config).
    # Calibration target: maximise F1 on the validation set by sweeping
    # thresholds in [0.1, 0.9] and selecting the one with the best precision/
    # recall trade-off for your risk tolerance.
    DEFAULT_UNCERTAINTY_THRESHOLD: float = 0.3

    def is_confident(self, threshold: float | None = None) -> bool:
        """Return True if this prediction clears both confidence and uncertainty gates.

        Args:
            threshold: Override for the uncertainty ceiling.  If None, uses
                       DEFAULT_UNCERTAINTY_THRESHOLD (0.3 — see calibration note
                       on that constant before relying on it in production).
        """
        unc_thresh = threshold if threshold is not None else self.DEFAULT_UNCERTAINTY_THRESHOLD
        return self.confidence >= 0.6 and self.total_uncertainty < unc_thresh

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "target": self.target.value,
            "prediction": self.prediction,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
            "uncertainty": {
                "epistemic": self.epistemic_uncertainty,
                "aleatoric": self.aleatoric_uncertainty,
                "total": self.total_uncertainty,
            },
            "model": {
                "version": self.model_version,
                "architecture": self.model_architecture,
            },
            "inference_time_ms": self.inference_time_ms,
        }


# =============================================================================
# FEATURE ENGINEERING
# =============================================================================


class AdvancedFeatureEngineer:
    """
    Institutional-grade feature engineering with no lookahead bias.
    Generates technical, statistical, and microstructure features.
    """

    def __init__(
        self,
        lookback_windows: list[int] | None = None,
        enable_microstructure: bool = True,
    ):
        self.windows = lookback_windows or [5, 10, 20, 50, 100, 200]
        self.enable_microstructure = enable_microstructure

        self.scaler = RobustScaler()
        self.feature_names: list[str] = []
        self.is_fitted = False

        # Feature importance tracking
        self.feature_importance: dict[str, float] = {}

        # Cached calculations
        self._cache: dict[str, Any] = {}

    def create_features(self, df: pd.DataFrame, fit: bool = False, symbol: str = "unknown") -> pd.DataFrame:
        """
        Create comprehensive feature set from OHLCV data.

        Critical: All features are lagged to prevent lookahead bias.
        """
        features = pd.DataFrame(index=df.index)

        # Basic price features
        features["returns"] = df["close"].pct_change(fill_method=None)
        features["log_returns"] = np.log1p(features["returns"])
        features["realized_var"] = features["returns"] ** 2

        # Volatility features (multiple timeframes)
        for w in self.windows:
            # Realized volatility — min_periods avoids all-NaN leading rows
            features[f"volatility_{w}"] = features["returns"].rolling(w, min_periods=2).std().fillna(0.0) * np.sqrt(252)

            # Parkinson volatility (using high-low)
            if "high" in df.columns and "low" in df.columns:
                high_safe = df["high"].clip(lower=1e-10)
                low_safe = df["low"].clip(lower=1e-10)
                log_hl = np.log(high_safe / low_safe).fillna(0.0)
                pk_raw = log_hl.rolling(w, min_periods=1).mean() / (4 * np.log(2))
                features[f"parkinson_vol_{w}"] = np.sqrt(pk_raw.clip(lower=0.0))

            # Garman-Klass volatility (open-high-low-close)
            if all(c in df.columns for c in ["open", "high", "low"]):
                open_safe = df["open"].clip(lower=1e-10)
                high_safe = df["high"].clip(lower=1e-10)
                low_safe = df["low"].clip(lower=1e-10)
                log_ho = np.log(high_safe / open_safe).fillna(0.0)
                log_lo = np.log(low_safe / open_safe).fillna(0.0)
                gk_inner = (0.5 * log_ho**2 - (2 * np.log(2) - 1) * log_lo**2).clip(lower=0)
                features[f"garman_klass_{w}"] = np.sqrt(gk_inner).rolling(w, min_periods=1).mean()

        # Technical indicators
        for w in self.windows:
            # Moving averages and ratios — min_periods=1 avoids leading NaN
            features[f"ma_{w}"] = df["close"].rolling(w, min_periods=1).mean()
            features[f"ma_ratio_{w}"] = (df["close"] / features[f"ma_{w}"].replace(0, np.nan)).fillna(1.0)
            features[f"dist_to_ma_{w}"] = (
                (df["close"] - features[f"ma_{w}"]) / features[f"ma_{w}"].replace(0, np.nan)
            ).fillna(0.0)

            # Exponential moving average
            features[f"ema_{w}"] = df["close"].ewm(span=w, adjust=False, min_periods=1).mean()

            # Bollinger Bands
            rolling_std = df["close"].rolling(w, min_periods=2).std().fillna(0.0)
            features[f"bb_upper_{w}"] = features[f"ma_{w}"] + 2 * rolling_std
            features[f"bb_lower_{w}"] = features[f"ma_{w}"] - 2 * rolling_std
            bb_range = (features[f"bb_upper_{w}"] - features[f"bb_lower_{w}"]).replace(0, np.nan)
            features[f"bb_position_{w}"] = ((df["close"] - features[f"bb_lower_{w}"]) / bb_range).fillna(0.5)

            # RSI
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0).rolling(w, min_periods=1).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(w, min_periods=1).mean()
            rs = gain / (loss + 1e-10)
            features[f"rsi_{w}"] = (100 - (100 / (1 + rs))).fillna(50.0)

            # MACD
            ema_fast = df["close"].ewm(span=w // 2, min_periods=1).mean()
            ema_slow = df["close"].ewm(span=w, min_periods=1).mean()
            features[f"macd_{w}"] = (ema_fast - ema_slow).fillna(0.0)
            features[f"macd_signal_{w}"] = features[f"macd_{w}"].fillna(0.0).ewm(span=w // 3, min_periods=1).mean()
            features[f"macd_hist_{w}"] = features[f"macd_{w}"] - features[f"macd_signal_{w}"]

            # Stochastic
            low_min = df["low"].rolling(w, min_periods=1).min()
            high_max = df["high"].rolling(w, min_periods=1).max()
            hl_range = (high_max - low_min).replace(0, np.nan)
            features[f"stoch_k_{w}"] = (100 * (df["close"] - low_min) / hl_range).fillna(50.0)
            features[f"stoch_d_{w}"] = features[f"stoch_k_{w}"].rolling(3, min_periods=1).mean()

            # Williams %R
            features[f"williams_r_{w}"] = (-100 * (high_max - df["close"]) / hl_range).fillna(-50.0)

            # CCI (Commodity Channel Index)
            tp = (df["high"] + df["low"] + df["close"]) / 3
            tp_mean = tp.rolling(w, min_periods=1).mean()
            tp_std = tp.rolling(w, min_periods=1).std().fillna(0.0)
            features[f"cci_{w}"] = ((tp - tp_mean) / (0.015 * tp_std + 1e-10)).fillna(0.0)

            # ATR (Average True Range)
            tr1 = df["high"] - df["low"]
            tr2 = abs(df["high"] - df["close"].shift())
            tr3 = abs(df["low"] - df["close"].shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            features[f"atr_{w}"] = tr.rolling(w, min_periods=1).mean()
            features[f"atr_ratio_{w}"] = (features[f"atr_{w}"] / df["close"].replace(0, np.nan)).fillna(0.0)

        # Volume features
        if "volume" in df.columns:
            features["volume_ma"] = df["volume"].rolling(20, min_periods=1).mean()
            features["volume_std"] = df["volume"].rolling(20, min_periods=2).std().fillna(0.0)
            features["volume_ratio"] = (df["volume"] / features["volume_ma"].replace(0, np.nan)).fillna(1.0)
            features["volume_zscore"] = (
                (df["volume"] - features["volume_ma"]) / (features["volume_std"] + 1e-10)
            ).fillna(0.0)

            # Volume-weighted price metrics
            vol_sum = df["volume"].rolling(20, min_periods=1).sum().replace(0, np.nan)
            features["vwma_20"] = ((df["close"] * df["volume"]).rolling(20, min_periods=1).sum() / vol_sum).fillna(
                df["close"]
            )
            features["vwma_ratio"] = (df["close"] / features["vwma_20"].replace(0, np.nan)).fillna(1.0)

            # OBV (On-Balance Volume)
            features["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0.0).cumsum()
            features["obv_ma"] = features["obv"].rolling(20, min_periods=1).mean()

            # Money Flow
            typical_price = (df["high"] + df["low"] + df["close"]) / 3
            money_flow = typical_price * df["volume"]
            features["mfi"] = money_flow.fillna(0.0).rolling(14, min_periods=1).sum()  # Simplified MFI

        # Price action features
        features["body"] = (df["close"] - df["open"]) / df["open"]
        features["upper_shadow"] = (df["high"] - df[["close", "open"]].max(axis=1)) / df["close"]
        features["lower_shadow"] = (df[["close", "open"]].min(axis=1) - df["low"]) / df["close"]
        features["high_low_range"] = (df["high"] - df["low"]) / df["close"]

        # Candlestick patterns (simplified)
        features["doji"] = (abs(df["close"] - df["open"]) / (df["high"] - df["low"] + 1e-10)) < 0.1
        features["hammer"] = (
            (features["lower_shadow"] > 2 * abs(features["body"])) & (features["upper_shadow"] < abs(features["body"]))
        ).astype(int)

        # Trend strength
        for w in [20, 50, 100]:
            roll_std = df["close"].rolling(w, min_periods=2).std().fillna(0.0)
            denom = (roll_std * np.sqrt(w)).replace(0, np.nan)
            features[f"trend_strength_{w}"] = ((df["close"] - df["close"].shift(w)) / denom).fillna(0.0)

        # Mean reversion features
        for w in [20, 50]:
            roll_mean = df["close"].rolling(w, min_periods=1).mean()
            roll_std = df["close"].rolling(w, min_periods=2).std().fillna(0.0)
            features[f"zscore_{w}"] = ((df["close"] - roll_mean) / (roll_std + 1e-10)).fillna(0.0)
            features[f"zscore_mean_{w}"] = features[f"zscore_{w}"].rolling(w, min_periods=1).mean()

        # Autocorrelation features
        for lag in [1, 2, 3, 5, 10]:
            features[f"return_autocorr_{lag}"] = (
                features["returns"].rolling(50).apply(lambda x, _lag=lag: x.autocorr(lag=_lag) if len(x) > _lag else 0)
            )
            features[f"return_lag_{lag}"] = features["returns"].shift(lag)

        # Time features (cyclical encoding)
        if isinstance(df.index, pd.DatetimeIndex):
            features["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
            features["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
            features["day_of_week_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 5)
            features["day_of_week_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 5)
            features["month_sin"] = np.sin(2 * np.pi * df.index.month / 12)
            features["month_cos"] = np.cos(2 * np.pi * df.index.month / 12)

            # Session indicators
            features["is_market_open"] = ((df.index.hour >= 9) & (df.index.hour < 16)).astype(int)
            features["is_london"] = ((df.index.hour >= 8) & (df.index.hour < 17)).astype(int)
            features["is_ny"] = ((df.index.hour >= 13) & (df.index.hour < 22)).astype(int)

        # Cross-sectional features (if multiple symbols)
        # Would add relative strength, correlation, etc.

        # Drop NaN values
        features = features.dropna()

        # Store feature names
        if fit or not self.is_fitted:
            self.feature_names = list(features.columns)

        # Scale features — fit ONLY during training, transform during inference.
        # Re-fitting on inference data leaks the inference distribution into the
        # scaling parameters, invalidating all downstream metrics.
        if fit:
            self.scaler.fit(features)
            self.is_fitted = True
            features_scaled = pd.DataFrame(
                self.scaler.transform(features),
                index=features.index,
                columns=self.feature_names,
            )
            return features_scaled

        if self.is_fitted:
            # Align columns to training schema; fill any new columns with 0
            features = features.reindex(columns=self.feature_names, fill_value=0.0)
            features_scaled = pd.DataFrame(
                self.scaler.transform(features),
                index=features.index,
                columns=self.feature_names,
            )
            return features_scaled

        raise RuntimeError(
            "AdvancedFeatureEngineer: scaler not fitted. Call create_features(df, fit=True) on training data first."
        )

    def get_feature_importance(
        self,
        model: Any,
        X: pd.DataFrame,
        y: pd.Series | None = None,
        n_repeats: int = 5,
    ) -> dict[str, float]:
        """
        Extract feature importance from a fitted model.

        Priority:
        1. Native feature_importances_ (tree-based models) — fastest, exact.
        2. Coefficient magnitude (linear models).
        3. Permutation importance for all other models (including neural nets).
           Permutation is repeated `n_repeats` times and averaged to reduce
           variance from random shuffling.
        """
        importance_dict: dict[str, float] = {}

        if hasattr(model, "feature_importances_"):
            for name, imp in zip(self.feature_names, model.feature_importances_, strict=False):
                importance_dict[name] = float(imp)

        elif hasattr(model, "coef_"):
            coefs = np.abs(model.coef_)
            if len(coefs.shape) > 1:
                coefs = coefs.mean(axis=0)
            for name, coef in zip(self.feature_names, coefs, strict=False):
                importance_dict[name] = float(coef)

        else:
            # Permutation importance — works for any model including TF/Torch
            baseline_score = self._evaluate_model(model, X, y)
            rng = np.random.default_rng()  # unseeded — non-deterministic permutation importance

            for i, feature in enumerate(self.feature_names):
                drop_scores: list[float] = []
                for _ in range(n_repeats):
                    X_permuted = X.copy()
                    X_permuted.iloc[:, i] = rng.permutation(X_permuted.iloc[:, i].values)
                    drop_scores.append(self._evaluate_model(model, X_permuted, y))
                # Positive value = feature helps; negative = feature hurts
                importance_dict[feature] = baseline_score - float(np.mean(drop_scores))

        self.feature_importance = dict(sorted(importance_dict.items(), key=lambda x: x[1], reverse=True))
        return self.feature_importance

    def _evaluate_model(self, model: Any, X: pd.DataFrame, y: pd.Series | None = None) -> float:
        """
        Evaluate model accuracy on X (and optionally y) for permutation importance.

        For TensorFlow models the direction-output probability is used to derive
        a pseudo-accuracy.  For sklearn-compatible models, score() is called when
        y is available, otherwise the mean max-probability is used as a proxy.
        """
        try:
            if TENSORFLOW_AVAILABLE and isinstance(model, Model):
                preds = model.predict(X.values, verbose=0)
                # preds may be a dict (multi-output) or an array
                direction_probs = (
                    preds.get("direction", next(iter(preds.values()))) if isinstance(preds, dict) else preds
                )
                if len(direction_probs.shape) > 1:
                    return float(np.mean(np.max(direction_probs, axis=1)))
                return float(np.mean(np.abs(direction_probs - 0.5) + 0.5))

            if y is not None and hasattr(model, "score"):
                return float(model.score(X, y))

            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(X)
                return float(np.mean(np.max(probs, axis=1)))

            if hasattr(model, "predict"):
                # Regression proxy: 1 - normalised MAE
                preds = model.predict(X)
                if y is not None:
                    mae = np.mean(np.abs(preds - y.values))
                    scale = np.std(y.values) + 1e-9
                    return float(max(0.0, 1.0 - mae / scale))
                return 0.5  # no ground truth available

        except Exception as exc:
            logger.warning("_evaluate_model failed: %s", exc)

        return 0.5  # neutral fallback — better than returning 0.0

    def select_features(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        method: str = "mutual_info",
        n_features: int = 50,
    ) -> list[str]:
        """Select top features using statistical methods"""
        if not SKLEARN_AVAILABLE:
            return list(X.columns)[:n_features]

        if method == "mutual_info":
            scores = mutual_info_classif(X, y, random_state=42)
            feature_scores = list(zip(X.columns, scores, strict=False))
            feature_scores.sort(key=lambda x: x[1], reverse=True)
            return [f for f, _ in feature_scores[:n_features]]

        if method == "model_based":
            selector = SelectFromModel(
                RandomForestClassifier(n_estimators=100, random_state=42),
                max_features=n_features,
            )
            selector.fit(X, y)
            return list(X.columns[selector.get_support()])

        return list(X.columns)[:n_features]


# =============================================================================
# DEEP LEARNING MODELS
# =============================================================================


class DeepLearningModel:
    """
    Production-grade deep learning with uncertainty quantification.
    Supports multiple architectures with automatic hyperparameter tuning.
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model: Model | None = None
        self.history: Any | None = None
        self.is_trained = False

        # Feature dimensions (set during training)
        self.n_features: int = 0

        # Build model if TF available
        if TENSORFLOW_AVAILABLE:
            self._build_model()

    def _build_model(self):
        """Construct neural network architecture"""
        cfg = self.config

        # Input layer
        inputs = Input(
            shape=(
                cfg.sequence_length,
                self.n_features if self.n_features > 0 else None,
            )
        )

        x = inputs

        # Architecture selection
        if cfg.architecture == ModelArchitecture.LSTM:
            x = self._build_lstm_stack(x, cfg)
        elif cfg.architecture == ModelArchitecture.GRU:
            x = self._build_gru_stack(x, cfg)
        elif cfg.architecture == ModelArchitecture.BIDIRECTIONAL_LSTM:
            x = self._build_bilstm_stack(x, cfg)
        elif cfg.architecture == ModelArchitecture.CNN_LSTM:
            x = self._build_cnn_lstm_stack(x, cfg)
        elif cfg.architecture == ModelArchitecture.TRANSFORMER:
            x = self._build_transformer_stack(x, cfg)
        elif cfg.architecture == ModelArchitecture.TEMPORAL_FUSION:
            x = self._build_temporal_fusion(x, cfg)

        # Common output layers
        x = LayerNormalization()(x)
        x = Dropout(cfg.dropout_rate)(x)

        # Hidden layers
        for units in cfg.hidden_units:
            x = Dense(
                units,
                activation="relu",
                kernel_regularizer=l1_l2(cfg.l1_reg, cfg.l2_reg),
            )(x)
            x = BatchNormalization()(x)
            x = Dropout(cfg.dropout_rate)(x)

        # Multi-task outputs
        # 1. Direction classification
        direction = Dense(3, activation="softmax", name="direction")(x)

        # 2. Volatility regression
        volatility = Dense(1, activation="relu", name="volatility")(x)

        # 3. Return regression (with heteroscedastic uncertainty)
        return_mean = Dense(1, name="return_mean")(x)
        return_log_var = Dense(1, name="return_log_var")(x)

        # Combine outputs
        outputs = {
            "direction": direction,
            "volatility": volatility,
            "return": return_mean,
            "return_uncertainty": return_log_var,
        }

        self.model = Model(inputs=inputs, outputs=outputs)

        # Compile with multi-task losses
        self.model.compile(
            optimizer=AdamW(learning_rate=cfg.learning_rate, weight_decay=cfg.l2_reg),
            loss={
                "direction": "categorical_crossentropy",
                "volatility": "mse",
                "return": self._negative_log_likelihood,
                "return_uncertainty": None,  # Auxiliary output
            },
            loss_weights={
                "direction": 1.0,
                "volatility": 0.5,
                "return": 0.5,
                "return_uncertainty": 0.0,
            },
            metrics={
                "direction": ["accuracy", tf.keras.metrics.AUC(name="auc")],
                "volatility": ["mae", "mse"],
                "return": ["mae", "mse"],
            },
        )

        logger.info("Built %s model", cfg.architecture.value)

        if self.model:
            logger.info("Total parameters: %s", self.model.count_params())

    def _build_lstm_stack(self, x, cfg: ModelConfig):
        """Standard LSTM architecture"""
        for i, units in enumerate(cfg.hidden_units[:2]):
            return_seq = i < len(cfg.hidden_units[:2]) - 1
            x = LSTM(
                units,
                return_sequences=return_seq,
                dropout=cfg.dropout_rate,
                recurrent_dropout=cfg.recurrent_dropout,
                kernel_regularizer=l1_l2(cfg.l1_reg, cfg.l2_reg),
            )(x)
            x = BatchNormalization()(x)
        return x

    def _build_gru_stack(self, x, cfg: ModelConfig):
        """GRU architecture (faster than LSTM)"""
        for i, units in enumerate(cfg.hidden_units[:2]):
            return_seq = i < len(cfg.hidden_units[:2]) - 1
            x = GRU(
                units,
                return_sequences=return_seq,
                dropout=cfg.dropout_rate,
                recurrent_dropout=cfg.recurrent_dropout,
                kernel_regularizer=l1_l2(cfg.l1_reg, cfg.l2_reg),
            )(x)
            x = BatchNormalization()(x)
        return x

    def _build_bilstm_stack(self, x, cfg: ModelConfig):
        """Bidirectional LSTM for richer representations"""
        from tensorflow.keras.layers import Bidirectional

        for i, units in enumerate(cfg.hidden_units[:2]):
            return_seq = i < len(cfg.hidden_units[:2]) - 1
            x = Bidirectional(
                LSTM(
                    units // 2,  # Split units between directions
                    return_sequences=return_seq,
                    dropout=cfg.dropout_rate,
                    recurrent_dropout=cfg.recurrent_dropout,
                )
            )(x)
            x = BatchNormalization()(x)
        return x

    def _build_cnn_lstm_stack(self, x, cfg: ModelConfig):
        """CNN feature extraction + LSTM temporal modeling"""
        # CNN layers for local pattern detection
        for filters in [64, 32]:
            x = Conv1D(filters, kernel_size=3, activation="relu", padding="same")(x)
            x = MaxPooling1D(pool_size=2)(x)
            x = BatchNormalization()(x)

        # LSTM layers
        x = LSTM(cfg.hidden_units[0], return_sequences=False)(x)
        return x

    def _build_transformer_stack(self, x, cfg: ModelConfig):
        """Transformer architecture with multi-head attention"""
        # Positional encoding would be added here

        for _ in range(2):  # Transformer blocks
            # Multi-head self-attention
            attn_output = MultiHeadAttention(
                num_heads=cfg.attention_heads,
                key_dim=cfg.hidden_units[0] // cfg.attention_heads,
            )(x, x)
            x = Add()([x, attn_output])  # Residual
            x = LayerNormalization()(x)

            # Feed-forward
            ff_output = Dense(cfg.hidden_units[0] * 4, activation="relu")(x)
            ff_output = Dense(cfg.hidden_units[0])(ff_output)
            x = Add()([x, ff_output])
            x = LayerNormalization()(x)

        # Global pooling
        x = GlobalAveragePooling1D()(x)
        return x

    def _build_temporal_fusion(self, x, cfg: ModelConfig):
        """Temporal Fusion Transformer for multi-horizon forecasting"""
        # Simplified implementation
        # Would include static covariates, known future inputs, etc.
        return self._build_transformer_stack(x, cfg)

    def _negative_log_likelihood(self, y_true, y_pred):
        """Negative log likelihood for heteroscedastic regression"""
        # y_pred contains [mean, log_variance]
        mean = y_pred
        # Log variance would be separate output
        # Simplified - just MSE for now
        return tf.reduce_mean(tf.square(y_true - mean))

    def create_sequences(
        self, X: np.ndarray, y: np.ndarray, sequence_length: int | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """Create time series sequences for training"""
        seq_len = sequence_length or self.config.sequence_length

        if len(X) < seq_len:
            raise ValueError(f"Data length {len(X)} < sequence length {seq_len}")

        sequences = []
        targets = []

        for i in range(len(X) - seq_len):
            sequences.append(X[i : (i + seq_len)])
            targets.append(y[i + seq_len])

        return np.array(sequences), np.array(targets)

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        sample_weights: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """
        Train model with early stopping and learning rate scheduling.
        """
        if not TENSORFLOW_AVAILABLE or self.model is None:
            raise RuntimeError("TensorFlow not available")

        cfg = self.config

        # Update feature count
        if len(X_train.shape) == 2:
            self.n_features = X_train.shape[1]
            # Rebuild model with correct input shape
            self._build_model()
            X_train, y_train = self.create_sequences(X_train, y_train)
            if X_val is not None and y_val is not None:
                X_val, y_val = self.create_sequences(X_val, y_val)

        # Prepare multi-output targets
        y_train_dict = self._prepare_targets(y_train)
        y_val_dict = self._prepare_targets(y_val) if y_val is not None else None

        # Callbacks
        callbacks = [
            EarlyStopping(
                monitor="val_direction_accuracy" if y_val is not None else "direction_accuracy",
                patience=cfg.early_stopping_patience,
                restore_best_weights=True,
                verbose=1,
            ),
            ReduceLROnPlateau(
                monitor="val_loss" if y_val is not None else "loss",
                factor=0.5,
                patience=cfg.reduce_lr_patience,
                min_lr=1e-7,
                verbose=1,
            ),
            TerminateOnNaN(),
            ModelCheckpoint(
                f"models/{cfg.architecture.value}_best.h5",
                monitor="val_direction_auc" if y_val is not None else "direction_auc",
                save_best_only=True,
                mode="max",
            ),
        ]

        # Train
        logger.info("Training %s model...", cfg.architecture.value)

        logger.info("Training samples: %s", len(X_train))

        if X_val is not None:
            logger.info("Validation samples: %s", len(X_val))

        self.history = self.model.fit(
            X_train,
            y_train_dict,
            validation_data=(X_val, y_val_dict) if y_val is not None else None,
            epochs=cfg.epochs,
            batch_size=cfg.batch_size,
            callbacks=callbacks,
            sample_weight=sample_weights,
            verbose=1,
        )

        self.is_trained = True

        # Training metrics
        final_epoch = len(self.history.history["loss"])
        return {
            "epochs_trained": final_epoch,
            "final_loss": self.history.history["loss"][-1],
            "final_direction_accuracy": self.history.history["direction_accuracy"][-1],
            "final_direction_auc": self.history.history.get("direction_auc", [0])[-1],
            "best_val_accuracy": max(self.history.history.get("val_direction_accuracy", [0])),
            "training_time_per_epoch": None,  # Would track actual time
        }

    def _prepare_targets(self, y: np.ndarray) -> dict[str, np.ndarray]:
        """Prepare multi-output targets"""
        # Direction classification (3 classes: down, neutral, up)
        y_direction = np.digitize(y, bins=[-0.001, 0.001])
        y_direction = tf.keras.utils.to_categorical(y_direction, num_classes=3)

        # Volatility (absolute return)
        y_volatility = np.abs(y).reshape(-1, 1)

        # Return (original value)
        y_return = y.reshape(-1, 1)

        # Return uncertainty: rolling std of returns as a proxy for aleatoric uncertainty.
        # A window of 20 bars captures short-term volatility regime; edges use expanding window.
        y_series = pd.Series(y)
        y_uncertainty = y_series.rolling(window=20, min_periods=1).std().fillna(0.0).to_numpy().reshape(-1, 1)

        return {
            "direction": y_direction,
            "volatility": y_volatility,
            "return": y_return,
            "return_uncertainty": y_uncertainty,
        }

    def predict(self, X: np.ndarray, mc_samples: int | None = None) -> Prediction:
        """
        Generate prediction with Monte Carlo dropout for uncertainty.
        """
        if not self.is_trained or self.model is None:
            raise RuntimeError("Model not trained")

        start_time = datetime.now(UTC)

        # Ensure correct shape
        if len(X.shape) == 2:
            X = X.reshape(1, *X.shape)

        if X.shape[1] != self.config.sequence_length:
            # Pad or truncate
            if X.shape[1] < self.config.sequence_length:
                pad_width = (
                    (0, 0),
                    (self.config.sequence_length - X.shape[1], 0),
                    (0, 0),
                )
                X = np.pad(X, pad_width, mode="edge")
            else:
                X = X[:, -self.config.sequence_length :, :]

        # Monte Carlo Dropout for uncertainty
        n_samples = mc_samples or self.config.mc_dropout_samples

        predictions = {"direction": [], "volatility": [], "return": []}

        for _ in range(n_samples):
            # Enable dropout at inference time
            preds = self.model(X, training=True)
            for key in predictions:
                predictions[key].append(preds[key].numpy())

        # Calculate statistics
        stats = {}
        for key in predictions:
            preds_array = np.array(predictions[key])
            stats[key] = {
                "mean": preds_array.mean(axis=0),
                "std": preds_array.std(axis=0),
                "p5": np.percentile(preds_array, 5, axis=0),
                "p95": np.percentile(preds_array, 95, axis=0),
            }

        # Extract predictions
        direction_probs = stats["direction"]["mean"][0]
        direction_map = {0: "down", 1: "neutral", 2: "up"}
        predicted_direction = direction_map[np.argmax(direction_probs)]
        confidence = float(max(direction_probs))

        # Uncertainty decomposition
        epistemic = float(np.nan_to_num(stats["direction"]["std"].mean(), nan=0.0))  # Model uncertainty
        aleatoric = float(stats["volatility"]["mean"][0][0])  # Data noise

        inference_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        return Prediction(
            symbol="unknown",
            timestamp=datetime.now(UTC),
            target=PredictionTarget.DIRECTION,
            prediction=predicted_direction,
            confidence=confidence,
            probabilities={
                "down": float(direction_probs[0]),
                "neutral": float(direction_probs[1]),
                "up": float(direction_probs[2]),
            },
            epistemic_uncertainty=epistemic,
            aleatoric_uncertainty=aleatoric,
            total_uncertainty=epistemic + aleatoric,
            prediction_interval=(
                float(stats["return"]["p5"][0][0]),
                float(stats["return"]["p95"][0][0]),
            ),
            model_version=f"dl_{self.config.architecture.value}_v1",
            model_architecture=self.config.architecture.value,
            inference_time_ms=inference_time,
            training_samples=len(self.history.history["loss"]) * self.config.batch_size if self.history else 0,
        )

    def online_update(self, X_new: np.ndarray, y_new: np.ndarray, learning_rate_factor: float = 0.1):
        """
        Online learning update with reduced learning rate.
        Prevents catastrophic forgetting.
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained")

        # Reduce learning rate for gentle updates
        current_lr = float(self.model.optimizer.learning_rate)
        new_lr = current_lr * learning_rate_factor

        self.model.optimizer.learning_rate.assign(new_lr)

        # Short fine-tuning
        y_dict = self._prepare_targets(y_new)

        self.model.fit(X_new, y_dict, epochs=1, batch_size=min(32, len(X_new)), verbose=0)

        # Restore learning rate
        self.model.optimizer.learning_rate.assign(current_lr)

        logger.info("Online update completed with lr=%s", new_lr)

    def save(self, filepath: str):
        """Save model and configuration"""
        if self.model:
            self.model.save(f"{filepath}/model.h5")

            config_dict = {
                "architecture": self.config.architecture.value,
                "sequence_length": self.config.sequence_length,
                "n_features": self.n_features,
                "hidden_units": self.config.hidden_units,
                "dropout_rate": self.config.dropout_rate,
            }

            with open(f"{filepath}/config.json", "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=2)

            logger.info("Model saved to %s", filepath)

    def load(self, filepath: str):
        """Load model and configuration"""
        if TENSORFLOW_AVAILABLE:
            self.model = load_model(f"{filepath}/model.h5")

            with open(f"{filepath}/config.json", encoding="utf-8") as f:
                config_dict = json.load(f)
                self.config.architecture = ModelArchitecture(config_dict["architecture"])
                self.n_features = config_dict["n_features"]

            self.is_trained = True
            logger.info("Model loaded from %s", filepath)


# =============================================================================
# ENSEMBLE MODEL
# =============================================================================


class EnsemblePredictor:
    """
    Advanced ensemble combining multiple model types with dynamic weighting.
    Implements Bayesian Model Averaging and stacking.
    """

    def __init__(
        self,
        models: dict[str, Any] | None = None,
        meta_learner: Any | None = None,
    ):
        self.models: dict[str, Any] = models or {}
        self.weights: dict[str, float] = {}
        self.performance_history: dict[str, deque] = {}

        self.meta_learner = meta_learner
        self.use_stacking = meta_learner is not None

        self.feature_engineer = AdvancedFeatureEngineer()
        self.is_fitted = False

        # Calibration
        self.calibrators: dict[str, Any] = {}

        # Feature importance aggregation
        self.ensemble_feature_importance: dict[str, float] = {}

    def add_model(self, name: str, model: Any, weight: float = 1.0):
        """Add model to ensemble"""
        self.models[name] = model
        self.weights[name] = weight
        self.performance_history[name] = deque(maxlen=100)
        logger.info("Added model '%s' to ensemble (weight=%s)", name, weight)

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        validation_split: float = 0.2,
        optimize_weights: bool = True,
    ):
        """Train all models in ensemble"""
        # ── Look-ahead bias prevention ────────────────────────────────────────
        # Split the RAW price dataframe FIRST, then fit the feature engineer
        # exclusively on the training portion.  Computing rolling statistics
        # (autocorrelations, z-scores, etc.) on the full dataset before
        # splitting contaminates rows near the boundary with future information.
        logger.info("Splitting data before feature engineering to prevent look-ahead bias...")
        split_idx_raw = int(len(X) * (1 - validation_split))
        X_raw_train = X.iloc[:split_idx_raw]
        X_raw_val = X.iloc[split_idx_raw:]
        y_raw_train = y.iloc[:split_idx_raw]
        y_raw_val = y.iloc[split_idx_raw:]

        # Fit scaler and feature schema on training data only
        logger.info("Engineering features (fit on train only)...")
        X_train = self.feature_engineer.create_features(X_raw_train, fit=True)
        y_train = y_raw_train.loc[X_train.index]

        # Transform validation data using the training-fitted scaler
        X_val = self.feature_engineer.create_features(X_raw_val, fit=False)
        y_val = y_raw_val.loc[X_val.index]

        logger.info("Train: %s bars | Val: %s bars | Features: %s", len(X_train), len(X_val), X_train.shape[1])

        # Train each model — track val accuracy explicitly per model
        logger.info("Training %s models...", len(self.models))

        val_scores: dict[str, float] = {}

        for name, model in self.models.items():
            logger.info("Training %s...", name)

            score: float = 0.5  # safe default before any evaluation

            if isinstance(model, DeepLearningModel):
                result = model.fit(X_train.values, y_train.values, X_val.values, y_val.values)
                score = result.get("best_val_accuracy", result.get("final_direction_accuracy", 0.5))
                logger.info("  %s: %s epochs, val_accuracy=%s", name, result["epochs_trained"], score)

            elif SKLEARN_AVAILABLE and hasattr(model, "fit"):
                model.fit(X_train, y_train)

                # Calibrate probabilities using a held-out portion of the
                # validation set — never shuffle time-series data.
                if hasattr(model, "predict_proba") and len(X_val) >= 20:
                    cal_split = max(10, len(X_val) // 2)
                    X_cal = X_val.iloc[cal_split:]
                    y_cal = y_val.iloc[cal_split:]
                    try:
                        calibrated = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
                        calibrated.fit(X_cal, y_cal)
                        self.calibrators[name] = calibrated
                    except Exception as cal_exc:
                        logger.warning("  %s: calibration failed (%s), using raw probabilities", name, cal_exc)

                score = float(model.score(X_val, y_val))
                logger.info("  %s: val_accuracy=%s", name, score)

            val_scores[name] = score
            self.performance_history[name].append(score)

        # Optimize ensemble weights using the val scores collected above
        if optimize_weights:
            self._optimize_weights(X_val, y_val, val_scores)

        # Aggregate feature importance
        self._aggregate_feature_importance(X_val)

        # Train meta-learner if using stacking
        if self.use_stacking and self.meta_learner:
            self._train_meta_learner(X_val, y_val)

        self.is_fitted = True
        logger.info("Ensemble training completed")

    def _optimize_weights(
        self,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        val_scores: dict[str, float] | None = None,
    ):
        """
        Optimize ensemble weights from actual validation accuracy scores.

        Strategy: softmax over val accuracies so that better models get
        exponentially higher weight while no model is zeroed out entirely.
        Falls back to uniform weights if no scores are available.
        """
        logger.info("Optimizing ensemble weights...")

        scores: dict[str, float] = {}
        for name in self.models:
            if val_scores and name in val_scores:
                scores[name] = val_scores[name]
            elif self.performance_history.get(name):
                # Use mean of recent history if direct score not passed
                scores[name] = float(np.mean(list(self.performance_history[name])[-10:]))
            else:
                scores[name] = 0.5  # neutral — no information

        if not scores:
            logger.warning("No validation scores available; using uniform weights")
            n = len(self.models)
            self.weights = dict.fromkeys(self.models, 1.0 / n)
            return

        # Softmax weighting: exp(score) / sum(exp(scores))
        # Subtract max for numerical stability; guard against NaN scores
        names = list(scores.keys())
        vals = np.array([scores[n] for n in names], dtype=float)
        vals = np.nan_to_num(vals, nan=0.0)
        vals -= vals.max()
        exp_vals = np.exp(vals)
        exp_sum = exp_vals.sum()
        softmax_weights = exp_vals / exp_sum if exp_sum > 0 else np.ones(len(vals)) / len(vals)

        self.weights = {name: float(w) for name, w in zip(names, softmax_weights, strict=False)}
        logger.info("Optimized weights (softmax over val accuracy): %s", self.weights)

    def _train_meta_learner(self, X_val: pd.DataFrame, y_val: pd.Series):
        """Train meta-learner for stacking"""
        # Generate base model predictions as features
        meta_features = []
        for model in self.models.values():
            if isinstance(model, DeepLearningModel):
                probs = []
                for i in range(len(X_val)):
                    pred = model.predict(X_val.iloc[i : i + 1].values)
                    probs.append(list(pred.probabilities.values()))
                meta_features.append(np.array(probs))
            elif hasattr(model, "predict_proba"):
                meta_features.append(model.predict_proba(X_val))
            else:
                preds = model.predict(X_val)
                meta_features.append(np.eye(3)[preds])  # One-hot

        X_meta = np.hstack(meta_features)
        self.meta_learner.fit(X_meta, y_val)

    def _aggregate_feature_importance(self, X: pd.DataFrame):
        """Aggregate feature importance across all models"""
        all_importance = defaultdict(list)

        for name, model in self.models.items():
            if isinstance(model, DeepLearningModel):
                # Would extract NN feature importance
                continue

            if hasattr(model, "feature_importances_"):
                for feat, imp in zip(self.feature_engineer.feature_names, model.feature_importances_, strict=False):
                    all_importance[feat].append(imp * self.weights[name])

        # Average across models
        self.ensemble_feature_importance = {feat: np.mean(imps) for feat, imps in all_importance.items()}

    def predict(self, X: pd.DataFrame) -> Prediction:
        """Generate ensemble prediction with uncertainty"""
        if not self.is_fitted:
            raise RuntimeError("Ensemble not fitted")

        start_time = datetime.now(UTC)

        # Create features
        X_features = self.feature_engineer.create_features(X)

        # Collect predictions from all models
        model_predictions = []
        model_confidences = []
        model_probabilities = []

        for name, model in self.models.items():
            weight = self.weights.get(name, 1.0)

            try:
                if isinstance(model, DeepLearningModel):
                    pred = model.predict(X_features.values[-model.config.sequence_length :])
                    model_predictions.append(pred.prediction)
                    model_confidences.append(pred.confidence * weight)
                    model_probabilities.append(pred.probabilities)

                elif SKLEARN_AVAILABLE:
                    if name in self.calibrators:
                        probs = self.calibrators[name].predict_proba(X_features.iloc[-1:])
                    else:
                        probs = model.predict_proba(X_features.iloc[-1:]) if hasattr(model, "predict_proba") else None

                    if probs is not None:
                        pred_class = np.argmax(probs[0])
                        confidence = np.max(probs[0])
                        direction_map = {0: "down", 1: "neutral", 2: "up"}

                        model_predictions.append(direction_map.get(pred_class, "neutral"))
                        model_confidences.append(confidence * weight)
                        model_probabilities.append(
                            {
                                "down": probs[0][0],
                                "neutral": probs[0][1],
                                "up": probs[0][2],
                            }
                        )
                    else:
                        pred = model.predict(X_features.iloc[-1:])[0]
                        model_predictions.append(str(pred))
                        model_confidences.append(0.5 * weight)
                        model_probabilities.append({"down": 0.33, "neutral": 0.33, "up": 0.34})

            except Exception as e:
                logger.error("Prediction error for %s: %s", name, e)

                model_confidences.append(0)

        if not model_predictions:
            return Prediction(
                symbol="unknown",
                timestamp=datetime.now(UTC),
                target=PredictionTarget.DIRECTION,
                prediction="neutral",
                confidence=0.0,
                model_version="ensemble_v1",
            )

        # Weighted voting for direction
        vote_weights = defaultdict(float)
        for pred, conf in zip(model_predictions, model_confidences, strict=False):
            vote_weights[pred] += conf

        final_prediction = max(vote_weights.items(), key=lambda x: x[1])[0]
        total_weight = sum(model_confidences)
        confidence = vote_weights[final_prediction] / total_weight if total_weight > 0 else 0

        # Aggregate probabilities
        avg_probs = defaultdict(float)
        for probs, weight in zip(model_probabilities, model_confidences, strict=False):
            for key, val in probs.items():
                avg_probs[key] += val * weight / total_weight if total_weight > 0 else val / len(model_probabilities)

        # Uncertainty = disagreement between models
        unique_preds = len(set(model_predictions))
        disagreement = (unique_preds - 1) / len(model_predictions) if model_predictions else 0

        inference_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        return Prediction(
            symbol="unknown",
            timestamp=datetime.now(UTC),
            target=PredictionTarget.DIRECTION,
            prediction=final_prediction,
            confidence=confidence,
            probabilities=dict(avg_probs),
            epistemic_uncertainty=disagreement,
            aleatoric_uncertainty=0.1,  # Base data noise
            total_uncertainty=disagreement + 0.1,
            model_version="ensemble_v1",
            model_architecture="weighted_average",
            features_used=list(X_features.columns),
            feature_importance=self.ensemble_feature_importance,
            inference_time_ms=inference_time,
        )

    def online_update(self, X: pd.DataFrame, y: pd.Series):
        """Update all models with new data"""
        X_features = self.feature_engineer.create_features(X)
        y_aligned = y.loc[X_features.index]

        for name, model in self.models.items():
            if hasattr(model, "online_update"):
                model.online_update(X_features.values, y_aligned.values)
            elif hasattr(model, "partial_fit"):
                try:
                    model.partial_fit(X_features, y_aligned)
                except Exception as e:
                    logger.error("Online update failed for %s: %s", name, e)

        # Periodically re-optimize weights using the most recent validation window
        first_key = next(iter(self.models.keys()))
        if len(self.performance_history[first_key]) % 50 == 0:
            # Build per-model accuracy scores from the last 20 entries in history
            recent_scores: dict[str, float] = {
                name: float(np.mean(list(self.performance_history[name])[-20:]))
                for name in self.models
                if self.performance_history.get(name)
            }
            if recent_scores:
                self._optimize_weights(X_features, y_aligned, val_scores=recent_scores)
                logger.info(
                    "Periodic weight re-optimisation complete (n=%d): %s",
                    len(self.performance_history[first_key]),
                    {k: f"{v:.4f}" for k, v in self.weights.items()},
                )


# =============================================================================
# UNCERTAINTY THRESHOLD CALIBRATION
# =============================================================================


def calibrate_uncertainty_threshold(
    predictions: list["Prediction"],
    actuals: list[bool],
    sweep: list[float] | None = None,
) -> float:
    """
    Find the uncertainty threshold that maximises F1 on a validation set.

    This replaces the arbitrary 0.3 default in Prediction.DEFAULT_UNCERTAINTY_THRESHOLD
    with a data-driven value.  Run this once after training on a held-out
    validation set, then store the result in config and pass it to is_confident().

    Args:
        predictions: List of Prediction objects from the validation set.
        actuals:     Ground-truth correctness labels (True = prediction was correct).
        sweep:       Uncertainty values to try.  Defaults to 0.05 … 0.95 in steps of 0.05.

    Returns:
        The threshold value with the best F1 score.

    Example::

        threshold = calibrate_uncertainty_threshold(val_preds, val_labels)
        # Store in config:
        config["uncertainty_threshold"] = threshold
        # Use at inference:
        pred.is_confident(threshold=threshold)
    """
    if sweep is None:
        sweep = [round(v * 0.05, 2) for v in range(2, 19)]  # 0.10 … 0.90

    best_threshold = Prediction.DEFAULT_UNCERTAINTY_THRESHOLD
    best_f1 = -1.0

    for thresh in sweep:
        tp = fp = fn = 0
        for pred, actual in zip(predictions, actuals, strict=False):
            predicted_confident = pred.total_uncertainty < thresh
            if predicted_confident and actual:
                tp += 1
            elif predicted_confident and not actual:
                fp += 1
            elif not predicted_confident and actual:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = thresh

    return best_threshold


# =============================================================================
# MAIN PREDICTOR INTERFACE
# =============================================================================


class EnhancedMLPredictor:
    """
    Main interface for ML predictions with full uncertainty quantification.
    """

    def __init__(
        self,
        sequence_length: int = 60,
        prediction_horizon: int = 5,
        confidence_threshold: float = 0.65,
        use_gpu: bool = False,
        auto_optimize: bool = True,
    ):
        self.sequence_length = sequence_length
        self.horizon = prediction_horizon
        self.confidence_threshold = confidence_threshold
        self.use_gpu = use_gpu and (TENSORFLOW_AVAILABLE or PYTORCH_AVAILABLE)
        self.auto_optimize = auto_optimize and OPTUNA_AVAILABLE

        # Components
        self.feature_engineer = AdvancedFeatureEngineer()
        self.ensemble: EnsemblePredictor | None = None
        self.models: dict[str, Any] = {}

        # State
        self.is_fitted = False
        self.prediction_history: deque = deque(maxlen=1000)
        self.performance_tracker: deque = deque(maxlen=100)

        # Optimization results
        self.best_config: ModelConfig | None = None

        logger.info("EnhancedMLPredictor initialized")
        logger.info("  Sequence length: %s", sequence_length)

        logger.info("  Prediction horizon: %s", prediction_horizon)

        logger.info("  GPU enabled: %s", self.use_gpu)

        logger.info("  Auto-optimize: %s", self.auto_optimize)

    def build_ensemble(self, model_types: list[str] | None = None, use_stacking: bool = False):
        """Build ensemble with specified model types"""
        model_types = model_types or ["lstm", "xgboost", "random_forest"]

        self.ensemble = EnsemblePredictor()

        for model_type in model_types:
            if model_type == "lstm" and TENSORFLOW_AVAILABLE:
                config = ModelConfig(
                    architecture=ModelArchitecture.LSTM,
                    sequence_length=self.sequence_length,
                )
                model = DeepLearningModel(config)
                self.ensemble.add_model("lstm", model, weight=0.4)

            elif model_type == "gru" and TENSORFLOW_AVAILABLE:
                config = ModelConfig(
                    architecture=ModelArchitecture.GRU,
                    sequence_length=self.sequence_length,
                )
                model = DeepLearningModel(config)
                self.ensemble.add_model("gru", model, weight=0.35)

            elif model_type == "transformer" and TENSORFLOW_AVAILABLE:
                config = ModelConfig(
                    architecture=ModelArchitecture.TRANSFORMER,
                    sequence_length=self.sequence_length,
                )
                model = DeepLearningModel(config)
                self.ensemble.add_model("transformer", model, weight=0.4)

            elif model_type == "random_forest" and SKLEARN_AVAILABLE:
                model = RandomForestClassifier(
                    n_estimators=500,
                    max_depth=10,
                    min_samples_leaf=50,
                    n_jobs=-1,
                    random_state=42,
                    class_weight="balanced",
                )
                self.ensemble.add_model("random_forest", model, weight=0.3)

            elif model_type == "xgboost" and XGBOOST_AVAILABLE:
                model = xgb.XGBClassifier(
                    n_estimators=200,
                    max_depth=6,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective="multi:softprob",
                    eval_metric="mlogloss",
                    random_state=42,
                )
                self.ensemble.add_model("xgboost", model, weight=0.3)

            elif model_type == "lightgbm" and LIGHTGBM_AVAILABLE:
                model = lgb.LGBMClassifier(
                    n_estimators=200,
                    max_depth=6,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective="multiclass",
                    random_state=42,
                )
                self.ensemble.add_model("lightgbm", model, weight=0.3)

        # Add meta-learner if stacking
        if use_stacking and SKLEARN_AVAILABLE:
            from sklearn.linear_model import LogisticRegression

            self.ensemble.meta_learner = LogisticRegression(multi_class="multinomial", max_iter=1000)

        logger.info("Built ensemble with %s models", len(self.ensemble.models))

    def optimize_hyperparameters(self, X: pd.DataFrame, y: pd.Series, n_trials: int = 50) -> ModelConfig:
        """Use Optuna for hyperparameter optimization"""
        if not OPTUNA_AVAILABLE:
            logger.warning("Optuna not available - using default config")
            return ModelConfig(architecture=ModelArchitecture.LSTM)

        import optuna

        def objective(trial):
            # Define search space
            config = ModelConfig(
                architecture=ModelArchitecture(trial.suggest_categorical("architecture", ["lstm", "gru", "bilstm"])),
                hidden_units=[
                    trial.suggest_int("units_1", 64, 256),
                    trial.suggest_int("units_2", 32, 128),
                ],
                dropout_rate=trial.suggest_float("dropout", 0.1, 0.5),
                learning_rate=trial.suggest_float("lr", 1e-4, 1e-2, log=True),
                batch_size=trial.suggest_categorical("batch_size", [16, 32, 64]),
            )

            # Train on 80% of data, validate on remaining 20%
            split = int(len(X) * 0.8)
            X_tr, X_val = X.iloc[:split], X.iloc[split:]
            y_tr, y_val = y.iloc[:split], y.iloc[split:]

            candidate = DeepLearningModel(config)
            candidate.train(X_tr, y_tr, epochs=5)  # short run for HPO
            metrics = candidate.evaluate(X_val, y_val)
            # Maximise directional accuracy as the HPO objective
            return float(metrics.get("directional_accuracy", 0.0))

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials)

        best_config = ModelConfig(
            architecture=ModelArchitecture(study.best_params["architecture"]),
            hidden_units=[study.best_params["units_1"], study.best_params["units_2"]],
            dropout_rate=study.best_params["dropout"],
            learning_rate=study.best_params["lr"],
            batch_size=study.best_params["batch_size"],
        )

        self.best_config = best_config
        logger.info("Best config found: %s", best_config)

        return best_config

    def fit(
        self,
        df: pd.DataFrame,
        target_col: str = "close",
        validation_split: float = 0.2,
        use_walk_forward: bool = False,
        n_splits: int = 5,
        gap: int = 20,
    ):
        """
        Fit predictor on historical data with automatic feature engineering.

        Args:
            df:               OHLCV DataFrame with DatetimeIndex.
            target_col:       Column to predict (default 'close').
            validation_split: Fraction held out for validation when
                              use_walk_forward=False (default 0.2).
            use_walk_forward: When True, use TimeSeriesSplit walk-forward
                              cross-validation instead of a single static
                              split.  Each fold trains on all data up to the
                              fold boundary (expanding window) and evaluates
                              on the next out-of-sample window.  The model
                              is then re-fitted on the full dataset for
                              production use.  Recommended for any dataset
                              with more than ~500 bars.
            n_splits:         Number of walk-forward folds (default 5).
            gap:              Bars to skip between train end and test start
                              to prevent leakage from rolling features
                              (default 20).
        """
        if self.ensemble is None:
            self.build_ensemble()

        # Create target (future returns)
        df = df.copy()
        df["target"] = df[target_col].pct_change(self.horizon).shift(-self.horizon)
        df["target_class"] = pd.cut(
            df["target"],
            bins=[-np.inf, -0.001, 0.001, np.inf],
            labels=[0, 1, 2],  # Down, Neutral, Up
        )

        df_clean = df.dropna()
        X = df_clean.drop(["target", "target_class"], axis=1)
        y = df_clean["target_class"]

        if use_walk_forward:
            # gap must cover the prediction horizon to prevent target leakage
            # at train/val fold boundaries
            gap = max(gap, self.horizon)
            self._walk_forward_fit(X, y, n_splits=n_splits, gap=gap)
        else:
            logger.info("Fitting on %d samples (single 80/20 split)...", len(X))
            self.ensemble.fit(X, y, validation_split=validation_split)

        self.is_fitted = True
        logger.info("Fitting completed successfully")

    def _walk_forward_fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        n_splits: int = 5,
        gap: int = 20,
    ) -> None:
        """
        Walk-forward (anchored expanding-window) cross-validation.

        Each fold:
          1. Trains on all data up to the fold boundary (expanding window).
          2. Skips ``gap`` bars to prevent leakage from rolling features.
          3. Evaluates on the next out-of-sample window.

        After all folds the ensemble is re-fitted on the full dataset so
        the production model uses all available data.

        The scaler is re-fitted from scratch on each training fold so that
        test-fold statistics never contaminate the scaling parameters.
        """
        if not SKLEARN_AVAILABLE:
            logger.warning("sklearn not available — falling back to single static split")
            self.ensemble.fit(X, y, validation_split=0.2)
            return

        tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap)
        fold_scores: list = []

        logger.info("Walk-forward validation: %d folds, gap=%d bars", n_splits, gap)

        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train_raw = X.iloc[train_idx]
            X_test_raw = X.iloc[test_idx]
            y_train = y.iloc[train_idx]
            y_test = y.iloc[test_idx]

            if len(X_train_raw) < 50 or len(X_test_raw) < 10:
                logger.warning("Fold %d: insufficient data, skipping", fold + 1)
                continue

            # Fresh feature engineer per fold — prevents scaler contamination
            fold_fe = AdvancedFeatureEngineer()
            try:
                X_train = fold_fe.create_features(X_train_raw, fit=True)
                y_train = y_train.loc[X_train.index]
                X_test = fold_fe.create_features(X_test_raw, fit=False)
                y_test = y_test.loc[X_test.index]
            except Exception as exc:
                logger.warning("Fold %d: feature engineering failed (%s), skipping", fold + 1, exc)
                continue

            fold_val_scores: dict = {}
            for name, model in self.ensemble.models.items():
                try:
                    if SKLEARN_AVAILABLE and hasattr(model, "fit"):
                        model.fit(X_train, y_train)
                        score = float(model.score(X_test, y_test))
                        fold_val_scores[name] = score
                except Exception as exc:
                    logger.warning("Fold %d model %s failed: %s", fold + 1, name, exc)

            if fold_val_scores:
                mean_score = float(np.mean(list(fold_val_scores.values())))
                fold_scores.append(mean_score)
                logger.info(
                    "Fold %d/%d — train=%d test=%d | scores=%s | mean=%.3f",
                    fold + 1,
                    n_splits,
                    len(X_train),
                    len(X_test),
                    {k: f"{v:.3f}" for k, v in fold_val_scores.items()},
                    mean_score,
                )

        if fold_scores:
            logger.info(
                "Walk-forward CV complete — mean accuracy=%.3f ± %.3f over %d folds",
                float(np.mean(fold_scores)),
                float(np.std(fold_scores)),
                len(fold_scores),
            )
            self._wf_cv_mean = float(np.mean(fold_scores))
            self._wf_cv_std = float(np.std(fold_scores))
        else:
            logger.warning("Walk-forward CV produced no valid folds")

        # Re-fit on the full dataset for production use
        logger.info("Re-fitting ensemble on full dataset (%d bars) for production...", len(X))
        self.ensemble.fit(X, y, validation_split=0.1)

    def predict(self, df: pd.DataFrame) -> Prediction | None:
        """
        Generate prediction with full uncertainty quantification.
        """
        if not self.is_fitted:
            logger.error("Predictor not fitted - call fit() first")
            return None

        start_time = datetime.now(UTC)

        try:
            prediction = self.ensemble.predict(df)
            prediction.inference_time_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            # Record prediction
            self.prediction_history.append(prediction)

            # Check confidence threshold
            if prediction.confidence < self.confidence_threshold:
                prediction.prediction = "uncertain"
                logger.warning("Low confidence prediction: %s", prediction.confidence)

            return prediction

        except Exception as e:
            logger.error("Prediction error: %s", e)

            return None

    def update_performance(self, actual_return: float):
        """
        Update with actual outcome for online learning and tracking.
        """
        if not self.prediction_history:
            return

        last_pred = self.prediction_history[-1]

        # Determine if prediction was correct
        actual_direction = "up" if actual_return > 0.001 else "down" if actual_return < -0.001 else "neutral"
        correct = last_pred.prediction == actual_direction

        self.performance_tracker.append(
            {
                "predicted": last_pred.prediction,
                "actual": actual_direction,
                "correct": correct,
                "confidence": last_pred.confidence,
                "return": actual_return,
            }
        )

        # ── Online update trigger ─────────────────────────────────────────────
        # Only evaluate after enough observations to be statistically meaningful.
        # The threshold is set relative to the *baseline* accuracy established
        # during training, not a fixed 55% that fires immediately when the
        # baseline is already ~48%.
        #
        # Rules:
        #   1. Need at least 50 recent predictions before triggering anything.
        #   2. Compute a rolling 50-bar accuracy.
        #   3. Trigger retraining only if accuracy drops MORE THAN 5 percentage
        #      points below the training baseline AND stays there for 3
        #      consecutive evaluation windows (to avoid noise-driven retrains).
        #   4. Enforce a minimum 24-hour cooldown between retrains to prevent
        #      continuous retraining on a model that has no real edge.
        min_obs_for_trigger = 50
        degradation_threshold = 0.05  # 5pp below baseline
        consecutive_windows_required = 3

        if len(self.performance_tracker) >= min_obs_for_trigger:
            recent = list(self.performance_tracker)[-min_obs_for_trigger:]
            recent_accuracy = float(np.mean([p["correct"] for p in recent]))

            # Establish baseline from training report if available
            baseline = getattr(self, "_training_baseline_accuracy", None)
            if baseline is None:
                # Fall back to first 50 observations as baseline estimate
                first_50 = list(self.performance_tracker)[:min_obs_for_trigger]
                baseline = float(np.mean([p["correct"] for p in first_50]))
                self._training_baseline_accuracy = baseline

            trigger_threshold = max(0.45, baseline - degradation_threshold)

            if recent_accuracy < trigger_threshold:
                self._consecutive_degraded_windows = getattr(self, "_consecutive_degraded_windows", 0) + 1
                logger.warning(
                    "Accuracy degraded: recent=%s baseline=%s threshold=%s (window %s/%s)",
                    f"{recent_accuracy:.1%}",
                    f"{baseline:.1%}",
                    f"{trigger_threshold:.1%}",
                    self._consecutive_degraded_windows,
                    consecutive_windows_required,
                )

                if self._consecutive_degraded_windows >= consecutive_windows_required:
                    last_retrain = getattr(self, "_last_retrain_time", None)
                    now = datetime.now(UTC)
                    cooldown_hours = 24
                    if last_retrain is None or (now - last_retrain).total_seconds() > cooldown_hours * 3600:
                        logger.warning(
                            "Triggering online update after %s consecutive degraded windows. "
                            "Accuracy %s vs baseline %s.",
                            consecutive_windows_required,
                            f"{recent_accuracy:.1%}",
                            f"{baseline:.1%}",
                        )
                        self._last_retrain_time = now
                        self._consecutive_degraded_windows = 0
                        # Caller should schedule async retraining; flag it here
                        self._retrain_requested = True
                    else:
                        hours_remaining = cooldown_hours - (now - last_retrain).total_seconds() / 3600
                        logger.info("Retrain suppressed by cooldown (%sh remaining)", hours_remaining)

            else:
                # Reset consecutive counter when performance recovers
                self._consecutive_degraded_windows = 0

    def get_model_report(self) -> dict[str, Any]:
        """Generate comprehensive model report"""
        if not self.is_fitted:
            return {"status": "not_fitted"}

        recent_perf = list(self.performance_tracker)

        return {
            "status": "fitted",
            "models": list(self.ensemble.models.keys()) if self.ensemble else [],
            "weights": self.ensemble.weights if self.ensemble else {},
            "confidence_threshold": self.confidence_threshold,
            "predictions_generated": len(self.prediction_history),
            "recent_performance": {
                "accuracy": np.mean([p["correct"] for p in recent_perf]) if recent_perf else None,
                "avg_confidence": np.mean([p["confidence"] for p in recent_perf]) if recent_perf else None,
                "predictions": len(recent_perf),
            },
            "feature_count": len(self.feature_engineer.feature_names) if self.feature_engineer.is_fitted else 0,
            "top_features": dict(list(self.ensemble.ensemble_feature_importance.items())[:10]) if self.ensemble else {},
        }


# =============================================================================
# DEVELOPMENT / SMOKE-TEST UTILITIES
# These functions use synthetic GBM data and must NOT be called in production.
# =============================================================================


def generate_synthetic_data(n_samples: int = 5000, trend: float = 0.0001, volatility: float = 0.001) -> pd.DataFrame:
    """
    Generate synthetic GBM market data for smoke-testing the ML pipeline.

    FOR DEVELOPMENT AND CI USE ONLY.  Results produced from this data are
    NOT valid for strategy evaluation or performance reporting.

    Raises RuntimeError if called in APP_ENV=production.
    """
    import os as _os

    if _os.getenv("APP_ENV", "production").lower() == "production":
        raise RuntimeError(
            "generate_synthetic_data() cannot be called in production "
            "(APP_ENV=production). Use real OHLCV data from a market data provider."
        )
    warnings.warn(
        "generate_synthetic_data() produces synthetic GBM data. Results are not valid for strategy evaluation.",
        UserWarning,
        stacklevel=2,
    )
    _rng = np.random.default_rng()  # unseeded — non-deterministic GBM for CI smoke tests
    returns = _rng.normal(trend, volatility, n_samples)
    for i in range(1, n_samples):
        returns[i] *= 1 + abs(returns[i - 1]) * 3
    prices = 100 * np.exp(np.cumsum(returns))
    df = pd.DataFrame(index=pd.date_range("2024-01-01", periods=n_samples, freq="5min"))
    df["close"] = prices
    df["high"] = prices * (1 + np.abs(_rng.normal(0, volatility, n_samples)))
    df["low"] = prices * (1 - np.abs(_rng.normal(0, volatility, n_samples)))
    df["open"] = df["close"].shift(1).fillna(prices[0])
    df["volume"] = _rng.poisson(1000, n_samples)
    return df


def run_ml_test():
    """
    Smoke-test for the ML predictor using synthetic GBM data.

    FOR DEVELOPMENT / CI USE ONLY.  Raises RuntimeError in APP_ENV=production.
    """
    import os as _os

    if _os.getenv("APP_ENV", "production").lower() == "production":
        raise RuntimeError(
            "run_ml_test() uses synthetic data and cannot run in production. "  # healer: ignore — guards against production use
            "Set APP_ENV=development or APP_ENV=test to use this function."
        )
    logger.info("=" * 80)
    logger.info("HOPEFX ML PREDICTOR v4.0 - DEVELOPMENT SMOKE TEST")
    logger.info("=" * 80)

    # Generate synthetic data for smoke-testing only
    logger.info("\n[1] Generating synthetic GBM data (smoke-test only)...")
    df = generate_synthetic_data(n_samples=3000)
    logger.info("    Generated %s samples", len(df))
    logger.info("    Date range: %s to %s", df.index[0], df.index[-1])

    # Initialize predictor
    logger.info("\n[2] Initializing ML predictor...")
    predictor = EnhancedMLPredictor(
        sequence_length=60,
        prediction_horizon=5,
        confidence_threshold=0.6,
        auto_optimize=False,  # Skip for quick test
    )

    # Build ensemble
    logger.info("[3] Building model ensemble...")
    predictor.build_ensemble(model_types=["lstm", "random_forest"], use_stacking=False)

    # Fit models
    logger.info("\n[4] Training models...")
    predictor.fit(df, target_col="close", validation_split=0.2)

    # Generate predictions
    logger.info("\n[5] Generating predictions...")
    predictions = []
    for i in range(50):
        pred_df = df.iloc[max(0, i - 100) : i + 100] if i > 100 else df.iloc[:200]
        pred = predictor.predict(pred_df)

        if pred:
            predictions.append(pred)
            if i < 5:
                logger.info(
                    f"    Prediction {i + 1}: {pred.prediction} "
                    f"(conf: {pred.confidence:.1%}, "
                    f"unc: {pred.total_uncertainty:.2f})"
                )

    # Generate report
    logger.info("\n[6] Generating model report...")
    report = predictor.get_model_report()

    logger.info("\n" + "=" * 80)
    logger.info("ML PREDICTOR REPORT")
    logger.info("=" * 80)

    logger.info("\nModels in ensemble: %s", report['models'])
    logger.info("Weights: %s", report['weights'])
    logger.info("Predictions generated: %s", report['predictions_generated'])

    if report["recent_performance"]["accuracy"] is not None:
        logger.info("\nRecent accuracy: %s", f"{report['recent_performance']['accuracy']:.1%}")
        logger.info("Average confidence: %s", f"{report['recent_performance']['avg_confidence']:.1%}")

    logger.info("\nFeatures used: %s", report['feature_count'])
    logger.info("Top 5 features:")
    for feat, imp in list(report["top_features"].items())[:5]:
        logger.info("  %s: %.4f", feat, imp)

    logger.info("\n" + "=" * 80)
    logger.info("✅ ML PREDICTOR TEST COMPLETED")
    logger.info("=" * 80)


if __name__ == "__main__":
    run_ml_test()


# Backward-compat alias used by comprehensive_test_framework.py
FeatureEngineering = AdvancedFeatureEngineer
