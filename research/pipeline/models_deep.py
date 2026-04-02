# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
4. HybridModel        — TCN encoder → bidirectional LSTM refinement → dense head
                        Combines TCN's parallel feature extraction with LSTM's
                        temporal memory for best-of-both-worlds performance.

All models share a common interface:
    model.fit(X_train, y_train, X_val, y_val)
    model.predict(X)          → np.ndarray of probabilities / values
    model.save(path)
    model.load(path)

Input shape: (batch, seq_len, n_features)
Output:      (batch, 1)  — probability for binary classification
                           or scalar for regression

Training improvements
---------------------
- Label smoothing (binary cross-entropy with smoothed targets)
- Class-imbalance weighting (pos_weight for BCEWithLogitsLoss)
- Gradient clipping (max_norm=1.0)
- ReduceLROnPlateau scheduler (patience=5, factor=0.5)
- Cosine annealing with warm restarts (optional)
- Mixed precision training when CUDA available (torch.amp)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ── PyTorch (preferred; lighter than TF for this use-case) ───────────────────
try:
    import torch
    from torch import nn
    from torch import optim
    from torch.utils.data import DataLoader, TensorDataset

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not installed — deep models unavailable")

# ── TensorFlow / Keras fallback ───────────────────────────────────────────────
try:
    import tensorflow as tf  # pylint: disable=unused-import

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
) -> tuple[np.ndarray, np.ndarray]:
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
    X_seq = np.stack([X[i : i + seq_len] for i in range(n)])
    y_seq = y[seq_len:]
    return X_seq.astype(np.float32), y_seq.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch model definitions
# ─────────────────────────────────────────────────────────────────────────────

if TORCH_AVAILABLE:

    class _AttentionPool(nn.Module):
        """
        Multi-head soft attention over sequence dimension → context vector.

        Uses a learned query vector to compute attention weights over all
        time steps, then returns the weighted sum as the context vector.
        This is more expressive than using only the last hidden state.
        """

        def __init__(self, hidden: int, n_heads: int = 1):
            super().__init__()
            self.n_heads = n_heads
            self.attn = nn.Linear(hidden, n_heads)
            self.out_proj = nn.Linear(hidden * n_heads, hidden) if n_heads > 1 else nn.Identity()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq, hidden)
            scores = self.attn(x)  # (batch, seq, n_heads)
            weights = torch.softmax(scores, dim=1)  # (batch, seq, n_heads)
            # Weighted sum for each head
            heads = [(weights[:, :, h : h + 1] * x).sum(dim=1) for h in range(self.n_heads)]
            ctx = torch.cat(heads, dim=-1)  # (batch, hidden * n_heads)
            return self.out_proj(ctx)  # (batch, hidden)

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
                *[_TCNBlock(channels, kernel, dilation=2**i, dropout=dropout) for i in range(n_levels)]
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

    class _HybridNet(nn.Module):
        """
        TCN encoder → bidirectional LSTM refinement → attention pool → dense head.

        Architecture rationale
        ----------------------
        TCN captures multi-scale local patterns in parallel (fast, no vanishing
        gradient).  The LSTM then models long-range temporal dependencies in the
        TCN's compressed representation.  Attention pool selects the most
        informative time steps.

        This hybrid typically outperforms either model alone on financial
        time-series because:
        - TCN handles the high-frequency noise filtering
        - LSTM captures regime-level memory (trend persistence)
        - Attention focuses on the most predictive bars in the window
        """

        def __init__(
            self,
            n_features: int,
            tcn_channels: int = 64,
            tcn_levels: int = 4,
            lstm_hidden: int = 64,
            lstm_layers: int = 2,
            dropout: float = 0.2,
            attn_heads: int = 2,
        ):
            super().__init__()
            # TCN encoder
            self.input_proj = nn.Conv1d(n_features, tcn_channels, 1)
            self.tcn_blocks = nn.Sequential(
                *[_TCNBlock(tcn_channels, kernel=3, dilation=2**i, dropout=dropout) for i in range(tcn_levels)]
            )
            # LSTM refinement (operates on TCN output)
            self.lstm = nn.LSTM(
                tcn_channels,
                lstm_hidden,
                num_layers=lstm_layers,
                dropout=dropout if lstm_layers > 1 else 0.0,
                bidirectional=True,
                batch_first=True,
            )
            lstm_out = lstm_hidden * 2  # bidirectional
            self.attn = _AttentionPool(lstm_out, n_heads=attn_heads)
            self.head = nn.Sequential(
                nn.LayerNorm(lstm_out),
                nn.Linear(lstm_out, 64),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(64, 1),
                nn.Sigmoid(),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq, features)
            # TCN path: needs (batch, features, seq)
            tcn_in = x.permute(0, 2, 1)
            tcn_in = self.input_proj(tcn_in)
            tcn_out = self.tcn_blocks(tcn_in)
            # Back to (batch, seq, channels) for LSTM
            lstm_in = tcn_out.permute(0, 2, 1)
            lstm_out, _ = self.lstm(lstm_in)
            ctx = self.attn(lstm_out)
            return self.head(ctx).squeeze(-1)


