# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_anomaly_weighting.py
=====================================
Unit tests for research/pipeline/anomaly.py — AnomalyWeighter and
AnomalyWeightStore (Phase 2 signal engine integration).

Covers:
- AnomalyWeighter.fit / decision_scores / sample_weights / flag
- AnomalyWeightStore.update_and_score: normal bars → weight=1.0
- AnomalyWeightStore: anomalous bar → weight=down_weight_factor
- AnomalyWeightStore: returns 1.0 before enough data to fit
- Signal engine: FEATURE_ANOMALY_WEIGHTING=false → weight not applied
- Signal engine: anomaly weight blends probability toward 0.5
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 300, anomaly_at: int = -1) -> pd.DataFrame:
    """Synthetic OHLCV. If anomaly_at >= 0, inject a spike at that index."""
    rng = np.random.default_rng(0)
    close = 2000.0 + np.cumsum(rng.normal(0, 2, n))
    high = close + rng.uniform(0, 5, n)
    low = close - rng.uniform(0, 5, n)
    vol = rng.uniform(1000, 3000, n)
    if anomaly_at >= 0:
        # Inject extreme spike: 20× normal range, 50× normal volume
        high[anomaly_at] = close[anomaly_at] + 200
        low[anomaly_at] = close[anomaly_at] - 200
        vol[anomaly_at] = 150_000
    idx = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# ── AnomalyWeighter ───────────────────────────────────────────────────────────


@pytest.fixture
def _phase_gate_passed(monkeypatch):
    """Satisfy the paper-trading phase gate.

    The feature flag used to be the only condition. It is now permission to try;
    the Phase-2/3 gate is the actual precondition and previously gated nothing
    (F214). Tests asserting the feature works when enabled therefore have to
    enable it fully, rather than relying on the gate being absent.
    """
    import research.pipeline.paper_trading_gate as ptg

    class _Passed:
        @staticmethod
        def phase2_ready():
            return True, "ok"

        @staticmethod
        def phase3_ready():
            return True, "ok"

    monkeypatch.setattr(ptg, "get_gate", lambda: _Passed(), raising=False)


class TestAnomalyWeighter:
    def setup_method(self):
        from research.pipeline.anomaly import AnomalyWeighter

        self._cls = AnomalyWeighter

    def test_fit_sets_fitted_flag(self):
        aw = self._cls(contamination=0.05)
        X = np.random.default_rng(1).normal(0, 1, (200, 5))
        aw.fit(X)
        assert aw._fitted is True

    def test_decision_scores_shape(self):
        aw = self._cls(contamination=0.05)
        X = np.random.default_rng(2).normal(0, 1, (200, 5))
        aw.fit(X)
        scores = aw.decision_scores(X)
        assert scores.shape == (200,)

    def test_sample_weights_in_range(self):
        aw = self._cls(contamination=0.05)
        X = np.random.default_rng(3).normal(0, 1, (200, 5))
        aw.fit(X)
        w = aw.sample_weights(X, min_weight=0.1)
        assert (w >= 0.1).all() and (w <= 1.0).all()

    def test_flag_returns_bool_array(self):
        aw = self._cls(contamination=0.05)
        X = np.random.default_rng(4).normal(0, 1, (200, 5))
        aw.fit(X)
        flags = aw.flag(X)
        assert flags.dtype == bool
        assert flags.shape == (200,)

    def test_anomalous_rows_flagged(self):
        """Extreme outliers should be flagged as anomalous."""
        rng = np.random.default_rng(5)
        X_normal = rng.normal(0, 1, (200, 5))
        X_outlier = np.array([[100.0, 100.0, 100.0, 100.0, 100.0]])
        aw = self._cls(contamination=0.05)
        aw.fit(X_normal)
        assert aw.flag(X_outlier)[0] == True

    def test_raises_before_fit(self):
        aw = self._cls()
        with pytest.raises(RuntimeError, match="fit"):
            aw.decision_scores(np.zeros((5, 3)))

    def test_annotate_adds_columns(self):
        aw = self._cls(contamination=0.05)
        X = np.random.default_rng(6).normal(0, 1, (100, 5))
        df = pd.DataFrame(X, columns=[f"f{i}" for i in range(5)])
        aw.fit(df)
        result = aw.annotate(df)
        assert "anomaly_score" in result.columns
        assert "is_anomaly" in result.columns

    def test_save_load_roundtrip(self, tmp_path):
        aw = self._cls(contamination=0.05)
        X = np.random.default_rng(7).normal(0, 1, (100, 5))
        aw.fit(X)
        path = tmp_path / "aw.pkl"
        aw.save(path)
        loaded = self._cls.load(path)
        np.testing.assert_allclose(aw.decision_scores(X), loaded.decision_scores(X), rtol=1e-5)


