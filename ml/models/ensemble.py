"""
Ensemble Price Prediction Model

Advanced ensemble model that combines multiple ML models for superior predictions:
- LSTM for sequential patterns
- Random Forest for feature-based patterns
- Gradient Boosting for residual learning
- Weighted averaging based on performance

Features:
- Dynamic weight adjustment based on recent performance
- Confidence-weighted predictions
- Multi-model consensus analysis
- Automatic model selection
"""

from typing import Dict, Any, Optional, List, Tuple
import numpy as np
import pandas as pd
import logging
from datetime import datetime
from dataclasses import dataclass, field

from .base import BaseMLModel

logger = logging.getLogger(__name__)


@dataclass
class ModelPrediction:
    """Individual model prediction with metadata."""
    model_name: str
    prediction: float
    confidence: float
    weight: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EnsemblePrediction:
    """Ensemble prediction result."""
    prediction: float
    confidence: float
    predictions_by_model: Dict[str, ModelPrediction]
    consensus: str  # 'strong', 'moderate', 'weak', 'divergent'
    direction: str  # 'bullish', 'bearish', 'neutral'
    volatility_factor: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'prediction': self.prediction,
            'confidence': self.confidence,
            'consensus': self.consensus,
            'direction': self.direction,
            'volatility_factor': self.volatility_factor,
            'timestamp': self.timestamp.isoformat(),
            'model_predictions': {
                name: {'prediction': mp.prediction, 'confidence': mp.confidence, 'weight': mp.weight}
                for name, mp in self.predictions_by_model.items()
            }
        }