# ─────────────────────────────────────────────────────────────────────────────
# Label-smoothed BCE loss
# ─────────────────────────────────────────────────────────────────────────────

if TORCH_AVAILABLE:

    class _LabelSmoothBCE(nn.Module):
        """
        Binary cross-entropy with label smoothing.

        Smoothing prevents the model from becoming over-confident on noisy
        financial labels.  A smoothing of 0.1 replaces labels {0,1} with
        {0.05, 0.95}.
        """

        def __init__(self, smoothing: float = 0.1, pos_weight: float | None = None):
            super().__init__()
            self.smoothing = smoothing
            self.pos_weight = pos_weight

        def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
            # Smooth targets
            target_smooth = target * (1 - self.smoothing) + 0.5 * self.smoothing
            eps = 1e-7
            pred = pred.clamp(eps, 1 - eps)
            loss = -(target_smooth * torch.log(pred) + (1 - target_smooth) * torch.log(1 - pred))
            if self.pos_weight is not None:
                weight = torch.where(
                    target > 0.5,
                    torch.tensor(self.pos_weight, device=pred.device),
                    torch.ones_like(pred),
                )
                loss = loss * weight
            return loss.mean()


# ─────────────────────────────────────────────────────────────────────────────
# Unified trainer wrapper
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DeepPredictorConfig:
    """Configuration for :class:`DeepPredictor`."""

    architecture: str = "lstm"
    n_features: int = 50
    seq_len: int = 60
    task: str = "binary"
    device: str = "auto"
    lr: float = 1e-3
    batch_size: int = 64
    max_epochs: int = 100
    patience: int = 10
    label_smoothing: float = 0.05
    pos_weight: float | None = None
    grad_clip: float = 1.0
    use_amp: bool = True


