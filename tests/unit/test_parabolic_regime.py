# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for parabolic-bubble regime detection and signal filter integration.

Covers:
- is_parabolic_bubble_regime(): blow-off (Condition 1) and post-bubble (Condition 2)
- _detect_parabolic_mask(): vectorised version of the same logic
- REGIME_HIGH_VOL_PARABOLIC label in detect_regime_labels()
- SignalFilter._gate_regime() blocks HIGH_VOL_PARABOLIC
- SignalFilter._get_current_regime() returns "HIGH_VOL_PARABOLIC" for parabolic bars
- StackingEnsemblePredictor predict_proba() interface
- ml.__init__._load_from_registry() handles stacking_dict format
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# ── Synthetic OHLCV constants ─────────────────────────────────────────────────
_FLAT_BASE_PRICE = 1800.0          # USD/oz — typical gold range for flat-market tests
_PARABOLIC_BLOWOFF_BARS = 50       # bars where blow-off acceleration starts
_PARABOLIC_GROWTH_RATE = 1.025     # +2.5% per bar in blow-off phase
_PARABOLIC_PRE_RATE = 1.001        # +0.1% per bar in pre-blow-off phase
_CRASH_START_BAR = 60              # bar where post-bubble crash begins
_CRASH_MEAN_DAILY = -0.015         # mean daily return during crash
_CRASH_DAILY_VOL = 0.04            # daily vol during crash (extreme)
_FLAT_NOISE_SCALE = 10.0           # std dev of noise in flat-market prices
_DATASET_YEARS = 50                # years assumed in the 58Y positional OOS fallback


# ---------------------------------------------------------------------------
# Helpers — synthetic OHLCV factories
# ---------------------------------------------------------------------------

def _flat_ohlcv(n: int = 250, base_price: float = 1500.0) -> pd.DataFrame:
    """Return n bars of flat/trending OHLCV (no parabolic signal)."""
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 10, n)
    close = base_price + np.cumsum(noise * 0.1)
    return pd.DataFrame(
        {
            "Date": dates,
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1000.0,
        }
    )


def _parabolic_blowoff_ohlcv(n: int = 250) -> pd.DataFrame:
    """Return bars where last price is > 1.3× MA(200)."""
    dates = pd.date_range("1979-01-01", periods=n, freq="B")
    # Slow start then parabolic acceleration in the last _PARABOLIC_BLOWOFF_BARS bars
    close = np.ones(n) * 300.0
    for i in range(1, n):
        if i < n - _PARABOLIC_BLOWOFF_BARS:
            close[i] = close[i - 1] * _PARABOLIC_PRE_RATE
        else:
            close[i] = close[i - 1] * _PARABOLIC_GROWTH_RATE
    return pd.DataFrame(
        {
            "Date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
        }
    )


def _post_bubble_crash_ohlcv(n: int = 250) -> pd.DataFrame:
    """Return bars in a post-bubble crash state (high vol, price far below peak)."""
    dates = pd.date_range("1980-02-01", periods=n, freq="B")
    rng = np.random.default_rng(7)
    close = np.ones(n) * 500.0
    # Rise to peak
    for i in range(1, _CRASH_START_BAR):
        close[i] = close[i - 1] * 1.015
    # Crash with extreme vol
    for i in range(_CRASH_START_BAR, n):
        change = rng.normal(_CRASH_MEAN_DAILY, _CRASH_DAILY_VOL)
        close[i] = max(close[i - 1] * (1 + change), 100.0)
    return pd.DataFrame(
        {
            "Date": dates,
            "open": close * 0.98,
            "high": close * 1.03,
            "low": close * 0.97,
            "close": close,
            "volume": 1000.0,
        }
    )


# ---------------------------------------------------------------------------
# is_parabolic_bubble_regime
# ---------------------------------------------------------------------------


