# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# ml/online_learner.py
"""
HOPEFX Online Learning Pipeline
Continuously adapts to market regime changes without catastrophic forgetting
"""

from __future__ import annotations

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False

    class _FakeModule:
        def __init__(self, *args, **kwargs):
            raise ImportError("torch is required. Install with: pip install torch")

    class nn:  # type: ignore[no-redef]
        Module = _FakeModule

    DataLoader = None  # type: ignore[assignment,misc]
    TensorDataset = None  # type: ignore[assignment,misc]
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd  # noqa: F401 — used in type annotations below


class EWCRegularizer:
    """
    Elastic Weight Consolidation (Kirkpatrick et al. 2017)
    Prevents catastrophic forgetting in neural networks.
    """

    def __init__(self, model: nn.Module, lambda_ewc: float = 1000):
        self.model = model
        self.lambda_ewc = lambda_ewc
        self.fisher_dict: Dict[str, torch.Tensor] = {}
        self.optimal_params: Dict[str, torch.Tensor] = {}
        self.ewc_loss = 0

    def update_fisher(self, dataloader: DataLoader):
        """Compute Fisher Information Matrix"""
        self.model.eval()
        fisher = {}

        # Initialize
        for name, param in self.model.named_parameters():
            fisher[name] = torch.zeros_like(param)

        # Accumulate gradients
        for batch_x, batch_y in dataloader:
            self.model.zero_grad()
            output = self.model(batch_x)
            loss = nn.functional.binary_cross_entropy(output, batch_y)
            loss.backward()

            for name, param in self.model.named_parameters():
                if param.grad is not None:
                    fisher[name] += param.grad.data**2

        # Average
        n = len(dataloader)
        for name in fisher:
            self.fisher_dict[name] = fisher[name] / n

        # Store optimal params
        for name, param in self.model.named_parameters():
            self.optimal_params[name] = param.data.clone()

    def compute_loss(self, model: nn.Module) -> torch.Tensor:
        """Compute EWC regularization loss"""
        if not self.fisher_dict:
            return torch.tensor(0.0)

        loss = 0
        for name, param in model.named_parameters():
            if name in self.fisher_dict:
                loss += (
                    self.fisher_dict[name] * (param - self.optimal_params[name]) ** 2
                ).sum()

        return self.lambda_ewc * loss


class OnlineLearner:
    """
    Continual learning for market prediction.
    Adapts to new data while preserving knowledge of past regimes.
    """

    def __init__(self, model: "nn.Module" = None, learning_rate: float = 1e-4):
        self.model = model
        if model is not None:
            self.optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=learning_rate,
                weight_decay=0.01,
            )
            self.ewc = EWCRegularizer(model)
        else:
            self.optimizer = None
            self.ewc = None

        # Experience replay buffer
        self.replay_buffer: deque = deque(maxlen=10000)
        self.batch_size = 32

        # Learning rate scheduler
        if self.optimizer is not None and torch is not None:
            self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                self.optimizer,
                mode="max",
                factor=0.5,
                patience=10,
            )
        else:
            self.scheduler = None

        # Metrics
        self.train_losses = []
        self.validation_accuracies = []

    def train_step(
        self,
        new_data: Tuple[np.ndarray, np.ndarray],
        validation_data: Optional[Tuple[np.ndarray, np.ndarray]] = None,
    ) -> float:
        """
        Single online training step with EWC and replay.

        Args:
            new_data: (features, labels) from latest batch
            validation_data: Optional validation set for EWC update
        """
        # Add to replay buffer
        X_new, y_new = new_data
        for i in range(len(X_new)):
            self.replay_buffer.append((X_new[i], y_new[i]))

        # Sample from replay buffer (experience replay)
        if len(self.replay_buffer) >= self.batch_size:
            indices = np.random.choice(
                len(self.replay_buffer),
                self.batch_size,
                replace=False,
            )
            batch = [self.replay_buffer[i] for i in indices]

            X_batch = torch.FloatTensor(np.stack([x for x, y in batch]))
            y_batch = torch.FloatTensor(np.stack([y for x, y in batch]))
        else:
            X_batch = torch.FloatTensor(X_new)
            y_batch = torch.FloatTensor(y_new)

        # Training
        self.model.train()
        self.optimizer.zero_grad()

        # Forward
        predictions = self.model(X_batch)

        # Task loss
        task_loss = nn.functional.binary_cross_entropy(predictions, y_batch)

        # EWC regularization (prevent forgetting)
        ewc_loss = self.ewc.compute_loss(self.model)

        # Total loss
        total_loss = task_loss + ewc_loss

        # Backward
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()

        # Update EWC periodically
        if validation_data and len(self.train_losses) % 100 == 0:
            val_loader = DataLoader(
                TensorDataset(
                    torch.FloatTensor(validation_data[0]),
                    torch.FloatTensor(validation_data[1]),
                ),
                batch_size=self.batch_size,
            )
            self.ewc.update_fisher(val_loader)

        self.train_losses.append(total_loss.item())

        return total_loss.item()

    def adapt_to_regime(self, regime: str, regime_data: Dict[str, np.ndarray]):
        """
        Fast adaptation to detected market regime.
        Uses regime-specific learning rate and EWC weight.
        """
        # Adjust learning rate based on regime volatility
        if regime == "volatile":
            for param_group in self.optimizer.param_groups:
                param_group["lr"] *= 1.5  # Faster adaptation
            self.ewc.lambda_ewc = 500  # Less regularization (more plasticity)
        elif regime == "ranging":
            for param_group in self.optimizer.param_groups:
                param_group["lr"] *= 0.8  # Slower, more stable
            self.ewc.lambda_ewc = 2000  # More regularization

    def get_learning_diagnostics(self) -> Dict:
        """Get diagnostics about learning process"""
        return {
            "train_loss_trend": np.polyfit(
                range(len(self.train_losses)),
                self.train_losses,
                1,
            )[0]
            if len(self.train_losses) > 10
            else 0,
            "buffer_size": len(self.replay_buffer),
            "ewc_lambda": self.ewc.lambda_ewc,
            "current_lr": self.optimizer.param_groups[0]["lr"],
        }


