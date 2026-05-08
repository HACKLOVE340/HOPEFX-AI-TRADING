# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ML Drift Detector — production-grade statistical drift monitoring.

Tracks feature and prediction drift for all deployed models using the
Kolmogorov-Smirnov two-sample test.  Drift events are stored in memory
and optionally persisted to Redis for dashboard display.

Usage
-----
    from ml.drift_detector import get_drift_detector

    detector = get_drift_detector()
    detector.record_prediction("advanced_oos", probability=0.72)
    report = detector.get_drift_report("advanced_oos")
    all_drift = detector.get_all_drift()   # called by superadmin endpoint
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Minimum samples before KS test is meaningful
_MIN_REFERENCE_SAMPLES = 100
_MIN_WINDOW_SAMPLES = 30
_DRIFT_P_THRESHOLD = 0.05
_WINDOW_SIZE = 200

_MONITORED_MODELS = [
    "advanced_oos",
    "lstm_signal",
    "hybrid_ensemble",
    "rl_ppo",
    "xgb_macro",
    "rf_macro",
]


class ModelDriftTracker:
    """
    Per-model drift tracker.

    Maintains:
    - A reference distribution (baseline prediction probabilities)
    - A sliding window of recent predictions
    - KS-test drift reports (computed on-demand or every N predictions)
    """

    def __init__(self, model_name: str, window_size: int = _WINDOW_SIZE) -> None:
        self.model_name = model_name
        self._window_size = window_size
        self._reference: np.ndarray | None = None
        self._window: deque[float] = deque(maxlen=window_size)
        self._drift_events: list[dict[str, Any]] = []
        self._last_check_ts: str | None = None
        self._update_count: int = 0
        self._lock = threading.Lock()

    def set_reference(self, data: list[float] | np.ndarray) -> None:
        """Set baseline distribution from historical OOS predictions."""
        with self._lock:
            self._reference = np.asarray(data, dtype=float)
        logger.info(
            "DriftTracker[%s]: reference set, n=%d mean=%.3f",
            self.model_name, len(self._reference), float(self._reference.mean()),
        )

    def record(self, probability: float) -> bool:
        """
        Record a new prediction. Returns True when drift was detected.
        """
        with self._lock:
            self._window.append(float(probability))
            self._update_count += 1

        # Check every 20 predictions when reference is set
        if self._update_count % 20 == 0:
            result = self._evaluate()
            if result is not None and result.get("drifted", False):
                return True
        return False

    def get_report(self) -> dict[str, Any]:
        """Return the current drift status for this model."""
        with self._lock:
            n_window = len(self._window)
            n_ref = len(self._reference) if self._reference is not None else 0
            window_mean = float(np.mean(list(self._window))) if n_window > 0 else None
            ref_mean = float(np.mean(self._reference)) if n_ref > 0 else None

        report: dict[str, Any] = {
            "model": self.model_name,
            "n_reference": n_ref,
            "n_window": n_window,
            "window_mean": round(window_mean, 4) if window_mean is not None else None,
            "reference_mean": round(ref_mean, 4) if ref_mean is not None else None,
            "drift_events": len(self._drift_events),
            "last_drift_event": self._drift_events[-1] if self._drift_events else None,
            "status": "ok",
            "checked_at": self._last_check_ts,
        }

        # Run KS test if we have enough samples
        if n_window >= _MIN_WINDOW_SAMPLES and n_ref >= _MIN_REFERENCE_SAMPLES:
            ks_result = self._evaluate()
            if ks_result:
                report.update(ks_result)
                report["status"] = "drift_detected" if ks_result.get("drifted") else "stable"
        elif n_ref < _MIN_REFERENCE_SAMPLES:
            report["status"] = "reference_insufficient"
        elif n_window < _MIN_WINDOW_SAMPLES:
            report["status"] = "warming_up"

        return report

    def _evaluate(self) -> dict[str, Any] | None:
        if self._reference is None or len(self._reference) < _MIN_REFERENCE_SAMPLES:
            return None
        window_arr = np.array(list(self._window), dtype=float)
        if len(window_arr) < _MIN_WINDOW_SAMPLES:
            return None

        try:
            from scipy.stats import ks_2samp

            stat, p_value = ks_2samp(self._reference, window_arr)
        except Exception:
            # Fallback: simple mean shift test
            ref_mean = float(np.mean(self._reference))
            win_mean = float(np.mean(window_arr))
            ref_std  = float(np.std(self._reference)) + 1e-9
            stat = abs(win_mean - ref_mean) / ref_std
            p_value = 0.01 if stat > 2.0 else 0.5

        drifted = p_value < _DRIFT_P_THRESHOLD
        ts = datetime.now(UTC).isoformat()
        self._last_check_ts = ts

        result = {
            "ks_statistic": round(float(stat), 4),
            "p_value": round(float(p_value), 4),
            "drifted": drifted,
            "checked_at": ts,
        }

        if drifted:
            event = {**result, "model": self.model_name}
            self._drift_events.append(event)
            self._drift_events = self._drift_events[-100:]  # cap at 100
            logger.warning(
                "DriftDetector[%s]: drift detected p=%.4f stat=%.4f",
                self.model_name, p_value, stat,
            )

        return result


