"""
research/pipeline/models_deep.py
==================================
Deep learning models for time-series prediction.

Models
------
1. LSTMPredictor      — stacked bidirectional LSTM with dropout + attention
2. TransformerPredictor — multi-head self-attention encoder (no decoder needed
                          for classification/regression on fixed windows)
3. TemporalConvNet    — dilated causal convolutions (TCN) — fast, parallelisable
4. HybridModel        — TCN encoder → LSTM refinement → dense head

All models share a common interface:
    model.fit(X_train, y_train, X_val, y_val)
    model.predict(X)          → np.ndarray of probabilities / values
    model.save(path)
    model.load(path)

Input shape: (batch, seq_len, n_features)
Output:      (batch, 1)  — probability for binary classification
                           or scalar for regression
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── PyTorch (preferred; lighter than TF for this use-case) ───────────────────
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not installed — deep models unavailable")

# ── TensorFlow / Keras fallback ───────────────────────────────────────────────
try:
    import tensorflow as tf
    from tensorflow.keras import layers, Model
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Sequence dataset builder
# ─────────────────────────────────────────────────────────────────────────────

def make_sequences(
    X: np.ndarray,
    y: np.ndarray,
    seq_len: int = 60,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert flat feature matrix to overlapping sequences.

    Parameters
    ----------
    X       : (n_samples, n_features)
    y       : (n_samples,)
    seq_len : Look-back window length

    Returns
    -------
    X_seq : (n_samples - seq_len, seq_len, n_features)
    y_seq : (n_samples - seq_len,)
    """
    n = len(X) - seq_len
    X_seq = np.stack([X[i: i + seq_len] for i in range(n)])
    y_seq = y[seq_len:]
    return X_seq.astype(np.float32), y_seq.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch model definitions
# ─────────────────────────────────────────────────────────────────────────────

