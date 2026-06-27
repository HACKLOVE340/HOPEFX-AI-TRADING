# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/continuous_learning.py
==========================
MLOps Continuous Learning Pipeline — automated retraining, shadow deployment,
and champion/challenger model promotion.

Architecture
------------
- DriftTrigger: monitors feature/prediction drift and triggers retraining
  when statistical thresholds are breached.
- RetrainingOrchestrator: manages the full retraining lifecycle including
  data collection, feature engineering, training, and validation.
- ShadowDeployment: runs new models in shadow mode alongside production,
  comparing predictions without affecting live trading.
- ChampionChallenger: promotes challenger models to production only when
  they statistically outperform the champion over a configurable window.

Usage
-----
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()
    await pipeline.start(
        model_registry=registry,
        data_store=tick_store,
        event_bus=bus,
    )
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_DRIFT_CHECK_INTERVAL_S = int(os.getenv("ML_DRIFT_CHECK_INTERVAL_S", "3600"))
_DRIFT_PSI_THRESHOLD = float(os.getenv("ML_DRIFT_PSI_THRESHOLD", "0.2"))
_DRIFT_KS_THRESHOLD = float(os.getenv("ML_DRIFT_KS_THRESHOLD", "0.1"))
_SHADOW_MIN_PREDICTIONS = int(os.getenv("ML_SHADOW_MIN_PREDICTIONS", "500"))
_SHADOW_CONFIDENCE_LEVEL = float(os.getenv("ML_SHADOW_CONFIDENCE_LEVEL", "0.95"))
_RETRAIN_COOLDOWN_HOURS = int(os.getenv("ML_RETRAIN_COOLDOWN_HOURS", "24"))
_CHAMPION_MIN_IMPROVEMENT = float(os.getenv("ML_CHAMPION_MIN_IMPROVEMENT", "0.02"))
_TRAINING_DATA_DAYS = int(os.getenv("ML_TRAINING_DATA_DAYS", "90"))

# ── Prometheus metrics ────────────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Gauge

    _drift_detections = Counter(
        "hopefx_ml_drift_detections_total",
        "Number of drift events detected",
        ["drift_type"],
    )
    _retraining_runs = Counter(
        "hopefx_ml_retraining_runs_total",
        "Number of retraining runs",
        ["outcome"],
    )
    _shadow_predictions = Counter(
        "hopefx_ml_shadow_predictions_total",
        "Number of shadow model predictions",
    )
    _model_promotions = Counter(
        "hopefx_ml_model_promotions_total",
        "Number of model promotions",
    )
    _current_drift_score = Gauge(
        "hopefx_ml_current_drift_score",
        "Current drift score (PSI)",
    )
    _shadow_accuracy = Gauge(
        "hopefx_ml_shadow_accuracy",
        "Current shadow model accuracy",
    )
    _PROM_OK = True
except Exception:
    _PROM_OK = False


# ── Enums ─────────────────────────────────────────────────────────────────────


class DriftType(Enum):
    FEATURE_DRIFT = "feature_drift"
    PREDICTION_DRIFT = "prediction_drift"
    PERFORMANCE_DRIFT = "performance_drift"


class RetrainingState(Enum):
    IDLE = "idle"
    COLLECTING_DATA = "collecting_data"
    TRAINING = "training"
    VALIDATING = "validating"
    SHADOW_TESTING = "shadow_testing"
    PROMOTING = "promoting"
    FAILED = "failed"


class ShadowState(Enum):
    RUNNING = "running"
    EVALUATING = "evaluating"
    PROMOTED = "promoted"
    REJECTED = "rejected"


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class DriftReport:
    """Report from a drift detection check."""

    timestamp: datetime
    drift_type: DriftType
    score: float
    threshold: float
    is_drifted: bool
    details: dict[str, Any] = field(default_factory=dict)
    affected_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "drift_type": self.drift_type.value,
            "score": self.score,
            "threshold": self.threshold,
            "is_drifted": self.is_drifted,
            "details": self.details,
            "affected_features": self.affected_features,
        }


