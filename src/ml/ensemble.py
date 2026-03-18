"""
XGBoost + LSTM ensemble with online learning capabilities.
"""
import os
import json
import joblib
import numpy as np
import asyncio
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime
from pathlib import Path
import structlog
import xgboost as xgb
from sklearn.preprocessing import RobustScaler

try:
    import tensorflow as tf
    from tensorflow import keras
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

logger = structlog.get_logger()


class EnsemblePredictor:
    """
    Production ML ensemble for XAUUSD prediction.
    Combines XGBoost (feature importance) with LSTM (temporal patterns).
    """
    
    def __init__(self, model_path: str = "./models"):
        self.model_path = Path(model_path)
        self.model_path.mkdir(parents=True, exist_ok=True)
        
        self.xgb_model: Optional[xgb.XGBClassifier] = None
        self.lstm_model: Optional[Any] = None
        self.scaler: Optional[RobustScaler] = None
        
        self._feature_cols: List[str] = []
        self._sequence_length: int = 60
        self._threshold: float = 0.6
        self._model_version: str = "1.0.0"
        
        # Online learning buffer
        self._retrain_buffer: List[Tuple[np.ndarray, int]] = []
        self._buffer_size: int = 1000
        
    async def load_models(self) -> bool:
        """Load pre-trained models from disk."""
        try:
            xgb_path = self.model_path / "xgb_model.json"
            scaler_path = self.model_path / "scaler.joblib"
            meta_path = self.model_path / "model_meta.json"
            
            if xgb_path.exists():
                self.xgb_model = xgb.XGBClassifier()
                self.xgb_model.load_model(str(xgb_path))
                logger.info("xgb_model_loaded")
            
            if scaler_path.exists():
                self.scaler = joblib.load(scaler_path)
                logger.info("scaler_loaded")
            
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                    self._feature_cols = meta.get("features", [])
                    self._model_version = meta.get("version", "1.0.0")
            
            # Load LSTM if available
            lstm_path = self.model_path / "lstm_model.keras"
            if TF_AVAILABLE and lstm_path.exists():
                self.lstm_model = keras.models.load_model(lstm_path)
                logger.info("lstm_model_loaded")
            
            return self.xgb_model is not None
            
        except Exception as e:
            logger.error("model_load_failed", error=str(e))
            return False
    
    async def predict(self, features: np.ndarray, 
                      sequence: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Generate ensemble prediction.
        
        Args:
            features: 1D array of engineered features
            sequence: 2D array [sequence_length, features] for LSTM
            
        Returns:
            Dict with prediction, confidence, and model contributions
        """
        if self.scaler is not None:
            features_scaled = self.scaler.transform(features.reshape(1, -1))
        else:
            features_scaled = features.reshape(1, -1)
        
        predictions = {}
        confidences = {}
        
        # XGBoost prediction
        if self.xgb_model is not None:
            xgb_proba = self.xgb_model.predict_proba(features_scaled)[0]
            xgb_pred = np.argmax(xgb_proba)
            predictions["xgboost"] = int(xgb_pred)
            confidences["xgboost"] = float(xgb_proba[xgb_pred])
        
        # LSTM prediction
        if self.lstm_model is not None and sequence is not None:
            if sequence.shape[0] < self._sequence_length:
                # Pad sequence
                pad_length = self._sequence_length - sequence.shape[0]
                sequence = np.pad(sequence, ((pad_length, 0), (0, 0)), mode='edge')
            
            sequence_batch = sequence.reshape(1, self._sequence_length, -1)
            lstm_proba = self.lstm_model.predict(sequence_batch, verbose=0)[0]
            lstm_pred = np.argmax(lstm_proba)
            predictions["lstm"] = int(lstm_pred)
            confidences["lstm"] = float(lstm_proba[lstm_pred])
        
        # Ensemble decision (weighted average)
        if len(predictions) == 2:
            # Weight XGBoost 0.4, LSTM 0.6 (LSTM better for time series)
            weights = {"xgboost": 0.4, "lstm": 0.6}
            weighted_proba = (
                confidences["xgboost"] * weights["xgboost"] +
                confidences["lstm"] * weights["lstm"]
            )
            
            # Agreement check
            if predictions["xgboost"] == predictions["lstm"]:
                final_pred = predictions["xgboost"]
                final_conf = weighted_proba
            else:
                # Disagreement - lower confidence
                final_pred = predictions["lstm"]  # Trust LSTM more
                final_conf = weighted_proba * 0.8
        elif "xgboost" in predictions:
            final_pred = predictions["xgboost"]
            final_conf = confidences["xgboost"]
        elif "lstm" in predictions:
            final_pred = predictions["lstm"]
            final_conf = confidences["lstm"]
        else:
            return {
                "signal": 0,  # HOLD
                "confidence": 0.0,
                "direction": "NEUTRAL",
                "models_used": []
            }
        
        # Determine signal
        if final_conf < self._threshold:
            signal = 0  # HOLD
            direction = "NEUTRAL"
        elif final_pred == 1:
            signal = 1  # BUY
            direction = "LONG"
        else:
            signal = -1  # SELL
            direction = "SHORT"
        
        return {
            "signal": signal,
            "confidence": final_conf,
            "direction": direction,
            "models_used": list(predictions.keys()),
            "model_predictions": predictions,
            "model_confidences": confidences,
            "threshold": self._threshold,
            "timestamp": datetime.utcnow().isoformat(),
            "version": self._model_version
        }
    
    async def partial_fit(self, features: np.ndarray, 
                          label: int) -> None:
        """
        Online learning update.
        Accumulates samples and triggers periodic retraining.
        """
        self._retrain_buffer.append((features, label))
        
        if len(self._retrain_buffer) >= self._buffer_size:
            await self._retrain()
    
    async def _retrain(self) -> None:
        """Incremental model update."""
        if not self._retrain_buffer or self.xgb_model is None:
            return
        
        logger.info("starting_incremental_retrain", 
                   samples=len(self._retrain_buffer))
        
        try:
            X = np.array([x for x, _ in self._retrain_buffer])
            y = np.array([y for _, y in self._retrain_buffer])
            
            if self.scaler is not None:
                X = self.scaler.transform(X)
            
            # XGBoost warm start
            self.xgb_model.fit(X, y, xgb_model=self.xgb_model)
            
            # Clear buffer
            self._retrain_buffer.clear()
            
            # Save updated model
            await self._save_models()
            
            logger.info("incremental_retrain_complete")
            
        except Exception as e:
            logger.error("retrain_failed", error=str(e))
    
    async def _save_models(self) -> None:
        """Persist models to disk."""
        if self.xgb_model is not None:
            self.xgb_model.save_model(str(self.model_path / "xgb_model.json"))
        
        if self.scaler is not None:
            joblib.dump(self.scaler, self.model_path / "scaler.joblib")
        
        meta = {
            "version": self._model_version,
            "features": self._feature_cols,
            "last_updated": datetime.utcnow().isoformat(),
            "sequence_length": self._sequence_length
        }
        with open(self.model_path / "model_meta.json", "w") as f:
            json.dump(meta, f, indent=2)
        
        logger.info("models_saved", version=self._model_version)
    
    async def train_initial(self, X: np.ndarray, y: np.ndarray,
                           feature_names: List[str]) -> None:
        """Initial training of ensemble."""
        logger.info("starting_initial_training", samples=len(X))
        
        # Fit scaler
        self.scaler = RobustScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Train XGBoost
        self.xgb_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            objective='binary:logistic',
            eval_metric='logloss'
        )
        self.xgb_model.fit(X_scaled, y)
        
        self._feature_cols = feature_names
        
        # Train LSTM if TF available
        if TF_AVAILABLE:
            await self._train_lstm(X, y)
        
        await self._save_models()
        logger.info("initial_training_complete")
    
    async def _train_lstm(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train LSTM on sequence data."""
        # Reshape for LSTM [samples, timesteps, features]
        # For simplicity, using windowed approach
        seq_length = self._sequence_length
        
        if len(X) < seq_length * 2:
            logger.warning("insufficient_data_for_lstm")
            return
        
        # Create sequences
        X_seq, y_seq = [], []
        for i in range(seq_length, len(X)):
            X_seq.append(X[i-seq_length:i])
            y_seq.append(y[i])
        
        X_seq = np.array(X_seq)
        y_seq = np.array(y_seq)
        
        # Build model
        model = keras.Sequential([
            keras.layers.LSTM(50, return_sequences=True, 
                             input_shape=(seq_length, X.shape[1])),
            keras.layers.Dropout(0.2),
            keras.layers.LSTM(50, return_sequences=False),
            keras.layers.Dropout(0.2),
            keras.layers.Dense(25),
            keras.layers.Dense(3, activation='softmax')  # HOLD, BUY, SELL
        ])
        
        model.compile(optimizer='adam', 
                     loss='sparse_categorical_crossentropy',
                     metrics=['accuracy'])
        
        # Train
        model.fit(X_seq, y_seq, epochs=10, batch_size=32, 
                 validation_split=0.2, verbose=0)
        
        self.lstm_model = model
        self.lstm_model.save(self.model_path / "lstm_model.keras")
        
        logger.info("lstm_training_complete")
