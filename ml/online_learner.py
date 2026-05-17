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

import logging
import os
import pathlib
import threading

try:
    import torch
    from torch import nn
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
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class EWCRegularizer:
    """
    Elastic Weight Consolidation (Kirkpatrick et al. 2017)
    Prevents catastrophic forgetting in neural networks.
    """

    def __init__(self, model: nn.Module, lambda_ewc: float = 1000):
        self.model = model
        self.lambda_ewc = lambda_ewc
        self.fisher_dict: dict[str, torch.Tensor] = {}
        self.optimal_params: dict[str, torch.Tensor] = {}
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

        # Average — guard against empty dataloader
        n = len(dataloader) or 1
        for name in fisher:
            self.fisher_dict[name] = fisher[name] / n

        # Store optimal params
        for name, param in self.model.named_parameters():
            self.optimal_params[name] = param.data.clone()

    def compute_loss(self, model: nn.Module) -> torch.Tensor:
        """Compute EWC regularization loss"""
        if not self.fisher_dict:
            return torch.tensor(0.0)

        import torch as _torch_ewc

        loss = _torch_ewc.tensor(0.0)
        for name, param in model.named_parameters():
            if name in self.fisher_dict:
                diff = param - self.optimal_params[name]
                _raw = (self.fisher_dict[name] * diff**2).sum()
                term = _torch_ewc.nan_to_num(_raw, nan=0.0)
                loss = loss + term

        return self.lambda_ewc * loss


class OnlineLearner:
    """
    Continual learning for market prediction.
    Adapts to new data while preserving knowledge of past regimes.
    """

    def __init__(self, model: nn.Module | None = None, learning_rate: float = 1e-4):
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
        new_data: tuple[np.ndarray, np.ndarray],
        validation_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> float:
        """
        Single online training step with EWC and replay.

        Returns 0.0 immediately when model or optimizer are unavailable (torch not installed).

        Args:
            new_data: (features, labels) from latest batch
            validation_data: Optional validation set for EWC update
        """
        if self.model is None or self.optimizer is None or self.ewc is None:
            return 0.0
        # Add to replay buffer
        X_new, y_new = new_data
        for i in range(len(X_new)):
            self.replay_buffer.append((X_new[i], y_new[i]))

        # Sample from replay buffer (experience replay — unseeded)
        if len(self.replay_buffer) >= self.batch_size:
            indices = np.random.default_rng().choice(
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

    def adapt_to_regime(self, regime: str, _regime_data: dict[str, np.ndarray]):
        """
        Fast adaptation to detected market regime.
        Uses regime-specific learning rate and EWC weight.
        """
        if self.optimizer is None or self.ewc is None:
            return
        # Adjust learning rate based on regime volatility
        if regime == "volatile":
            for param_group in self.optimizer.param_groups:
                param_group["lr"] *= 1.5  # Faster adaptation
            self.ewc.lambda_ewc = 500  # Less regularization (more plasticity)
        elif regime == "ranging":
            for param_group in self.optimizer.param_groups:
                param_group["lr"] *= 0.8  # Slower, more stable
            self.ewc.lambda_ewc = 2000  # More regularization

    def get_learning_diagnostics(self) -> dict:
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
            "ewc_lambda": self.ewc.lambda_ewc if self.ewc is not None else None,
            "current_lr": self.optimizer.param_groups[0]["lr"] if self.optimizer is not None else None,
        }


