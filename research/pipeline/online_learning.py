# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/online_learning.py
=======================================
Incremental / online learning layer.

Extends the existing ml/online_learner.py (EWC + replay for neural nets) with:
  1. IncrementalXGBoost  — XGBoost trained in chunks via `xgb_model` warm-start
  2. OnlineEnsemble      — combines IncrementalXGBoost + the deep OnlineLearner
  3. DriftDetector       — Page-Hinkley test to flag concept drift
  4. ADWINDriftDetector  — Adaptive Windowing (ADWIN) for more sensitive drift
  5. AdaptiveBlendWeights — online update of primary/online blend weights based
                            on recent accuracy of each model
  6. OnlineLearnerStore  — production store with persistence and warm-start

Design principles
-----------------
- No full re-train on every new bar: too slow for live trading.
- Warm-start XGBoost: pass the previous booster as `xgb_model` to `train()`.
  Each call adds `n_new_rounds` trees on top of the existing forest.
- The deep model (from ml/online_learner.py) uses EWC + experience replay to
  update weights without catastrophic forgetting.
- DriftDetector monitors prediction error; when drift is detected it signals
  the orchestrator to trigger a partial re-train on a recent window.
- AdaptiveBlendWeights tracks rolling accuracy of primary vs online model and
  shifts blend weights toward the better-performing model.

Usage
-----
    from research.pipeline.online_learning import IncrementalXGBoost, DriftDetector

    model = IncrementalXGBoost(n_base_rounds=300, n_new_rounds=20)
    model.fit(X_train, y_train)                    # initial fit

    # Live loop
    for X_new, y_new in stream:
        model.update(X_new, y_new)                 # incremental update
        preds = model.predict_proba(X_new)
        drift = detector.update(y_new, preds)
        if drift:
            model.reset_and_refit(X_recent, y_recent)
