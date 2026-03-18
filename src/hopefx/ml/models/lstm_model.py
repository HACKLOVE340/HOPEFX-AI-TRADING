"""Production LSTM with attention for time series."""

from __future__ import annotations

import torch
import torch.nn as nn
import numpy as np
from pathlib import Path
from typing import Tuple

from hopefx.ml.pipeline import BaseModel, ModelMetadata


class AttentionLSTM(nn.Module):
    """LSTM with multi-head attention for price prediction."""

    def __init__(
        self,
        input_size: int = 50,
        hidden_size: int = 128,
        num_layers: int = 2,
        num_heads: int = 4,
        dropout: float = 0.2,
        output_size: int = 3  # long, short, neutral
    ) -> None:
        super().__init__()
        
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=True
        )
        
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size * 2,  # bidirectional
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True
        )
        
        self.fc = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, output_size)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # LSTM encoding
        lstm_out, _ = self.lstm(x)  # (batch, seq, hidden*2)
        
        # Self-attention
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        
        # Global average pooling
        pooled = attn_out.mean(dim=1)
        
        # Classification
        return self.fc(pooled)


class LSTMOnlineModel(BaseModel):
    """Online learning capable LSTM."""

    def __init__(self, model_id: str = "lstm_attention") -> None:
        super().__init__(model_id)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model: Optional[AttentionLSTM] = None
        self.optimizer: Optional[torch.optim.Optimizer] = None
        self.scheduler: Optional[torch.optim.lr_scheduler._LRScheduler] = None
        
        # Hyperparameters
        self.sequence_length = 100
        self.learning_rate = 0.001
        self.batch_size = 32

    async def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train LSTM on time series data."""
        self.model = AttentionLSTM(
            input_size=X.shape[-1],
            hidden_size=128,
            num_layers=2
        ).to(self.device)
        
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=self.learning_rate,
            weight_decay=0.01
        )
        
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, mode='min', patience=5
        )

        # Prepare sequences
        sequences, targets = self._create_sequences(X, y)
        
        # Training loop with early stopping
        best_loss = float('inf')
        patience = 10
        patience_counter = 0

        for epoch in range(100):
            self.model.train()
            total_loss = 0
            
            for i in range(0, len(sequences), self.batch_size):
                batch_x = torch.FloatTensor(sequences[i:i+self.batch_size]).to(self.device)
                batch_y = torch.LongTensor(targets[i:i+self.batch_size]).to(self.device)
                
                self.optimizer.zero_grad()
                outputs = self.model(batch_x)
                loss = nn.CrossEntropyLoss()(outputs, batch_y)
                loss.backward()
                
                # Gradient clipping
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                
                self.optimizer.step()
                total_loss += loss.item()

            avg_loss = total_loss / (len(sequences) / self.batch_size)
            self.scheduler.step(avg_loss)

            # Early stopping
            if avg_loss < best_loss:
                best_loss = avg_loss
                patience_counter = 0
                # Save best model
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

        self._is_trained = True
        self.metadata = ModelMetadata(
            model_id=self.model_id,
            version=self.version,
            created_at=datetime.utcnow().isoformat(),
            feature_hash="",
            train_samples=len(X),
            val_score=float(best_loss),
            hyperparameters={
                "hidden_size": 128,
                "num_layers": 2,
                "sequence_length": self.sequence_length,
            }
        )

    async def predict(self, X: np.ndarray) -> np.ndarray:
        """Generate predictions."""
        if not self._is_trained or self.model is None:
            raise RuntimeError("Model not trained")

        self.model.eval()
        
        with torch.no_grad():
            # Prepare sequence
            if len(X) < self.sequence_length:
                # Pad if needed
                padding = np.zeros((self.sequence_length - len(X), X.shape[-1]))
                X = np.vstack([padding, X])
            
            x_tensor = torch.FloatTensor(X[-self.sequence_length:]).unsqueeze(0).to(self.device)
            output = self.model(x_tensor)
            probs = torch.softmax(output, dim=1)
            
            return probs.cpu().numpy()[0]

    def _create_sequences(
        self,
        X: np.ndarray,
        y: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Create sequences for LSTM."""
        sequences = []
        targets = []
        
        for i in range(len(X) - self.sequence_length):
            sequences.append(X[i:i+self.sequence_length])
            targets.append(y[i+self.sequence_length])
        
        return np.array(sequences), np.array(targets)

    def save(self, path: Path) -> None:
        """Save PyTorch model."""
        if self.model is None:
            return
        
        path.mkdir(parents=True, exist_ok=True)
        torch.save({
            'model_state': self.model.state_dict(),
            'optimizer_state': self.optimizer.state_dict() if self.optimizer else None,
            'metadata': self.metadata.__dict__ if self.metadata else {},
        }, path / f"{self.model_id}.pt")

    def load(self, path: Path) -> None:
        """Load PyTorch model."""
        model_path = path / f"{self.model_id}.pt"
        if not model_path.exists():
            return
        
        checkpoint = torch.load(model_path, map_location=self.device)
        
        self.model = AttentionLSTM()
        self.model.load_state_dict(checkpoint['model_state'])
        self.model.to(self.device)
        
        if checkpoint.get('optimizer_state'):
            self.optimizer = torch.optim.AdamW(self.model.parameters())
            self.optimizer.load_state_dict(checkpoint['optimizer_state'])
        
        self._is_trained = True
