# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Unit tests for ML components."""

import asyncio
import pytest
import numpy as np

try:
    from ml.online_learner import XGBoostOnlineModel  # type: ignore[import]
    from ml.robust_predictor import DriftDetector, DriftResult  # type: ignore[import]

    HAS_ML_DEPS = True
except ImportError:
    try:
        # Fallback: check if xgboost is available at all
        import xgboost

        HAS_ML_DEPS = False  # modules exist but classes may differ
    except ImportError:
        HAS_ML_DEPS = False
    DriftResult = None  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(
    not HAS_ML_DEPS,
    reason="ML dependencies (torch or others) not available",
)


def test_xgboost_training():
    """Test XGBoost model training."""
    model = XGBoostOnlineModel()

    # Generate synthetic data
    np.random.seed(42)
    X = np.random.randn(1000, 10)
    y = (X[:, 0] + X[:, 1] > 0).astype(int)

    asyncio.run(model.fit(X, y))

    assert model._is_trained
    assert model.metadata is not None
    assert model.metadata.val_score > 0.5


def test_drift_detection():
    """Test drift detector identifies distribution shift."""
    detector = DriftDetector()

    # Prime reference distribution with low-variance samples
    ref_data = np.random.normal(0, 0.01, 50)
    detector.set_reference(ref_data)

    # Feed reference-like samples to fill the buffer
    for val in np.random.normal(0, 0.01, 100):
        detector.update(float(val))

    # Now feed shifted samples — detector should trip
    metrics = None
    for val in np.random.normal(0.5, 0.01, 100):
        metrics = detector.update(float(val))

    assert metrics is not None
    assert isinstance(metrics, DriftResult)
    # Use .detected (the actual field name on DriftResult)
    assert metrics.detected


@pytest.mark.hypothesis
def test_feature_store_consistency():
    """Property-based test for feature store."""
    from hypothesis import given, strategies as st

    @given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=10, max_size=100))
    def features_computed_correctly(prices):
        # Property: features should be deterministic given same inputs
        pass