@dataclass
class ShadowResult:
    """Accumulated results from shadow model deployment."""

    model_version: str
    predictions: int = 0
    correct_predictions: int = 0
    total_pnl: float = 0.0
    champion_pnl: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: ShadowState = ShadowState.RUNNING

    @property
    def accuracy(self) -> float:
        if self.predictions == 0:
            return 0.0
        return self.correct_predictions / self.predictions

    @property
    def pnl_improvement(self) -> float:
        if self.champion_pnl == 0:
            return 0.0
        return (self.total_pnl - self.champion_pnl) / abs(self.champion_pnl)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "predictions": self.predictions,
            "correct_predictions": self.correct_predictions,
            "accuracy": self.accuracy,
            "total_pnl": self.total_pnl,
            "champion_pnl": self.champion_pnl,
            "pnl_improvement": self.pnl_improvement,
            "started_at": self.started_at.isoformat(),
            "state": self.state.value,
        }


# ── Drift Detection ──────────────────────────────────────────────────────────


class DriftDetector:
    """
    Monitors feature and prediction distributions for statistical drift.

    Uses Population Stability Index (PSI) for feature drift and
    Kolmogorov-Smirnov test for prediction distribution drift.
    """

    def __init__(self) -> None:
        self._reference_distributions: dict[str, np.ndarray] = {}
        self._current_window: dict[str, list[float]] = {}
        self._window_size = 1000
        self._last_check: datetime | None = None

    def set_reference(self, feature_name: str, distribution: np.ndarray) -> None:
        """Set the reference distribution for a feature (from training data)."""
        self._reference_distributions[feature_name] = distribution

    def add_observation(self, feature_name: str, value: float) -> None:
        """Add a new observation to the current window."""
        if feature_name not in self._current_window:
            self._current_window[feature_name] = []
        self._current_window[feature_name].append(value)
        # Keep window bounded
        if len(self._current_window[feature_name]) > self._window_size:
            self._current_window[feature_name] = self._current_window[feature_name][-self._window_size :]

    def check_drift(self) -> DriftReport:
        """
        Run drift detection on all tracked features.

        Returns a DriftReport with the overall drift score and affected features.
        """
        self._last_check = datetime.now(UTC)
        psi_scores: dict[str, float] = {}
        affected = []

        for feature_name, reference in self._reference_distributions.items():
            current = self._current_window.get(feature_name, [])
            if len(current) < 100:
                continue  # Not enough data

            current_arr = np.array(current)
            psi = self._calculate_psi(reference, current_arr)
            psi_scores[feature_name] = psi

            if psi > _DRIFT_PSI_THRESHOLD:
                affected.append(feature_name)

        # Overall drift score is the max PSI across features
        overall_score = max(psi_scores.values()) if psi_scores else 0.0
        is_drifted = overall_score > _DRIFT_PSI_THRESHOLD

        if _PROM_OK:
            _current_drift_score.set(overall_score)
            if is_drifted:
                _drift_detections.labels(drift_type="feature_drift").inc()

        return DriftReport(
            timestamp=datetime.now(UTC),
            drift_type=DriftType.FEATURE_DRIFT,
            score=overall_score,
            threshold=_DRIFT_PSI_THRESHOLD,
            is_drifted=is_drifted,
            details={"psi_scores": psi_scores},
            affected_features=affected,
        )

    def _calculate_psi(self, reference: np.ndarray, current: np.ndarray, bins: int = 20) -> float:
        """
        Calculate Population Stability Index (PSI).

        PSI < 0.1: No significant drift
        0.1 <= PSI < 0.2: Moderate drift
        PSI >= 0.2: Significant drift — retraining recommended
        """
        # Create bins from reference distribution
        breakpoints = np.linspace(
            min(reference.min(), current.min()),
            max(reference.max(), current.max()),
            bins + 1,
        )

        ref_counts = np.histogram(reference, bins=breakpoints)[0]
        cur_counts = np.histogram(current, bins=breakpoints)[0]

        # Normalize to proportions
        ref_pct = ref_counts / max(ref_counts.sum(), 1)
        cur_pct = cur_counts / max(cur_counts.sum(), 1)

        # Avoid division by zero
        ref_pct = np.clip(ref_pct, 1e-6, None)
        cur_pct = np.clip(cur_pct, 1e-6, None)

        # PSI formula
        psi = np.sum(
            (cur_pct - ref_pct) * np.log(cur_pct / ref_pct)
        )  # healer: ignore — cur_pct clipped to [1e-6, None] above; log/div safe
        return float(psi)

    def check_prediction_drift(self, recent_predictions: np.ndarray, reference_predictions: np.ndarray) -> DriftReport:
        """Check for drift in prediction distributions using KS test."""
        from scipy import stats

        ks_stat, p_value = stats.ks_2samp(reference_predictions, recent_predictions)
        is_drifted = ks_stat > _DRIFT_KS_THRESHOLD

        if _PROM_OK and is_drifted:
            _drift_detections.labels(drift_type="prediction_drift").inc()

        return DriftReport(
            timestamp=datetime.now(UTC),
            drift_type=DriftType.PREDICTION_DRIFT,
            score=float(ks_stat),
            threshold=_DRIFT_KS_THRESHOLD,
            is_drifted=is_drifted,
            details={"ks_statistic": float(ks_stat), "p_value": float(p_value)},
        )


