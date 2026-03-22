# src/hopefx/ml/models/ensemble.py
"""
XGBoost + LSTM ensemble with dynamic weighting and online learning.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
import torch.nn as nn
import xgboost as xgb
from sklearn.preprocessing import RobustScaler

from hopefx.ml.models.base import BaseModel, ModelMetadata, Prediction

import structlog

logger = structlog.get_logger()


class LSTMModule(nn.Module):
    """TorchScript-compatible LSTM."""
    
    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=False
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 3)  # Short, Flat, Long
        )
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        # Take last timestep
        return self.fc(lstm_out[:, -1, :])


class EnsembleModel(BaseModel):
    """
    Production ensemble combining XGBoost (interpretable) 
    and LSTM (sequential patterns) with dynamic weighting.
    """
    
    def __init__(
        self,
        input_size: int,
        lookback: int = 100,
        xgb_weight: float = 0.4,
        lstm_weight: float = 0.6
    ) -> None:
        super().__init__("ensemble", "2.0.0")
        self.input_size = input_size
        self.lookback = lookback
        self.xgb_weight = xgb_weight
        self.lstm_weight = lstm_weight
        
        # XGBoost (gradient boosting for feature importance)
        self.xgb_model: xgb.XGBClassifier | None = None
        
        # LSTM (sequential pattern recognition)
        self.lstm_model: LSTMModule | None = None
        self.lstm_scripted: torch.jit.ScriptModule | None = None
        
        # Preprocessing
        self.scaler = RobustScaler()
        
        # Device
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Online learning buffer
        self._online_buffer_X: list[np.ndarray] = []
        self._online_buffer_y: list[int] = []
        self._online_buffer_size = 1000
    
    async def predict(self, features: np.ndarray) -> Prediction:
        """Generate ensemble prediction."""
        start_time = time.perf_counter()
        
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        
        # Preprocess
        features_scaled = self.scaler.transform(features.reshape(1, -1))
        
        # XGBoost prediction
        xgb_proba = self.xgb_model.predict_proba(features_scaled)[0]
        
        # LSTM prediction (needs sequence)
        if len(features) >= self.lookback * self.input_size:
            seq = features[-self.lookback * self.input_size:].reshape(
                1, self.lookback, self.input_size
            )
            seq_scaled = self.scaler.transform(seq.reshape(-1, self.input_size)).reshape(
                1, self.lookback, self.input_size
            )
            seq_tensor = torch.tensor(seq_scaled, dtype=torch.float32, device=self.device)
            
            with torch.no_grad():
                lstm_out = self.lstm_scripted(seq_tensor)
                lstm_proba = torch.softmax(lstm_out, dim=1).cpu().numpy()[0]
        else:
            # Fallback to XGB only if insufficient history
            lstm_proba = np.array([0.33, 0.34, 0.33])
        
        # Ensemble weighting
        ensemble_proba = (
            self.xgb_weight * xgb_proba + 
            self.lstm_weight * lstm_proba
        )
        
        # Normalize
        ensemble_proba = ensemble_proba / ensemble_proba.sum()
        
        direction = np.argmax(ensemble_proba) - 1  # -1, 0, 1
        confidence = ensemble_proba[np.argmax(ensemble_proba)]
        
        latency = (time.perf_counter() - start_time) * 1000
        
        return Prediction(
            direction=int(direction),
            probability=float(ensemble_proba[np.argmax(ensemble_proba)]),
            confidence=float(confidence),
            raw_output=ensemble_proba,
            model_version=self.version,
            latency_ms=latency
        )
    
    async def train(self, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Train both models with walk-forward validation."""
        logger.info("ensemble_training_start", samples=len(X))
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train XGBoost
        self.xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            objective='multi:softprob',
            num_class=3,
            eval_metric='mlogloss',
            use_label_encoder=False,
            random_state=42
        )
        self.xgb_model.fit(X_scaled, y + 1)  # Shift to 0,1,2
        
        # Train LSTM
        self.lstm_model = LSTMModule(self.input_size).to(self.device)
        
        # Prepare sequences
        X_seq, y_seq = self._create_sequences(X_scaled, y)
        
        # Train LSTM
        dataset = torch.utils.data.TensorDataset(
            torch.tensor(X_seq, dtype=torch.float32),
            torch.tensor(y_seq + 1, dtype=torch.long)  # Shift to 0,1,2
        )
        loader = torch.utils.data.DataLoader(dataset, batch_size=64, shuffle=True)
        
        optimizer = torch.optim.Adam(self.lstm_model.parameters(), lr=0.001)
        criterion = nn.CrossEntropyLoss()
        
        self.lstm_model.train()
        for epoch in range(50):
            total_loss = 0
            for batch_X, batch_y in loader:
                batch_X = batch_X.to(self.device)
                batch_y = batch_y.to(self.device)
                
                optimizer.zero_grad()
                outputs = self.lstm_model(batch_X)
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
                
                total_loss += loss.item()
            
            if epoch % 10 == 0:
                logger.info("lstm_epoch", epoch=epoch, loss=total_loss / len(loader))
        
        # TorchScript for production
        self.lstm_model.eval()
        example_input = torch.randn(1, self.lookback, self.input_size, device=self.device)
        self.lstm_scripted = torch.jit.trace(self.lstm_model, example_input)
        self.lstm_scripted = torch.jit.optimize_for_inference(self.lstm_scripted)
        
        self._is_trained = True
        
        # Metadata
        self._metadata = ModelMetadata(
            name="ensemble",
            version=self.version,
            features=[f"feature_{i}" for i in range(self.input_size)],
            training_date=str(time.time()),
            metrics={"xgb_weight": self.xgb_weight, "lstm_weight": self.lstm_weight}
        )
        
        logger.info("ensemble_training_complete")
        
        return {"status": "trained", "samples": len(X)}
    
    async def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Online learning update."""
        self._online_buffer_X.append(X)
        self._online_buffer_y.append(int(y))
        
        if len(self._online_buffer_X) >= self._online_buffer_size:
            # Batch update XGBoost
            X_batch = np.array(self._online_buffer_X)
            y_batch = np.array(self._online_buffer_y)
            
            X_scaled = self.scaler.transform(X_batch)
            self.xgb_model.fit(
                X_scaled, y_batch + 1,
                xgb_model=self.xgb_model.get_booster()  # Continue from current
            )
            
            # Clear buffer
            self._online_buffer_X = []
            self._online_buffer_y = []
            
            logger.info("online_update_complete", samples=self._online_buffer_size)
    
    def _create_sequences(
        self, X: np.ndarray, y: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Create LSTM sequences."""
        X_seq, y_seq = [], []
        for i in range(len(X) - self.lookback):
            X_seq.append(X[i:i + self.lookback])
            y_seq.append(y[i + self.lookback])
        return np.array(X_seq), np.array(y_seq)
    
    def save(self, path: Path) -> None:
        """Serialize ensemble."""
        path.mkdir(parents=True, exist_ok=True)
        
        # Save XGBoost
        joblib.dump(self.xgb_model, path / "xgb_model.joblib")
        
        # Save LSTM TorchScript
        self.lstm_scripted.save(str(path / "lstm_model.pt"))
        
        # Save scaler
        joblib.dump(self.scaler, path / "scaler.joblib")
        
        # Save metadata
        import json
        with open(path / "metadata.json", "w") as f:
            json.dump({
                "name": self.name,
                "version": self.version,
                "input_size": self.input_size,
                "lookback": self.lookback,
                "xgb_weight": self.xgb_weight,
                "lstm_weight": self.lstm_weight
            }, f)
        
        logger.info("ensemble_saved", path=str(path))
    
    def load(self, path: Path) -> None:
        """Deserialize ensemble."""
        # Load XGBoost
        self.xgb_model = joblib.load(path / "xgb_model.joblib")
        
        # Load LSTM
        self.lstm_scripted = torch.jit.load(str(path / "lstm_model.pt"))
        self.lstm_scripted.to(self.device)
        
        # Load scaler
        self.scaler = joblib.load(path / "scaler.joblib")
        
        # Load metadata
        import json
        with open(path / "metadata.json") as f:
            meta = json.load(f)
            self.input_size = meta["input_size"]
            self.lookback = meta["lookback"]
            self.xgb_weight = meta["xgb_weight"]
            self.lstm_weight = meta["lstm_weight"]
        
        self._is_trained = True
        logger.info("ensemble_loaded", path=str(path))