if TORCH_AVAILABLE:

    class _AttentionPool(nn.Module):
        """Soft attention over sequence dimension → context vector."""

        def __init__(self, hidden: int):
            super().__init__()
            self.attn = nn.Linear(hidden, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq, hidden)
            weights = torch.softmax(self.attn(x), dim=1)  # (batch, seq, 1)
            return (weights * x).sum(dim=1)               # (batch, hidden)

    class _LSTMNet(nn.Module):
        def __init__(
            self,
            n_features: int,
            hidden: int = 128,
            n_layers: int = 3,
            dropout: float = 0.3,
            bidirectional: bool = True,
        ):
            super().__init__()
            self.lstm = nn.LSTM(
                n_features,
                hidden,
                num_layers=n_layers,
                dropout=dropout if n_layers > 1 else 0.0,
                bidirectional=bidirectional,
                batch_first=True,
            )
            lstm_out = hidden * (2 if bidirectional else 1)
            self.attn = _AttentionPool(lstm_out)
            self.head = nn.Sequential(
                nn.Linear(lstm_out, 64),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(64, 1),
                nn.Sigmoid(),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out, _ = self.lstm(x)
            ctx = self.attn(out)
            return self.head(ctx).squeeze(-1)

    class _TransformerNet(nn.Module):
        def __init__(
            self,
            n_features: int,
            d_model: int = 128,
            n_heads: int = 4,
            n_layers: int = 3,
            dropout: float = 0.1,
            seq_len: int = 60,
        ):
            super().__init__()
            self.input_proj = nn.Linear(n_features, d_model)
            # Learnable positional encoding
            self.pos_emb = nn.Embedding(seq_len, d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=n_heads,
                dim_feedforward=d_model * 4,
                dropout=dropout,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
            self.head = nn.Sequential(
                nn.Linear(d_model, 64),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(64, 1),
                nn.Sigmoid(),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq, features)
            positions = torch.arange(x.size(1), device=x.device).unsqueeze(0)
            x = self.input_proj(x) + self.pos_emb(positions)
            enc = self.encoder(x)
            # Use last token as summary
            return self.head(enc[:, -1, :]).squeeze(-1)

    class _TCNBlock(nn.Module):
        """Single dilated causal convolution residual block."""

        def __init__(self, channels: int, kernel: int, dilation: int, dropout: float):
            super().__init__()
            pad = (kernel - 1) * dilation
            self.conv1 = nn.Conv1d(channels, channels, kernel, padding=pad, dilation=dilation)
            self.conv2 = nn.Conv1d(channels, channels, kernel, padding=pad, dilation=dilation)
            self.drop = nn.Dropout(dropout)
            self.relu = nn.ReLU()
            self._pad = pad

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # Causal: trim right padding
            out = self.relu(self.conv1(x)[..., : -self._pad] if self._pad else self.conv1(x))
            out = self.drop(out)
            out = self.relu(self.conv2(out)[..., : -self._pad] if self._pad else self.conv2(out))
            out = self.drop(out)
            return self.relu(out + x)

    class _TCNNet(nn.Module):
        def __init__(
            self,
            n_features: int,
            channels: int = 64,
            n_levels: int = 6,
            kernel: int = 3,
            dropout: float = 0.2,
        ):
            super().__init__()
            self.input_proj = nn.Conv1d(n_features, channels, 1)
            self.blocks = nn.Sequential(
                *[_TCNBlock(channels, kernel, dilation=2 ** i, dropout=dropout) for i in range(n_levels)]
            )
            self.head = nn.Sequential(
                nn.AdaptiveAvgPool1d(1),
                nn.Flatten(),
                nn.Linear(channels, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
                nn.Sigmoid(),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq, features) → (batch, features, seq)
            x = x.permute(0, 2, 1)
            x = self.input_proj(x)
            x = self.blocks(x)
            return self.head(x).squeeze(-1)


# ─────────────────────────────────────────────────────────────────────────────
# Unified trainer wrapper
# ─────────────────────────────────────────────────────────────────────────────

class DeepPredictor:
    """
    Unified training / inference wrapper for all PyTorch deep models.

    Parameters
    ----------
    architecture : 'lstm' | 'transformer' | 'tcn'
    n_features   : Number of input features
    seq_len      : Sequence length (look-back window)
    task         : 'binary' | 'regression'
    device       : 'cuda' | 'cpu' | 'auto'
    """

    ARCHITECTURES = {"lstm": "_LSTMNet", "transformer": "_TransformerNet", "tcn": "_TCNNet"}

    def __init__(
        self,
        architecture: str = "lstm",
        n_features: int = 50,
        seq_len: int = 60,
        task: str = "binary",
        device: str = "auto",
        lr: float = 1e-3,
        batch_size: int = 64,
        max_epochs: int = 100,
        patience: int = 10,
        **model_kwargs,
    ):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required for DeepPredictor")

        self.architecture = architecture
        self.n_features = n_features
        self.seq_len = seq_len
        self.task = task
        self.lr = lr
        self.batch_size = batch_size
        self.max_epochs = max_epochs
        self.patience = patience

        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.model = self._build_model(n_features, seq_len, **model_kwargs).to(self.device)
        self.optimizer = optim.AdamW(self.model.parameters(), lr=lr, weight_decay=1e-4)
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(self.optimizer, T_max=max_epochs)
        self.criterion = nn.BCELoss() if task == "binary" else nn.MSELoss()
        self._history: dict = {"train_loss": [], "val_loss": []}

    def _build_model(self, n_features: int, seq_len: int, **kwargs) -> nn.Module:
        arch = self.architecture.lower()
        if arch == "lstm":
            return _LSTMNet(n_features, **kwargs)
        elif arch == "transformer":
            return _TransformerNet(n_features, seq_len=seq_len, **kwargs)
        elif arch == "tcn":
            return _TCNNet(n_features, **kwargs)
        else:
            raise ValueError(f"Unknown architecture: {arch}")

    def _to_loader(self, X: np.ndarray, y: np.ndarray, shuffle: bool) -> DataLoader:
        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32)
        return DataLoader(TensorDataset(X_t, y_t), batch_size=self.batch_size, shuffle=shuffle)

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
    ) -> dict:
        """
        Train the model.

        X_train shape: (n_samples, seq_len, n_features)
        y_train shape: (n_samples,)
        """
        train_loader = self._to_loader(X_train, y_train, shuffle=True)
        val_loader = self._to_loader(X_val, y_val, shuffle=False) if X_val is not None else None

        best_val_loss = float("inf")
        patience_counter = 0
        best_state = None

        for epoch in range(self.max_epochs):
            # ── Train ─────────────────────────────────────────────────────────
            self.model.train()
            train_losses = []
            for X_b, y_b in train_loader:
                X_b, y_b = X_b.to(self.device), y_b.to(self.device)
                self.optimizer.zero_grad()
                pred = self.model(X_b)
                loss = self.criterion(pred, y_b)
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.optimizer.step()
                train_losses.append(loss.item())

            self.scheduler.step()
            avg_train = np.mean(train_losses)
            self._history["train_loss"].append(avg_train)

            # ── Validate ──────────────────────────────────────────────────────
            if val_loader:
                self.model.eval()
                val_losses = []
                with torch.no_grad():
                    for X_b, y_b in val_loader:
                        X_b, y_b = X_b.to(self.device), y_b.to(self.device)
                        pred = self.model(X_b)
                        val_losses.append(self.criterion(pred, y_b).item())
                avg_val = np.mean(val_losses)
                self._history["val_loss"].append(avg_val)

                if avg_val < best_val_loss:
                    best_val_loss = avg_val
                    best_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1

                if epoch % 10 == 0:
                    logger.info(
                        "Epoch %3d  train=%.4f  val=%.4f  patience=%d",
                        epoch, avg_train, avg_val, patience_counter,
                    )

                if patience_counter >= self.patience:
                    logger.info("Early stopping at epoch %d", epoch)
                    break
            else:
                if epoch % 10 == 0:
                    logger.info("Epoch %3d  train=%.4f", epoch, avg_train)

        if best_state:
            self.model.load_state_dict(best_state)

        return self._history

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return probability array (binary) or value array (regression)."""
        self.model.eval()
        X_t = torch.tensor(X, dtype=torch.float32).to(self.device)
        with torch.no_grad():
            preds = []
            for i in range(0, len(X_t), self.batch_size):
                batch = X_t[i: i + self.batch_size]
                preds.append(self.model(batch).cpu().numpy())
        return np.concatenate(preds)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "architecture": self.architecture,
                "n_features": self.n_features,
                "seq_len": self.seq_len,
                "task": self.task,
            },
            path,
        )
        logger.info("Model saved → %s", path)

    @classmethod
    def load(cls, path: str | Path, device: str = "auto") -> "DeepPredictor":
        checkpoint = torch.load(path, map_location="cpu")
        predictor = cls(
            architecture=checkpoint["architecture"],
            n_features=checkpoint["n_features"],
            seq_len=checkpoint["seq_len"],
            task=checkpoint["task"],
            device=device,
        )
        predictor.model.load_state_dict(checkpoint["state_dict"])
        logger.info("Model loaded ← %s", path)
        return predictor
