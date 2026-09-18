from __future__ import annotations

import pytest

from ml.model_quality_gate import ModelQualityGate


def test_quality_gate_passes_only_when_all_signals_pass() -> None:
    snapshot = ModelQualityGate(
        minimum_calibration=0.7,
        maximum_drift=0.4,
        minimum_data_quality=0.9,
    ).evaluate(calibration_score=0.8, drift_score=0.2, data_quality_score=0.95)

    assert snapshot.passed is True
    assert snapshot.reason_codes == ()


def test_quality_gate_fails_closed_when_a_signal_is_missing() -> None:
    snapshot = ModelQualityGate().evaluate(
        calibration_score=0.8,
        drift_score=None,
        data_quality_score=1.0,
    )

    assert snapshot.passed is False
    assert "DRIFT_UNAVAILABLE_OR_ABOVE_THRESHOLD" in snapshot.reason_codes


def test_quality_gate_reports_all_failed_reasons() -> None:
    snapshot = ModelQualityGate(minimum_calibration=0.5).evaluate(
        calibration_score=0.0,
        drift_score=2.0,
        data_quality_score=0.2,
    )

    assert snapshot.passed is False
    assert len(snapshot.reason_codes) == 3
    with pytest.raises(RuntimeError, match="model quality gate failed"):
        ModelQualityGate().require_pass(
            calibration_score=0.0,
            drift_score=2.0,
            data_quality_score=0.2,
        )


def test_quality_gate_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        ModelQualityGate(minimum_calibration=1.1)
    with pytest.raises(ValueError):
        ModelQualityGate(maximum_drift=-0.1)
    with pytest.raises(ValueError):
        ModelQualityGate(minimum_data_quality=-0.1)
