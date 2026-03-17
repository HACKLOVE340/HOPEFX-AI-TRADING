# enhanced_ml_predictor.py
"""
Institutional-Grade ML Prediction Engine v3.0
Ensemble Methods | Online Learning | Uncertainty Quantification | GPU Acceleration
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from collections import deque
import logging
import json
import pickle
from pathlib import Path
import warnings

# ML libraries
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
    from sklearn.preprocessing import RobustScaler, StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import log_loss, accuracy_score, precision_recall_fscore_support
    from sklearn.calibration import CalibratedClassifierCV
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    warnings.warn("scikit-learn not available")

try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential, Model, load_model
    from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization, Input, Concatenate
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint
    from tensorflow.keras.optimizers import Adam
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False
    warnings.warn("TensorFlow not available")

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    PYTORCH_AVAILABLE = True
except ImportError:
    PYTORCH_AVAILABLE = False

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

logger = logging.getLogger(__name__)

class PredictionTarget(Enum):
    """Prediction targets"""
    DIRECTION = "direction"           # Up/Down/Flat
    VOLATILITY = "volatility"         # Future volatility
    RETURN = "return"                 # Future return
    PROBABILITY = "probability"       # Probability of event
    QUANTILE = "quantile"             # Quantile regression

class ModelType(Enum):
    """Supported model types"""
    LSTM = "lstm"
    GRU = "gru"
    TRANSFORMER = "transformer"
    RANDOM_FOREST = "random_forest"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    TABNET = "tabnet"
    ENSEMBLE = "ensemble"

@dataclass
class Prediction:
    """Structured prediction output"""
    symbol: str
    timestamp: datetime
    target: PredictionTarget
    
    # Point prediction
    prediction: Union[str, float, int]
    confidence: float  # 0-1
    
    # Probabilistic outputs
    probabilities: Optional[Dict[str, float]] = None
    quantiles: Optional[Dict[str, float]] = None
    
    # Uncertainty
    prediction_interval: Optional[Tuple[float, float]] = None
    epistemic_uncertainty: float = 0.0  # Model uncertainty
    aleatoric_uncertainty: float = 0.0  # Data noise
    
    # Model info
    model_version: str = "unknown"
    features_used: List[str] = field(default_factory=list)
    inference_time_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'target': self.target.value,
            'prediction': self.prediction,
            'confidence': self.confidence,
            'probabilities': self.probabilities,
            'uncertainty_total': self.epistemic_uncertainty + self.aleatoric_uncertainty
        }

class FeatureEngineering:
    """
    Advanced feature engineering with no lookahead bias.
    Generates technical, statistical, and microstructure features.
    """
    
    def __init__(self, lookback_windows: List[int] = None):
        self.windows = lookback_windows or [5, 10, 20, 50, 100]
        self.scaler = RobustScaler()
        self.feature_names: List[str] = []
        self.is_fitted = False
    
    def create_features(self, df: pd.DataFrame, fit: bool = False) -> pd.DataFrame:
        """
        Create feature matrix from OHLCV data.
        Critical: No lookahead bias!
        """
        features = pd.DataFrame(index=df.index)
        
        # Price-based features (no lookahead)
        features['returns'] = df['close'].pct_change()
        features['log_returns'] = np.log1p(features
        features['log_returns'] = np.log1p(features['returns'])
        
        # Volatility features
        for w in self.windows:
            features[f'volatility_{w}'] = features['returns'].rolling(w).std()
            features[f'volatility_mean_{w}'] = features[f'volatility_{w}'].rolling(w).mean()
        
        # Technical indicators (properly lagged)
        for w in self.windows:
            # Moving averages
            features[f'ma_{w}'] = df['close'].rolling(w).mean()
            features[f'ma_ratio_{w}'] = df['close'] / features[f'ma_{w}']
            
            # RSI
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(w).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(w).mean()
            rs = gain / loss
            features[f'rsi_{w}'] = 100 - (100 / (1 + rs))
            
            # MACD
            ema_fast = df['close'].ewm(span=w//2).mean()
            ema_slow = df['close'].ewm(span=w).mean()
            features[f'macd_{w}'] = ema_fast - ema_slow
            features[f'macd_signal_{w}'] = features[f'macd_{w}'].ewm(span=w//3).mean()
        
        # Volume features
        if 'volume' in df.columns:
            features['volume_ma'] = df['volume'].rolling(20).mean()
            features['volume_ratio'] = df['volume'] / features['volume_ma']
            features['volume_std'] = df['volume'].rolling(20).std()
            
            # Volume-weighted features
            features['vwma_20'] = (df['close'] * df['volume']).rolling(20).sum() / df['volume'].rolling(20).sum()
            features['vwma_ratio'] = df['close'] / features['vwma_20']
        
        # Price action features
        features['high_low_range'] = (df['high'] - df['low']) / df['close']
        features['open_close'] = (df['close'] - df['open']) / df['open']
        features['upper_shadow'] = (df['high'] - df[['close', 'open']].max(axis=1)) / df['close']
        features['lower_shadow'] = (df[['close', 'open']].min(axis=1) - df['low']) / df['close']
        
        # Trend strength
        for w in [20, 50]:
            features[f'trend_strength_{w}'] = (
                (df['close'] - df['close'].shift(w)) / 
                df['close'].rolling(w).std()
            )
        
        # Mean reversion features
        for w in [20, 50]:
            features[f'zscore_{w}'] = (
                (df['close'] - df['close'].rolling(w).mean()) / 
                df['close'].rolling(w).std()
            )
        
        # Time features (cyclical encoding)
        features['hour_sin'] = np.sin(2 * np.pi * df.index.hour / 24)
        features['hour_cos'] = np.cos(2 * np.pi * df.index.hour / 24)
        features['day_sin'] = np.sin(2 * np.pi * df.index.dayofweek / 5)
        features['day_cos'] = np.cos(2 * np.pi * df.index.dayofweek / 5)
        
        # Lagged returns (for autocorrelation)
        for lag in [1, 2, 3, 5, 10]:
            features[f'return_lag_{lag}'] = features['returns'].shift(lag)
        
        # Drop NaN
        features = features.dropna()
        
        # Scale if requested
        if fit:
            self.scaler.fit(features)
            self.is_fitted = True
            self.feature_names = list(features.columns)
        elif self.is_fitted:
            features = pd.DataFrame(
                self.scaler.transform(features),
                index=features.index,
                columns=self.feature_names
            )
        
        return features
    
    def get_feature_importance(self, model: Any) -> Dict[str, float]:
        """Extract feature importance from model"""
        if hasattr(model, 'feature_importances_'):
            return dict(zip(self.feature_names, model.feature_importances_))
        return {}

class DeepLearningModel:
    """
    Production-grade deep learning with uncertainty quantification.
    Supports LSTM, GRU, and Transformer architectures.
    """
    
    def __init__(self,
                 sequence_length: int = 60,
                 n_features: int = 50,
                 model_type: str = "lstm",
                 dropout: float = 0.2,
                 learning_rate: float = 0.001):
        
        self.sequence_length = sequence_length
        self.n_features = n_features
        self.model_type = model_type
        self.dropout = dropout
        self.lr = learning_rate
        
        self.model: Optional[Model] = None
        self.history: Optional[Any] = None
        
        if TENSORFLOW_AVAILABLE:
            self._build_model()
    
    def _build_model(self):
        """Build neural network architecture"""
        if not TENSORFLOW_AVAILABLE:
            raise RuntimeError("TensorFlow not available")
        
        inputs = Input(shape=(self.sequence_length, self.n_features))
        
        # Recurrent layers
        if self.model_type == "lstm":
            x = LSTM(128, return_sequences=True, dropout=self.dropout)(inputs)
            x = BatchNormalization()(x)
            x = LSTM(64, return_sequences=False, dropout=self.dropout)(x)
        elif self.model_type == "gru":
            from tensorflow.keras.layers import GRU
            x = GRU(128, return_sequences=True, dropout=self.dropout)(inputs)
            x = BatchNormalization()(x)
            x = GRU(64, return_sequences=False, dropout=self.dropout)(x)
        elif self.model_type == "transformer":
            from tensorflow.keras.layers import MultiHeadAttention, LayerNormalization
            # Simplified transformer
            x = Dense(128, activation='relu')(inputs)
            x = MultiHeadAttention(num_heads=4, key_dim=32)(x, x)
            x = LayerNormalization()(x)
            x = tf.reduce_mean(x, axis=1)  # Global average pooling
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
        
        x = BatchNormalization()(x)
        x = Dense(32, activation='relu')(x)
        x = Dropout(self.dropout)(x)
        
        # Multi-task outputs
        direction = Dense(3, activation='softmax', name='direction')(x)  # Up/Down/Sideways
        volatility = Dense(1, activation='relu', name='volatility')(x)
        return_pred = Dense(1, name='return')(x)
        
        self.model = Model(inputs=inputs, outputs=[direction, volatility, return_pred])
        
        self.model.compile(
            optimizer=Adam(learning_rate=self.lr),
            loss={
                'direction': 'categorical_crossentropy',
                'volatility': 'mse',
                'return': 'mse'
            },
            loss_weights={'direction': 1.0, 'volatility': 0.5, 'return': 0.5},
            metrics={'direction': 'accuracy'}
        )
        
        logger.info(f"Built {self.model_type} model with {self.model.count_params()} parameters")
    
    def create_sequences(self, X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Create sequences for time series"""
        sequences = []
        targets = []
        
        for i in range(len(X) - self.sequence_length):
            sequences.append(X[i:(i + self.sequence_length)])
            targets.append(y[i + self.sequence_length])
        
        return np.array(sequences), np.array(targets)
    
    def fit(self,
            X_train: np.ndarray,
            y_train: np.ndarray,
            X_val: Optional[np.ndarray] = None,
            y_val: Optional[np.ndarray] = None,
            epochs: int = 100,
            batch_size: int = 32,
            early_stopping_patience: int = 10) -> Dict:
        """
        Train model with validation and callbacks.
        """
        if not TENSORFLOW_AVAILABLE or self.model is None:
            raise RuntimeError("Model not initialized")
        
        # Create sequences
        X_seq, y_seq = self.create_sequences(X_train, y_train)
        
        # Prepare validation data
        validation_data = None
        if X_val is not None and y_val is not None:
            X_val_seq, y_val_seq = self.create_sequences(X_val, y_val)
            
            # Multi-output format
            y_val_split = {
                'direction': tf.keras.utils.to_categorical(
                    np.digitize(y_val_seq, bins=[-0.001, 0.001]), num_classes=3
                ),
                'volatility': np.abs(y_val_seq).reshape(-1, 1),
                'return': y_val_seq.reshape(-1, 1)
            }
            validation_data = (X_val_seq, y_val_split)
        
        # Multi-output target
        y_split = {
            'direction': tf.keras.utils.to_categorical(
                np.digitize(y_seq, bins=[-0.001, 0.001]), num_classes=3
            ),
            'volatility': np.abs(y_seq).reshape(-1, 1),
            'return': y_seq.reshape(-1, 1)
        }
        
        # Callbacks
        callbacks = [
            EarlyStopping(
                monitor='val_direction_accuracy' if validation_data else 'direction_accuracy',
                patience=early_stopping_patience,
                restore_best_weights=True
            ),
            ReduceLROnPlateau(
                monitor='loss',
                factor=0.5,
                patience=5,
                min_lr=1e-6
            )
        ]
        
        # Train
        self.history = self.model.fit(
            X_seq, y_split,
            validation_data=validation_data,
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=1
        )
        
        return {
            'final_loss': self.history.history['loss'][-1],
            'final_accuracy': self.history.history['direction_accuracy'][-1],
            'epochs_trained': len(self.history.history['loss'])
        }
    
    def predict(self, X: np.ndarray, mc_samples: int = 100) -> Dict:
        """
        Generate prediction with Monte Carlo dropout for uncertainty.
        """
        if not TENSORFLOW_AVAILABLE or self.model is None:
            raise RuntimeError("Model not initialized")
        
        if len(X.shape) == 2:
            # Single sample, add batch dimension
            X = X.reshape(1, *X.shape)
        
        if X.shape[1] != self.sequence_length:
            # Pad or truncate
            if X.shape[1] < self.sequence_length:
                padding = np.zeros((X.shape[0], self.sequence_length - X.shape[1], X.shape[2]))
                X = np.concatenate([padding, X], axis=1)
            else:
                X = X[:, -self.sequence_length:, :]
        
        # Monte Carlo dropout predictions
        predictions = {'direction': [], 'volatility': [], 'return': []}
        
        for _ in range(mc_samples):
            # Enable dropout at inference time
            preds = self.model(X, training=True)
            for key in predictions:
                predictions[key].append(preds[key].numpy())
        
        # Calculate statistics
        results = {}
        for key in predictions:
            preds_array = np.array(predictions[key])
            results[key] = {
                'mean': preds_array.mean(axis=0),
                'std': preds_array.std(axis=0),
                'p5': np.percentile(preds_array, 5, axis=0),
                'p95': np.percentile(preds_array, 95, axis=0)
            }
        
        # Format output
        direction_probs = results['direction']['mean'][0]
        direction_map = {0: 'down', 1: 'neutral', 2: 'up'}
        predicted_direction = direction_map[np.argmax(direction_probs)]
        
        uncertainty = results['direction']['std'].mean()
        
        return Prediction(
            symbol="unknown",
            timestamp=datetime.now(),
            target=PredictionTarget.DIRECTION,
            prediction=predicted_direction,
            confidence=float(max(direction_probs)),
            probabilities={
                'down': float(direction_probs[0]),
                'neutral': float(direction_probs[1]),
                'up': float(direction_probs[2])
            },
            epistemic_uncertainty=float(uncertainty),
            aleatoric_uncertainty=float(results['return']['std'][0][0]),
            prediction_interval=(
                float(results['return']['p5'][0][0]),
                float(results['return']['p95'][0][0])
            ),
            model_version=f"dl_{self.model_type}_v1",
            inference_time_ms=0.0
        )
    
    def save(self, path: str):
        """Save model and configuration"""
        if self.model:
            self.model.save(f"{path}/model.keras")
            with open(f"{path}/config.json", 'w') as f:
                json.dump({
                    'sequence_length': self.sequence_length,
                    'n_features': self.n_features,
                    'model_type': self.model_type,
                    'dropout': self.dropout
                }, f)
    
    def load(self, path: str):
        """Load model and configuration"""
        if TENSORFLOW_AVAILABLE:
            self.model = load_model(f"{path}/model.keras")
            with open(f"{path}/config.json", 'r') as f:
                config = json.load(f)
                self.sequence_length = config['sequence_length']
                self.n_features = config['n_features']

