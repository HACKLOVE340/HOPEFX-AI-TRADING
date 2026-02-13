"""
LSTM Price Prediction Model

Long Short-Term Memory neural network for time series price prediction.
Uses TensorFlow/Keras for deep learning.
"""

from typing import Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
import logging

from .base import BaseMLModel

logger = logging.getLogger(__name__)


class LSTMPricePredictor(BaseMLModel):
    """
    LSTM model for price prediction.
    
    Features:
    - Multi-layer LSTM architecture
    - Dropout for regularization
    - Time series sequence handling
    - Price movement prediction
    """
    
    def __init__(self, name: str = "LSTM_Predictor", config: Optional[Dict] = None):
        """
        Initialize LSTM model.
        
        Args:
            name: Model name
            config: Configuration dict with:
                - sequence_length: Lookback period (default: 60)
                - lstm_units: LSTM layer sizes (default: [50, 50])
                - dropout: Dropout rate (default: 0.2)
                - epochs: Training epochs (default: 100)
                - batch_size: Batch size (default: 32)
                - learning_rate: Learning rate (default: 0.001)
        """
        super().__init__(name, config)
        
        # Model parameters
        self.sequence_length = self.config.get('sequence_length', 60)
        self.lstm_units = self.config.get('lstm_units', [50, 50])
        self.dropout = self.config.get('dropout', 0.2)
        self.epochs = self.config.get('epochs', 100)
        self.batch_size = self.config.get('batch_size', 32)
        self.learning_rate = self.config.get('learning_rate', 0.001)
        
        # Data scaling
        self.scaler_X = None
        self.scaler_y = None
    
    def build(self) -> None:
        """Build LSTM model architecture."""
        try:
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout
            from tensorflow.keras.optimizers import Adam
            
            model = Sequential()
            
            # First LSTM layer
            model.add(LSTM(
                units=self.lstm_units[0],
                return_sequences=len(self.lstm_units) > 1,
                input_shape=(self.sequence_length, 1)
            ))
            model.add(Dropout(self.dropout))
            
            # Additional LSTM layers
            for i, units in enumerate(self.lstm_units[1:], 1):
                return_seq = i < len(self.lstm_units) - 1
                model.add(LSTM(units=units, return_sequences=return_seq))
                model.add(Dropout(self.dropout))
            
            # Output layer
            model.add(Dense(units=1))
            
            # Compile model
            model.compile(
                optimizer=Adam(learning_rate=self.learning_rate),
                loss='mean_squared_error',
                metrics=['mae']
            )
            
            self.model = model
            self.logger.info(f"LSTM model built with architecture: {self.lstm_units}")
            
        except ImportError:
            self.logger.error("TensorFlow not installed. Please install: pip install tensorflow")
            raise
        except Exception as e:
            self.logger.error(f"Error building LSTM model: {e}")
            raise
    
    def _prepare_sequences(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare sequences for LSTM training.
        
        Args:
            data: Time series data
            
        Returns:
            X (sequences), y (targets)
        """
        X, y = [], []
        
        for i in range(self.sequence_length, len(data)):
            X.append(data[i-self.sequence_length:i, 0])
            y.append(data[i, 0])
        
        return np.array(X), np.array(y)
    
    def _scale_data(self, X: np.ndarray, y: np.ndarray, 
                    fit: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """
        Scale data using MinMaxScaler.
        
        Args:
            X: Features
            y: Labels
            fit: Whether to fit scalers (training) or just transform (prediction)
            
        Returns:
            Scaled X and y
        """
        from sklearn.preprocessing import MinMaxScaler
        
        if fit:
            self.scaler_X = MinMaxScaler()
            self.scaler_y = MinMaxScaler()
            
            X_scaled = self.scaler_X.fit_transform(X.reshape(-1, 1))
            y_scaled = self.scaler_y.fit_transform(y.reshape(-1, 1))
        else:
            if self.scaler_X is None or self.scaler_y is None:
                raise ValueError("Scalers not fitted. Train model first.")
            
            X_scaled = self.scaler_X.transform(X.reshape(-1, 1))
            y_scaled = self.scaler_y.transform(y.reshape(-1, 1))
        
        return X_scaled, y_scaled
    
    def train(self, X_train: np.ndarray, y_train: np.ndarray,
              X_val: Optional[np.ndarray] = None,
              y_val: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Train LSTM model.
        
        Args:
            X_train: Training features (time series)
            y_train: Training labels
            X_val: Validation features
            y_val: Validation labels
            
        Returns:
            Training history
        """
        try:
            # Build model if not built
            if self.model is None:
                self.build()
            
            # Scale data
            X_train_scaled, y_train_scaled = self._scale_data(X_train, y_train, fit=True)
            
            # Prepare sequences
            X_seq, y_seq = self._prepare_sequences(
                np.concatenate([X_train_scaled, y_train_scaled.reshape(-1, 1)], axis=1)
            )
            
            # Reshape for LSTM [samples, time steps, features]
            X_seq = X_seq.reshape(X_seq.shape[0], X_seq.shape[1], 1)
            
            # Prepare validation data if provided
            validation_data = None
            if X_val is not None and y_val is not None:
                X_val_scaled, y_val_scaled = self._scale_data(X_val, y_val, fit=False)
                X_val_seq, y_val_seq = self._prepare_sequences(
                    np.concatenate([X_val_scaled, y_val_scaled.reshape(-1, 1)], axis=1)
                )
                X_val_seq = X_val_seq.reshape(X_val_seq.shape[0], X_val_seq.shape[1], 1)
                validation_data = (X_val_seq, y_val_seq)
            
            # Train model
            from tensorflow.keras.callbacks import EarlyStopping
            
            early_stop = EarlyStopping(
                monitor='val_loss' if validation_data else 'loss',
                patience=10,
                restore_best_weights=True
            )
            
            history = self.model.fit(
                X_seq, y_seq,
                epochs=self.epochs,
                batch_size=self.batch_size,
                validation_data=validation_data,
                callbacks=[early_stop],
                verbose=0
            )
            
            self.is_trained = True
            self.training_history.append({
                'timestamp': pd.Timestamp.now().isoformat(),
                'epochs': len(history.history['loss']),
                'final_loss': float(history.history['loss'][-1]),
                'final_val_loss': float(history.history['val_loss'][-1]) if validation_data else None,
            })
            
            self.logger.info(f"LSTM training complete. Final loss: {history.history['loss'][-1]:.6f}")
            
            return {
                'loss': history.history['loss'],
                'val_loss': history.history.get('val_loss'),
                'mae': history.history.get('mae'),
                'val_mae': history.history.get('val_mae'),
            }
            
        except Exception as e:
            self.logger.error(f"Error training LSTM: {e}")
            raise
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Make price predictions.
        
        Args:
            X: Input features (time series)
            
        Returns:
            Price predictions
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")
        
        try:
            # Scale input
            X_scaled = self.scaler_X.transform(X.reshape(-1, 1))
            
            # Prepare sequences
            X_seq = []
            for i in range(self.sequence_length, len(X_scaled)):
                X_seq.append(X_scaled[i-self.sequence_length:i, 0])
            
            X_seq = np.array(X_seq)
            X_seq = X_seq.reshape(X_seq.shape[0], X_seq.shape[1], 1)
            
            # Predict
            predictions_scaled = self.model.predict(X_seq, verbose=0)
            
            # Inverse transform
            predictions = self.scaler_y.inverse_transform(predictions_scaled)
            
            return predictions.flatten()
            
        except Exception as e:
            self.logger.error(f"Error making LSTM predictions: {e}")
            raise
    
    def predict_next(self, recent_data: np.ndarray, steps: int = 1) -> np.ndarray:
        """
        Predict next N steps.
        
        Args:
            recent_data: Recent price data (at least sequence_length)
            steps: Number of steps to predict
            
        Returns:
            Array of predictions
        """
        if len(recent_data) < self.sequence_length:
            raise ValueError(f"Need at least {self.sequence_length} data points")
        
        predictions = []
        current_sequence = recent_data[-self.sequence_length:].copy()
        
        for _ in range(steps):
            # Predict next value
            pred = self.predict(current_sequence)
            predictions.append(pred[-1])
            
            # Update sequence
            current_sequence = np.append(current_sequence[1:], pred[-1])
        
        return np.array(predictions)
    
    def get_model_summary(self) -> str:
        """Get model architecture summary."""
        if self.model is None:
            return "Model not built"
        
        from io import StringIO
        import sys
        
        stream = StringIO()
        self.model.summary(print_fn=lambda x: stream.write(x + '\n'))
        return stream.getvalue()