class EnsemblePredictor:
    """
    Ensemble of models with different architectures.
    Provides robust predictions via model diversity.
    """

    def __init__(self, models: List[nn.Module], weights: Optional[List[float]] = None):
        self.models = models
        self.weights = weights or [1.0 / len(models)] * len(models)
        self.performance_history: Dict[int, List[float]] = {
            i: [] for i in range(len(models))
        }

    def predict(self, X: np.ndarray) -> Tuple[float, float]:
        """
        Ensemble prediction with uncertainty estimation.

        Returns:
            (mean_prediction, uncertainty)
        """
        X_tensor = torch.FloatTensor(X)

        predictions = []
        with torch.no_grad():
            for model in self.models:
                model.eval()
                pred = model(X_tensor)
                predictions.append(pred.numpy())

        # Weighted average
        predictions = np.array(predictions)
        weighted_pred = np.average(predictions, axis=0, weights=self.weights)

        # Uncertainty = variance across models
        uncertainty = np.var(predictions, axis=0)

        return float(weighted_pred.mean()), float(uncertainty.mean())

    def update_weights(self, recent_performance: Dict[int, float]):
        """
        Update ensemble weights based on recent performance.
        Poor performers get reduced weight.
        """
        # Softmax weighting based on performance
        exp_perf = np.exp(
            [recent_performance.get(i, 0) for i in range(len(self.models))],
        )
        self.weights = (exp_perf / exp_perf.sum()).tolist()

    def add_model(self, model: nn.Module, initial_weight: float = 0.1):
        """Add new model to ensemble (for continual expansion)"""
        self.models.append(model)
        # Redistribute weights
        total = sum(self.weights) + initial_weight
        self.weights = [w * (1 - initial_weight / total) for w in self.weights] + [
            initial_weight / total,
        ]


# ── Sklearn-compatible incremental wrapper ────────────────────────────────────


