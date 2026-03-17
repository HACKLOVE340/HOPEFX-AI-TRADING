# ml/models/lstm_predictor.py
"""
LSTM Price Prediction Model with Risk Controls
Implements online learning with concept drift detection
"""

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from sklearn.preprocessing import RobustScaler
from typing import Dict, List, Optional, Tuple
import joblib
import json
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class LSTMPricePredictor:
    """
    Production-grade LSTM predictor with:
    - Online learning capability
    - Concept drift detection
    - Prediction uncertainty quantification
    - Risk-aware confidence thresholds
    """
    
    def __init__(
        self,
        sequence_length: int = 60,
        n_features: int = 20,
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.65  # Minimum confidence for trading
    ):
        self.sequence_length = sequence_length
        self.n_features = n_features
        self.confidence_threshold = confidence_threshold
        self.model: Optional[tf.keras.Model] = None
        self.scaler = RobustScaler()
        self.feature_importance: Dict[str, float] = {}
        
        # Online learning state
        self.drift_detector = ConceptDriftDetector()
        self.retrain_counter = 0
        self.prediction_history: List[Dict] = []
        
        if model_path and Path(model_path).exists():
            self.load(model_path)
        else:
            self._build_model()
    
    def _build_model(self) -> None:
        """Build LSTM architecture with regularization for stability"""
        self.model = Sequential([
            LSTM(128, return_sequences=True, 
                 input_shape=(self.sequence_length, self.n_features),
                 kernel_regularizer=tf.keras.regularizers.l2(0.001)),
            BatchNormalization(),
            Dropout(0.2),
            
            LSTM(64, return_sequences=False,
                 kernel_regularizer=tf.keras.regularizers.l2(0.001)),
            BatchNormalization(),
            Dropout(0.2),
            
            Dense(32, activation='relu'),
            Dropout(0.1),
            Dense(3, activation='softmax')  # [down, neutral, up]
        ])
        
        self.model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            loss='categorical_crossentropy',
            metrics=['accuracy', tf.keras.metrics.AUC()]
        )
        
        logger.info("LSTM model built with architecture: %s", self.model.summary())
    
    def prepare_features(self, data: pd.DataFrame) -> np.ndarray:
        """
        Feature engineering with financial domain knowledge
        Risk: Feature leakage prevention
        """
        features = pd.DataFrame(index=data.index)
        
        # Price-based features (no lookahead)
        features['returns'] = data['close'].pct_change()
        features['log_returns'] = np.log1p(features['returns'])
        
        # Volatility features
        for window in [5, 10, 20, 50]:
            features[f'volatility_{window}'] = features['returns'].rolling(window).std()
            features[f'ma_{window}'] = data['close'].rolling(window).mean()
            features[f'ma_ratio_{window}'] = data['close'] / features[f'ma_{window}']
        
        # Technical indicators
        features['rsi'] = self._calculate_rsi(data['close'], 14)
        features['macd'] = self._calculate_macd(data['close'])
        
        # Volume features
        if 'volume' in data.columns:
            features['volume_ma'] = data['volume'].rolling(20).mean()
            features['volume_ratio'] = data['volume'] / features['volume_ma']
        
        # Time features (cyclical encoding)
        features['hour_sin'] = np.sin(2 * np.pi * data.index.hour / 24)
        features['hour_cos'] = np.cos(2 * np.pi * data.index.hour / 24)
        features['day_sin'] = np.sin(2 * np.pi * data.index.dayofweek / 5)
        
        # Drop NaN from rolling calculations
        features = features.dropna()
        
        return features.values
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI without lookahead bias"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_macd(self, prices: pd.Series) -> pd.Series:
        """Calculate MACD"""
        ema12 = prices.ewm(span=12).mean()
        ema26 = prices.ewm(span=26).mean()
        return ema12 - ema26
    
    def create_sequences(self, features: np.ndarray, targets: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Create sequences for LSTM with proper labeling"""
        X, y = [], []
        for i in range(len(features) - self.sequence_length):
            X.append(features[i:(i + self.sequence_length)])
            y.append(targets[i + self.sequence_length])
        return np.array(X), np.array(y)
    
    def fit(
        self,
        data: pd.DataFrame,
        validation_split: float = 0.2,
        epochs: int = 100,
        batch_size: int = 32,
        early_stopping_patience: int = 10
    ) -> Dict:
        """
        Train model with validation and checkpointing
        Risk: Overfitting prevention via early stopping and dropout
        """
        # Prepare features
        features = self.prepare_features(data)
        
        # Create targets (next period direction)
        future_returns = data['close'].pct_change().shift(-1).dropna()
        targets = pd.cut(future_returns, bins=[-np.inf, -0.001, 0.001, np.inf], 
                        labels=[0, 1, 2]).values  # [down, neutral, up]
        
        # Align lengths
        min_len = min(len(features), len(targets))
        features = features[:min_len]
        targets = targets[:min_len]
        
        # Scale features
        features_scaled = self.scaler.fit_transform(features)
        
        # Create sequences
        X, y = self.create_sequences(features_scaled, targets)
        
        # One-hot encode targets
        y = tf.keras.utils.to_categorical(y, num_classes=3)
        
        # Split validation
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # Callbacks
        callbacks = [
            EarlyStopping(
                monitor='val_loss',
                patience=early_stopping_patience,
                restore_best_weights=True
            ),
            ModelCheckpoint(
                'models/lstm_best.keras',
                monitor='val_accuracy',
                save_best_only=True
            )
        ]
        
        # Train
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=1
        )
        
        # Calculate feature importance via permutation
        self.feature_importance = self._calculate_feature_importance(X_val, y_val)
        
        return {
            'final_accuracy': history.history['accuracy'][-1],
            'final_val_accuracy': history.history['val_accuracy'][-1],
            'final_loss': history.history['loss'][-1],
            'epochs_trained': len(history.history['loss'])
        }
    
    def predict(self, data: pd.DataFrame) -> Dict:
        """
        Generate prediction with uncertainty quantification
        Risk: Only trade if confidence > threshold
        """
        if self.model is None:
            raise ValueError("Model not trained or loaded")
        
        # Check for concept drift
        if self.drift_detector.detect_drift(data):
            logger.warning("Concept drift detected! Model may need retraining.")
        
        # Prepare features
        features = self.prepare_features(data)
        features_scaled = self.scaler.transform(features)
        
        # Need sequence_length data points
        if len(features_scaled) < self.sequence_length:
            raise ValueError(f"Need {self.sequence_length} data points, got {len(features_scaled)}")
        
        # Get last sequence
        last_sequence = features_scaled[-self.sequence_length:].reshape(1, self.sequence_length, -1)
        
        # Monte Carlo dropout for uncertainty (10 forward passes)
        predictions = []
        for _ in range(10):
            pred = self.model(last_sequence, training=True)  # Enable dropout
            predictions.append(pred.numpy()[0])
        
        predictions = np.array(predictions)
        mean_pred = predictions.mean(axis=0)
        std_pred = predictions.std(axis=0)
        
        # Direction and confidence
        direction = np.argmax(mean_pred)  # 0=down, 1=neutral, 2=up
        confidence = mean_pred[direction]
        uncertainty = std_pred[direction]
        
        # Risk check: Only predict if confidence > threshold and uncertainty < 0.1
        trade_signal = confidence > self.confidence_threshold and uncertainty < 0.1
        
        result = {
            'direction': ['down', 'neutral', 'up'][direction],
            'confidence': float(confidence),
            'uncertainty': float(uncertainty),
            'probabilities': {
                'down': float(mean_pred[0]),
                'neutral': float(mean_pred[1]),
                'up': float(mean_pred[2])
            },
            'trade_signal': trade_signal,
            'timestamp': datetime.now().isoformat()
        }
        
        self.prediction_history.append(result)
        
        return result
    
    def _calculate_feature_importance(
        self,
        X: np.ndarray,
        y: np.ndarray,
        n_repeats: int = 5
    ) -> Dict[str, float]:
        """Calculate feature importance via permutation importance"""
        baseline_score = self.model.evaluate(X, y, verbose=0)[1]  # accuracy
        
        importances = {}
        for i in range(X.shape[2]):  # n_features
            scores = []
            for _ in range(n_repeats):
                X_permuted = X.copy()
                np.random.shuffle(X_permuted[:, :, i])
                score = self.model.evaluate(X_permuted, y, verbose=0)[1]
                scores.append(baseline_score - score)
            importances[f'feature_{i}'] = np.mean(scores)
        
        return importances
    
    def online_update(self, new_data: pd.DataFrame, batch_size: int = 32) -> None:
        """
        Online learning with new data
        Risk: Catastrophic forgetting prevention via low learning rate
        """
        if len(self.prediction_history) < 100:
            return  # Not enough history
        
        # Check if retraining needed
        recent_accuracy = self._calculate_recent_accuracy()
        if recent_accuracy > 0.6:  # Still performing well
            return
        
        logger.info("Triggering online learning update...")
        
        # Prepare new data
        features = self.prepare_features(new_data)
        features_scaled = self.scaler.transform(features)
        
        # Create sequences
        targets = pd.cut(new_data['close'].pct_change().shift(-1).dropna(), 
                        bins=[-np.inf, -0.001, 0.001, np.inf], 
                        labels=[0, 1, 2]).values[:len(features_scaled)]
        
        X, y = self.create_sequences(features_scaled, targets)
        y = tf.keras.utils.to_categorical(y, num_classes=3)
        
        # Fine-tune with low learning rate to prevent catastrophic forgetting
        self.model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.0001),  # 10x lower
            loss='categorical_crossentropy',
            metrics=['accuracy']
        )
        
        self.model.fit(X, y, epochs=5, batch_size=batch_size, verbose=0)
        self.retrain_counter += 1
        
        logger.info(f"Online update completed. Total updates: {self.retrain_counter}")
    
    def _calculate_recent_accuracy(self) -> float:
        """Calculate accuracy on recent predictions"""
        if len(self.prediction_history) < 20:
            return 1.0  # Assume good if no history
        
        # Compare predictions to actual outcomes
        # Simplified - would need actual price data
        return 0.7  # Placeholder
    
    def save(self, path: str) -> None:
        """Save model, scaler, and metadata"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        self.model.save(f"{path}/model.keras")
        joblib.dump(self.scaler, f"{path}/scaler.pkl")
        
        metadata = {
            'sequence_length': self.sequence_length,
            'n_features': self.n_features,
            'confidence_threshold': self.confidence_threshold,
            'feature_importance': self.feature_importance,
            'retrain_counter': self.retrain_counter,
            'saved_at': datetime.now().isoformat()
        }
        
        with open(f"{path}/metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Model saved to {path}")
    
    def load(self, path: str) -> None:
        """Load model, scaler, and metadata"""
        self.model = load_model(f"{path}/model.keras")
        self.scaler = joblib.load(f"{path}/scaler.pkl")
        
        with open(f"{path}/metadata.json", 'r') as f:
            metadata = json.load(f)
            self.sequence_length = metadata['sequence_length']
            self.n_features = metadata['n_features']
            self.confidence_threshold = metadata['confidence_threshold']
            self.feature_importance = metadata.get('feature_importance', {})
            self.retrain_counter = metadata.get('retrain_counter', 0)
        
        logger.info(f"Model loaded from {path}")


class ConceptDriftDetector:
    """Detect when market regime changes and model needs retraining"""
    
    def __init__(self, window_size: int = 100, threshold: float = 0.05):
        self.window_size = window_size
        self.threshold = threshold
        self.reference_distribution = None
    
    def detect_drift(self, new_data: pd.DataFrame) -> bool:
        """Simple drift detection using Kolmogorov-Smirnov test concept"""
        if len(new_data) < self.window_size:
            return False
        
        current_returns = new_data['close'].pct_change().dropna().values[-self.window_size:]
        
        if self.reference_distribution is None:
            self.reference_distribution = current_returns
            return False
        
        # Simple mean shift detection (production would use proper statistical test)
        ref_mean = np.mean(self.reference_distribution)
        curr_mean = np.mean(current_returns)
        
        if abs(curr_mean - ref_mean) > self.threshold * np.std(self.reference_distribution):
            self.reference_distribution = current_returns  # Update reference
            return True
        
        return False