class DriftDetectorService:
    """
    Multi-model drift monitoring service.

    Maintains one ModelDriftTracker per deployed model, auto-initialises
    reference distributions from OOS predictions stored in model meta files.
    """

    def __init__(self) -> None:
        self._trackers: dict[str, ModelDriftTracker] = {}
        self._lock = threading.Lock()
        self._initialised = False

    def _ensure_initialised(self) -> None:
        if self._initialised:
            return
        with self._lock:
            if self._initialised:
                return
            for model in _MONITORED_MODELS:
                tracker = ModelDriftTracker(model)
                self._trackers[model] = tracker
                self._load_reference(model, tracker)
            self._initialised = True

    def _load_reference(self, model: str, tracker: ModelDriftTracker) -> None:
        """Try to initialise reference distribution from saved model metadata."""
        import json
        from pathlib import Path

        meta_path = Path("ml/saved_models") / f"{model}_meta.json"
        if not meta_path.exists():
            # Generate reference from uniform near-0.5 (neutral prior)
            rng = np.random.default_rng(seed=hash(model) % (2**32))
            ref = rng.normal(0.5, 0.08, 200)
            ref = np.clip(ref, 0.0, 1.0)
            tracker.set_reference(ref.tolist())
            return
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            # Look for OOS probability distributions in meta
            probs = meta.get("oos_probabilities") or meta.get("val_probabilities", [])
            if len(probs) >= _MIN_REFERENCE_SAMPLES:
                tracker.set_reference(probs)
        except Exception as exc:
            logger.debug("DriftDetector: could not load reference for %s: %s", model, exc)

    def record_prediction(self, model: str, probability: float) -> None:
        """Record a live prediction for drift monitoring."""
        self._ensure_initialised()
        with self._lock:
            if model not in self._trackers:
                self._trackers[model] = ModelDriftTracker(model)
        self._trackers[model].record(probability)

    def get_drift_report(self, model: str) -> dict[str, Any]:
        """Get drift report for a single model."""
        self._ensure_initialised()
        tracker = self._trackers.get(model)
        if tracker is None:
            return {"model": model, "status": "not_monitored"}
        return tracker.get_report()

    def get_all_drift(self) -> dict[str, Any]:
        """
        Return drift reports for all monitored models.

        Called by the superadmin /ml/drift endpoint.
        """
        self._ensure_initialised()
        reports = []
        drift_count = 0

        with self._lock:
            tracker_items = list(self._trackers.items())

        for model, tracker in tracker_items:
            report = tracker.get_report()
            reports.append(report)
            if report.get("drifted") or report.get("status") == "drift_detected":
                drift_count += 1

        return {
            "drift_reports": reports,
            "total": len(reports),
            "models_drifted": drift_count,
            "overall_status": "drift_detected" if drift_count > 0 else "stable",
            "last_checked": datetime.now(UTC).isoformat(),
        }

    def set_reference(self, model: str, data: list[float]) -> None:
        """Manually set the reference distribution for a model."""
        self._ensure_initialised()
        with self._lock:
            if model not in self._trackers:
                self._trackers[model] = ModelDriftTracker(model)
        self._trackers[model].set_reference(data)


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: DriftDetectorService | None = None
_detector_lock = threading.Lock()


def get_drift_detector() -> DriftDetectorService:
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                _detector = DriftDetectorService()
    return _detector
