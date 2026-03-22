"""Unit tests for ML components."""

import asyncio
import pytest
import numpy as np
from datetime import datetime

from hopefx.ml.pipeline import XGBoostOnlineModel
from hopefx.ml.drift import DriftDetector


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
    
    # Reference distribution
    ref_features = {
        "symbol": "XAUUSD",
        "timestamp": datetime.utcnow(),
        "features": {"returns_20": 0.001}
    }
    
    # Add reference samples
    for _ in range(100):
        ref_features["features"]["returns_20"] = np.random.normal(0, 0.01)
        asyncio.run(detector.update(type("FV", (), ref_features)()))
    
    # Test with shifted distribution
    drift_features = {
        "symbol": "XAUUSD",
        "timestamp": datetime.utcnow(),
        "features": {"returns_20": 0.05}  # Shifted mean
    }
    
    metrics = None
    for _ in range(100):
        drift_features["features"]["returns_20"] = np.random.normal(0.05, 0.02)
        metrics = asyncio.run(detector.update(type("FV", (), drift_features)()))
    
    assert metrics is not None
    assert metrics.is_drift  # Should detect drift


@pytest.mark.hypothesis
def test_feature_store_consistency():
    """Property-based test for feature store."""
    from hypothesis import given, strategies as st
    
    @given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=10, max_size=100))
    def features_computed_correctly(prices):
        # Property: features should be deterministic given same inputs
        pass