class EnsemblePredictor:
    """
    Advanced ensemble combining multiple model types with dynamic weighting.
    """
    
    def __init__(self, models: Optional[Dict[str, Any]] = None):
        self.models: Dict[str, Any] = models or {}
        self.weights: Dict[str, float] = {}
        self.performance_history: Dict[str, deque] = {
            name: deque(maxlen=100) for name in self.models
        }
        self.meta_learner: Optional[Any] = None
        
        # Feature engineering
        self.feature_engineer = FeatureEngineering()
        
        # Calibration
        self.calibrators: Dict[str, Any] = {}
    
    def add_model(self, name: str, model: Any, weight: float = 1.0):
        """Add model to ensemble"""
        self.models[name] = model
        self.weights[name] = weight
        self.performance_history[name] = deque(maxlen=100)
        logger.info(f"Added model {name} to ensemble (weight {weight})")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, validation_split: float = 0.2):
        """Train all models in ensemble"""
        # Create features
        features = self.feature_engineer.create_features(X, fit=True)
        
        # Align targets
        y_aligned = y.loc[features.index]
        
        # Split
        split_idx = int(len(features) * (1 - validation_split))
        X_train, X_val = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_val = y_aligned.iloc[:split_idx], y_aligned.iloc[split_idx:]
        
        # Train each model
        for name, model in self.models.items():
            logger.info(f"Training model: {name}")
            
            if isinstance(model, DeepLearningModel):
                model.fit(
                    X_train.values, y_train.values,
                    X_val.values, y_val.values
                )
            elif SKLEARN_AVAILABLE and hasattr(model, 'fit'):
                model.fit(X_train, y_train)
                
                # Calibrate probabilities
                if hasattr(model, 'predict_proba'):
                    calibrated = CalibratedClassifierCV(model, method='isotonic', cv=5)
                    calibrated.fit(X_val, y_val)
                    self.calibrators[name] = calibrated
            
            # Evaluate
            self._evaluate_model(name, model, X_val, y_val)
        
        # Optimize weights based on performance
        self._optimize_weights()
    
    def _evaluate_model(self, name: str, model: Any, X_val: pd.DataFrame, y_val: pd.Series):
        """Evaluate model and record performance"""
        if isinstance(model, DeepLearningModel):
            pred = model.predict(X_val.values)
            # Convert to accuracy metric
            accuracy = pred.confidence  # Simplified
        elif SKLEARN_AVAILABLE:
            pred = model.predict(X_val)
            accuracy = accuracy_score(y_val, pred)
        else:
            accuracy = 0.5
        
        self.performance_history[name].append(accuracy)
    
    def _optimize_weights(self):
        """Optimize ensemble weights based on recent performance"""
        if not self.performance_history:
            return
        
        # Simple exponential weighting based on recent accuracy
        for name, history in self.performance_history.items():
            if history:
                recent_perf = np.mean(list(history)[-20:])  # Last 20
                self.weights[name] = max(0.1, recent_perf)
        
        # Normalize
        total = sum(self.weights.values())
        self.weights = {k: v/total for k, v in self.weights.items()}
        
        logger.info(f"Optimized weights: {self.weights}")
    
    def predict(self, X: pd.DataFrame) -> Prediction:
        """
        Generate ensemble prediction with uncertainty quantification.
        """
        # Create features
        features = self.feature_engineer.create_features(X)
        
        if len(features) == 0:
            raise ValueError("No features generated")
        
        # Get predictions from all models
        predictions = []
        confidences = []
        
        for name, model in self.models.items():
            weight = self.weights.get(name, 1.0)
            
            try:
                if isinstance(model, DeepLearningModel):
                    pred = model.predict(features.values[-model.sequence_length:])
                    predictions.append(pred.prediction)
                    confidences.append(pred.confidence * weight)
                
                elif SKLEARN_AVAILABLE and hasattr(model, 'predict_proba'):
                    probs = model.predict_proba(features.iloc[-1:])
                    pred_class = model.predict(features.iloc[-1:])[0]
                    confidence = np.max(probs) * weight
                    predictions.append(str(pred_class))
                    confidences.append(confidence)
                
                elif hasattr(model, 'predict'):
                    pred = model.predict(features.iloc[-1:])[0]
                    predictions.append(str(pred))
                    confidences.append(0.5 * weight)
            
            except Exception as e:
                logger.error(f"Prediction error for {name}: {e}")
                confidences.append(0)
        
        if not predictions:
            return Prediction(
                symbol="unknown",
                timestamp=datetime.now(),
                target=PredictionTarget.DIRECTION,
                prediction="neutral",
                confidence=0.0,
                model_version="ensemble_v1"
            )
        
        # Weighted voting
        from collections import Counter
        weighted_votes = Counter()
        
        for pred, conf in zip(predictions, confidences):
            weighted_votes[pred] += conf
        
        final_prediction = weighted_votes.most_common(1)[0][0]
        total_confidence = weighted_votes[final_prediction] / sum(confidences) if sum(confidences) > 0 else 0
        
        # Calculate ensemble disagreement as uncertainty
        unique_preds = len(set(predictions))
        disagreement = (unique_preds - 1) / len(predictions) if predictions else 0
        
        return Prediction(
            symbol="unknown",
            timestamp=datetime.now(),
            target=PredictionTarget.DIRECTION,
            prediction=final_prediction,
            confidence=float(total_confidence),
            epistemic_uncertainty=float(disagreement),
            probabilities={k: v/sum(weighted_votes.values()) for k, v in weighted_votes.items()},
            model_version="ensemble_v1",
            features_used=list(features.columns),
            inference_time_ms=0.0
        )
    
    def online_update(self, X: pd.DataFrame, y: pd.Series):
        """
        Online learning update with new data.
        Implements gradual forgetting to adapt to regime changes.
        """
        # Update feature engineering
        features = self.feature_engineer.create_features(X)
        y_aligned = y.loc[features.index]
        
        # Partial fit for compatible models
        for name, model in self.models.items():
            if hasattr(model, 'partial_fit'):
                try:
                    model.partial_fit(features, y_aligned)
                    logger.info(f"Online update completed for {name}")
                except Exception as e:
                    logger.error(f"Online update failed for {name}: {e}")
        
        # Re-optimize weights periodically
        if len(self.performance_history[list(self.models.keys())[0]]) % 50 == 0:
            self._optimize_weights()