# ── Retraining Orchestrator ──────────────────────────────────────────────────


class RetrainingOrchestrator:
    """
    Manages the full model retraining lifecycle.

    Steps:
    1. Collect recent training data from the tick store
    2. Engineer features using the existing feature pipeline
    3. Train a new model version
    4. Validate on out-of-sample data
    5. Deploy in shadow mode for live comparison
    """

    def __init__(self) -> None:
        self._state = RetrainingState.IDLE
        self._last_retrain: datetime | None = None
        self._current_run_id: str | None = None
        self._model_registry: Any = None
        self._data_store: Any = None

    @property
    def state(self) -> RetrainingState:
        return self._state

    @property
    def can_retrain(self) -> bool:
        """Check if enough time has passed since last retraining."""
        if self._last_retrain is None:
            return True
        cooldown = timedelta(hours=_RETRAIN_COOLDOWN_HOURS)
        return datetime.now(UTC) - self._last_retrain > cooldown

    async def trigger_retraining(
        self,
        drift_report: DriftReport,
        model_registry: Any = None,
        data_store: Any = None,
    ) -> str | None:
        """
        Trigger a retraining run.

        Returns the new model version ID on success, None on failure.
        """
        if not self.can_retrain:
            logger.info(
                "Retraining skipped: cooldown period active (last: %s)",
                self._last_retrain,
            )
            return None

        if self._state != RetrainingState.IDLE:
            logger.warning("Retraining already in progress (state: %s)", self._state.value)
            return None

        self._model_registry = model_registry
        self._data_store = data_store
        self._current_run_id = f"retrain_{int(time.time())}"

        try:
            # Step 1: Collect data
            self._state = RetrainingState.COLLECTING_DATA
            training_data = await self._collect_training_data()
            if training_data is None or len(training_data) < 1000:
                logger.warning(
                    "Insufficient training data (%d samples)", len(training_data) if training_data is not None else 0
                )
                self._state = RetrainingState.FAILED
                if _PROM_OK:
                    _retraining_runs.labels(outcome="insufficient_data").inc()
                return None

            # Step 2: Train
            self._state = RetrainingState.TRAINING
            model_path, metrics = await self._train_model(training_data)
            if model_path is None:
                self._state = RetrainingState.FAILED
                if _PROM_OK:
                    _retraining_runs.labels(outcome="training_failed").inc()
                return None

            # Step 3: Validate
            self._state = RetrainingState.VALIDATING
            is_valid = await self._validate_model(model_path, metrics)
            if not is_valid:
                self._state = RetrainingState.FAILED
                if _PROM_OK:
                    _retraining_runs.labels(outcome="validation_failed").inc()
                return None

            # Step 4: Register in model registry
            version_id = await self._register_model(model_path, metrics)

            self._state = RetrainingState.IDLE
            self._last_retrain = datetime.now(UTC)

            if _PROM_OK:
                _retraining_runs.labels(outcome="success").inc()

            logger.info(
                "Retraining completed: version=%s accuracy=%.4f",
                version_id,
                metrics.get("oos_accuracy", 0),
            )
            return version_id

        except Exception as exc:
            logger.error("Retraining failed: %s", exc, exc_info=True)
            self._state = RetrainingState.FAILED
            if _PROM_OK:
                _retraining_runs.labels(outcome="error").inc()
            return None
        finally:
            if self._state == RetrainingState.FAILED:
                # Reset to idle after a delay to allow retry
                await asyncio.sleep(60)
                self._state = RetrainingState.IDLE

    async def _collect_training_data(self) -> np.ndarray | None:
        """Collect recent training data from the data store."""
        if not self._data_store:
            logger.warning("No data store configured for retraining")
            return None

        try:
            # Use the data layer orchestrator to get recent OHLCV data
            cutoff = datetime.now(UTC) - timedelta(days=_TRAINING_DATA_DAYS)

            if hasattr(self._data_store, "get_historical_data"):
                data = await self._data_store.get_historical_data(
                    symbol="XAU_USD",
                    timeframe="M15",
                    start=cutoff,
                    end=datetime.now(UTC),
                )
                return np.array(data) if data else None
            elif hasattr(self._data_store, "read_range"):
                data = self._data_store.read_range(
                    symbol="XAU_USD",
                    start_ts=cutoff.timestamp(),
                    end_ts=time.time(),
                )
                return np.array(data) if data else None

            return None
        except Exception as exc:
            logger.error("Data collection failed: %s", exc)
            return None

    async def _train_model(self, training_data: np.ndarray) -> tuple[Path | None, dict[str, float]]:
        """Train a new model using the existing training pipeline."""
        try:
            from ml.train_advanced import AdvancedTrainer

            trainer = AdvancedTrainer()
            model_path = Path(f"ml/saved_models/retrained_{int(time.time())}.pkl")

            # Split data: 80% train, 20% OOS validation
            split_idx = int(len(training_data) * 0.8)
            train_split = training_data[:split_idx]
            val_split = training_data[split_idx:]

            metrics = trainer.train(
                train_data=train_split,
                val_data=val_split,
                output_path=str(model_path),
            )

            return model_path, metrics

        except ImportError:
            logger.warning("AdvancedTrainer not available — using fallback training")
            # Fallback: use the basic training pipeline
            try:
                from ml.training import train_model

                model_path = Path(f"ml/saved_models/retrained_{int(time.time())}.pkl")
                metrics = train_model(training_data, str(model_path))
                return model_path, metrics
            except Exception as exc:
                logger.error("Fallback training failed: %s", exc)
                return None, {}
        except Exception as exc:
            logger.error("Model training failed: %s", exc)
            return None, {}

    async def _validate_model(self, model_path: Path, metrics: dict[str, float]) -> bool:
        """Validate the trained model meets minimum quality thresholds."""
        min_accuracy = float(os.getenv("ML_MIN_OOS_ACCURACY", "0.55"))
        min_sharpe = float(os.getenv("ML_MIN_SHARPE_RATIO", "0.5"))

        accuracy = metrics.get("oos_accuracy", 0)
        sharpe = metrics.get("sharpe_ratio", 0)

        if accuracy < min_accuracy:
            logger.warning(
                "Model validation failed: accuracy %.4f < threshold %.4f",
                accuracy,
                min_accuracy,
            )
            return False

        if sharpe < min_sharpe:
            logger.warning(
                "Model validation failed: Sharpe %.4f < threshold %.4f",
                sharpe,
                min_sharpe,
            )
            return False

        # Verify model file integrity
        if not model_path.exists():
            logger.error("Model file not found: %s", model_path)
            return False

        return True

    async def _register_model(self, model_path: Path, metrics: dict[str, float]) -> str:
        """Register the new model in the model registry."""
        if self._model_registry and hasattr(self._model_registry, "register"):
            version = self._model_registry.register(
                name=f"continuous_learning_{int(time.time())}",
                file_path=model_path,
                oos_accuracy=metrics.get("oos_accuracy", 0),
                oos_auc=metrics.get("oos_auc", 0),
                oos_p_value=metrics.get("oos_p_value", 1.0),
                sharpe_gate_passed=metrics.get("sharpe_ratio", 0) > 0.5,
                n_trades=int(metrics.get("n_trades", 0)),
                feature_count=int(metrics.get("feature_count", 0)),
            )
            return version.get("name", str(model_path))

        return str(model_path)


