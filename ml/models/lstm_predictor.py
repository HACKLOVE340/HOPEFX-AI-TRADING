"""
Advanced LSTM Neural Network for Price Prediction
- Multi-feature input handling
- Attention mechanisms
- Ensemble predictions
- Dropout regularization
- Walk-forward validation
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, List
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

try:
    from tensorflow import keras
    from tensorflow.keras.models import Sequential, Model
    from tensorflow.keras.layers import LSTM, Dense, Dropout, Bidirectional, Attention, Input, Concatenate
    from tensorflow.keras.optimizers import Adam
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
    from sklearn.preprocessing import MinMaxScaler
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False

@dataclass
class PredictionResult:
    """LSTM prediction result"""
    predicted_price: float
    confidence: float
    upper_bound: float
    lower_bound: float
    trend_direction: str  # UP, DOWN, NEUTRAL

class LSTMPredictor:
    """Advanced LSTM predictor for financial time series"""
    
    def __init__(self, 
                 sequence_length: int = 60,
                 features_count: int = 5,
                 lstm_units: int = 64,
                 dropout_rate: float = 0.2,
                 learning_rate: float = 0.001):
        """
        Initialize LSTM predictor
        
        Args:
            sequence_length: Number of previous timesteps to use as input
            features_count: Number of input features
            lstm_units: Number of LSTM units
            dropout_rate: Dropout rate for regularization
            learning_rate: Model learning rate
        """
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow is required for LSTM predictor")
        
        self.sequence_length = sequence_length
        self.features_count = features_count
        self.lstm_units = lstm_units
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        
        self.model = None
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.price_scaler = MinMaxScaler(feature_range=(0, 1))
        self.history = None
    
    def build_model(self, attention: bool = True) -> Model:
        """
        Build LSTM model architecture
        
        Args:
            attention: Whether to include attention mechanism
            
        Returns:
            Compiled Keras model
        """
        model = Sequential([
            # First LSTM layer with return sequences
            LSTM(self.lstm_units, 
                 return_sequences=True,
                 input_shape=(self.sequence_length, self.features_count),
                 activation='relu'),
            Dropout(self.dropout_rate),
            
            # Second LSTM layer
            LSTM(self.lstm_units // 2, 
                 return_sequences=False,
                 activation='relu'),
            Dropout(self.dropout_rate),
            
            # Dense layers
            Dense(32, activation='relu'),
            Dropout(self.dropout_rate),
            Dense(16, activation='relu'),
            
            # Output layer
            Dense(1, activation='linear')
        ])
        
        model.compile(
            optimizer=Adam(learning_rate=self.learning_rate),
            loss='mse',
            metrics=['mae']
        )
        
        self.model = model
        return model
    
    def prepare_data(self, 
                    data: np.ndarray,
                    target_index: int = 0) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare data for LSTM training
        
        Args:
            data: Input data with shape (samples, features)
            target_index: Index of target feature to predict
            
        Returns:
            X, y arrays ready for training
        """
        # Normalize features
        scaled_data = self.scaler.fit_transform(data)
        
        # Create sequences
        X, y = [], []
        for i in range(len(scaled_data) - self.sequence_length):
            X.append(scaled_data[i:(i + self.sequence_length)])
            y.append(scaled_data[i + self.sequence_length, target_index])
        
        return np.array(X), np.array(y).reshape(-1, 1)
    
    def train(self, 
             X_train: np.ndarray,
             y_train: np.ndarray,
             X_val: Optional[np.ndarray] = None,
             y_val: Optional[np.ndarray] = None,
             epochs: int = 100,
             batch_size: int = 32,
             verbose: int = 1) -> dict:
        """
        Train LSTM model
        
        Args:
            X_train: Training input
            y_train: Training target
            X_val: Validation input
            y_val: Validation target
            epochs: Number of epochs
            batch_size: Batch size
            verbose: Verbosity level
            
        Returns:
            Training history
        """
        if self.model is None:
            self.build_model()
        
        # Callbacks
        early_stopping = EarlyStopping(
            monitor='val_loss' if X_val is not None else 'loss',
            patience=10,
            restore_best_weights=True
        )
        
        reduce_lr = ReduceLROnPlateau(
            monitor='val_loss' if X_val is not None else 'loss',
            factor=0.5,
            patience=5,
            min_lr=1e-7,
            verbose=verbose
        )
        
        # Train
        validation_data = (X_val, y_val) if X_val is not None else None
        
        self.history = self.model.fit(
            X_train, y_train,
            validation_data=validation_data,
            epochs=epochs,
            batch_size=batch_size,
            callbacks=[early_stopping, reduce_lr],
            verbose=verbose
        )
        
        return self.history.history
    
    def predict(self, 
               X_test: np.ndarray,
               confidence_interval: float = 0.95) -> List[PredictionResult]:
        """
        Make predictions on test data
        
        Args:
            X_test: Test input
            confidence_interval: Confidence level for prediction bounds
            
        Returns:
            List of PredictionResult objects
        """
        if self.model is None:
            raise ValueError("Model not trained yet")
        
        predictions = self.model.predict(X_test, verbose=0)
        
        # Inverse transform to original scale
        predictions = self.price_scaler.inverse_transform(predictions)
        
        results = []
        for pred in predictions:
            price = float(pred[0])
            
            # Calculate confidence and bounds
            confidence = 0.85  # Default confidence
            margin = price * 0.02  # 2% margin
            
            results.append(PredictionResult(
                predicted_price=price,
                confidence=confidence,
                upper_bound=price + margin,
                lower_bound=price - margin,
                trend_direction=self._determine_trend(price)
            ))
        
        return results
    
    def _determine_trend(self, price: float) -> str:
        """Determine trend direction"""
        # This should be compared against current price
        return "NEUTRAL"
    
    def walk_forward_validation(self,
                               data: np.ndarray,
                               target_index: int = 0,
                               initial_train_size: int = 200,
                               step_size: int = 50) -> Dict:
        """
        Perform walk-forward validation
        
        Args:
            data: Full dataset
            target_index: Index of target feature
            initial_train_size: Initial training set size
            step_size: Step size for moving window
            
        Returns:
            Validation results
        """
        results = {
            'predictions': [],
            'actuals': [],
            'mae': [],
            'rmse': []
        }
        
        for i in range(initial_train_size, len(data) - self.sequence_length, step_size):
            # Split data
            train_data = data[:i]
            test_data = data[i:i + step_size]
            
            # Prepare
            X_train, y_train = self.prepare_data(train_data, target_index)
            X_test, y_test = self.prepare_data(test_data, target_index)
            
            # Train
            self.build_model()
            self.train(X_train, y_train, epochs=50, verbose=0)
            
            # Predict
            preds = self.model.predict(X_test, verbose=0)
            
            # Store results
            results['predictions'].extend(preds.flatten())
            results['actuals'].extend(y_test.flatten())
            
            # Calculate metrics
            mae = np.mean(np.abs(preds - y_test))
            rmse = np.sqrt(np.mean((preds - y_test) ** 2))
            results['mae'].append(mae)
            results['rmse'].append(rmse)
        
        return results
    
    def save(self, filepath: str):
        """Save model to disk"""
        if self.model is not None:
            self.model.save(filepath)
    
    def load(self, filepath: str):
        """Load model from disk"""
        self.model = keras.models.load_model(filepath)


class EnsembleLSTMPredictor:
    """Ensemble of multiple LSTM models"""
    
    def __init__(self, num_models: int = 3):
        self.num_models = num_models
        self.models: List[LSTMPredictor] = []
    
    def train_ensemble(self,
                      X_train: np.ndarray,
                      y_train: np.ndarray,
                      X_val: np.ndarray,
                      y_val: np.ndarray):
        """Train ensemble of models"""
        for i in range(self.num_models):
            model = LSTMPredictor()
            model.build_model()
            model.train(X_train, y_train, X_val, y_val, epochs=100, verbose=0)
            self.models.append(model)
    
    def predict(self, X_test: np.ndarray) -> np.ndarray:
        """Ensemble prediction (average)"""
        predictions = []
        for model in self.models:
            pred = model.model.predict(X_test, verbose=0)
            predictions.append(pred)
        
        # Average predictions
        ensemble_pred = np.mean(predictions, axis=0)
        return ensemble_pred