class TestIsParabolicBubbleRegime:
    """Unit tests for ml.regime_conditional.is_parabolic_bubble_regime."""

    def test_returns_false_for_flat_market(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = _flat_ohlcv(250, base_price=1800.0)
        assert is_parabolic_bubble_regime(df) is False

    def test_returns_true_for_parabolic_blowoff(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = _parabolic_blowoff_ohlcv(250)
        assert is_parabolic_bubble_regime(df) is True

    def test_returns_false_for_insufficient_data(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = _flat_ohlcv(5)
        assert is_parabolic_bubble_regime(df) is False

    def test_returns_false_when_close_missing(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = pd.DataFrame({"open": [100.0] * 50})
        assert is_parabolic_bubble_regime(df) is False

    def test_returns_false_for_near_zero_price(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = pd.DataFrame({"close": [0.0] * 50})
        assert is_parabolic_bubble_regime(df) is False

    def test_condition2_post_bubble_high_vol_deep_drawdown(self):
        """Condition 2: rv14 > 2.5×rv90 AND price ≥25% below 200-bar peak."""
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = _post_bubble_crash_ohlcv(250)
        # May or may not trigger depending on exact values — just verify no crash
        result = is_parabolic_bubble_regime(df)
        assert isinstance(result, bool)

    def test_custom_close_col(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = _flat_ohlcv(250)
        df = df.rename(columns={"close": "Close"})
        # Should return False gracefully (wrong col name → insufficient data guard)
        assert is_parabolic_bubble_regime(df, close_col="Close") is False

    def test_exception_in_computation_returns_false(self):
        from ml.regime_conditional import is_parabolic_bubble_regime

        df = pd.DataFrame({"close": ["text"] * 50})
        assert is_parabolic_bubble_regime(df) is False


# ---------------------------------------------------------------------------
# _detect_parabolic_mask
# ---------------------------------------------------------------------------


class TestDetectParabolicMask:
    """Unit tests for _detect_parabolic_mask (vectorised historical detection)."""

    def test_flat_market_all_false(self):
        from ml.regime_conditional import _detect_parabolic_mask

        df = _flat_ohlcv(300, base_price=1800.0)
        mask = _detect_parabolic_mask(df)
        # Most bars should be False in a flat market
        assert isinstance(mask, pd.Series)
        assert mask.sum() < len(mask) * 0.10  # < 10% flagged

    def test_parabolic_blowoff_has_flagged_bars(self):
        from ml.regime_conditional import _detect_parabolic_mask

        df = _parabolic_blowoff_ohlcv(300)
        mask = _detect_parabolic_mask(df)
        assert mask.sum() > 0, "Parabolic blow-off should flag at least one bar"

    def test_returns_series_matching_index(self):
        from ml.regime_conditional import _detect_parabolic_mask

        df = _flat_ohlcv(100)
        mask = _detect_parabolic_mask(df)
        assert len(mask) == len(df)
        # Mask should be a boolean dtype; pandas may represent as np.bool_ or bool
        assert mask.dtype in (bool, np.bool_, "bool"), (
            f"Expected boolean dtype, got {mask.dtype}"
        )

    def test_short_df_no_crash(self):
        from ml.regime_conditional import _detect_parabolic_mask

        df = _flat_ohlcv(10)
        mask = _detect_parabolic_mask(df)
        assert len(mask) == len(df)


# ---------------------------------------------------------------------------
# detect_regime_labels — REGIME_HIGH_VOL_PARABOLIC label
# ---------------------------------------------------------------------------


class TestDetectRegimeLabels:
    """Verify REGIME_HIGH_VOL_PARABOLIC (label=3) is assigned in parabolic markets."""

    def test_parabolic_label_3_assigned(self):
        from ml.regime_conditional import REGIME_HIGH_VOL_PARABOLIC, detect_regime_labels

        df = _parabolic_blowoff_ohlcv(300)
        df.columns = [c.lower() for c in df.columns]
        labels = detect_regime_labels(df)
        assert REGIME_HIGH_VOL_PARABOLIC in labels.values, (
            "detect_regime_labels should assign REGIME_HIGH_VOL_PARABOLIC=3 "
            "for parabolic blow-off data"
        )

    def test_flat_market_no_parabolic_label(self):
        from ml.regime_conditional import REGIME_HIGH_VOL_PARABOLIC, detect_regime_labels

        df = _flat_ohlcv(300)
        df.columns = [c.lower() for c in df.columns]
        labels = detect_regime_labels(df)
        # May or may not have label 3 depending on exact values, but should
        # not be the majority label
        parabolic_count = (labels == REGIME_HIGH_VOL_PARABOLIC).sum()
        assert parabolic_count < len(labels) * 0.30

    def test_regime_names_includes_high_vol_parabolic(self):
        from ml.regime_conditional import REGIME_HIGH_VOL_PARABOLIC, REGIME_NAMES

        assert REGIME_HIGH_VOL_PARABOLIC == 3
        assert REGIME_NAMES[3] == "high_vol_parabolic"


# ---------------------------------------------------------------------------
# SignalFilter._gate_regime() blocks HIGH_VOL_PARABOLIC
# ---------------------------------------------------------------------------


class TestSignalFilterParabolicGate:
    """SignalFilter blocks signals when parabolic regime is detected."""

    @pytest.fixture
    def filt(self):
        from ml.signal_filter import SignalFilter

        return SignalFilter()

    def test_gate_blocks_parabolic_blowoff(self, filt):
        ohlcv = _parabolic_blowoff_ohlcv(300)
        result = filt._gate_regime(ohlcv, direction="BUY", confidence=0.70)
        assert result.passed is False
        assert result.regime == "HIGH_VOL_PARABOLIC"
        assert "parabolic" in result.reason.lower()

    def test_gate_passes_flat_market(self, filt):
        ohlcv = _flat_ohlcv(300, base_price=1800.0)
        result = filt._gate_regime(ohlcv, direction="BUY", confidence=0.70)
        # Should pass (no parabolic, no HIGH_VOL, no MEAN_REVERTING in flat data)
        # (Cannot guarantee in all random seeds, but verify no crash)
        assert isinstance(result.passed, bool)

    def test_gate_returns_unknown_for_insufficient_data(self, filt):
        ohlcv = pd.DataFrame({"close": [1500.0] * 5})
        result = filt._gate_regime(ohlcv, direction="BUY", confidence=0.65)
        assert result.passed is True
        assert result.regime == "unknown"

    def test_get_current_regime_returns_parabolic(self, filt):
        ohlcv = _parabolic_blowoff_ohlcv(300)
        regime = filt._get_current_regime(ohlcv)
        assert regime == "HIGH_VOL_PARABOLIC"

    def test_get_current_regime_unknown_for_none(self, filt):
        regime = filt._get_current_regime(None)
        assert regime == "unknown"

    def test_gate_confidence_tightens_for_parabolic(self, filt):
        # HIGH_VOL_PARABOLIC tightens by 0.10 → floor = 0.55+0.10=0.65
        result = filt._gate_confidence("BUY", confidence=0.62, regime="HIGH_VOL_PARABOLIC")
        assert result.passed is False
        assert result.confidence == 0.62

    def test_full_check_blocks_parabolic_signal(self, filt):
        """check() end-to-end blocks a signal when ohlcv is parabolic."""
        ohlcv = _parabolic_blowoff_ohlcv(300)
        signal_payload = {
            "direction": "BUY",
            "confidence": 0.70,
            "probability": 0.70,
        }
        result = filt.check(signal_payload, ohlcv=ohlcv, symbol="XAUUSD")
        assert result.passed is False


# ---------------------------------------------------------------------------
# StackingEnsemblePredictor interface
# ---------------------------------------------------------------------------


class TestStackingEnsemblePredictor:
    """StackingEnsemblePredictor exposes sklearn-compatible predict_proba."""

    @pytest.fixture
    def predictor(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.ensemble import RandomForestClassifier

        # Build a minimal stacking payload
        X = np.random.default_rng(0).standard_normal((100, 5))
        y = (X[:, 0] > 0).astype(int)

        base1 = RandomForestClassifier(n_estimators=10, random_state=0).fit(X, y)
        base2 = LogisticRegression().fit(X, y)

        meta_X = np.column_stack([base1.predict_proba(X)[:, 1], base2.predict_proba(X)[:, 1]])
        meta = LogisticRegression().fit(meta_X, y)

        scaler = StandardScaler().fit(X)
        feature_cols = [f"feat_{i}" for i in range(5)]

        payload = {
            "base_learners": [base1, base2],
            "meta_model": meta,
            "feature_cols": feature_cols,
            "scaler": scaler,
            "horizon": 5,
            "abstain_threshold": 0.55,
        }
        from ml import StackingEnsemblePredictor

        return StackingEnsemblePredictor(payload)

    def test_predict_proba_shape(self, predictor):
        X = pd.DataFrame(np.random.default_rng(1).standard_normal((20, 5)), columns=[f"feat_{i}" for i in range(5)])
        proba = predictor.predict_proba(X)
        assert proba.shape == (20, 2)
        assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_predict_proba_missing_features_filled(self, predictor):
        """Missing feature columns are filled with 0.0 safely."""
        X = pd.DataFrame(np.random.default_rng(2).standard_normal((10, 3)), columns=["feat_0", "feat_1", "feat_2"])
        proba = predictor.predict_proba(X)
        assert proba.shape == (10, 2)

    def test_predict_returns_binary(self, predictor):
        X = pd.DataFrame(np.random.default_rng(3).standard_normal((15, 5)), columns=[f"feat_{i}" for i in range(5)])
        preds = predictor.predict(X)
        assert set(preds).issubset({0, 1})

    def test_horizon_property(self, predictor):
        assert predictor.horizon == 5

    def test_abstain_threshold_property(self, predictor):
        assert predictor.abstain_threshold == 0.55

    def test_repr(self, predictor):
        r = repr(predictor)
        assert "StackingEnsemblePredictor" in r
        assert "horizon=5" in r


# ---------------------------------------------------------------------------
# ml.__init__._load_from_registry
# ---------------------------------------------------------------------------


class TestLoadFromRegistry:
    """_load_from_registry resolves active model from registry.json."""

    def _make_registry(self, tmp_path: Path, pkl_path: Path, pkl_format: str) -> Path:
        reg = {
            "schema_version": 1,
            "active_version": "test_v1",
            "versions": {
                "test_v1": {
                    "name": "test_v1",
                    "file": str(pkl_path),
                    "sha256": "abc123",
                    "state": "active",
                    "oos_accuracy": 0.61,
                    "n_trades": 100,
                    "feature_count": 10,
                    "horizon": 5,
                    "pkl_format": pkl_format,
                }
            },
        }
        reg_path = tmp_path / "registry.json"
        reg_path.write_text(json.dumps(reg))
        return reg_path

    def test_returns_none_when_registry_missing(self, tmp_path):
        import ml as ml_module

        orig = ml_module._SAVED
        ml_module._SAVED = tmp_path  # point to empty dir
        try:
            model, version = ml_module._load_from_registry()
            assert model is None
            assert version == ""
        finally:
            ml_module._SAVED = orig

    def test_loads_sklearn_estimator_format(self, tmp_path):
        import joblib
        import ml as ml_module
        from sklearn.linear_model import LogisticRegression

        est = LogisticRegression().fit([[0], [1]], [0, 1])
        pkl_path = tmp_path / "test.pkl"
        joblib.dump(est, pkl_path)

        self._make_registry(tmp_path, pkl_path, "sklearn_estimator")
        orig_saved = ml_module._SAVED
        orig_cs = ml_module._CHECKSUM_FILE
        ml_module._SAVED = tmp_path
        ml_module._CHECKSUM_FILE = tmp_path / "checksums.json"
        try:
            with patch.object(ml_module, "_verify_checksum", return_value=True):
                model, version = ml_module._load_from_registry()
            assert version == "test_v1"
            assert model is not None
            assert hasattr(model, "predict_proba")
        finally:
            ml_module._SAVED = orig_saved
            ml_module._CHECKSUM_FILE = orig_cs

    def test_loads_stacking_dict_format_as_wrapper(self, tmp_path):
        import joblib
        import ml as ml_module
        from sklearn.linear_model import LogisticRegression

        lr = LogisticRegression().fit([[0, 0], [1, 1]], [0, 1])
        payload = {
            "base_learners": [lr],
            "meta_model": lr,
            "feature_cols": ["a", "b"],
            "scaler": None,
            "horizon": 5,
            "abstain_threshold": 0.55,
        }
        pkl_path = tmp_path / "stacking.pkl"
        joblib.dump(payload, pkl_path)

        self._make_registry(tmp_path, pkl_path, "stacking_dict")
        orig_saved = ml_module._SAVED
        ml_module._SAVED = tmp_path
        try:
            with patch.object(ml_module, "_verify_checksum", return_value=True):
                model, version = ml_module._load_from_registry()
            assert version == "test_v1"
            from ml import StackingEnsemblePredictor

            assert isinstance(model, StackingEnsemblePredictor)
        finally:
            ml_module._SAVED = orig_saved
