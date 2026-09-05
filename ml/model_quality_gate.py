from __future__ import annotations

"""Fail-closed quality gates for model decisions.

This module complements the existing stale-model and drift monitors without
replacing them. Callers can use the result as additional evidence before a
candidate reaches paper or live execution.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelQualitySnapshot:
    calibration_ok: bool
    drift_ok: bool
    data_quality_ok: bool
    calibration_score: float | None = None
    drift_score: float | None = None
    data_quality_score: float | None = None
    reason_codes: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.calibration_ok and self.drift_ok and self.data_quality_ok


class ModelQualityGate:
    """Evaluate independent quality signals with explicit reason codes."""

    def __init__(
        self,
        *,
        minimum_calibration: float = 0.0,
        maximum_drift: float = 1.0,
        minimum_data_quality: float = 1.0,
    ) -> None:
        if not 0.0 <= minimum_calibration <= 1.0:
            raise ValueError("minimum_calibration must be between 0 and 1")
        if maximum_drift < 0.0:
            raise ValueError("maximum_drift must be non-negative")
        if not 0.0 <= minimum_data_quality <= 1.0:
            raise ValueError("minimum_data_quality must be between 0 and 1")
        self.minimum_calibration = minimum_calibration
        self.maximum_drift = maximum_drift
        self.minimum_data_quality = minimum_data_quality

    def evaluate(
        self,
        *,
        calibration_score: float | None,
        drift_score: float | None,
        data_quality_score: float | None,
    ) -> ModelQualitySnapshot:
        reasons: list[str] = []
        calibration_ok = calibration_score is not None and calibration_score >= self.minimum_calibration
        drift_ok = drift_score is not None and drift_score <= self.maximum_drift
        data_quality_ok = data_quality_score is not None and data_quality_score >= self.minimum_data_quality

        if not calibration_ok:
            reasons.append("CALIBRATION_UNAVAILABLE_OR_BELOW_THRESHOLD")
        if not drift_ok:
            reasons.append("DRIFT_UNAVAILABLE_OR_ABOVE_THRESHOLD")
        if not data_quality_ok:
            reasons.append("DATA_QUALITY_UNAVAILABLE_OR_BELOW_THRESHOLD")

        return ModelQualitySnapshot(
            calibration_ok=calibration_ok,
            drift_ok=drift_ok,
            data_quality_ok=data_quality_ok,
            calibration_score=calibration_score,
            drift_score=drift_score,
            data_quality_score=data_quality_score,
            reason_codes=tuple(reasons),
        )

    def require_pass(self, **scores: float | None) -> ModelQualitySnapshot:
        snapshot = self.evaluate(**scores)
        if not snapshot.passed:
            raise RuntimeError("model quality gate failed: " + ", ".join(snapshot.reason_codes))
        return snapshot


__all__ = ["ModelQualityGate", "ModelQualitySnapshot"]
