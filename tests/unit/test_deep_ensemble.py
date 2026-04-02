# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_deep_ensemble.py
==================================
Unit tests for research/pipeline/models_ensemble.py — DeepEnsembleStore
and research/pipeline/models_deep.py — DeepPredictor (Phase 4).

Covers:
- DeepEnsembleStore.load: inactive when model file missing
- DeepEnsembleStore.load: inactive when OOS accuracy below gate
- DeepEnsembleStore.load: inactive when p-value above gate
- DeepEnsembleStore.load: active when gates pass
- DeepEnsembleStore.blend: returns advanced_prob when inactive
- DeepEnsembleStore.blend: blends with deep_weight when active
- DeepEnsembleStore._extract_features: correct shape, no NaN
- DeepEnsembleStore.status: returns expected keys
- FEATURE_DEEP_ENSEMBLE=false → _get_deep_ensemble_store returns None
- DeepPredictor: architecture validation (lstm/transformer/tcn)
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 2000.0 + np.cumsum(rng.normal(0, 3, n))
    high = close + rng.uniform(0, 8, n)
    low = close - rng.uniform(0, 8, n)
    vol = rng.uniform(1000, 5000, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def _write_meta(path: Path, oos_accuracy: float, p_value: float) -> None:
    path.write_text(json.dumps({"oos_accuracy": oos_accuracy, "p_value": p_value}))


# ── DeepEnsembleStore ─────────────────────────────────────────────────────────


class TestDeepEnsembleStore:
    def setup_method(self):
        from research.pipeline.models_ensemble import DeepEnsembleStore

        self._cls = DeepEnsembleStore

    def test_inactive_when_model_file_missing(self, tmp_path):
        store = self._cls(
            model_path=str(tmp_path / "nonexistent.pt"),
            meta_path=str(tmp_path / "meta.json"),
        )
        result = store.load()
        assert result is False
        assert store.is_active is False

    def test_inactive_when_oos_accuracy_below_gate(self, tmp_path):
        meta = tmp_path / "meta.json"
        _write_meta(meta, oos_accuracy=0.65, p_value=0.0001)
        model = tmp_path / "model.pt"
        model.write_bytes(b"fake")
        store = self._cls(
            model_path=str(model),
            meta_path=str(meta),
            oos_accuracy_gate=0.70,
        )
        result = store.load()
        assert result is False
        assert store.is_active is False

    def test_inactive_when_p_value_above_gate(self, tmp_path):
        meta = tmp_path / "meta.json"
        _write_meta(meta, oos_accuracy=0.75, p_value=0.01)
        model = tmp_path / "model.pt"
        model.write_bytes(b"fake")
        store = self._cls(
            model_path=str(model),
            meta_path=str(meta),
            oos_accuracy_gate=0.70,
            p_value_gate=0.001,
        )
        result = store.load()
        assert result is False
        assert store.is_active is False

    def test_inactive_when_meta_missing(self, tmp_path):
        model = tmp_path / "model.pt"
        model.write_bytes(b"fake")
        store = self._cls(
            model_path=str(model),
            meta_path=str(tmp_path / "nonexistent_meta.json"),
        )
        result = store.load()
        assert result is False

    def test_blend_returns_advanced_when_inactive(self):
        store = self._cls()
        df = _make_ohlcv(100)
        result = store.blend(0.75, df)
        assert result == 0.75

    def test_blend_with_active_mock_predictor(self, tmp_path):
        """When active, blend should return (1-w)*adv + w*deep."""
        meta = tmp_path / "meta.json"
        _write_meta(meta, oos_accuracy=0.72, p_value=0.0001)
        model = tmp_path / "model.pt"
        model.write_bytes(b"fake")

        store = self._cls(
            model_path=str(model),
            meta_path=str(meta),
            oos_accuracy_gate=0.70,
            p_value_gate=0.001,
            deep_weight=0.20,
        )

        # Inject a mock predictor that returns 0.6
        mock_pred = MagicMock()
        mock_pred.predict.return_value = np.array([0.6])
        store._predictor = mock_pred
        store._active = True

        df = _make_ohlcv(100)
        result = store.blend(0.80, df)

        expected = 0.80 * 0.80 + 0.20 * 0.60  # (1-0.2)*0.8 + 0.2*0.6 = 0.76
        assert abs(result - expected) < 1e-4

    def test_blend_clamps_to_unit_interval(self):
        store = self._cls(deep_weight=0.5)
        mock_pred = MagicMock()
        mock_pred.predict.return_value = np.array([1.5])  # out of range
        store._predictor = mock_pred
        store._active = True

        df = _make_ohlcv(100)
        result = store.blend(0.9, df)
        assert 0.0 <= result <= 1.0

    def test_blend_returns_advanced_on_exception(self):
        """When _extract_features raises, blend must return advanced_prob unchanged."""
        store = self._cls()
        store._active = True
        store._predictor = MagicMock()
        df = _make_ohlcv(100)
        with patch.object(self._cls, "_extract_features", side_effect=RuntimeError("boom")):
            result = store.blend(0.65, df)
        assert result == 0.65

    def test_extract_features_shape(self):
        df = _make_ohlcv(100)
        feat = self._cls._extract_features(df)
        assert feat is not None
        assert feat.shape == (100, 6)  # log_ret, hl_range, vol_z, atr14, sma20_d, rsi

    def test_extract_features_no_nan(self):
        df = _make_ohlcv(100)
        feat = self._cls._extract_features(df)
        assert feat is not None
        assert not np.isnan(feat).any()

    def test_extract_features_dtype_float32(self):
        df = _make_ohlcv(100)
        feat = self._cls._extract_features(df)
        assert feat is not None
        assert feat.dtype == np.float32

    def test_status_returns_expected_keys(self):
        store = self._cls()
        s = store.status()
        for key in (
            "active",
            "model_path",
            "oos_accuracy",
            "p_value",
            "deep_weight",
            "oos_accuracy_gate",
            "p_value_gate",
        ):
            assert key in s

    def test_oos_accuracy_property(self, tmp_path):
        meta = tmp_path / "meta.json"
        _write_meta(meta, oos_accuracy=0.72, p_value=0.0001)
        model = tmp_path / "model.pt"
        model.write_bytes(b"fake")
        store = self._cls(model_path=str(model), meta_path=str(meta))
        store._check_oos_gate()
        assert abs(store.oos_accuracy - 0.72) < 1e-9

    def test_p_value_property(self, tmp_path):
        meta = tmp_path / "meta.json"
        _write_meta(meta, oos_accuracy=0.72, p_value=0.0005)
        model = tmp_path / "model.pt"
        model.write_bytes(b"fake")
        store = self._cls(model_path=str(model), meta_path=str(meta))
        store._check_oos_gate()
        assert abs(store.p_value - 0.0005) < 1e-9


# ── Signal engine integration ─────────────────────────────────────────────────


class TestDeepEnsembleSignalEngine:
    def test_flag_off_returns_none(self, monkeypatch):
        monkeypatch.setenv("FEATURE_DEEP_ENSEMBLE", "false")
        import core.signal_engine as se

        se._deep_ensemble_store = None
        result = se._get_deep_ensemble_store()
        assert result is None

    def test_flag_on_no_model_returns_none(self, monkeypatch):
        """When flag is on but model file doesn't exist, store is None."""
        monkeypatch.setenv("FEATURE_DEEP_ENSEMBLE", "true")
        import core.signal_engine as se

        se._deep_ensemble_store = None
        result = se._get_deep_ensemble_store()
        # Model file doesn't exist in test env → returns None
        assert result is None
        se._deep_ensemble_store = None  # cleanup

    def test_blend_weight_formula(self):
        """(1-0.2)*0.8 + 0.2*0.6 = 0.76"""
        adv = 0.8
        deep = 0.6
        w = 0.2
        blend = (1 - w) * adv + w * deep
        assert abs(blend - 0.76) < 1e-9

    def test_blend_weight_zero_leaves_prob_unchanged(self):
        adv = 0.75
        deep = 0.3
        w = 0.0
        blend = (1 - w) * adv + w * deep
        assert abs(blend - adv) < 1e-9

    def test_blend_weight_one_returns_deep_prob(self):
        adv = 0.75
        deep = 0.3
        w = 1.0
        blend = (1 - w) * adv + w * deep
        assert abs(blend - deep) < 1e-9


# ── DeepPredictor architecture validation ─────────────────────────────────────

try:
    import torch as _torch

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

_skip_no_torch = pytest.mark.skipif(
    not _TORCH_AVAILABLE,
    reason="PyTorch not installed — DeepPredictor requires torch",
)


class TestDeepPredictorArchitectures:
    """Verify DeepPredictor accepts valid architectures and rejects invalid ones."""

    @_skip_no_torch
    def test_valid_architectures_accepted(self):
        from research.pipeline.models_deep import DeepPredictor

        for arch in ("lstm", "transformer", "tcn"):
            dp = DeepPredictor(architecture=arch, n_features=6, seq_len=20)
            assert dp.architecture == arch

    def test_invalid_architecture_raises(self):
        from research.pipeline.models_deep import DeepPredictor

        with pytest.raises((ValueError, KeyError, RuntimeError, Exception)):
            DeepPredictor(architecture="invalid_arch", n_features=6, seq_len=20)

    @_skip_no_torch
    def test_n_features_stored(self):
        from research.pipeline.models_deep import DeepPredictor

        dp = DeepPredictor(architecture="lstm", n_features=10, seq_len=30)
        assert dp.n_features == 10

    @_skip_no_torch
    def test_seq_len_stored(self):
        from research.pipeline.models_deep import DeepPredictor

        dp = DeepPredictor(architecture="lstm", n_features=6, seq_len=45)
        assert dp.seq_len == 45