"""

from __future__ import annotations

import logging
import pickle  # nosec B403 - joblib tried first; pickle only for legacy fallback
import threading
from collections import deque
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb

    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("xgboost not installed — IncrementalXGBoost unavailable")

# Import existing EWC-based online learner
try:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    DEEP_ONLINE_AVAILABLE = True
except Exception:
    DEEP_ONLINE_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Page-Hinkley drift detector
# ─────────────────────────────────────────────────────────────────────────────


class DriftDetector:
    """
    Page-Hinkley test for concept drift detection.

    Monitors the running mean of prediction errors.  When the cumulative
    deviation exceeds a threshold, drift is flagged.

    Parameters
    ----------
    delta     : Minimum acceptable mean shift (sensitivity)
    threshold : Detection threshold λ — higher = less sensitive
    alpha     : Forgetting factor for running mean (0 = no forgetting)
    """

    def __init__(self, delta: float = 0.005, threshold: float = 50.0, alpha: float = 0.01):
        self.delta = delta
        self.threshold = threshold
        self.alpha = alpha
        self._mean: float = 0.0
        self._sum: float = 0.0
        self._min_sum: float = 0.0
        self._n: int = 0
        self.drift_count: int = 0
        self._error_history: deque[float] = deque(maxlen=1000)

    def update(self, y_true: np.ndarray, y_prob: np.ndarray) -> bool:
        """
        Feed new predictions and return True if drift is detected.

        Parameters
        ----------
        y_true : Ground-truth binary labels
        y_prob : Predicted probabilities
        """
        # Use log-loss as the error signal
        eps = 1e-7
        y_prob = np.clip(y_prob, eps, 1 - eps)
        errors = -(y_true * np.log(y_prob) + (1 - y_true) * np.log(1 - y_prob))
        mean_error = float(errors.mean())
        self._error_history.append(mean_error)

        # Update running mean with forgetting
        self._mean = (1 - self.alpha) * self._mean + self.alpha * mean_error
        self._n += 1

        # Page-Hinkley statistic
        self._sum += mean_error - self._mean - self.delta
        self._min_sum = min(self._min_sum, self._sum)

        ph_stat = self._sum - self._min_sum

        if ph_stat > self.threshold:
            self.drift_count += 1
            self._reset_stat()
            logger.warning(
                "Concept drift detected (count=%d)  PH=%.2f  mean_error=%.4f",
                self.drift_count,
                ph_stat,
                mean_error,
            )
            return True
        return False

    def _reset_stat(self) -> None:
        self._sum = 0.0
        self._min_sum = 0.0

    def reset(self) -> None:
        """Full reset — call after re-training."""
        self._mean = 0.0
        self._sum = 0.0
        self._min_sum = 0.0
        self._n = 0

    @property
    def recent_error(self) -> float:
        if not self._error_history:
            return 0.0
        return float(np.mean(list(self._error_history)[-20:]))


# ─────────────────────────────────────────────────────────────────────────────
# ADWIN drift detector
# ─────────────────────────────────────────────────────────────────────────────


class ADWINDriftDetector:
    """
    Adaptive Windowing (ADWIN) drift detector.

    ADWIN maintains a variable-length window of recent error values and
    detects drift by testing whether the mean of any sub-window differs
    significantly from the rest.  It is more sensitive than Page-Hinkley
    for gradual drift and automatically adjusts its window size.

    This is a lightweight pure-Python implementation suitable for the
    fill rates seen in live trading (not a streaming big-data scenario).

    Parameters
    ----------
    delta       : Confidence parameter — smaller = more sensitive (default 0.002).
    max_buckets : Maximum number of exponential histogram buckets.
    """

    def __init__(self, delta: float = 0.002, max_buckets: int = 5) -> None:
        self.delta = delta
        self.max_buckets = max_buckets
        self._window: deque[float] = deque()
        self._total: float = 0.0
        self._n: int = 0
        self.drift_count: int = 0

    def update(self, error: float) -> bool:
        """
        Add one error observation and return True if drift is detected.

        Parameters
        ----------
        error : Scalar prediction error for the latest observation.
        """
        self._window.append(error)
        self._total += error
        self._n += 1

        # Limit window to avoid O(n²) scan on very long runs
        if self._n > 2000:  # noqa: PLR2004
            removed = self._window.popleft()
            self._total -= removed
            self._n -= 1

        return self._detect_change()

    def _detect_change(self) -> bool:
        """
        Scan all cut-points in the window for a significant mean shift.
        Uses Hoeffding bound: |μ₀ - μ₁| > ε_cut → drift.
        """
        if self._n < 30:  # noqa: PLR2004
            return False

        window = list(self._window)
        n = len(window)
        total = self._total

        cumsum = 0.0
        for i in range(1, n):
            cumsum += window[i - 1]
            n0, n1 = i, n - i
            mu0 = cumsum / n0
            mu1 = (total - cumsum) / n1

            # Hoeffding bound for the cut-point
            m = 1.0 / (1.0 / n0 + 1.0 / n1)
            epsilon_cut = np.sqrt(np.log(2.0 / self.delta) / (2.0 * m))

            if abs(mu0 - mu1) >= epsilon_cut:
                self.drift_count += 1
                # Discard the older half of the window
                for _ in range(i):
                    removed = self._window.popleft()
                    self._total -= removed
                    self._n -= 1
                logger.warning(
                    "ADWIN drift detected (count=%d): |μ₀-μ₁|=%.4f ε=%.4f",
                    self.drift_count,
                    abs(mu0 - mu1),
                    epsilon_cut,
                )
                return True
        return False

    def reset(self) -> None:
        """Full reset — call after re-training."""
        self._window.clear()
        self._total = 0.0
        self._n = 0

    @property
    def window_size(self) -> int:
        return self._n

    @property
    def mean_error(self) -> float:
        if self._n == 0:
            return 0.0
        return self._total / self._n


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive blend weights
# ─────────────────────────────────────────────────────────────────────────────


class AdaptiveBlendWeights:
    """
    Online update of primary/online blend weights based on recent accuracy.

    Tracks rolling accuracy of the primary model and the online learner
    separately.  Shifts blend weights toward the better-performing model
    using exponential moving average updates.

    The weights are constrained to [min_weight, max_weight] to prevent
    the online learner from dominating before it has enough data.

    Parameters
    ----------
    initial_primary : Starting weight for the primary model (default 0.7).
    learning_rate   : EMA learning rate for weight updates (default 0.05).
    min_primary     : Minimum weight for the primary model (default 0.5).
    max_primary     : Maximum weight for the primary model (default 0.95).
    window          : Rolling window for accuracy tracking (default 50).
    """

    def __init__(
        self,
        initial_primary: float = 0.7,
        learning_rate: float = 0.05,
        min_primary: float = 0.5,
        max_primary: float = 0.95,
        window: int = 50,
    ) -> None:
        self._primary_weight = float(np.clip(initial_primary, min_primary, max_primary))
        self.learning_rate = learning_rate
        self.min_primary = min_primary
        self.max_primary = max_primary
        self._primary_correct: deque[float] = deque(maxlen=window)
        self._online_correct: deque[float] = deque(maxlen=window)

    def update(
        self,
        label: int,
        primary_prob: float,
        online_prob: float,
    ) -> None:
        """
        Update blend weights based on which model was more accurate.

        Parameters
        ----------
        label        : True binary label (0 or 1).
        primary_prob : Primary model probability.
        online_prob  : Online learner probability.
        """
        primary_correct = float(int(round(primary_prob)) == label)
        online_correct = float(int(round(online_prob)) == label)

        self._primary_correct.append(primary_correct)
        self._online_correct.append(online_correct)

        if len(self._primary_correct) < 10:  # noqa: PLR2004
            return  # not enough data yet

        primary_acc = float(np.mean(self._primary_correct))
        online_acc = float(np.mean(self._online_correct))

        # Shift weight toward the better model
        if primary_acc > online_acc:
            target = self._primary_weight + self.learning_rate * (primary_acc - online_acc)
        else:
            target = self._primary_weight - self.learning_rate * (online_acc - primary_acc)

        self._primary_weight = float(np.clip(target, self.min_primary, self.max_primary))

    @property
    def primary_weight(self) -> float:
        return self._primary_weight

    @property
    def online_weight(self) -> float:
        return 1.0 - self._primary_weight

    def status(self) -> dict:
        return {
            "primary_weight": round(self._primary_weight, 4),
            "online_weight": round(self.online_weight, 4),
            "primary_acc": round(
                float(np.mean(self._primary_correct)) if self._primary_correct else 0.0,
                4,
            ),
            "online_acc": round(float(np.mean(self._online_correct)) if self._online_correct else 0.0, 4),
            "n_samples": len(self._primary_correct),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Incremental XGBoost
# ─────────────────────────────────────────────────────────────────────────────


class IncrementalXGBoost:
    """
    XGBoost with warm-start incremental updates.

    Each call to `update()` adds `n_new_rounds` trees to the existing booster
    without re-training from scratch.  A sliding replay buffer ensures the
    model doesn't forget older patterns entirely.

    Parameters
    ----------
    n_base_rounds   : Trees in the initial full fit
    n_new_rounds    : Trees added per incremental update
    buffer_size     : Max samples kept in the replay buffer
    feature_cols    : Column names (set automatically on first fit)
    """

    def __init__(
        self,
        n_base_rounds: int = 300,
        n_new_rounds: int = 20,
        buffer_size: int = 5000,
        xgb_params: dict | None = None,
    ):
        if not XGB_AVAILABLE:
            raise RuntimeError("xgboost required for IncrementalXGBoost")

        self.n_base_rounds = n_base_rounds
        self.n_new_rounds = n_new_rounds
        self.buffer_size = buffer_size
        self.xgb_params = xgb_params or {
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": -1,
        }

        self._booster: xgb.Booster | None = None
        self._scaler = StandardScaler()
        self._feature_cols: list[str] | None = None
        self._replay_X: deque[np.ndarray] = deque(maxlen=buffer_size)
        self._replay_y: deque[float] = deque(maxlen=buffer_size)
        self._update_count: int = 0

    # ── Initial fit ───────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> IncrementalXGBoost:
        """Full initial training."""
        self._feature_cols = list(X.columns)
        X_sc = self._scaler.fit_transform(X)

        dtrain = xgb.DMatrix(X_sc, label=y, feature_names=self._feature_cols)
        self._booster = xgb.train(
            self.xgb_params,
            dtrain,
            num_boost_round=self.n_base_rounds,
            verbose_eval=False,
        )

        # Seed replay buffer
        for i in range(len(X_sc)):
            self._replay_X.append(X_sc[i])
            self._replay_y.append(float(y[i]))

        logger.info(
            "IncrementalXGBoost initial fit: %d samples, %d trees",
            len(y),
            self.n_base_rounds,
        )
        return self

    # ── Incremental update ────────────────────────────────────────────────────

    def update(self, X: pd.DataFrame, y: np.ndarray) -> IncrementalXGBoost:
        """
        Add new data and grow the booster by `n_new_rounds` trees.

        Combines new data with a random sample from the replay buffer to
        prevent catastrophic forgetting of older patterns.
        """
        if self._booster is None:
            raise RuntimeError("Call fit() before update()")

        X_sc = self._scaler.transform(X[self._feature_cols])

        # Add to replay buffer
        for i in range(len(X_sc)):
            self._replay_X.append(X_sc[i])
            self._replay_y.append(float(y[i]))

        # Sample from replay buffer
        buf_size = len(self._replay_X)
        n_replay = min(buf_size, max(len(X_sc) * 4, 256))
        idx = np.random.choice(buf_size, n_replay, replace=False)
        X_replay = np.stack([self._replay_X[i] for i in idx])
        y_replay = np.array([self._replay_y[i] for i in idx])

        # Combine new + replay
        X_combined = np.vstack([X_sc, X_replay])
        y_combined = np.concatenate([y, y_replay])

        dtrain = xgb.DMatrix(X_combined, label=y_combined, feature_names=self._feature_cols)
        self._booster = xgb.train(
            self.xgb_params,
            dtrain,
            num_boost_round=self.n_new_rounds,
            xgb_model=self._booster,  # warm-start: append trees
            verbose_eval=False,
        )

        self._update_count += 1
        logger.debug(
            "IncrementalXGBoost update #%d: +%d trees  total_trees=%d",
            self._update_count,
            self.n_new_rounds,
            self._booster.num_boosted_rounds(),
        )
        return self

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self._booster is None:
            raise RuntimeError("Model not fitted")
        X_sc = self._scaler.transform(X[self._feature_cols])
        dmat = xgb.DMatrix(X_sc, feature_names=self._feature_cols)
        return self._booster.predict(dmat)

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)

    # ── Reset + refit ─────────────────────────────────────────────────────────

    def reset_and_refit(self, X: pd.DataFrame, y: np.ndarray) -> IncrementalXGBoost:
        """
        Full re-train on a recent window (called after drift detection).
        Preserves the scaler fit from the original training data.
        """
        logger.info("IncrementalXGBoost: full re-train on %d samples after drift", len(y))
        X_sc = self._scaler.transform(X[self._feature_cols])
        dtrain = xgb.DMatrix(X_sc, label=y, feature_names=self._feature_cols)
        self._booster = xgb.train(
            self.xgb_params,
            dtrain,
            num_boost_round=self.n_base_rounds,
            verbose_eval=False,
        )
        self._replay_X.clear()
        self._replay_y.clear()
        for i in range(len(X_sc)):
            self._replay_X.append(X_sc[i])
            self._replay_y.append(float(y[i]))
        return self

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path, compress=3)
        logger.info("IncrementalXGBoost saved → %s", path)

    @classmethod
    def load(cls, path: str | Path) -> IncrementalXGBoost:
        try:
            obj = joblib.load(path)  # nosec B301 - path set by class constructor from saved_models
        except Exception:
            with open(path, "rb") as f:
                obj = pickle.load(f)  # nosec B301 - joblib failed; legacy pickle fallback
        logger.info("IncrementalXGBoost loaded ← %s", path)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# Online ensemble: incremental XGB + deep EWC model
# ─────────────────────────────────────────────────────────────────────────────


class OnlineEnsemble:
    """
    Live-updating ensemble combining IncrementalXGBoost and the EWC deep model.

    The blend weight is updated online using a simple exponential moving
    average of each model's recent accuracy.

    Parameters
    ----------
    xgb_model   : Pre-fitted IncrementalXGBoost
    deep_model  : Pre-fitted OnlineLearner (from ml/online_learner.py)
    init_weight : Initial weight for XGBoost (0–1); deep gets 1 - init_weight
    ema_alpha   : EMA decay for weight updates
    """

    def __init__(
        self,
        xgb_model: IncrementalXGBoost,
        deep_model=None,
        init_weight: float = 0.5,
        ema_alpha: float = 0.05,
    ):
        self.xgb = xgb_model
        self.deep = deep_model
        self.w_xgb = init_weight
        self.ema_alpha = ema_alpha
        self.drift_detector = DriftDetector()
        self._xgb_acc_ema: float = 0.5
        self._deep_acc_ema: float = 0.5

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        xgb_prob = self.xgb.predict_proba(X)
        if self.deep is not None:
            try:
                import torch

                X_arr = X.values.astype(np.float32)
                # Deep model expects (batch, seq, features) — use last bar only
                X_t = torch.tensor(X_arr).unsqueeze(1)
                self.deep.model.eval()
                with torch.no_grad():
                    deep_prob = self.deep.model(X_t).cpu().numpy().squeeze()
                return self.w_xgb * xgb_prob + (1 - self.w_xgb) * deep_prob
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        return xgb_prob

    def update(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        X_arr: np.ndarray | None = None,
    ) -> bool:
        """
        Incremental update. Returns True if drift was detected.

        Parameters
        ----------
        X     : Feature DataFrame for XGBoost update
        y     : Ground-truth labels
        X_arr : Numpy array for deep model update (optional)
        """
        # Update XGBoost
        self.xgb.update(X, y)

        # Update deep model
        if self.deep is not None and X_arr is not None:
            try:
                self.deep.train_step((X_arr, y))
            except Exception as exc:
                logger.debug("Deep online update failed: %s", exc)

        # Update blend weights based on recent accuracy
        xgb_prob = self.xgb.predict_proba(X)
        xgb_acc = float(((xgb_prob > 0.5).astype(int) == y).mean())  # noqa: PLR2004
        self._xgb_acc_ema = (1 - self.ema_alpha) * self._xgb_acc_ema + self.ema_alpha * xgb_acc

        total = self._xgb_acc_ema + self._deep_acc_ema
        self.w_xgb = self._xgb_acc_ema / total if total > 0 else 0.5

        # Check for drift
        return self.drift_detector.update(y, xgb_prob)


# ─────────────────────────────────────────────────────────────────────────────
# OnlineLearnerStore — production live-inference store for signal engine
# ─────────────────────────────────────────────────────────────────────────────


class OnlineLearnerStore:
    """
    Production online learning store for the signal engine (Phase 3).

    Maintains an IncrementalXGBoost that updates its weights on each confirmed
    fill.  At inference time, its probability is blended with the primary model:

        final_prob = primary_weight * advanced_prob + online_weight * online_prob

    Default blend: 0.7 * advanced + 0.3 * online (spec-defined).

    The online learner starts in a "warming up" state and only contributes to
    the blend after `min_fills` confirmed fills have been processed.

    Drift detection: both Page-Hinkley and ADWIN detectors run in parallel.
    Either firing triggers a reset and refit on the recent fill buffer.

    Adaptive weights: when `adaptive_weights=True`, blend weights shift toward
    the better-performing model based on rolling accuracy.

    Persistence: when `persist_path` is set, the fitted model is saved after
    each refit and loaded on startup for warm-start.

    Parameters
    ----------
    primary_weight   : Starting weight for the primary model (default 0.7).
    online_weight    : Starting weight for the online learner (default 0.3).
    min_fills        : Minimum fills before the online learner contributes.
    buffer_size      : Max fills kept in the replay buffer.
    adaptive_weights : Shift blend weights based on rolling accuracy.
    use_adwin        : Use ADWIN in addition to Page-Hinkley for drift detection.
    persist_path     : Path to save/load the fitted model for warm-start.
    """

    PRIMARY_WEIGHT: float = 0.7
    ONLINE_WEIGHT: float = 0.3

    def __init__(
        self,
        primary_weight: float = 0.7,
        online_weight: float = 0.3,
        min_fills: int = 20,
        buffer_size: int = 500,
        adaptive_weights: bool = True,
        use_adwin: bool = True,
        persist_path: str | None = None,
    ) -> None:
        # Normalise weights to sum to 1
        total = primary_weight + online_weight
        self.primary_weight = primary_weight / total
        self.online_weight = online_weight / total

        self.min_fills = min_fills
        self.adaptive_weights = adaptive_weights
        self.persist_path = Path(persist_path) if persist_path else None

        self._model: IncrementalXGBoost | None = None
        self._ph_detector = DriftDetector()
        self._adwin_detector = ADWINDriftDetector() if use_adwin else None
        self._blend_weights = (
            AdaptiveBlendWeights(
                initial_primary=self.primary_weight,
            )
            if adaptive_weights
            else None
        )

        self._fill_buffer_X: deque[np.ndarray] = deque(maxlen=buffer_size)
        self._fill_buffer_y: deque[float] = deque(maxlen=buffer_size)
        self._fill_count: int = 0
        self._ready: bool = False
        self._lock = threading.Lock()

        # Warm-start from persisted model
        if self.persist_path and self.persist_path.exists():
            self._load_persisted()

    # ── Effective blend weights (adaptive or fixed) ───────────────────────────

    @property
    def _effective_primary_weight(self) -> float:
        if self._blend_weights is not None:
            return self._blend_weights.primary_weight
        return self.primary_weight

    @property
    def _effective_online_weight(self) -> float:
        return 1.0 - self._effective_primary_weight

    # ── Warm-up check ─────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True when the online learner has enough fills to contribute."""
        return self._ready and self._model is not None

    # ── On confirmed fill ─────────────────────────────────────────────────────

    def on_fill(
        self,
        features: pd.DataFrame,
        label: int,
        primary_prob: float | None = None,
    ) -> bool:
        """
        Update the online learner with a confirmed fill.

        Parameters
        ----------
        features     : Feature DataFrame for the filled bar.
        label        : 1 if the trade was profitable, 0 otherwise.
        primary_prob : Primary model probability at fill time (for adaptive weights).

        Returns
        -------
        drift_detected : True if concept drift was detected and model was reset.
        """
        if not XGB_AVAILABLE:
            return False

        with self._lock:
            y = np.array([float(label)])
            feat_row = features.values[0] if len(features) > 0 else np.zeros(1)
            self._fill_buffer_X.append(feat_row.copy())
            self._fill_buffer_y.append(float(label))
            self._fill_count += 1

            # Initial fit once we have enough fills
            if self._model is None and self._fill_count >= self.min_fills:
                self._initial_fit()
                return False

            if self._model is None:
                return False

            # Incremental update
            try:
                self._model.update(features, y)
            except Exception as exc:
                logger.debug("OnlineLearnerStore.on_fill update failed: %s", exc)
                return False

            # Drift detection (Page-Hinkley + ADWIN)
            drift = False
            try:
                proba = self._model.predict_proba(features)
                online_prob = float(proba[0])

                # Page-Hinkley
                drift = self._ph_detector.update(y, proba)

                # ADWIN (log-loss error)
                if self._adwin_detector is not None and not drift:
                    eps = 1e-7
                    p = float(np.clip(online_prob, eps, 1 - eps))
                    logloss = -(label * np.log(p) + (1 - label) * np.log(1 - p))
                    drift = self._adwin_detector.update(logloss)

                # Adaptive weight update
                if self._blend_weights is not None and primary_prob is not None:
                    self._blend_weights.update(label, primary_prob, online_prob)

            except Exception as exc:
                logger.debug("OnlineLearnerStore drift check failed: %s", exc)

            if drift:
                logger.warning(
                    "OnlineLearnerStore: drift detected after %d fills — resetting",
                    self._fill_count,
                )
                self._reset_and_refit()
                return True

            return False

    def _initial_fit(self) -> None:
        """Fit the online learner on the accumulated fill buffer."""
        try:
            X = np.array(list(self._fill_buffer_X))
            y = np.array(list(self._fill_buffer_y))
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            cols = [f"f{i}" for i in range(X.shape[1])]
            X_df = pd.DataFrame(X, columns=cols)
            self._model = IncrementalXGBoost(n_base_rounds=100, n_new_rounds=10)
            self._model.fit(X_df, y)
            self._ready = True
            logger.info("OnlineLearnerStore: initial fit on %d fills", len(y))
            self._save_persisted()
        except Exception as exc:
            logger.warning("OnlineLearnerStore initial fit failed: %s", exc)

    def _reset_and_refit(self) -> None:
        """Reset after drift and refit on recent buffer."""
        try:
            X = np.array(list(self._fill_buffer_X))
            y = np.array(list(self._fill_buffer_y))
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            cols = [f"f{i}" for i in range(X.shape[1])]
            X_df = pd.DataFrame(X, columns=cols)
            if self._model is not None:
                self._model.reset_and_refit(X_df, y)
            self._ph_detector.reset()
            if self._adwin_detector is not None:
                self._adwin_detector.reset()
            logger.info("OnlineLearnerStore: reset and refit on %d fills", len(y))
            self._save_persisted()
        except Exception as exc:
            logger.warning("OnlineLearnerStore reset_and_refit failed: %s", exc)

    # ── Inference ─────────────────────────────────────────────────────────────

    def blend(
        self,
        advanced_prob: float,
        features: pd.DataFrame,
    ) -> float:
        """
        Blend the primary model probability with the online learner.

        Returns advanced_prob unchanged when the online learner is not ready.

        Parameters
        ----------
        advanced_prob : Probability from the primary model (advanced_oos.pkl).
        features      : Feature DataFrame for the current bar.

        Returns
        -------
        blended_prob : primary_weight * advanced_prob + online_weight * online_prob
        """
        if not self.is_ready or self._model is None:
            return advanced_prob

        try:
            # Align feature columns to what the online model was trained on
            n_cols = len(self._fill_buffer_X[0]) if self._fill_buffer_X else 0
            if n_cols == 0:
                return advanced_prob

            cols = [f"f{i}" for i in range(n_cols)]
            feat_arr = features.values
            if feat_arr.shape[1] >= n_cols:
                X_df = pd.DataFrame(feat_arr[:, :n_cols], columns=cols)
            else:
                pad = np.zeros((feat_arr.shape[0], n_cols - feat_arr.shape[1]))
                X_df = pd.DataFrame(np.hstack([feat_arr, pad]), columns=cols)

            online_prob = float(self._model.predict_proba(X_df)[0])
            pw = self._effective_primary_weight
            ow = self._effective_online_weight
            blended = pw * advanced_prob + ow * online_prob
            logger.debug(
                "OnlineLearner blend: adv=%.4f online=%.4f w=[%.2f,%.2f] → %.4f",
                advanced_prob,
                online_prob,
                pw,
                ow,
                blended,
            )
            return float(np.clip(blended, 0.0, 1.0))
        except Exception as exc:
            logger.debug("OnlineLearnerStore.blend failed (non-fatal): %s", exc)
            return advanced_prob

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_persisted(self) -> None:
        if self.persist_path is None or self._model is None:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._model.save(self.persist_path)
            logger.debug("OnlineLearnerStore: model saved → %s", self.persist_path)
        except Exception as exc:
            logger.debug("OnlineLearnerStore persist save failed: %s", exc)

    def _load_persisted(self) -> None:
        if self.persist_path is None:
            return
        try:
            self._model = IncrementalXGBoost.load(self.persist_path)
            self._ready = True
            logger.info("OnlineLearnerStore: warm-started from %s", self.persist_path)
        except Exception as exc:
            logger.debug("OnlineLearnerStore warm-start failed: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    @property
    def fill_count(self) -> int:
        return self._fill_count

    @property
    def drift_count(self) -> int:
        ph = self._ph_detector.drift_count
        adwin = self._adwin_detector.drift_count if self._adwin_detector else 0
        return ph + adwin

    def status(self) -> dict:
        blend_status = self._blend_weights.status() if self._blend_weights else {}
        return {
            "ready": self.is_ready,
            "fill_count": self._fill_count,
            "ph_drift_count": self._ph_detector.drift_count,
            "adwin_drift_count": self._adwin_detector.drift_count if self._adwin_detector else 0,
            "recent_error": self._ph_detector.recent_error,
            "primary_weight": round(self._effective_primary_weight, 4),
            "online_weight": round(self._effective_online_weight, 4),
            "adaptive_weights": self.adaptive_weights,
            "blend_weights": blend_status,
            "adwin_window": self._adwin_detector.window_size if self._adwin_detector else 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton factory
# ─────────────────────────────────────────────────────────────────────────────

_store_registry: dict[str, OnlineLearnerStore] = {}
_registry_lock = threading.Lock()


def get_online_learner(
    symbol: str = "XAUUSD",
    persist_path: Path | None = None,
    primary_weight: float = 0.7,
    online_weight: float = 0.3,
    min_fills: int = 20,
    adaptive_weights: bool = True,
) -> OnlineLearnerStore:
    """
    Return (or create) the singleton ``OnlineLearnerStore`` for *symbol*.

    This is the canonical factory used by ``ml/inference_engine.py`` and any
    other module that needs to interact with the Phase-3 online learner.

    Parameters
    ----------
    symbol:
        Trading symbol key (e.g. ``"XAUUSD"``).  One store per symbol.
    persist_path:
        Where to save/load the incremental XGBoost model.  Defaults to
        ``ml/saved_models/online_{symbol.lower()}.pkl``.
    primary_weight / online_weight:
        Initial blend weights (must sum to 1.0).
    min_fills:
        Minimum confirmed fills before the online model contributes to blending.
    adaptive_weights:
        When True, blend weights shift toward the better-performing model.

    Returns
    -------
    OnlineLearnerStore singleton for *symbol*.
    """
    key = symbol.upper()
    with _registry_lock:
        if key not in _store_registry:
            if persist_path is None:
                persist_path = Path("ml/saved_models") / f"online_{key.lower()}.pkl"
            store = OnlineLearnerStore(
                primary_weight=primary_weight,
                online_weight=online_weight,
                min_fills=min_fills,
                adaptive_weights=adaptive_weights,
                persist_path=persist_path,
            )
            _store_registry[key] = store
            logger.info("OnlineLearnerStore created for symbol=%s persist=%s", key, persist_path)
        return _store_registry[key]


def reset_online_learner(symbol: str = "XAUUSD") -> bool:
    """
    Remove the singleton for *symbol* from the registry so the next call to
    ``get_online_learner()`` creates a fresh instance.

    Returns True if a store was removed, False if none existed.
    """
    key = symbol.upper()
    with _registry_lock:
        if key in _store_registry:
            del _store_registry[key]
            logger.info("OnlineLearnerStore reset for symbol=%s", key)
            return True
        return False


def list_online_learners() -> dict[str, dict]:
    """Return status snapshots for all registered online learner stores."""
    with _registry_lock:
        return {sym: store.status() for sym, store in _store_registry.items()}