class EnsemblePredictor(BaseMLModel):
    """
    Advanced ensemble model combining multiple prediction models.

    Combines:
    - LSTM for time-series patterns
    - Random Forest for feature relationships
    - Gradient Boosting for complex interactions
    - XGBoost for fast, accurate predictions

    Features:
    - Dynamic weight adjustment based on recent accuracy
    - Confidence-calibrated predictions
    - Consensus analysis across models
    - Adaptive model selection
    """

    def __init__(self, name: str = "Ensemble_Predictor", config: Optional[Dict] = None):
        """
        Initialize ensemble model.

        Args:
            name: Model name
            config: Configuration dict with:
                - sequence_length: Lookback period (default: 60)
                - use_lstm: Enable LSTM model (default: True)
                - use_rf: Enable Random Forest (default: True)
                - use_gb: Enable Gradient Boosting (default: True)
                - use_xgb: Enable XGBoost (default: True)
                - dynamic_weights: Adjust weights based on performance (default: True)
                - confidence_threshold: Min confidence for prediction (default: 0.5)
        """
        super().__init__(name, config)

        # Configuration
        self.sequence_length = self.config.get('sequence_length', 60)
        self.use_lstm = self.config.get('use_lstm', True)
        self.use_rf = self.config.get('use_rf', True)
        self.use_gb = self.config.get('use_gb', True)
        self.use_xgb = self.config.get('use_xgb', True)
        self.dynamic_weights = self.config.get('dynamic_weights', True)
        self.confidence_threshold = self.config.get('confidence_threshold', 0.5)

        # Model weights (adjusted based on performance)
        self.model_weights = {
            'lstm': 0.30,
            'random_forest': 0.25,
            'gradient_boosting': 0.25,
            'xgboost': 0.20,
        }

        # Individual models
        self.models = {}

        # Performance tracking
        self.model_performance = {
            'lstm': {'correct': 0, 'total': 0, 'mse': 0.0, 'recent_errors': []},
            'random_forest': {'correct': 0, 'total': 0, 'mse': 0.0, 'recent_errors': []},
            'gradient_boosting': {'correct': 0, 'total': 0, 'mse': 0.0, 'recent_errors': []},
            'xgboost': {'correct': 0, 'total': 0, 'mse': 0.0, 'recent_errors': []},
        }

        # Scalers
        self.scaler_X = None
        self.scaler_y = None

        # Prediction history for confidence calibration
        self.prediction_history = []

    def build(self) -> None:
        """Build all component models."""
        try:
            # Build LSTM model
            if self.use_lstm:
                self._build_lstm()

            # Build Random Forest
            if self.use_rf:
                self._build_random_forest()

            # Build Gradient Boosting
            if self.use_gb:
                self._build_gradient_boosting()

            # Build XGBoost
            if self.use_xgb:
                self._build_xgboost()

            self.logger.info(f"Ensemble built with models: {list(self.models.keys())}")

        except Exception as e:
            self.logger.error(f"Error building ensemble: {e}")
            raise

    def _build_lstm(self):
        """Build LSTM component."""
        try:
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
            from tensorflow.keras.optimizers import Adam

            model = Sequential([
                LSTM(64, return_sequences=True, input_shape=(self.sequence_length, 1)),
                Dropout(0.2),
                BatchNormalization(),
                LSTM(32, return_sequences=False),
                Dropout(0.2),
                Dense(16, activation='relu'),
                Dense(1)
            ])

            model.compile(
                optimizer=Adam(learning_rate=0.001),
                loss='huber',
                metrics=['mae']
            )

            self.models['lstm'] = model
            self.logger.info("LSTM model built")

        except ImportError:
            self.logger.warning("TensorFlow not available, skipping LSTM")
            self.use_lstm = False

    def _build_random_forest(self):
        """Build Random Forest component."""
        try:
            from sklearn.ensemble import RandomForestRegressor

            self.models['random_forest'] = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                min_samples_leaf=2,
                n_jobs=-1,
                random_state=42
            )
            self.logger.info("Random Forest model built")

        except ImportError:
            self.logger.warning("scikit-learn not available, skipping Random Forest")
            self.use_rf = False

    def _build_gradient_boosting(self):
        """Build Gradient Boosting component."""
        try:
            from sklearn.ensemble import GradientBoostingRegressor

            self.models['gradient_boosting'] = GradientBoostingRegressor(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=5,
                min_samples_split=5,
                min_samples_leaf=2,
                subsample=0.8,
                random_state=42
            )
            self.logger.info("Gradient Boosting model built")

        except ImportError:
            self.logger.warning("scikit-learn not available, skipping Gradient Boosting")
            self.use_gb = False

    def _build_xgboost(self):
        """Build XGBoost component."""
        try:
            import xgboost as xgb

            self.models['xgboost'] = xgb.XGBRegressor(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=5,
                subsample=0.8,
                colsample_bytree=0.8,
                objective='reg:squarederror',
                random_state=42
            )
            self.logger.info("XGBoost model built")

        except ImportError:
            self.logger.warning("XGBoost not available, skipping")
            self.use_xgb = False

    def _prepare_features(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare features for training/prediction.

        Creates features:
        - Lagged values
        - Moving averages
        - Momentum indicators
        - Volatility features
        """
        features = []
        targets = []

        for i in range(self.sequence_length, len(data)):
            window = data[i-self.sequence_length:i]

            # Technical features
            feature_vector = [
                window[-1],  # Current value
                np.mean(window),  # SMA
                np.std(window),  # Volatility
                np.mean(window[-10:]),  # Short-term MA
                np.mean(window[-20:]) if len(window) >= 20 else np.mean(window),  # Medium MA
                window[-1] - window[-2] if len(window) >= 2 else 0,  # Momentum 1
                window[-1] - window[-5] if len(window) >= 5 else 0,  # Momentum 5
                np.max(window) - np.min(window),  # Range
                (window[-1] - np.min(window)) / (np.max(window) - np.min(window) + 1e-8),  # %K
                np.mean(np.diff(window)),  # Trend
            ]

            features.append(feature_vector)
            targets.append(data[i])

        return np.array(features), np.array(targets)

    def _prepare_lstm_sequences(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare sequences for LSTM."""
        X, y = [], []
        for i in range(self.sequence_length, len(data)):
            X.append(data[i-self.sequence_length:i])
            y.append(data[i])
        return np.array(X).reshape(-1, self.sequence_length, 1), np.array(y)

    def train(self, X_train: np.ndarray, y_train: np.ndarray,
              X_val: Optional[np.ndarray] = None,
              y_val: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Train all component models.

        Args:
            X_train: Training features (raw price series)
            y_train: Not used (targets generated from X_train)
            X_val: Validation features
            y_val: Not used

        Returns:
            Training results for all models
        """
        if not self.models:
            self.build()

        try:
            from sklearn.preprocessing import MinMaxScaler

            # Scale data
            self.scaler_X = MinMaxScaler()
            data_scaled = self.scaler_X.fit_transform(X_train.reshape(-1, 1)).flatten()

            # Prepare features
            X_features, y_targets = self._prepare_features(data_scaled)

            # Scale targets
            self.scaler_y = MinMaxScaler()
            y_scaled = self.scaler_y.fit_transform(y_targets.reshape(-1, 1)).flatten()

            results = {}

            # Train LSTM
            if 'lstm' in self.models:
                self.logger.info("Training LSTM...")
                X_lstm, y_lstm = self._prepare_lstm_sequences(data_scaled)

                from tensorflow.keras.callbacks import EarlyStopping
                early_stop = EarlyStopping(patience=10, restore_best_weights=True)

                history = self.models['lstm'].fit(
                    X_lstm, y_lstm,
                    epochs=50,
                    batch_size=32,
                    validation_split=0.2,
                    callbacks=[early_stop],
                    verbose=0
                )
                results['lstm'] = {
                    'loss': float(history.history['loss'][-1]),
                    'val_loss': float(history.history.get('val_loss', [0])[-1])
                }
                self.logger.info(f"LSTM trained: loss={results['lstm']['loss']:.6f}")

            # Train Random Forest
            if 'random_forest' in self.models:
                self.logger.info("Training Random Forest...")
                self.models['random_forest'].fit(X_features, y_scaled)
                results['random_forest'] = {'trained': True}
                self.logger.info("Random Forest trained")

            # Train Gradient Boosting
            if 'gradient_boosting' in self.models:
                self.logger.info("Training Gradient Boosting...")
                self.models['gradient_boosting'].fit(X_features, y_scaled)
                results['gradient_boosting'] = {'trained': True}
                self.logger.info("Gradient Boosting trained")

            # Train XGBoost
            if 'xgboost' in self.models:
                self.logger.info("Training XGBoost...")
                self.models['xgboost'].fit(X_features, y_scaled)
                results['xgboost'] = {'trained': True}
                self.logger.info("XGBoost trained")

            self.is_trained = True
            self.training_history.append({
                'timestamp': datetime.now().isoformat(),
                'results': results,
                'data_points': len(X_train)
            })

            return results

        except Exception as e:
            self.logger.error(f"Error training ensemble: {e}")
            raise

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Make ensemble predictions.

        Args:
            X: Input features (raw price series)

        Returns:
            Array of predictions
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")

        ensemble_predictions = self.predict_with_confidence(X)
        return np.array([p.prediction for p in ensemble_predictions])

    def predict_with_confidence(self, X: np.ndarray) -> List[EnsemblePrediction]:
        """
        Make predictions with confidence scores and model breakdown.

        Args:
            X: Input features (raw price series)

        Returns:
            List of EnsemblePrediction objects
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")

        try:
            # Scale data
            data_scaled = self.scaler_X.transform(X.reshape(-1, 1)).flatten()

            # Prepare features
            X_features, _ = self._prepare_features(data_scaled)

            predictions = []

            for i in range(len(X_features)):
                model_predictions = {}

                # Get LSTM prediction
                if 'lstm' in self.models:
                    lstm_seq = data_scaled[i:i+self.sequence_length].reshape(1, self.sequence_length, 1)
                    if lstm_seq.shape[1] == self.sequence_length:
                        lstm_pred_scaled = self.models['lstm'].predict(lstm_seq, verbose=0)[0][0]
                        lstm_pred = self.scaler_y.inverse_transform([[lstm_pred_scaled]])[0][0]
                        model_predictions['lstm'] = ModelPrediction(
                            model_name='lstm',
                            prediction=lstm_pred,
                            confidence=self._calculate_model_confidence('lstm'),
                            weight=self.model_weights['lstm']
                        )

                # Get Random Forest prediction
                if 'random_forest' in self.models:
                    rf_pred_scaled = self.models['random_forest'].predict([X_features[i]])[0]
                    rf_pred = self.scaler_y.inverse_transform([[rf_pred_scaled]])[0][0]
                    model_predictions['random_forest'] = ModelPrediction(
                        model_name='random_forest',
                        prediction=rf_pred,
                        confidence=self._calculate_model_confidence('random_forest'),
                        weight=self.model_weights['random_forest']
                    )

                # Get Gradient Boosting prediction
                if 'gradient_boosting' in self.models:
                    gb_pred_scaled = self.models['gradient_boosting'].predict([X_features[i]])[0]
                    gb_pred = self.scaler_y.inverse_transform([[gb_pred_scaled]])[0][0]
                    model_predictions['gradient_boosting'] = ModelPrediction(
                        model_name='gradient_boosting',
                        prediction=gb_pred,
                        confidence=self._calculate_model_confidence('gradient_boosting'),
                        weight=self.model_weights['gradient_boosting']
                    )

                # Get XGBoost prediction
                if 'xgboost' in self.models:
                    xgb_pred_scaled = self.models['xgboost'].predict([X_features[i]])[0]
                    xgb_pred = self.scaler_y.inverse_transform([[xgb_pred_scaled]])[0][0]
                    model_predictions['xgboost'] = ModelPrediction(
                        model_name='xgboost',
                        prediction=xgb_pred,
                        confidence=self._calculate_model_confidence('xgboost'),
                        weight=self.model_weights['xgboost']
                    )

                # Calculate ensemble prediction
                ensemble_pred = self._combine_predictions(model_predictions)
                predictions.append(ensemble_pred)

            return predictions

        except Exception as e:
            self.logger.error(f"Error making ensemble predictions: {e}")
            raise

    def _combine_predictions(self, model_predictions: Dict[str, ModelPrediction]) -> EnsemblePrediction:
        """Combine individual model predictions into ensemble prediction."""

        if not model_predictions:
            return EnsemblePrediction(
                prediction=0.0,
                confidence=0.0,
                predictions_by_model={},
                consensus='divergent',
                direction='neutral',
                volatility_factor=0.0
            )

        # Weight predictions by confidence and weight
        weighted_sum = 0.0
        weight_total = 0.0
        all_predictions = []

        for name, mp in model_predictions.items():
            combined_weight = mp.weight * mp.confidence
            weighted_sum += mp.prediction * combined_weight
            weight_total += combined_weight
            all_predictions.append(mp.prediction)

        # Ensemble prediction
        final_prediction = weighted_sum / weight_total if weight_total > 0 else 0.0

        # Calculate consensus
        if len(all_predictions) > 1:
            std_dev = np.std(all_predictions)
            mean_pred = np.mean(all_predictions)
            cv = std_dev / abs(mean_pred) if mean_pred != 0 else 1.0

            if cv < 0.05:
                consensus = 'strong'
            elif cv < 0.15:
                consensus = 'moderate'
            elif cv < 0.30:
                consensus = 'weak'
            else:
                consensus = 'divergent'
        else:
            consensus = 'single_model'

        # Calculate overall confidence
        avg_confidence = np.mean([mp.confidence for mp in model_predictions.values()])
        consensus_factor = {'strong': 1.2, 'moderate': 1.0, 'weak': 0.8, 'divergent': 0.6, 'single_model': 0.9}
        final_confidence = min(avg_confidence * consensus_factor[consensus], 1.0)

        # Determine direction (relative to recent values)
        direction = 'neutral'
        # This would be compared to current price in practice

        # Volatility factor
        volatility_factor = np.std(all_predictions) / abs(np.mean(all_predictions)) if all_predictions else 0.0

        return EnsemblePrediction(
            prediction=final_prediction,
            confidence=final_confidence,
            predictions_by_model=model_predictions,
            consensus=consensus,
            direction=direction,
            volatility_factor=volatility_factor
        )

    def _calculate_model_confidence(self, model_name: str) -> float:
        """Calculate confidence for a specific model based on recent performance."""
        perf = self.model_performance[model_name]

        if perf['total'] == 0:
            return 0.5  # Default confidence

        # Calculate accuracy
        accuracy = perf['correct'] / perf['total']

        # Calculate recent MSE factor
        if perf['recent_errors']:
            recent_mse = np.mean([e**2 for e in perf['recent_errors'][-20:]])
            mse_factor = 1.0 / (1.0 + recent_mse)
        else:
            mse_factor = 0.5

        # Combine factors
        confidence = (accuracy * 0.6 + mse_factor * 0.4)
        return min(max(confidence, 0.1), 0.95)  # Clip between 0.1 and 0.95

    def update_performance(self, model_name: str, prediction: float, actual: float):
        """Update model performance tracking."""
        if model_name not in self.model_performance:
            return

        perf = self.model_performance[model_name]
        error = prediction - actual

        perf['total'] += 1
        perf['recent_errors'].append(error)
        perf['recent_errors'] = perf['recent_errors'][-100:]  # Keep last 100

        # Direction accuracy
        if (prediction > 0 and actual > 0) or (prediction < 0 and actual < 0):
            perf['correct'] += 1

        # Update MSE
        perf['mse'] = np.mean([e**2 for e in perf['recent_errors']])

        # Update weights if dynamic
        if self.dynamic_weights:
            self._update_weights()

    def _update_weights(self):
        """Dynamically update model weights based on performance."""
        total_confidence = 0.0
        confidences = {}

        for model_name in self.models.keys():
            conf = self._calculate_model_confidence(model_name)
            confidences[model_name] = conf
            total_confidence += conf

        if total_confidence > 0:
            for model_name in self.models.keys():
                self.model_weights[model_name] = confidences[model_name] / total_confidence

    def get_model_summary(self) -> Dict[str, Any]:
        """Get summary of all models in ensemble."""
        return {
            'models': list(self.models.keys()),
            'weights': self.model_weights.copy(),
            'performance': {
                name: {
                    'accuracy': perf['correct'] / perf['total'] if perf['total'] > 0 else 0,
                    'total_predictions': perf['total'],
                    'recent_mse': np.mean([e**2 for e in perf['recent_errors'][-20:]]) if perf['recent_errors'] else 0
                }
                for name, perf in self.model_performance.items()
                if name in self.models
            },
            'is_trained': self.is_trained,
            'config': self.config
        }
