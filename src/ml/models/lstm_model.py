"""
TorchScript LSTM for production inference.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from src.ml.models.base import BaseModel


class LSTMNetwork(nn.Module):
    """LSTM architecture."""
    
    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        output_size: int = 1
    ):
        super().__init__()
        
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=False
        )
        
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, output_size)
        self.sigmoid = nn.Sigmoid()
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        # Take last timestep
        last_hidden = lstm_out[:, -1, :]
        dropped = self.dropout(last_hidden)
        output = self.fc(dropped)
        return self.sigmoid(output)


class LSTMModel(BaseModel):
    """
    Production LSTM with TorchScript compilation.
    """
    
    def __init__(
        self,
        name: str = "lstm",
        version: str = "1.0.0",
        input_size: int = 32,
        sequence_length: int = 50,
        hidden_size: int = 128,
        num_layers: int = 2
    ):
        super().__init__(name, version)
        
        self.input_size = input_size
        self.sequence_length = sequence_length
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        
        self._model: LSTMNetwork | torch.jit.ScriptModule | None = None
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._scaler_params: dict | None = None
    
    def _init_model(self) -> None:
        """Initialize LSTM network."""
        self._model = LSTMNetwork(
            input_size=self.input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers
        ).to(self._device)
    
    def train(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None:
        """Train LSTM model."""
        if self._model is None:
            self._init_model()
        
        # Convert to sequences
        X_seq = self._create_sequences(X)
        y_seq = y[self.sequence_length - 1:]
        
        # Convert to tensors
        X_tensor = torch.FloatTensor(X_seq).to(self._device)
        y_tensor = torch.FloatTensor(y_seq).to(self._device)
        
        # Training setup
        criterion = nn.BCELoss()
        optimizer = torch.optim.Adam(self._model.parameters(), lr=kwargs.get("lr", 0.001))
        
        # Training loop
        self._model.train()
        epochs = kwargs.get("epochs", 50)
        batch_size = kwargs.get("batch_size", 32)
        
        for epoch in range(epochs):
            total_loss = 0
            for i in range(0, len(X_tensor), batch_size):
                batch_x = X_tensor[i:i+batch_size]
                batch_y = y_tensor[i:i+batch_size]
                
                optimizer.zero_grad()
                outputs = self._model(batch_x).squeeze()
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
                
                total_loss += loss.item()
            
            if epoch % 10 == 0:
                print(f"Epoch {epoch}, Loss: {total_loss / len(X_tensor):.4f}")
        
        self._is_trained = True
        
        # Compile to TorchScript for production
        self._compile_torchscript()
    
    def _create_sequences(self, data: np.ndarray) -> np.ndarray:
        """Create sequences for LSTM."""
        sequences = []
        for i in range(len(data) - self.sequence_length + 1):
            seq = data[i:i+self.sequence_length]
            sequences.append(seq)
        return np.array(sequences)
    
    def _compile_torchscript(self) -> None:
        """Compile to TorchScript for optimized inference."""
        if self._model is None:
            return
        
        self._model.eval()
        example_input = torch.randn(1, self.sequence_length, self.input_size).to(self._device)
        
        try:
            scripted = torch.jit.trace(self._model, example_input)
            self._model = scripted
        except Exception as e:
            print(f"TorchScript compilation failed: {e}")
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """Predict class labels."""
        proba = self.predict_proba(features)
        return (proba > 0.5).astype(int)
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Predict probabilities."""
        if not self._is_trained or self._model is None:
            raise RuntimeError("Model not trained")
        
        self._model.eval()
        
        # Handle single sample
        if len(features.shape) == 1:
            features = features.reshape(1, -1)
        
        # Create sequence if needed
        if features.shape[1] != self.sequence_length:
            # Pad or truncate
            if features.shape[1] < self.sequence_length:
                pad = np.zeros((features.shape[0], self.sequence_length - features.shape[1], features.shape[2]))
                features = np.concatenate([pad, features], axis=1)
            else:
                features = features[:, -self.sequence_length:, :]
        
        with torch.no_grad():
            X = torch.FloatTensor(features).to(self._device)
            outputs = self._model(X).squeeze().cpu().numpy()
        
        return outputs if outputs.ndim > 0 else np.array([outputs])
    
    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Online learning - fine-tune on new data."""
        if not self._is_trained:
            self.train(X, y)
            return
        
        # Fine-tuning with small learning rate
        self._model.train()
        optimizer = torch.optim.Adam(self._model.parameters(), lr=0.0001)
        criterion = nn.BCELoss()
        
        X_seq = self._create_sequences(X)
        y_seq = y[self.sequence_length - 1:]
        
        X_tensor = torch.FloatTensor(X_seq).to(self._device)
        y_tensor = torch.FloatTensor(y_seq).to(self._device)
        
        # Single epoch fine-tuning
        for i in range(0, len(X_tensor), 32):
            batch_x = X_tensor[i:i+32]
            batch_y = y_tensor[i:i+32]
            
            optimizer.zero_grad()
            outputs = self._model(batch_x).squeeze()
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
    
    def save(self, path: Path) -> None:
        """Save model to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save TorchScript model
        if isinstance(self._model, torch.jit.ScriptModule):
            self._model.save(str(path.with_suffix(".pt")))
        else:
            torch.save(self._model.state_dict(), path.with_suffix(".pth"))
        
        # Save metadata
        metadata = {
            "name": self.name,
            "version": self.version,
            "input_size": self.input_size,
            "sequence_length": self.sequence_length,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "is_trained": self._is_trained,
            "feature_names": self._feature_names,
            "scaler_params": self._scaler_params
        }
        
        with open(path.with_suffix(".json"), "w") as f:
            json.dump(metadata, f)
    
    def load(self, path: Path) -> None:
        """Load model from disk."""
        # Load metadata
        with open(path.with_suffix(".json"), "r") as f:
            metadata = json.load(f)
        
        self.name = metadata["name"]
        self.version = metadata["version"]
        self.input_size = metadata["input_size"]
        self.sequence_length = metadata["sequence_length"]
        self.hidden_size = metadata["hidden_size"]
        self.num_layers = metadata["num_layers"]
        self._is_trained = metadata["is_trained"]
        self._feature_names = metadata.get("feature_names")
        self._scaler_params = metadata.get("scaler_params")
        
        # Load model weights
        model_path = path.with_suffix(".pt")
        if model_path.exists():
            self._model = torch.jit.load(str(model_path))
        else:
            self._init_model()
            self._model.load_state_dict(torch.load(path.with_suffix(".pth")))
            self._model.to(self._device)