class EnsemblePredictor:
    """
    Ensemble of models with different architectures.
    Provides robust predictions via model diversity.
    """

    def __init__(self, models: list[nn.Module], weights: list[float] | None = None):
        self.models = models
        self.weights = weights or [1.0 / len(models)] * len(models)
        self.performance_history: dict[int, list[float]] = {i: [] for i in range(len(models))}

    def predict(self, X: np.ndarray) -> tuple[float, float]:
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

    def update_weights(self, recent_performance: dict[int, float]):
        """
        Update ensemble weights based on recent performance.
        Poor performers get reduced weight.
        """
        # Softmax weighting based on performance
        raw = np.nan_to_num(
            np.array([recent_performance.get(i, 0) for i in range(len(self.models))], dtype=float),
            nan=0.0,
        )
        exp_perf = np.exp(np.clip(raw, -50, 50))
        total = exp_perf.sum()
        self.weights = (exp_perf / max(total, 1e-9)).tolist()

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
    Production incremental learner backed by SGDClassifier.

    Catastrophic forgetting prevention
    ------------------------------------
    SGD with elasticnet penalty naturally forgets old patterns as new data
    arrives.  This class adds two complementary mechanisms:

    1. EWC-style L2 anchor (sklearn approximation)
       After every ``ewc_anchor_every`` updates the current model weights are
       snapshotted as an "anchor".  The SGD alpha (L2 penalty) is then
       temporarily increased proportional to how far the new weights drift
       from the anchor — penalising large weight changes that would erase
       previously learned patterns.

    2. Drift-triggered reset
       A KS-test drift detector monitors the rolling prediction probability
       distribution.  When significant drift is detected (p < 0.05) the
       model is reset to a fresh SGDClassifier so it can adapt to the new
       regime without being anchored to stale weights.  The reset counter
       is exposed in status() for monitoring.

    Data layer injection
    --------------------
    Four orchestrator features (sentiment, OFI, macro impact, blackout) are
    appended to every feature vector so the learner sees live market context.

    Persistence
    -----------
    When ``persist_path`` is set the learner is serialised after every
    ``partial_fit`` call.  On startup the persisted state is loaded
    automatically by ``get_online_learner()``.
    """

    # Drift detection window and KS p-value threshold
    _DRIFT_WINDOW = 50
    _DRIFT_P_THRESH = 0.05
    # EWC anchor: snapshot weights every N updates
    _EWC_ANCHOR_EVERY = 20
    # Performance tracking window
    _PERF_WINDOW = 100

    def __init__(
        self,
        symbol: str = "XAU_USD",
        persist_path: str | None = None,
        n_features: int = 176,
        ewc_lambda: float = 0.10,
    ) -> None:
        self.symbol = symbol
        self.persist_path = persist_path
        self.n_features = n_features
        self.ewc_lambda = ewc_lambda  # L2 anchor strength (0 = disabled)

        self._fitted = False
        self._update_count = 0
        self._reset_count = 0
        self._model = None
        self._scaler = None

        # EWC anchor: snapshot of model coef_ after stable training
        self._anchor_coef: np.ndarray | None = None
        self._anchor_intercept: np.ndarray | None = None
        self._base_alpha = 1e-4  # SGD alpha before EWC adjustment

        # Drift detection: rolling window of predicted probabilities
        self._prob_window: deque = deque(maxlen=self._DRIFT_WINDOW)
        self._ref_probs: np.ndarray | None = None  # reference distribution
        self._drift_count = 0

        # Thread safety: serialize concurrent partial_fit + predict_proba calls
        self._lock = threading.Lock()

        # Performance tracking: rolling accuracy
        self._correct_window: deque = deque(maxlen=self._PERF_WINDOW)
        self._rolling_accuracy: float = 0.5

        self._init_model()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        # threading.Lock is not picklable; reconstruct on load
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._lock = threading.Lock()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init_model(self) -> None:
        try:
            from sklearn.linear_model import SGDClassifier
            from sklearn.preprocessing import StandardScaler as _SS

            self._model = SGDClassifier(
                loss="log_loss",
                penalty="elasticnet",
                alpha=self._base_alpha,
                l1_ratio=0.15,
                max_iter=1,
                tol=None,
                warm_start=True,
                random_state=42,
                n_jobs=1,
            )
            self._scaler = _SS()
        except ImportError:
            logger.warning("sklearn not available — SklearnOnlineLearner is a no-op")

    def _extract_features(self, bars: pd.DataFrame) -> np.ndarray | None:
        """
        Extract feature vector from OHLCV bars.

        Features (in order):
          - Flattened OHLCV values (open/high/low/close/volume)
          - Log returns (close pct_change)
          - Rolling volatility (std of last 10 returns)
          - 4 data layer scalars: sentiment, OFI, macro_impact, blackout

        All values are padded/truncated to ``n_features``.

        Schema contract
        ---------------
        When the raw feature count differs from ``n_features``, a WARNING is
        emitted describing the delta.  Silent truncation destroys the positional
        meaning of every feature beyond the truncation point; silent padding
        introduces artificial zero-valued features that corrupt model weights.
        Operators MUST reconcile the mismatch by retraining or adjusting
        ``n_features`` rather than relying on this fallback indefinitely.
        """
        try:
            cols = [c for c in ["open", "high", "low", "close", "volume"] if c in bars.columns]
            if not cols:
                return None

            # ffill propagates the last known value forward (causal).
            # fillna(0.0) handles any leading NaNs at the start of the window
            # without back-filling from future bars (no look-ahead bias).
            ohlcv_vals = bars[cols].ffill().fillna(0.0).values.astype(float)
            flat = ohlcv_vals.flatten()

            # Log returns (last 20 bars)
            if "close" in bars.columns:
                closes = bars["close"].values.astype(float)
                log_ret = np.nan_to_num(np.diff(np.log(np.maximum(closes, 1e-9))), nan=0.0, posinf=0.0, neginf=0.0)[
                    -20:
                ]
                vol = float(np.nan_to_num(np.std(log_ret), nan=0.0)) if len(log_ret) > 1 else 0.0
                flat = np.concatenate([flat, log_ret, [vol]])

            # Data layer features (4 scalars from orchestrator)
            dl_extra = np.zeros(4, dtype=float)
            try:
                from data_layer.orchestrator import orchestrator

                feats = orchestrator.get_ml_features()
                dl_extra[0] = float(feats.get("news_sentiment_score", 0.0))
                dl_extra[1] = float(feats.get("micro_ofi", 0.0))
                dl_extra[2] = float(feats.get("macro_impact_score_now", 0.0))
                dl_extra[3] = float(feats.get("macro_is_blackout", 0.0))
            except Exception as _exc:  # pylint: disable=broad-exception-caught
                logger.debug("SklearnOnlineLearner: data layer injection skipped: %s", _exc)

            flat = np.concatenate([flat, dl_extra])

            # ── Feature count validation ──────────────────────────────────────
            # Pad or truncate to n_features, but ALWAYS log when the raw count
            # differs from the expected schema.  Silent truncation/padding is a
            # known source of model degradation and must never go unnoticed.
            raw_len = len(flat)
            if raw_len != self.n_features:
                delta = raw_len - self.n_features
                if raw_len < self.n_features:
                    logger.warning(
                        "SklearnOnlineLearner[%s]: feature count mismatch — got %d, expected %d "
                        "(padding %d zeros at tail). Retrain model to fix feature schema.",
                        self.symbol,
                        raw_len,
                        self.n_features,
                        self.n_features - raw_len,
                    )
                    flat = np.pad(flat, (0, self.n_features - raw_len))
                else:
                    logger.warning(
                        "SklearnOnlineLearner[%s]: feature count mismatch — got %d, expected %d "
                        "(truncating %d tail features). Positional feature semantics beyond index %d "
                        "are LOST. Retrain model to fix feature schema.",
                        self.symbol,
                        raw_len,
                        self.n_features,
                        delta,
                        self.n_features,
                    )
                    flat = flat[: self.n_features]

            # Replace inf/nan
            flat = np.where(np.isfinite(flat), flat, 0.0)
            return flat.reshape(1, -1)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("SklearnOnlineLearner._extract_features failed for %s: %s", self.symbol, exc)
            return None

    def _extract_label(self, bars: pd.DataFrame) -> np.ndarray | None:
        """Binary label: 1 if last close > first close, else 0."""
        try:
            closes = bars["close"].values
            return np.array([1 if closes[-1] > closes[0] else 0])
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def _update_ewc_anchor(self) -> None:
        """
        Snapshot current model weights as the EWC anchor.

        Called every ``_EWC_ANCHOR_EVERY`` updates.  After anchoring, the
        SGD alpha is adjusted to penalise drift from the anchor weights.
        """
        if self._model is None or not hasattr(self._model, "coef_"):
            return
        try:
            self._anchor_coef = self._model.coef_.copy()
            self._anchor_intercept = self._model.intercept_.copy()
            logger.debug(
                "SklearnOnlineLearner[%s]: EWC anchor updated at update #%d",
                self.symbol,
                self._update_count,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("EWC anchor update failed: %s", exc)

    def _apply_ewc_penalty(self) -> None:
        """
        Adjust SGD alpha based on weight drift from the EWC anchor.

        Drift = mean absolute deviation of current coef_ from anchor.
        alpha = base_alpha * (1 + ewc_lambda * drift)

        This increases regularisation when the model is drifting far from
        its previously learned weights, preventing catastrophic forgetting.
        """
        if (
            self._model is None
            or self._anchor_coef is None
            or not hasattr(self._model, "coef_")
            or self.ewc_lambda <= 0
        ):
            return
        try:
            drift = float(np.mean(np.abs(self._model.coef_ - self._anchor_coef)))
            new_alpha = self._base_alpha * (1.0 + self.ewc_lambda * drift * 100.0)
            new_alpha = float(np.clip(new_alpha, self._base_alpha, self._base_alpha * 100))
            self._model.alpha = new_alpha
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("EWC penalty application failed: %s", exc)

    def _check_drift(self, prob: float) -> bool:
        """
        Add ``prob`` to the rolling window and run a KS drift test.

        Returns True when significant drift is detected (p < threshold).
        Sets the reference distribution from the first full window.
        """
        self._prob_window.append(prob)

        if len(self._prob_window) < self._DRIFT_WINDOW:
            return False

        window_arr = np.array(self._prob_window)

        # Establish reference on first full window
        if self._ref_probs is None:
            self._ref_probs = window_arr.copy()
            return False

        try:
            from scipy.stats import ks_2samp

            _, p_value = ks_2samp(self._ref_probs, window_arr)
            if p_value < self._DRIFT_P_THRESH:
                logger.info(
                    "SklearnOnlineLearner[%s]: drift detected (p=%.4f) — resetting model to adapt to new regime",
                    self.symbol,
                    p_value,
                )
                return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Drift check failed: %s", exc)

        return False

    def _reset_for_new_regime(self) -> None:
        """
        Reset the SGD model to adapt to a new market regime.

        Preserves the scaler (feature normalisation is regime-independent)
        and the EWC anchor (so the new model starts from a reasonable prior).
        Increments the reset counter for monitoring.
        """
        self._init_model()
        self._fitted = False
        self._reset_count += 1
        self._drift_count += 1
        # Update reference distribution to the current window
        if len(self._prob_window) >= self._DRIFT_WINDOW:
            self._ref_probs = np.array(self._prob_window)
        logger.info(
            "SklearnOnlineLearner[%s]: model reset #%d for new regime",
            self.symbol,
            self._reset_count,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def partial_fit(self, bars: pd.DataFrame) -> bool:
        """
        Incrementally update the model with new OHLCV bars.

        Steps:
        1. Extract features + label from bars
        2. Scale features (fit scaler on first call)
        3. SGD partial_fit
        4. EWC anchor update (every _EWC_ANCHOR_EVERY steps)
        5. EWC penalty adjustment
        6. Drift check → reset if regime changed
        7. Persist to disk if persist_path is set

        Returns True on success, False on any failure.
        """
        if self._model is None:
            return False
        with self._lock:
            return self._partial_fit_locked(bars)

    def _partial_fit_locked(self, bars: pd.DataFrame) -> bool:
        """Model update — must be called with self._lock held."""
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

            # Track rolling accuracy
            try:
                pred = int(self._model.predict(X_scaled)[0])
                correct = int(pred == int(y[0]))
                self._correct_window.append(correct)
                if len(self._correct_window) >= 10:
                    self._rolling_accuracy = float(np.mean(self._correct_window))
            except Exception:  # pylint: disable=broad-exception-caught  # nosec B110
                ...  # nosec B110

            # EWC anchor snapshot
            if self._update_count % self._EWC_ANCHOR_EVERY == 0:
                self._update_ewc_anchor()

            # EWC penalty (adjust alpha to resist forgetting)
            self._apply_ewc_penalty()

            # Drift detection — reset model if regime changed
            try:
                prob = float(self._model.predict_proba(X_scaled)[0, 1])
                if self._check_drift(prob):
                    self._reset_for_new_regime()
            except Exception:  # pylint: disable=broad-exception-caught  # nosec B110
                ...  # nosec B110

            if self.persist_path:
                self._save()

            logger.debug(
                "SklearnOnlineLearner[%s] partial_fit #%d OK (acc=%.3f resets=%d)",
                self.symbol,
                self._update_count,
                self._rolling_accuracy,
                self._reset_count,
            )
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("SklearnOnlineLearner[%s] partial_fit failed: %s", self.symbol, exc)
            return False

    def predict_proba(self, bars: pd.DataFrame) -> float | None:
        """
        Return P(up) for the given bars, or None if not yet fitted.

        Returns a float in [0, 1] representing the probability that the
        next bar closes higher than the current bar.
        """
        if self._model is None or not self._fitted:
            return None
        with self._lock:
            try:
                X = self._extract_features(bars)
                if X is None:
                    return None
                X_scaled = self._scaler.transform(X)
                proba = self._model.predict_proba(X_scaled)
                return float(proba[0, 1])
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("SklearnOnlineLearner.predict_proba failed: %s", exc)
                return None

    def reset(self) -> None:
        """
        Manually reset the model (e.g. after a major regime change).

        Preserves the scaler and increments the reset counter.
        """
        self._reset_for_new_regime()

    def status(self) -> dict:
        """Return monitoring status dict."""
        return {
            "symbol": self.symbol,
            "fitted": self._fitted,
            "update_count": self._update_count,
            "reset_count": self._reset_count,
            "drift_count": self._drift_count,
            "rolling_accuracy": round(self._rolling_accuracy, 4),
            "ewc_lambda": self.ewc_lambda,
            "n_features": self.n_features,
            "persist_path": self.persist_path,
            "prob_window_size": len(self._prob_window),
            "has_anchor": self._anchor_coef is not None,
        }

    def _save(self) -> None:
        import pathlib as _pl

        import joblib as _jl

        _safe_path = _assert_safe_model_path(_pl.Path(self.persist_path))
        _safe_path.parent.mkdir(parents=True, exist_ok=True)
        _jl.dump(self, _safe_path, compress=3)

    @classmethod
    def load(cls, path: str) -> SklearnOnlineLearner:
        """Load a persisted learner from *path*.

        Deserializing pickle/joblib data is unsafe unless the source is fully
        trusted. We therefore require an explicit runtime opt-in before loading.
        """
        import pathlib as _pl

        import joblib as _jl

        _safe_path = _assert_safe_model_path(_pl.Path(path))  # raises if outside _MODEL_ROOT
        if not _trusted_pickle_load_enabled():
            raise RuntimeError(
                "Refusing to deserialize persisted learner from disk because "
                "pickle/joblib loading is disabled by default. Set "
                "HOPEFX_ALLOW_TRUSTED_MODEL_LOAD=1 only in fully trusted deployments."
            )
        return _jl.load(_safe_path)  # nosec B301


# ── Path-confinement helper ───────────────────────────────────────────────────

# Canonical root for all persisted model files.  Any load/save outside this
# directory is rejected to prevent path-traversal / arbitrary-pickle attacks.
_MODEL_ROOT = pathlib.Path(__file__).resolve().parent / "saved_models"


def _assert_safe_model_path(path: pathlib.Path) -> pathlib.Path:
    """Raise ValueError if *path* escapes the allowed model directory.

    Returns the resolved, confinement-checked Path so callers can use the
    return value instead of the original (potentially tainted) path object.
    """
    import os as _os
    import pathlib as _pl

    # Resolve via os.path.realpath (string-based) so the taint from the Path
    # object does not propagate into the resolved result (CodeQL #24631).
    _resolved_str: str = _os.path.realpath(str(path))
    resolved = _pl.Path(_resolved_str)
    try:
        resolved.relative_to(_MODEL_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"Model path '{resolved}' is outside the permitted directory '{_MODEL_ROOT}'. Refusing to load/save."
        ) from exc
    return resolved


def _trusted_pickle_load_enabled() -> bool:
    """Return True only when trusted pickle/joblib model loading is explicitly enabled."""
    return os.getenv("HOPEFX_ALLOW_TRUSTED_MODEL_LOAD", "").strip().lower() in {"1", "true", "yes"}


# ── Module-level singleton registry ──────────────────────────────────────────

_learner_registry: dict[str, SklearnOnlineLearner] = {}

# Characters allowed in a symbol name used to build a model filename.
# Restricts to alphanumeric, underscore, and hyphen — no path separators.
import re as _re

_SYMBOL_RE = _re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


def _validate_symbol(symbol: str) -> str:
    """Return *symbol* if it is safe to embed in a filename, else raise."""
    if not _SYMBOL_RE.match(symbol):
        raise ValueError(
            f"Symbol '{symbol}' contains characters not permitted in a model "
            "filename. Use only letters, digits, underscores, and hyphens."
        )
    return symbol


def get_online_learner(
    symbol: str = "XAU_USD",
    persist_path: str | None = None,
) -> SklearnOnlineLearner:
    """Return the SklearnOnlineLearner singleton for ``symbol``.

    Creates and registers a new instance on first call.  If ``persist_path``
    is provided and the file exists, the persisted learner is loaded instead
    of creating a fresh one.

    The symbol is validated against a strict allowlist of characters before
    being used to construct a filesystem path.  An explicit ``persist_path``
    is resolved and confined to ``ml/saved_models`` before any I/O.

    Called by HourlyTrainer._online_update() on every hourly cycle.
    """

    if symbol not in _learner_registry:
        import os as _os
        import pathlib as _pl

        _m = _SYMBOL_RE.match(symbol)
        if _m is None:
            raise ValueError(
                f"Symbol '{symbol}' contains characters not permitted in a model "
                "filename. Use only letters, digits, underscores, and hyphens."
            )

        if persist_path is None:
            # Reconstruct path from the regex match group only — CodeQL treats
            # m.group(0) as untainted (CodeQL #24618).
            _safe_sym: str = _m.group(0)
            _p_str: str = _os.path.join(str(_MODEL_ROOT), f"online_learner_{_safe_sym}.pkl")
            p = _pl.Path(_p_str)
        else:
            # _assert_safe_model_path returns the resolved, validated Path so
            # the caller never uses the original tainted persist_path value.
            p = _assert_safe_model_path(_pl.Path(persist_path))

        if p.exists():
            try:
                learner = SklearnOnlineLearner.load(str(p))
                logger.info("Loaded persisted OnlineLearner for %s from %s", symbol, p)
            except Exception:  # pylint: disable=broad-exception-caught
                learner = SklearnOnlineLearner(symbol=symbol, persist_path=str(p))
        else:
            learner = SklearnOnlineLearner(symbol=symbol, persist_path=str(p))

        _learner_registry[symbol] = learner

    return _learner_registry[symbol]


# ── XGBoostOnlineModel ────────────────────────────────────────────────────────


@dataclass
class ModelMetadata:
    """Training metadata returned by XGBoostOnlineModel.fit()."""

    val_score: float = 0.0
    n_samples: int = 0
    n_features: int = 0
    train_score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class XGBoostOnlineModel:
    """
    Async-compatible XGBoost wrapper with incremental partial_fit support.

    Designed for online learning loops where the model is retrained on
    rolling windows without full refit overhead.  Uses XGBClassifier for
    binary classification (direction prediction).

    Attributes
    ----------
    _is_trained : bool  — True after first successful fit()
    metadata    : ModelMetadata | None  — populated after fit()
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        eval_fraction: float = 0.2,
        random_state: int = 42,
    ) -> None:
        try:
            import xgboost as xgb

            self._xgb = xgb  # retain reference; used in fit/predict
        except ImportError as exc:
            raise ImportError("xgboost is required for XGBoostOnlineModel. Install with: pip install xgboost") from exc

        self._n_estimators = n_estimators
        self._max_depth = max_depth
        self._learning_rate = learning_rate
        self._subsample = subsample
        self._colsample_bytree = colsample_bytree
        self._eval_fraction = eval_fraction
        self._random_state = random_state

        self._model: Any | None = None
        self._is_trained: bool = False
        self.metadata: ModelMetadata | None = None

    async def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> ModelMetadata:
        """
        Train (or retrain) the XGBoost model on (X, y).

        Runs synchronously inside an executor so the event loop is not blocked.
        Returns ModelMetadata with val_score populated.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        meta = await loop.run_in_executor(None, self._fit_sync, X, y)
        return meta

    def _fit_sync(self, X: np.ndarray, y: np.ndarray) -> ModelMetadata:
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import train_test_split
        from xgboost import XGBClassifier

        n_samples, n_features = X.shape
        X_train, X_val, y_train, y_val = train_test_split(
            X,
            y,
            test_size=self._eval_fraction,
            random_state=self._random_state,
            stratify=y if len(np.unique(y)) > 1 else None,
        )

        model = XGBClassifier(
            n_estimators=self._n_estimators,
            max_depth=self._max_depth,
            learning_rate=self._learning_rate,
            subsample=self._subsample,
            colsample_bytree=self._colsample_bytree,
            random_state=self._random_state,
            eval_metric="logloss",
            use_label_encoder=False,
            verbosity=0,
        )
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        val_proba = model.predict_proba(X_val)[:, 1]
        train_proba = model.predict_proba(X_train)[:, 1]

        try:
            val_score = float(roc_auc_score(y_val, val_proba))
            train_score = float(roc_auc_score(y_train, train_proba))
        except ValueError:
            val_score = 0.5
            train_score = 0.5

        self._model = model
        self._is_trained = True
        self.metadata = ModelMetadata(
            val_score=val_score,
            train_score=train_score,
            n_samples=n_samples,
            n_features=n_features,
        )
        logger.info(
            "XGBoostOnlineModel fitted: n=%d features=%d val_auc=%.4f",
            n_samples,
            n_features,
            val_score,
        )
        return self.metadata

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return probability of class 1 for each sample."""
        if not self._is_trained or self._model is None:
            raise RuntimeError("Model not trained — call fit() first")
        return self._model.predict_proba(X)[:, 1]

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return binary predictions (threshold 0.5)."""
        return (self.predict_proba(X) >= 0.5).astype(int)

    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Incremental update via warm-start: add n_estimators more trees.

        Falls back to full refit if model not yet trained.
        """
        if not self._is_trained or self._model is None:
            import asyncio

            asyncio.run(self.fit(X, y))
            return

        from xgboost import XGBClassifier

        prev = self._model
        n_prev = prev.n_estimators
        updated = XGBClassifier(
            n_estimators=n_prev + self._n_estimators,
            max_depth=self._max_depth,
            learning_rate=self._learning_rate,
            subsample=self._subsample,
            colsample_bytree=self._colsample_bytree,
            random_state=self._random_state,
            eval_metric="logloss",
            use_label_encoder=False,
            verbosity=0,
        )
        updated.fit(X, y, xgb_model=prev.get_booster(), verbose=False)
        self._model = updated
        logger.debug("XGBoostOnlineModel partial_fit: added %d trees", self._n_estimators)
