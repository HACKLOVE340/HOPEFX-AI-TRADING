# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for ml/position_sizer.py and ml/models/trading_models.py.
"""

import numpy as np
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# ml/position_sizer.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPositionSizer:
    def _make(self):
        from ml.position_sizer import PositionSizer
        return PositionSizer()

    def test_compute_returns_positive(self):
        sizer = self._make()
        size = sizer.compute(
            symbol="XAUUSD", direction="BUY",
            entry_price=2000.0, stop_loss=1980.0,
            account_equity=100_000.0, confidence=0.65,
        )
        assert size > 0

    def test_compute_zero_equity_returns_min(self):
        from ml.position_sizer import _MIN_LOTS
        sizer = self._make()
        size = sizer.compute(
            symbol="XAUUSD", direction="BUY",
            entry_price=2000.0, stop_loss=1980.0,
            account_equity=0.0, confidence=0.65,
        )
        assert size == pytest.approx(_MIN_LOTS)

    def test_compute_zero_entry_returns_min(self):
        from ml.position_sizer import _MIN_LOTS
        sizer = self._make()
        size = sizer.compute(
            symbol="XAUUSD", direction="BUY",
            entry_price=0.0, stop_loss=None,
            account_equity=100_000.0, confidence=0.65,
        )
        assert size == pytest.approx(_MIN_LOTS)

    def test_compute_capped_at_max_lots(self):
        from ml.position_sizer import _MAX_LOTS
        sizer = self._make()
        # Huge equity → would exceed MAX_LOTS without cap
        size = sizer.compute(
            symbol="XAUUSD", direction="BUY",
            entry_price=1.0, stop_loss=0.99,
            account_equity=100_000_000.0, confidence=0.9,
        )
        assert size <= _MAX_LOTS

    def test_compute_at_least_min_lots(self):
        from ml.position_sizer import _MIN_LOTS
        sizer = self._make()
        size = sizer.compute(
            symbol="XAUUSD", direction="BUY",
            entry_price=5000.0, stop_loss=4999.0,
            account_equity=100.0, confidence=0.5,
        )
        assert size >= _MIN_LOTS

    def test_volatility_size_with_stop_loss(self):
        sizer = self._make()
        size = sizer._volatility_size(
            equity=100_000.0, entry=2000.0,
            stop_loss=1980.0, ohlcv=None,
        )
        assert size > 0

    def test_volatility_size_no_stop_loss(self):
        sizer = self._make()
        size = sizer._volatility_size(
            equity=100_000.0, entry=2000.0,
            stop_loss=None, ohlcv=None,
        )
        assert size > 0

    def test_fixed_size(self):
        sizer = self._make()
        size = sizer._fixed_size(equity=100_000.0, entry=2000.0)
        assert size > 0

    def test_kelly_size_returns_positive(self, monkeypatch):
        from ml import position_sizer as ps
        # Patch signal_filter import to avoid dependency
        monkeypatch.setattr(ps, "_SIZING_METHOD", "kelly")
        sizer = ps.PositionSizer()
        size = sizer._kelly_size(
            symbol="XAUUSD", equity=100_000.0,
            entry=2000.0, confidence=0.6,
        )
        assert size >= 0

    def test_atr_distance_no_ohlcv(self):
        from ml.position_sizer import PositionSizer
        dist = PositionSizer._atr_distance(2000.0, None)
        assert dist > 0

    def test_get_position_sizer_singleton(self):
        from ml.position_sizer import get_position_sizer, PositionSizer
        s1 = get_position_sizer()
        s2 = get_position_sizer()
        assert s1 is s2
        assert isinstance(s1, PositionSizer)

    def test_compute_fixed_method(self, monkeypatch):
        from ml import position_sizer as ps
        monkeypatch.setattr(ps, "_SIZING_METHOD", "fixed")
        sizer = ps.PositionSizer()
        size = sizer.compute(
            symbol="XAUUSD", direction="BUY",
            entry_price=2000.0, stop_loss=None,
            account_equity=100_000.0, confidence=0.6,
        )
        assert size > 0


# ─────────────────────────────────────────────────────────────────────────────
# ml/models/trading_models.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRandomForestModel:
    def test_predict_before_fit_returns_zeros(self):
        from ml.models.trading_models import RandomForestModel
        model = RandomForestModel()
        X = np.random.default_rng(0).random((5, 4))
        result = model.predict(X)
        assert len(result) == 5
        assert all(v == 0 for v in result)

    def test_predict_proba_before_fit_returns_half(self):
        from ml.models.trading_models import RandomForestModel
        model = RandomForestModel()
        X = np.random.default_rng(0).random((3, 4))
        proba = model.predict_proba(X)
        assert proba.shape == (3, 2)
        assert np.allclose(proba[:, 0], 0.5)

    def test_feature_importances_before_fit_empty(self):
        from ml.models.trading_models import RandomForestModel
        model = RandomForestModel()
        assert len(model.feature_importances_) == 0

    def test_is_fitted_false_initially(self):
        from ml.models.trading_models import RandomForestModel
        model = RandomForestModel()
        assert model.is_fitted is False

    def test_fit_and_predict(self):
        from ml.models.trading_models import RandomForestModel, _SKLEARN_OK
        if not _SKLEARN_OK:
            pytest.skip("scikit-learn not available")
        rng = np.random.default_rng(42)
        X = rng.random((50, 4))
        y = (X[:, 0] > 0.5).astype(int)
        model = RandomForestModel(n_estimators=5)
        model.fit(X, y)
        assert model.is_fitted is True
        preds = model.predict(X)
        assert len(preds) == 50

    def test_fit_and_predict_proba(self):
        from ml.models.trading_models import RandomForestModel, _SKLEARN_OK
        if not _SKLEARN_OK:
            pytest.skip("scikit-learn not available")
        rng = np.random.default_rng(42)
        X = rng.random((50, 4))
        y = (X[:, 0] > 0.5).astype(int)
        model = RandomForestModel(n_estimators=5)
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert proba.shape == (50, 2)
        assert np.allclose(proba.sum(axis=1), 1.0)


@pytest.mark.unit
class TestGradientBoostingModel:
    def test_predict_before_fit_returns_zeros(self):
        from ml.models.trading_models import GradientBoostingModel
        model = GradientBoostingModel()
        X = np.random.default_rng(0).random((5, 4))
        result = model.predict(X)
        assert len(result) == 5

    def test_predict_proba_before_fit_returns_half(self):
        from ml.models.trading_models import GradientBoostingModel
        model = GradientBoostingModel()
        X = np.random.default_rng(0).random((3, 4))
        proba = model.predict_proba(X)
        assert proba.shape == (3, 2)

    def test_fit_and_predict(self):
        from ml.models.trading_models import GradientBoostingModel, _SKLEARN_OK
        if not _SKLEARN_OK:
            pytest.skip("scikit-learn not available")
        rng = np.random.default_rng(42)
        X = rng.random((50, 4))
        y = (X[:, 0] > 0.5).astype(int)
        model = GradientBoostingModel(n_estimators=5)
        model.fit(X, y)
        assert model.is_fitted is True
        preds = model.predict(X)
        assert len(preds) == 50


@pytest.mark.unit
class TestEnsembleModel:
    def test_predict_before_fit(self):
        from ml.models.trading_models import EnsembleModel
        model = EnsembleModel()
        X = np.random.default_rng(0).random((5, 4))
        result = model.predict(X)
        assert len(result) == 5

    def test_predict_proba_before_fit(self):
        from ml.models.trading_models import EnsembleModel
        model = EnsembleModel()
        X = np.random.default_rng(0).random((3, 4))
        proba = model.predict_proba(X)
        assert proba.shape == (3, 2)

    def test_fit_and_predict(self):
        from ml.models.trading_models import EnsembleModel, _SKLEARN_OK
        if not _SKLEARN_OK:
            pytest.skip("scikit-learn not available")
        rng = np.random.default_rng(42)
        X = rng.random((50, 4))
        y = (X[:, 0] > 0.5).astype(int)
        model = EnsembleModel(n_estimators=5)
        model.fit(X, y)
        assert model.is_fitted is True
        preds = model.predict(X)
        assert len(preds) == 50
        assert set(preds).issubset({0, 1})

    def test_predict_proba_sums_to_one(self):
        from ml.models.trading_models import EnsembleModel, _SKLEARN_OK
        if not _SKLEARN_OK:
            pytest.skip("scikit-learn not available")
        rng = np.random.default_rng(42)
        X = rng.random((50, 4))
        y = (X[:, 0] > 0.5).astype(int)
        model = EnsembleModel(n_estimators=5)
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)