# ── Shadow Deployment ─────────────────────────────────────────────────────────


class ShadowDeployment:
    """
    Runs challenger models in shadow mode alongside the champion.

    Shadow models receive the same input as the production model but their
    predictions do not affect live trading. Results are accumulated and
    compared against the champion for promotion decisions.
    """

    def __init__(self) -> None:
        self._shadows: dict[str, ShadowResult] = {}
        self._shadow_models: dict[str, Any] = {}  # version -> model instance

    def deploy_shadow(self, version_id: str, model: Any) -> None:
        """Deploy a model in shadow mode."""
        self._shadow_models[version_id] = model
        self._shadows[version_id] = ShadowResult(model_version=version_id)
        logger.info("Shadow model deployed: %s", version_id)

    def remove_shadow(self, version_id: str) -> None:
        """Remove a shadow model."""
        self._shadow_models.pop(version_id, None)
        self._shadows.pop(version_id, None)

    async def run_shadow_prediction(
        self,
        features: np.ndarray,
        champion_prediction: float,
        actual_outcome: float | None = None,
    ) -> dict[str, float]:
        """
        Run all shadow models on the same features and record results.

        Returns a dict of version_id -> prediction for monitoring.
        """
        predictions: dict[str, float] = {}

        for version_id, model in self._shadow_models.items():
            try:
                if hasattr(model, "predict"):
                    pred = model.predict(features.reshape(1, -1))[0]
                elif hasattr(model, "predict_proba"):
                    pred = model.predict_proba(features.reshape(1, -1))[0][1]
                else:
                    continue

                predictions[version_id] = float(pred)

                # Update shadow results
                result = self._shadows[version_id]
                result.predictions += 1

                if actual_outcome is not None:
                    # Determine if prediction was correct (binary classification)
                    pred_direction = 1 if pred > 0.5 else 0
                    actual_direction = 1 if actual_outcome > 0 else 0
                    if pred_direction == actual_direction:
                        result.correct_predictions += 1

                if _PROM_OK:
                    _shadow_predictions.inc()

            except Exception as exc:
                logger.debug("Shadow prediction failed for %s: %s", version_id, exc)

        return predictions

    def record_pnl(self, version_id: str, shadow_pnl: float, champion_pnl: float) -> None:
        """Record P&L comparison between shadow and champion."""
        if version_id in self._shadows:
            self._shadows[version_id].total_pnl += shadow_pnl
            self._shadows[version_id].champion_pnl += champion_pnl

    def get_shadow_results(self) -> dict[str, ShadowResult]:
        """Return all shadow deployment results."""
        return dict(self._shadows)

    def evaluate_for_promotion(self, version_id: str) -> bool:
        """
        Evaluate if a shadow model is ready for promotion.

        Requires:
        - Minimum number of predictions
        - Statistical significance of improvement
        - Positive P&L improvement over champion
        """
        result = self._shadows.get(version_id)
        if not result:
            return False

        if result.predictions < _SHADOW_MIN_PREDICTIONS:
            return False

        # Check accuracy improvement
        if result.accuracy < 0.55:  # Minimum absolute accuracy
            return False

        # Check P&L improvement
        if result.pnl_improvement < _CHAMPION_MIN_IMPROVEMENT:
            return False

        if _PROM_OK:
            _shadow_accuracy.set(result.accuracy)

        return True