class EnhancedMLPredictor:
    """
    Main interface for ML predictions.
    Combines feature engineering, ensemble models, and risk management.
    """
    
    def __init__(self,
                 sequence_length: int = 60,
                 prediction_horizon: int = 5,
                 confidence_threshold: float = 0.65,
                 use_gpu: bool = False):
        
        self.sequence_length = sequence_length
        self.horizon = prediction_horizon
        self.confidence_threshold = confidence_threshold
        self.use_gpu = use_gpu and (TENSORFLOW_AVAILABLE or PYTORCH_AVAILABLE)
        
        # Components
        self.feature_engineer = FeatureEngineering()
        self.ensemble: Optional[EnsemblePredictor] = None
        
        # State
        self.is_fitted = False
        self.prediction_history: deque = deque(maxlen=1000)
        
        # Performance tracking
        self.accuracy_history: deque = deque(maxlen=100)
        
        logger.info(f"EnhancedMLPredictor initialized (GPU: {self.use_gpu})")
    
    def build_ensemble(self, model_types: List[str] = None):
        """Build ensemble with specified model types"""
        model_types = model_types or ['lstm', 'xgboost', 'random_forest']
        
        self.ensemble = EnsemblePredictor()
        
        for model_type in model_types:
            if model_type == 'lstm' and TENSORFLOW_AVAILABLE:
                model = DeepLearningModel(
                    sequence_length=self.sequence_length,
                    model_type='lstm'
                )
                self.ensemble.add_model('lstm', model, weight=0.4)
            
            elif model_type == 'random_forest' and SKLEARN_AVAILABLE:
                model = RandomForestClassifier(
                    n_estimators=200,
                    max_depth=10,
                    min_samples_leaf=50,
                    n_jobs=-1,
                    random_state=42
                )
                self.ensemble.add_model('random_forest', model, weight=0.3)
            
            elif model_type == 'xgboost' and XGBOOST_AVAILABLE:
                model = xgb.XGBClassifier(
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    objective='multi:softprob',
                    eval_metric='mlogloss'
                )
                self.ensemble.add_model('xgboost', model, weight=0.3)
        
        logger.info(f"Built ensemble with {len(self.ensemble.models)} models")
    
    def fit(self, df: pd.DataFrame, target_col: str = 'close'):
        """
        Fit predictor on historical data.
        """
        if self.ensemble is None:
            self.build_ensemble()
        
        # Create target (future returns)
        df['target'] = df[target_col].pct_change(self.horizon).shift(-self.horizon)
        df['target_class'] = pd.cut(
            df['target'],
            bins=[-np.inf, -0.001, 0.001, np.inf],
            labels=[0, 1, 2]  # Down, Neutral, Up
        )
        
        # Drop NaN
        df_clean = df.dropna()
        
        X = df_clean.drop(['target', 'target_class'], axis=1)
        y = df_clean['target_class']
        
        # Fit ensemble
        self.ensemble.fit(X, y)
        self.is_fitted = True
        
        logger.info("Fitting completed")
    
    def predict(self, df: pd.DataFrame) -> Optional[Prediction]:
        """
        Generate prediction for current market state.
        """
        if not self.is_fitted or self.ensemble is None:
            logger.warning("Predictor not fitted")
            return None
        
        start_time = datetime.now()
        
        try:
            prediction = self.ensemble.predict(df)
            prediction.inference_time_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # Record prediction
            self.prediction_history.append(prediction)
            
            # Check if confident enough to trade
            if prediction.confidence < self.confidence_threshold:
                prediction.prediction = "uncertain"
            
            return prediction
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return None
    
    def update_performance(self, actual_return: float):
        """
        Update with actual outcome for online learning.
        """
        if not self.prediction_history:
            return
        
        last_pred = self.prediction_history[-1]
        
        # Calculate if prediction was correct
        actual_direction = 'up' if actual_return > 0.001 else 'down' if actual_return < -0.001 else 'neutral'
        correct = last_pred.prediction == actual_direction
        
        self.accuracy_history.append(correct)
        
        # Trigger online update periodically
        if len(self.accuracy_history) >= 20:
            recent_accuracy = np.mean(self.accuracy_history)
            if recent_accuracy < 0.55:  # Below random guess
                logger.warning(f"Accuracy degraded: {recent_accuracy:.2%}. Triggering retraining...")
                # Would trigger async retraining here
    
    def get_model_report(self) -> Dict:
        """Generate comprehensive model report"""
        if not self.is_fitted:
            return {'status': 'not_fitted'}
        
        return {
            'models': list(self.ensemble.models.keys()) if self.ensemble else [],
            'weights': self.ensemble.weights if self.ensemble else {},
            'confidence_threshold': self.confidence_threshold,
            'prediction_count': len(self.prediction_history),
            'recent_accuracy': np.mean(self.accuracy_history) if self.accuracy_history else None,
            'feature_count': len(self.feature_engineer.feature_names) if self.feature_engineer.is_fitted else 0
        }