class SklearnOnlineLearner:
    """
    Sklearn-compatible incremental learner backed by SGDClassifier.

    Provides ``partial_fit()`` so the HourlyTrainer can feed recent bars
    without requiring PyTorch.  Falls back gracefully when sklearn is absent.

    The learner is stateless across restarts unless ``persist_path`` is set,
    in which case it is serialised to disk after every ``partial_fit`` call.
    """

    def __init__(
        self,
        symbol: str = "XAU_USD",
        persist_path: Optional[str] = None,
        n_features: int = 176,
    ) -> None:
        self.symbol = symbol
        self.persist_path = persist_path
        self.n_features = n_features
        self._fitted = False
        self._update_count = 0
        self._model = None
        self._scaler = None
        self._init_model()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init_model(self) -> None:
        try:
            from sklearn.linear_model import SGDClassifier
            from sklearn.preprocessing import StandardScaler as _SS

            self._model = SGDClassifier(
                loss="log_loss",
                penalty="elasticnet",
                alpha=1e-4,
                l1_ratio=0.15,
                max_iter=1,
                tol=None,
                warm_start=True,
                random_state=42,
                n_jobs=1,
            )
            self._scaler = _SS()
        except ImportError:
            import logging as _log

            _log.getLogger(__name__).warning(
                "sklearn not available — SklearnOnlineLearner is a no-op"
            )

    def _extract_features(self, bars: "pd.DataFrame") -> Optional[np.ndarray]:
        """Extract a simple feature vector from OHLCV bars."""
        try:
            import pandas as pd  # noqa: F401

            cols = [c for c in ["open", "high", "low", "close", "volume"] if c in bars.columns]
            if not cols:
                return None
            X = bars[cols].ffill().bfill().values.astype(float)
            # Pad or truncate to n_features
            n = X.shape[0] * X.shape[1]
            flat = X.flatten()
            if n < self.n_features:
                flat = np.pad(flat, (0, self.n_features - n))
            else:
                flat = flat[: self.n_features]
            return flat.reshape(1, -1)
        except Exception:
            return None

    def _extract_label(self, bars: "pd.DataFrame") -> Optional[np.ndarray]:
        """Binary label: 1 if last close > first close, else 0."""
        try:
            closes = bars["close"].values
            return np.array([1 if closes[-1] > closes[0] else 0])
        except Exception:
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def partial_fit(self, bars: "pd.DataFrame") -> bool:
        """
        Incrementally update the model with new OHLCV bars.

        Args:
            bars: DataFrame with columns open/high/low/close/volume.

        Returns:
            True if the update succeeded, False otherwise.
        """
        if self._model is None:
            return False
        try:
            X = self._extract_features(bars)
            y = self._extract_label(bars)
            if X is None or y is None:
                return False

            if not self._fitted:
                self._scaler.fit(X)
                self._fitted = True

            X_scaled = self._scaler.transform(X)
            self._model.partial_fit(X_scaled, y, classes=[0, 1])
            self._update_count += 1

            if self.persist_path:
                self._save()

            import logging as _log
            _log.getLogger(__name__).debug(
                "SklearnOnlineLearner[%s] partial_fit #%d OK",
                self.symbol,
                self._update_count,
            )
            return True
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "SklearnOnlineLearner[%s] partial_fit failed: %s", self.symbol, exc
            )
            return False

    def predict_proba(self, bars: "pd.DataFrame") -> Optional[float]:
        """Return P(up) for the given bars, or None if not yet fitted."""
        if self._model is None or not self._fitted:
            return None
        try:
            X = self._extract_features(bars)
            if X is None:
                return None
            X_scaled = self._scaler.transform(X)
            proba = self._model.predict_proba(X_scaled)
            return float(proba[0, 1])
        except Exception:
            return None

    def status(self) -> Dict:
        return {
            "symbol": self.symbol,
            "fitted": self._fitted,
            "update_count": self._update_count,
            "persist_path": self.persist_path,
        }

    def _save(self) -> None:
        import pickle as _pkl
        import pathlib as _pl

        path = _pl.Path(self.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            _pkl.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "SklearnOnlineLearner":
        import pickle as _pkl

        with open(path, "rb") as f:
            return _pkl.load(f)


# ── Module-level singleton registry ──────────────────────────────────────────

_learner_registry: Dict[str, SklearnOnlineLearner] = {}


def get_online_learner(
    symbol: str = "XAU_USD",
    persist_path: Optional[str] = None,
) -> SklearnOnlineLearner:
    """
    Return the SklearnOnlineLearner singleton for ``symbol``.

    Creates and registers a new instance on first call.  If ``persist_path``
    is provided and the file exists, the persisted learner is loaded instead
    of creating a fresh one.

    Called by HourlyTrainer._online_update() on every hourly cycle.
    """
    global _learner_registry  # noqa: PLW0603

    if symbol not in _learner_registry:
        if persist_path is None:
            persist_path = f"ml/saved_models/online_learner_{symbol}.pkl"

        import pathlib as _pl

        p = _pl.Path(persist_path)
        if p.exists():
            try:
                learner = SklearnOnlineLearner.load(str(p))
                import logging as _log
                _log.getLogger(__name__).info(
                    "Loaded persisted OnlineLearner for %s from %s", symbol, p
                )
            except Exception:
                learner = SklearnOnlineLearner(symbol=symbol, persist_path=str(p))
        else:
            learner = SklearnOnlineLearner(symbol=symbol, persist_path=str(p))

        _learner_registry[symbol] = learner

    return _learner_registry[symbol]