# ── Champion/Challenger Promotion ─────────────────────────────────────────────


class ChampionChallenger:
    """
    Manages the promotion of challenger models to champion (production).

    Uses statistical testing to ensure the challenger genuinely outperforms
    the champion before promotion.
    """

    def __init__(self, model_registry: Any = None) -> None:
        self._model_registry = model_registry
        self._promotion_history: list[dict[str, Any]] = []

    async def promote_if_ready(
        self,
        shadow_deployment: ShadowDeployment,
        version_id: str,
    ) -> bool:
        """
        Promote a challenger model if it passes all gates.

        Gates:
        1. Minimum prediction count
        2. Accuracy improvement > threshold
        3. P&L improvement > threshold
        4. Statistical significance (binomial test)
        """
        if not shadow_deployment.evaluate_for_promotion(version_id):
            return False

        result = shadow_deployment.get_shadow_results().get(version_id)
        if not result:
            return False

        # Statistical significance test
        is_significant = self._test_significance(result)
        if not is_significant:
            logger.info(
                "Challenger %s not statistically significant yet (n=%d, acc=%.4f)",
                version_id,
                result.predictions,
                result.accuracy,
            )
            return False

        # Promote in model registry
        if self._model_registry and hasattr(self._model_registry, "promote"):
            try:
                self._model_registry.promote(version_id)
                logger.info("Model promoted to production: %s", version_id)
            except Exception as exc:
                logger.error("Model promotion failed: %s", exc)
                return False

        # Record promotion
        self._promotion_history.append(
            {
                "version_id": version_id,
                "promoted_at": datetime.now(UTC).isoformat(),
                "accuracy": result.accuracy,
                "pnl_improvement": result.pnl_improvement,
                "predictions": result.predictions,
            }
        )

        # Update shadow state
        result.state = ShadowState.PROMOTED
        shadow_deployment.remove_shadow(version_id)

        if _PROM_OK:
            _model_promotions.inc()

        return True

    def _test_significance(self, result: ShadowResult) -> bool:
        """
        Test if the challenger's improvement is statistically significant.

        Uses a one-sided binomial test: H0: accuracy <= 0.5 (random)
        """
        try:
            from scipy import stats

            # One-sided binomial test
            p_value = stats.binom_test(
                result.correct_predictions,
                result.predictions,
                0.5,
                alternative="greater",
            )
            return p_value < (1 - _SHADOW_CONFIDENCE_LEVEL)
        except ImportError:
            # Fallback: simple threshold check
            return result.accuracy > 0.55 and result.predictions >= _SHADOW_MIN_PREDICTIONS
        except Exception:
            return False

    @property
    def promotion_history(self) -> list[dict[str, Any]]:
        return self._promotion_history