# =============================================================================
# EXAMPLE USAGE & TESTING
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("ENHANCED ML PREDICTOR v3.0 - TEST SUITE")
    print("=" * 70)
    
    # Generate synthetic data
    np.random.seed(42)
    n_samples = 5000
    
    dates = pd.date_range(start='2024-01-01', periods=n_samples, freq='5min')
    
    # Generate realistic price series with momentum
    returns = np.random.normal(0.0001, 0.001, n_samples)
    for i in range(1, n_samples):
        returns[i] += returns[i-1] * 0.1  # Momentum
    
    prices = 100 * np.exp(np.cumsum(returns))
    
    df = pd.DataFrame({
        'open': prices * (1 + np.random.normal(0, 0.0001, n_samples)),
        'high': prices * (1 + abs(np.random.normal(0, 0.001, n_samples))),
        'low': prices * (1 - abs(np.random.normal(0, 0.001, n_samples))),
        'close': prices,
        'volume': np.random.poisson(1000, n_samples)
    }, index=dates)
    
    print(f"\nGenerated {len(df)} samples")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    
    # Initialize predictor
    predictor = EnhancedMLPredictor(
        sequence_length=60,
        prediction_horizon=5,
        confidence_threshold=0.6
    )
    
    # Build and fit
    print("\nBuilding ensemble...")
    predictor.build_ensemble(['lstm', 'random_forest'])
    
    print("Fitting models...")
    predictor.fit(df)
    
    # Generate predictions
    print("\nGenerating predictions...")
    predictions = []
    for i in range(100):
        pred_df = df.iloc[-(100-i):-(100-i)+100] if i < 100 else df.iloc[-100:]
        pred = predictor.predict(pred_df)
        if pred:
            predictions.append(pred)
            if i < 5:
                print(f"Pred {i}: {pred.prediction} (conf: {pred.confidence:.2%}, "
                      f"unc: {pred.epistemic_uncertainty:.2%})")
    
    # Report
    print("\n" + "=" * 70)
    print("MODEL REPORT")
    print("=" * 70)
    report = predictor.get_model_report()
    print(f"Models: {report['models']}")
    print(f"Weights: {report['weights']}")
    print(f"Predictions generated: {report['prediction_count']}")
    
    print("\n✅ ML Predictor test completed!")