class DeepPredictor:
    """
    Unified training / inference wrapper for all PyTorch deep models.

    Parameters
    ----------
    architecture  : 'lstm' | 'transformer' | 'tcn' | 'hybrid'
    n_features    : Number of input features
    seq_len       : Sequence length (look-back window)
    task          : 'binary' | 'regression'
    device        : 'cuda' | 'cpu' | 'auto'
    lr            : Initial learning rate
    batch_size    : Mini-batch size
    max_epochs    : Maximum training epochs
    patience      : Early stopping patience (val loss)
    label_smoothing : Label smoothing for binary classification (0 = off)
    pos_weight    : Class imbalance weight for positive class (None = balanced)
    grad_clip     : Gradient clipping max norm (default 1.0)
    use_amp       : Mixed precision training (auto-disabled on CPU)
    """

    ARCHITECTURES = {
        "lstm": "_LSTMNet",
        "transformer": "_TransformerNet",
        "tcn": "_TCNNet",
        "hybrid": "_HybridNet",
    }

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
        label_smoothing: float = 0.05,
        pos_weight: float | None = None,
        grad_clip: float = 1.0,
        use_amp: bool = True,
        **model_kwargs,
    ):
        # Validate architecture before any torch dependency
        if architecture not in self.ARCHITECTURES:
            raise ValueError(f"Unknown architecture '{architecture}'. Valid options: {list(self.ARCHITECTURES.keys())}")

        # Torch is required — raise immediately so callers get a clear error
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required for DeepPredictor")

        # Store all hyperparameters
        self.architecture = architecture
        self.n_features = n_features
        self.seq_len = seq_len
        self.task = task
        self.lr = lr
        self.batch_size = batch_size
        self.max_epochs = max_epochs
        self.patience = patience
        self.label_smoothing = label_smoothing
        self.pos_weight = pos_weight
        self.grad_clip = grad_clip
        self._device_str = device
        self._use_amp_requested = use_amp
        self._model_kwargs = model_kwargs
        self._history: dict = {"train_loss": [], "val_loss": [], "lr": []}

        # Defer heavy torch initialisation to _init_torch() called by fit/predict
        self.model = None
        self.optimizer = None
        self.scheduler = None
        self.criterion = None
        self.device = None
        self.use_amp = False
        self._scaler = None

    def _init_torch(self) -> None:
        """Initialise PyTorch model, optimiser, and loss. Called lazily."""
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required for DeepPredictor")
        if self.model is not None:
            return  # already initialised

        if self._device_str == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(self._device_str)

        self.use_amp = self._use_amp_requested and self.device.type == "cuda"
        self._scaler = torch.cuda.amp.GradScaler() if self.use_amp else None

        self.model = self._build_model(self.n_features, self.seq_len, **self._model_kwargs).to(self.device)
        self.optimizer = optim.AdamW(self.model.parameters(), lr=self.lr, weight_decay=1e-4)
        self.scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer,
            mode="min",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
        )
        if self.task == "binary":
            self.criterion = _LabelSmoothBCE(smoothing=self.label_smoothing, pos_weight=self.pos_weight)  # pylint: disable=possibly-used-before-assignment
        else:
            self.criterion = nn.MSELoss()

    def _build_model(self, n_features: int, seq_len: int, **kwargs) -> nn.Module:
        arch = self.architecture.lower()
        if arch == "lstm":
            return _LSTMNet(n_features, **kwargs)  # pylint: disable=possibly-used-before-assignment
        elif arch == "transformer":
            return _TransformerNet(n_features, seq_len=seq_len, **kwargs)  # pylint: disable=possibly-used-before-assignment
        elif arch == "tcn":
            return _TCNNet(n_features, **kwargs)  # pylint: disable=possibly-used-before-assignment
        elif arch == "hybrid":
            return _HybridNet(n_features, **kwargs)  # pylint: disable=possibly-used-before-assignment
        else:
            raise ValueError(f"Unknown architecture '{arch}'. Choose from: {list(self.ARCHITECTURES)}")

    def _to_loader(self, X: np.ndarray, y: np.ndarray, shuffle: bool) -> DataLoader:
        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32)
        return DataLoader(
            TensorDataset(X_t, y_t),
            batch_size=self.batch_size,
            shuffle=shuffle,
            pin_memory=self.device.type == "cuda",
            num_workers=0,
        )

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        class_weight: bool = True,
    ) -> dict:
        """
        Train the model with early stopping, LR scheduling, and gradient clipping.

        Parameters
        ----------
        X_train      : (n_samples, seq_len, n_features)
        y_train      : (n_samples,) binary labels or regression targets
        X_val, y_val : Optional validation set for early stopping
        class_weight : Auto-compute pos_weight from class distribution

        Returns
        -------
        Training history dict with train_loss, val_loss, lr per epoch.
        """
        self._init_torch()
        # Auto class weighting for imbalanced binary targets
        if class_weight and self.task == "binary" and self.pos_weight is None:
            n_pos = float(y_train.sum())
            n_neg = float(len(y_train) - n_pos)
            if n_pos > 0 and n_neg > 0:
                computed_pw = n_neg / n_pos
                self.criterion = _LabelSmoothBCE(
                    smoothing=self.label_smoothing,
                    pos_weight=float(np.clip(computed_pw, 0.5, 5.0)),
                )

        train_loader = self._to_loader(X_train, y_train, shuffle=True)
        val_loader = self._to_loader(X_val, y_val, shuffle=False) if X_val is not None else None

        best_val_loss = float("inf")
        patience_counter = 0
        best_state: dict | None = None

        for epoch in range(self.max_epochs):
            # ── Train ─────────────────────────────────────────────────────────
            self.model.train()
            train_losses = []
            for X_b, y_b in train_loader:
                X_b_d, y_b_d = X_b.to(self.device), y_b.to(self.device)
                self.optimizer.zero_grad(set_to_none=True)

                if self.use_amp and self._scaler is not None:
                    with torch.cuda.amp.autocast():
                        pred = self.model(X_b_d)
                        loss = self.criterion(pred, y_b_d)
                    self._scaler.scale(loss).backward()
                    self._scaler.unscale_(self.optimizer)
                    nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip)
                    self._scaler.step(self.optimizer)
                    self._scaler.update()
                else:
                    pred = self.model(X_b_d)
                    loss = self.criterion(pred, y_b_d)
                    loss.backward()
                    nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip)
                    self.optimizer.step()

                train_losses.append(loss.item())

            avg_train = float(np.mean(train_losses))
            self._history["train_loss"].append(avg_train)
            current_lr = self.optimizer.param_groups[0]["lr"]
            self._history["lr"].append(current_lr)

            # ── Validate ──────────────────────────────────────────────────────
            if val_loader is not None:
                self.model.eval()
                val_losses = []
                with torch.no_grad():
                    for X_b, y_b in val_loader:
                        X_b_d, y_b_d = X_b.to(self.device), y_b.to(self.device)
                        pred = self.model(X_b_d)
                        val_losses.append(self.criterion(pred, y_b_d).item())
                avg_val = float(np.mean(val_losses))
                self._history["val_loss"].append(avg_val)

                # ReduceLROnPlateau step
                self.scheduler.step(avg_val)

                if avg_val < best_val_loss:
                    best_val_loss = avg_val
                    best_state = {k: v.cpu().clone() for k, v in self.model.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1

                if epoch % 10 == 0:
                    logger.info(
                        "Epoch %3d  train=%.4f  val=%.4f  lr=%.2e  patience=%d",
                        epoch,
                        avg_train,
                        avg_val,
                        current_lr,
                        patience_counter,
                    )

                if patience_counter >= self.patience:
                    logger.info(
                        "Early stopping at epoch %d (best_val=%.4f)",
                        epoch,
                        best_val_loss,
                    )
                    break
            elif epoch % 10 == 0:
                logger.info(
                    "Epoch %3d  train=%.4f  lr=%.2e",
                    epoch,
                    avg_train,
                    current_lr,
                )

        # Restore best weights
        if best_state is not None:
            self.model.load_state_dict(best_state)
            logger.info("Restored best model (val_loss=%.4f)", best_val_loss)

        return self._history

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return probability array (binary) or value array (regression)."""
        self._init_torch()
        self.model.eval()
        X_t = torch.tensor(X, dtype=torch.float32).to(self.device)
        preds = []
        with torch.no_grad():
            for i in range(0, len(X_t), self.batch_size):
                batch = X_t[i : i + self.batch_size]
                preds.append(self.model(batch).cpu().numpy())
        return np.concatenate(preds)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Alias for predict() — returns probabilities for binary task."""
        return self.predict(X)

    def evaluate(
        self,
        X: np.ndarray,
        y: np.ndarray,
        threshold: float = 0.5,
    ) -> dict:
        """
        Compute accuracy, AUC, and F1 on a held-out set.

        Returns a dict with keys: accuracy, auc, f1, n_samples.
        """
        from sklearn.metrics import accuracy_score, roc_auc_score, f1_score

        proba = self.predict(X)
        preds = (proba >= threshold).astype(int)
        result = {
            "accuracy": float(accuracy_score(y, preds)),
            "f1": float(f1_score(y, preds, zero_division=0)),
            "n_samples": len(y),
        }
        try:
            result["auc"] = float(roc_auc_score(y, proba))
        except (ValueError, TypeError):
            result["auc"] = 0.5
        return result

    def save(self, path: str | Path) -> None:
        self._init_torch()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "architecture": self.architecture,
                "n_features": self.n_features,
                "seq_len": self.seq_len,
                "task": self.task,
                "label_smoothing": self.label_smoothing,
                "pos_weight": self.pos_weight,
            },
            path,
        )
        logger.info("DeepPredictor saved → %s", path)

    @classmethod
    def load(cls, path: str | Path, device: str = "auto") -> DeepPredictor:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"DeepPredictor model not found: {path}")
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required for DeepPredictor.load()")
        # weights_only=False required: checkpoint contains non-tensor metadata
        # (architecture, task, label_smoothing). Path is validated by caller.
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)  # nosec B614
        predictor = cls(
            architecture=checkpoint["architecture"],
            n_features=checkpoint["n_features"],
            seq_len=checkpoint["seq_len"],
            task=checkpoint.get("task", "binary"),
            device=device,
            label_smoothing=checkpoint.get("label_smoothing", 0.05),
            pos_weight=checkpoint.get("pos_weight", None),
        )
        predictor._init_torch()
        predictor.model.load_state_dict(checkpoint["state_dict"])
        predictor.model.eval()
        logger.info("DeepPredictor loaded ← %s", path)
        return predictor

    def parameter_count(self) -> int:
        """Return total number of trainable parameters."""
        self._init_torch()
        return sum(p.numel() for p in self.model.parameters() if p.requires_grad)