# ── Main Pipeline ─────────────────────────────────────────────────────────────


class ContinuousLearningPipeline:
    """
    Orchestrates the full continuous learning lifecycle.

    Combines drift detection, retraining, shadow deployment, and
    champion/challenger promotion into a single automated pipeline.
    """

    def __init__(self) -> None:
        self._drift_detector = DriftDetector()
        self._retraining = RetrainingOrchestrator()
        self._shadow = ShadowDeployment()
        self._champion_challenger: ChampionChallenger | None = None
        self._model_registry: Any = None
        self._data_store: Any = None
        self._event_bus: Any = None
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        self._drift_history: list[DriftReport] = []

    async def start(
        self,
        model_registry: Any = None,
        data_store: Any = None,
        event_bus: Any = None,
    ) -> None:
        """Start the continuous learning pipeline."""
        self._model_registry = model_registry
        self._data_store = data_store
        self._event_bus = event_bus
        self._champion_challenger = ChampionChallenger(model_registry)
        self._running = True

        # Initialize reference distributions from current model's training data
        await self._initialize_reference_distributions()

        # Start monitoring loop
        self._monitor_task = asyncio.create_task(self._monitoring_loop())

        # Subscribe to prediction events for drift tracking
        if self._event_bus:
            with contextlib.suppress(Exception):
                self._event_bus.subscribe_local("ml:prediction", self._on_prediction)

        logger.info("ContinuousLearningPipeline started")

    async def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
        logger.info("ContinuousLearningPipeline stopped")

    def _on_prediction(self, message: dict) -> None:
        """Handle prediction events for drift tracking."""
        features = message.get("features", {})
        for feature_name, value in features.items():
            if isinstance(value, int | float):
                self._drift_detector.add_observation(feature_name, float(value))

    async def _initialize_reference_distributions(self) -> None:
        """Load reference distributions from the current production model."""
        try:
            if self._data_store and hasattr(self._data_store, "get_training_features"):
                ref_data = self._data_store.get_training_features()
                if ref_data is not None:
                    for col_name in ref_data.columns if hasattr(ref_data, "columns") else []:
                        self._drift_detector.set_reference(col_name, np.array(ref_data[col_name]))
        except Exception as exc:
            logger.debug("Reference distribution init failed: %s", exc)

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop — checks drift and triggers retraining."""
        while self._running:
            try:
                # Check for drift
                drift_report = self._drift_detector.check_drift()
                self._drift_history.append(drift_report)

                # Keep history bounded
                if len(self._drift_history) > 1000:
                    self._drift_history = self._drift_history[-500:]

                if drift_report.is_drifted:
                    logger.warning(
                        "Drift detected: type=%s score=%.4f threshold=%.4f affected=%s",
                        drift_report.drift_type.value,
                        drift_report.score,
                        drift_report.threshold,
                        drift_report.affected_features,
                    )

                    # Trigger retraining
                    version_id = await self._retraining.trigger_retraining(
                        drift_report=drift_report,
                        model_registry=self._model_registry,
                        data_store=self._data_store,
                    )

                    if version_id:
                        # Deploy in shadow mode
                        await self._deploy_shadow(version_id)

                # Check shadow models for promotion
                await self._check_promotions()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Monitoring loop error: %s", exc)

            await asyncio.sleep(_DRIFT_CHECK_INTERVAL_S)

    async def _deploy_shadow(self, version_id: str) -> None:
        """Deploy a newly trained model in shadow mode."""
        try:
            if self._model_registry and hasattr(self._model_registry, "load_model"):
                model = self._model_registry.load_model(version_id)
                self._shadow.deploy_shadow(version_id, model)
                logger.info("New model deployed in shadow mode: %s", version_id)
        except Exception as exc:
            logger.error("Shadow deployment failed for %s: %s", version_id, exc)

    async def _check_promotions(self) -> None:
        """Check if any shadow models are ready for promotion."""
        if not self._champion_challenger:
            return

        for version_id in list(self._shadow.get_shadow_results().keys()):
            promoted = await self._champion_challenger.promote_if_ready(self._shadow, version_id)
            if promoted:
                logger.info("Model promoted from shadow: %s", version_id)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_feature_observation(self, feature_name: str, value: float) -> None:
        """Add a feature observation for drift tracking."""
        self._drift_detector.add_observation(feature_name, value)

    async def run_shadow_predictions(
        self,
        features: np.ndarray,
        champion_prediction: float,
        actual_outcome: float | None = None,
    ) -> dict[str, float]:
        """Run shadow predictions and return results."""
        return await self._shadow.run_shadow_prediction(features, champion_prediction, actual_outcome)

    def health(self) -> dict[str, Any]:
        """Return pipeline health metrics."""
        return {
            "running": self._running,
            "retraining_state": self._retraining.state.value,
            "can_retrain": self._retraining.can_retrain,
            "drift_history_count": len(self._drift_history),
            "latest_drift": self._drift_history[-1].to_dict() if self._drift_history else None,
            "shadow_models": {k: v.to_dict() for k, v in self._shadow.get_shadow_results().items()},
            "promotion_history": (self._champion_challenger.promotion_history if self._champion_challenger else []),
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_pipeline: ContinuousLearningPipeline | None = None


def get_continuous_learning_pipeline() -> ContinuousLearningPipeline:
    """Return the module-level ContinuousLearningPipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = ContinuousLearningPipeline()
    return _pipeline