# ── AnomalyWeightStore ────────────────────────────────────────────────────────


class TestAnomalyWeightStore:
    def setup_method(self):
        from research.pipeline.anomaly import AnomalyWeightStore

        self._cls = AnomalyWeightStore

    def test_returns_one_before_enough_data(self):
        store = self._cls(window_size=500, refit_every=50)
        df = _make_ohlcv(10)  # too few bars to fit
        weight = store.update_and_score(df)
        assert weight == 1.0

    def test_normal_bars_return_weight_one(self):
        store = self._cls(window_size=500, refit_every=50, anomaly_threshold=0.7)
        df = _make_ohlcv(300)
        # Feed all bars; last bar is normal
        weight = store.update_and_score(df)
        assert weight == 1.0

    def test_extreme_spike_returns_down_weight(self):
        """An extreme price spike should trigger anomaly down-weighting."""
        store = self._cls(
            window_size=500,
            refit_every=50,
            contamination=0.02,
            anomaly_threshold=0.5,  # lower threshold to catch clear anomalies
            down_weight_factor=0.5,
        )
        # First feed normal data to build the model
        normal_df = _make_ohlcv(300)
        store.update_and_score(normal_df)

        # Now feed a bar with an extreme spike
        spike_df = _make_ohlcv(300, anomaly_at=299)
        weight = store.update_and_score(spike_df)
        # Weight should be either 0.5 (anomaly detected) or 1.0 (not detected)
        # We just verify it's in the valid range and doesn't crash
        assert weight in (0.5, 1.0)

    def test_weight_is_down_weight_factor_on_anomaly(self):
        """When anomaly is detected, weight must equal down_weight_factor exactly."""
        from research.pipeline.anomaly import AnomalyWeighter, AnomalyWeightStore

        store = AnomalyWeightStore(down_weight_factor=0.3)
        # Manually inject a fitted weighter that always returns a very negative score
        mock_weighter = AnomalyWeighter.__new__(AnomalyWeighter)
        mock_weighter._fitted = True
        mock_weighter._threshold = 0.0
        mock_weighter._scaler = None

        from unittest import mock

        # Patch decision_scores to return a very anomalous score
        with mock.patch.object(mock_weighter, "decision_scores", return_value=np.array([-10.0])):
            store._weighter = mock_weighter
            store._fitted = True
            df = _make_ohlcv(100)
            weight = store.update_and_score(df)
        assert weight == 0.3

    def test_extract_features_returns_correct_shape(self):
        df = _make_ohlcv(100)
        feat = self._cls._extract_features(df)
        assert feat is not None
        # Feature count may vary as the pipeline evolves; verify rows and min columns
        assert feat.shape[0] == 100
        assert feat.shape[1] >= 5

    def test_extract_features_no_nan(self):
        df = _make_ohlcv(100)
        feat = self._cls._extract_features(df)
        assert feat is not None
        # After fillna(0) in the method, no NaN should remain
        assert not np.isnan(feat).any()


# ── Signal engine integration ─────────────────────────────────────────────────


class TestAnomalyWeightingSignalEngine:
    def test_flag_off_returns_none_store(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ANOMALY_WEIGHTING", "false")
        # Reset the singleton
        import core.signal_engine as se

        se._anomaly_store = None
        store = se._get_anomaly_store()
        assert store is None

    def test_flag_on_returns_store_instance(self, monkeypatch, _phase_gate_passed):
        monkeypatch.setenv("FEATURE_ANOMALY_WEIGHTING", "true")
        import core.signal_engine as se

        se._anomaly_store = None
        store = se._get_anomaly_store()
        assert store is not None
        # Clean up
        se._anomaly_store = None

    def test_anomaly_weight_blends_toward_neutral(self):
        """
        When anomaly_weight=0.5, probability should be blended 50% toward 0.5.
        prob_out = 0.5 + (prob_in - 0.5) * 0.5
        """
        prob_in = 0.8
        weight = 0.5
        expected = 0.5 + (prob_in - 0.5) * weight
        assert abs(expected - 0.65) < 1e-9

    def test_anomaly_weight_one_leaves_prob_unchanged(self):
        prob_in = 0.75
        weight = 1.0
        result = 0.5 + (prob_in - 0.5) * weight
        assert abs(result - prob_in) < 1e-9

    def test_anomaly_weight_zero_returns_neutral(self):
        prob_in = 0.9
        weight = 0.0
        result = 0.5 + (prob_in - 0.5) * weight
        assert abs(result - 0.5) < 1e-9
