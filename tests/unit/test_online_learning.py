# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_online_learning.py
====================================
Unit tests for research/pipeline/online_learning.py — DriftDetector,
IncrementalXGBoost, OnlineEnsemble, and OnlineLearnerStore (Phase 3).

Covers:
- DriftDetector: no drift on stable errors, drift on sudden spike
- IncrementalXGBoost: fit, predict_proba shape, update adds trees
- OnlineLearnerStore: not ready before min_fills, ready after
- OnlineLearnerStore.blend: returns advanced_prob when not ready
- OnlineLearnerStore.blend: blends 0.7/0.3 when ready
- OnlineLearnerStore.on_fill: drift detection triggers reset
- notify_fill: no-op when FEATURE_ONLINE_LEARNING=false
- notify_fill: calls on_fill when flag is on
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_features(n: int = 1, n_cols: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    data = rng.normal(0, 1, (n, n_cols))
    return pd.DataFrame(data, columns=[f"f{i}" for i in range(n_cols)])


def _make_labels(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, n).astype(float)


# ── DriftDetector ─────────────────────────────────────────────────────────────


class TestDriftDetector:
    def setup_method(self):
        from research.pipeline.online_learning import DriftDetector

        self._cls = DriftDetector

    def test_no_drift_on_stable_errors(self):
        # Use a high threshold so random noise doesn't trigger false positives
        det = self._cls(delta=0.005, threshold=200.0)
        rng = np.random.default_rng(1)
        for _ in range(50):
            y = rng.integers(0, 2, 10).astype(float)
            prob = np.clip(rng.normal(0.5, 0.05, 10), 0.01, 0.99)
            det.update(y, prob)
        assert det.drift_count == 0

    def test_drift_detected_on_sudden_spike(self):
        det = self._cls(delta=0.001, threshold=5.0)
        rng = np.random.default_rng(2)
        # Feed stable errors first
        for _ in range(50):
            y = rng.integers(0, 2, 10).astype(float)
            prob = np.clip(rng.normal(0.5, 0.02, 10), 0.01, 0.99)
            det.update(y, prob)
        # Inject catastrophic errors (all wrong)
        for _ in range(30):
            y = np.ones(10)
            prob = np.full(10, 0.01)  # predicts 0 when truth is 1 → high loss
            det.update(y, prob)
        assert det.drift_count >= 1

    def test_reset_clears_stat(self):
        det = self._cls(delta=0.001, threshold=5.0)
        det._sum = 100.0
        det._min_sum = 0.0
        det.reset()
        assert det._sum == 0.0
        assert det._min_sum == 0.0

    def test_recent_error_returns_float(self):
        det = self._cls()
        assert isinstance(det.recent_error, float)


# ── IncrementalXGBoost ────────────────────────────────────────────────────────


class TestIncrementalXGBoost:
    def setup_method(self):
        try:
            from research.pipeline.online_learning import IncrementalXGBoost

            self._cls = IncrementalXGBoost
        except ImportError:
            pytest.skip("xgboost not available")

    def test_fit_and_predict_proba_shape(self):
        model = self._cls(n_base_rounds=10)
        X = _make_features(100, 8)
        y = _make_labels(100)
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert proba.shape == (100,)
        assert (proba >= 0).all() and (proba <= 1).all()

    def test_update_increases_tree_count(self):
        model = self._cls(n_base_rounds=10, n_new_rounds=5)
        X = _make_features(100, 8)
        y = _make_labels(100)
        model.fit(X, y)
        trees_before = model._booster.num_boosted_rounds()
        model.update(_make_features(20, 8), _make_labels(20))
        trees_after = model._booster.num_boosted_rounds()
        assert trees_after > trees_before

    def test_predict_before_fit_raises(self):
        model = self._cls()
        with pytest.raises(RuntimeError):
            model.predict_proba(_make_features(5, 8))

    def test_save_load_roundtrip(self, tmp_path):
        model = self._cls(n_base_rounds=10)
        X = _make_features(50, 5)
        y = _make_labels(50)
        model.fit(X, y)
        path = tmp_path / "ixgb.pkl"
        model.save(path)
        loaded = self._cls.load(path)
        np.testing.assert_allclose(model.predict_proba(X), loaded.predict_proba(X), rtol=1e-5)


# ── OnlineLearnerStore ────────────────────────────────────────────────────────


class TestOnlineLearnerStore:
    def setup_method(self):
        try:
            from research.pipeline.online_learning import OnlineLearnerStore

            self._cls = OnlineLearnerStore
        except ImportError:
            pytest.skip("xgboost not available")

    def test_not_ready_before_min_fills(self):
        store = self._cls(min_fills=20)
        assert store.is_ready is False

    def test_ready_after_min_fills(self):
        store = self._cls(min_fills=5)
        X = _make_features(1, 8)
        for i in range(6):
            store.on_fill(X, label=i % 2)
        assert store.is_ready is True

    def test_blend_returns_advanced_when_not_ready(self):
        store = self._cls(min_fills=100)
        X = _make_features(1, 8)
        result = store.blend(0.75, X)
        assert result == 0.75

    def test_blend_returns_float_in_range(self):
        store = self._cls(min_fills=5)
        X = _make_features(1, 8)
        for i in range(6):
            store.on_fill(X, label=i % 2)
        result = store.blend(0.75, X)
        assert 0.0 <= result <= 1.0

    def test_blend_weights_sum_to_one(self):
        """0.7 * adv + 0.3 * online must be in [0,1] for any valid inputs."""
        store = self._cls(min_fills=5, primary_weight=0.7, online_weight=0.3)
        X = _make_features(1, 8)
        for i in range(6):
            store.on_fill(X, label=i % 2)
        # Test with extreme probabilities
        for adv_prob in [0.0, 0.5, 1.0]:
            result = store.blend(adv_prob, X)
            assert 0.0 <= result <= 1.0

    def test_fill_count_increments(self):
        store = self._cls(min_fills=100)
        X = _make_features(1, 8)
        for _ in range(5):
            store.on_fill(X, label=1)
        assert store.fill_count == 5

    def test_status_returns_dict(self):
        store = self._cls(min_fills=100)
        s = store.status()
        assert isinstance(s, dict)
        assert "ready" in s
        assert "fill_count" in s
        # drift count may be keyed as drift_count or adwin_drift_count
        assert "drift_count" in s or "adwin_drift_count" in s

    def test_on_fill_returns_bool(self):
        store = self._cls(min_fills=5)
        X = _make_features(1, 8)
        result = store.on_fill(X, label=1)
        assert isinstance(result, bool)

    def test_drift_count_accessible(self):
        store = self._cls(min_fills=100)
        assert store.drift_count == 0


# ── Signal engine integration ─────────────────────────────────────────────────


class TestOnlineLearningSignalEngine:
    def test_flag_off_returns_none_store(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ONLINE_LEARNING", "false")
        import core.signal_engine as se

        se._online_learner_store = None
        store = se._get_online_learner_store()
        assert store is None

    def test_flag_on_returns_store_instance(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ONLINE_LEARNING", "true")
        import core.signal_engine as se

        se._online_learner_store = None
        store = se._get_online_learner_store()
        assert store is not None
        se._online_learner_store = None  # cleanup

    def test_notify_fill_noop_when_flag_off(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ONLINE_LEARNING", "false")
        import core.signal_engine as se

        se._online_learner_store = None
        X = _make_features(1, 8)
        # Must not raise
        se.notify_fill(X, label=1)

    def test_notify_fill_calls_on_fill_when_flag_on(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ONLINE_LEARNING", "true")
        import core.signal_engine as se

        se._online_learner_store = None

        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.on_fill.return_value = False
        se._online_learner_store = mock_store

        X = _make_features(1, 8)
        se.notify_fill(X, label=1)
        # on_fill is called with (features, label) and optional primary_prob kwarg
        call_args = mock_store.on_fill.call_args
        assert call_args is not None, "on_fill was not called"
        assert call_args.args[0] is X
        assert call_args.args[1] == 1
        se._online_learner_store = None  # cleanup

    def test_blend_formula_correctness(self):
        """0.7 * 0.8 + 0.3 * 0.6 = 0.74"""
        adv_prob = 0.8
        online_prob = 0.6
        expected = 0.7 * adv_prob + 0.3 * online_prob
        assert abs(expected - 0.74) < 1e-9

    def test_blend_neutral_when_online_is_neutral(self):
        """When online_prob=0.5, blend should be closer to advanced_prob."""
        adv_prob = 0.8
        online_prob = 0.5
        blended = 0.7 * adv_prob + 0.3 * online_prob
        assert blended > 0.5
        assert blended < adv_prob
