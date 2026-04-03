# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_sharpe_tracker_and_lstm.py

Unit tests for:
  - ml.train_advanced.SharpeProgressTracker
  - ml.lstm_signal_layer.LSTMSignalLayer  (model-absent / fallback paths)
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ml.train_advanced import SharpeProgressTracker, _sharpe_se, sharpe_gate_check

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(0)


def _make_returns(n: int, mean: float = 0.001, std: float = 0.01) -> list[float]:
    return RNG.normal(mean, std, n).tolist()


def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    """Minimal OHLCV DataFrame for LSTM layer tests."""
    closes = np.cumprod(1 + RNG.normal(0.0001, 0.005, n)) * 1800.0
    df = pd.DataFrame(
        {
            "open": closes * 0.999,
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": RNG.integers(1000, 5000, n).astype(float),
        }
    )
    return df


# ===========================================================================
# SharpeProgressTracker
# ===========================================================================


class TestSharpeProgressTrackerInit:
    def test_default_construction(self):
        t = SharpeProgressTracker()
        assert t.n_trades == 0
        assert not t.is_gate_passed

    def test_custom_params(self):
        t = SharpeProgressTracker(target_n=300, target_sharpe=1.0, annualise=8736)
        assert t._target_n == 300
        assert t._target_sharpe == 1.0
        assert t._annualise == 8736

    def test_invalid_target_n(self):
        with pytest.raises(ValueError, match="target_n"):
            SharpeProgressTracker(target_n=1)

    def test_invalid_annualise(self):
        with pytest.raises(ValueError, match="annualise"):
            SharpeProgressTracker(annualise=0)


class TestSharpeProgressTrackerUpdate:
    def test_single_trade_insufficient(self):
        t = SharpeProgressTracker()
        s = t.update(0.01)
        assert s["n_trades"] == 1
        assert s["gate_passed"] is False
        assert math.isinf(s["sharpe_se"])

    def test_two_trades_computes_sharpe(self):
        t = SharpeProgressTracker()
        t.update(0.01)
        s = t.update(-0.005)
        assert s["n_trades"] == 2
        assert isinstance(s["sharpe"], float)
        assert not math.isinf(s["sharpe_se"])

    def test_gate_not_passed_below_target_n(self):
        t = SharpeProgressTracker(target_n=600)
        for r in _make_returns(100, mean=0.005):
            t.update(r)
        s = t.status()
        assert s["n_trades"] == 100
        assert s["gate_passed"] is False
        assert s["pct_to_gate"] == pytest.approx(100 / 600 * 100, abs=0.1)

    def test_gate_passed_when_n_and_sharpe_met(self):
        # Use very high-return series to guarantee Sharpe > 1.5
        t = SharpeProgressTracker(target_n=10, target_sharpe=0.5)
        for r in _make_returns(10, mean=0.05, std=0.001):
            t.update(r)
        s = t.status()
        assert s["n_trades"] == 10
        assert s["gate_passed"] is True

    def test_gate_blocked_when_sharpe_too_low(self):
        # Enough trades but negative returns → Sharpe < target
        t = SharpeProgressTracker(target_n=5, target_sharpe=2.0)
        for r in _make_returns(5, mean=-0.01, std=0.001):
            t.update(r)
        s = t.status()
        assert s["gate_passed"] is False

    def test_pct_to_gate_caps_at_100(self):
        t = SharpeProgressTracker(target_n=5)
        for r in _make_returns(10):
            t.update(r)
        assert t.status()["pct_to_gate"] == 100.0

    def test_annualised_return_and_vol_positive(self):
        t = SharpeProgressTracker()
        for r in _make_returns(50, mean=0.001, std=0.005):
            t.update(r)
        s = t.status()
        assert s["annualised_return"] > 0
        assert s["annualised_vol"] > 0

    def test_zero_variance_returns_zero_sharpe(self):
        t = SharpeProgressTracker()
        for _ in range(10):
            t.update(0.001)  # identical returns → std=0
        s = t.status()
        # std=0 → annualised_vol=0 → sharpe=0 (guarded division)
        assert s["sharpe"] == 0.0


class TestSharpeProgressTrackerReset:
    def test_reset_clears_returns(self):
        t = SharpeProgressTracker()
        for r in _make_returns(20):
            t.update(r)
        assert t.n_trades == 20
        t.reset()
        assert t.n_trades == 0
        s = t.status()
        assert s["gate_passed"] is False

    def test_reset_then_reuse(self):
        t = SharpeProgressTracker(target_n=5, target_sharpe=0.1)
        for r in _make_returns(5, mean=0.05, std=0.001):
            t.update(r)
        assert t.is_gate_passed
        t.reset()
        assert not t.is_gate_passed


class TestSharpeProgressTrackerToDict:
    def test_to_dict_matches_status(self):
        t = SharpeProgressTracker()
        for r in _make_returns(10):
            t.update(r)
        assert t.to_dict() == t.status()


class TestSharpeProgressTrackerMessage:
    def test_message_contains_n_trades(self):
        t = SharpeProgressTracker()
        for r in _make_returns(5):
            t.update(r)
        assert "5" in t.status()["message"]

    def test_gate_passed_message(self):
        # Need N >= target_n AND SE <= 0.10 (requires ~600 trades at SR=1.52).
        # Use target_n=600 with high-return, low-vol series so Sharpe >> target.
        t = SharpeProgressTracker(target_n=600, target_sharpe=0.5, annualise=252)
        for r in _make_returns(600, mean=0.005, std=0.001):
            t.update(r)
        s = t.status()
        assert s["gate_passed"] is True
        assert "PASSED" in s["message"]


# ---------------------------------------------------------------------------
# sharpe_gate_check and _sharpe_se (existing helpers — regression guard)
# ---------------------------------------------------------------------------


class TestSharpeGateCheck:
    def test_blocked_below_target_n(self):
        result = sharpe_gate_check(n_trades=48, sharpe=1.52, target_n=600)
        assert result["gate_passed"] is False
        assert result["n_trades"] == 48
        assert result["se"] > 0.10

    def test_passed_at_target_n(self):
        result = sharpe_gate_check(n_trades=600, sharpe=1.52, target_n=600)
        assert result["gate_passed"] is True
        assert result["credible"] is True

    def test_se_decreases_with_more_trades(self):
        se_small = _sharpe_se(50)
        se_large = _sharpe_se(600)
        assert se_large < se_small

    def test_se_infinite_for_one_trade(self):
        assert math.isinf(_sharpe_se(1))

    def test_result_keys_present(self):
        r = sharpe_gate_check(100)
        for key in (
            "n_trades",
            "sharpe",
            "se",
            "credible",
            "gate_passed",
            "target_n",
            "n_required_for_se_010",
            "message",
        ):
            assert key in r


# ===========================================================================
# LSTMSignalLayer — model-absent / fallback paths
# ===========================================================================


class TestLSTMSignalLayerNoModel:
    """Tests that run without a trained model file — verify graceful fallback."""

    def setup_method(self):
        from ml.lstm_signal_layer import LSTMSignalLayer

        # Point at a path that definitely does not exist
        self.layer = LSTMSignalLayer(
            model_path="/tmp/nonexistent_lstm_signal.pt",
            seq_len=10,
            min_bars=20,
        )

    def test_is_available_false_without_model(self):
        assert self.layer.is_available() is False

    def test_predict_returns_neutral_without_model(self):
        ohlcv = _make_ohlcv(50)
        result = self.layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "neutral"
        assert result["abstain"] is True
        assert result["probability"] == 0.5

    def test_predict_returns_neutral_insufficient_bars(self):
        ohlcv = _make_ohlcv(5)  # fewer than min_bars=20
        result = self.layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_predict_result_has_required_keys(self):
        ohlcv = _make_ohlcv(50)
        result = self.layer.predict(ohlcv, symbol="XAUUSD")
        required = {
            "direction",
            "probability",
            "confidence",
            "high_confidence",
            "abstain",
            "model_version",
            "bars_used",
            "last_close",
            "feature_count",
            "latency_ms",
        }
        assert required.issubset(result.keys())

    def test_predict_probability_in_range(self):
        ohlcv = _make_ohlcv(50)
        result = self.layer.predict(ohlcv, symbol="XAUUSD")
        assert 0.0 <= result["probability"] <= 1.0

    def test_predict_confidence_in_range(self):
        ohlcv = _make_ohlcv(50)
        result = self.layer.predict(ohlcv, symbol="XAUUSD")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_stats_structure(self):
        stats = self.layer.stats
        assert "loaded" in stats
        assert "predict_count" in stats
        assert "abstain_rate" in stats
        assert stats["loaded"] is False

    def test_abstain_count_increments(self):
        ohlcv = _make_ohlcv(50)
        self.layer.predict(ohlcv)
        self.layer.predict(ohlcv)
        assert self.layer.stats["predict_count"] == 2
        assert self.layer.stats["abstain_count"] >= 2

    def test_load_attempted_only_once(self):
        """Model load should not be retried on every predict call."""
        ohlcv = _make_ohlcv(50)
        for _ in range(5):
            self.layer.predict(ohlcv)
        # _load_attempted is True after first attempt
        assert self.layer._load_attempted is True


class TestLSTMSignalLayerWithMockModel:
    """Tests with a mocked DeepPredictor to exercise the inference path."""

    def _make_layer_with_mock(self, proba: float):
        """Return a loaded LSTMSignalLayer backed by a mock predictor."""
        import pathlib
        import tempfile

        from ml.lstm_signal_layer import LSTMSignalLayer

        # Create a dummy file so _load() passes the existence check
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as tmp:
            model_path = pathlib.Path(tmp.name)

        layer = LSTMSignalLayer(model_path=model_path, seq_len=5, min_bars=10)

        # Inject mock predictor directly
        mock_pred = MagicMock()
        mock_pred.predict.return_value = np.array([proba])
        mock_pred.n_features = 8
        layer._predictor = mock_pred
        layer._loaded = True
        layer._load_attempted = True
        layer._n_features = 8

        return layer

    # build_advanced_features is imported inside _build_sequence via
    # "from ml.advanced_features import build_advanced_features", so we
    # patch it at its definition site.
    _FEAT_PATCH = "ml.advanced_features.build_advanced_features"

    def test_long_signal_above_threshold(self):
        layer = self._make_layer_with_mock(proba=0.75)
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            X = pd.DataFrame(RNG.normal(0, 1, (50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "long"
        assert result["abstain"] is False
        assert result["probability"] == pytest.approx(0.75, abs=0.01)

    def test_short_signal_below_threshold(self):
        layer = self._make_layer_with_mock(proba=0.20)
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            X = pd.DataFrame(RNG.normal(0, 1, (50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "short"
        assert result["abstain"] is False

    def test_neutral_in_dead_band(self):
        layer = self._make_layer_with_mock(proba=0.50)
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            X = pd.DataFrame(RNG.normal(0, 1, (50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_high_confidence_flag(self):
        layer = self._make_layer_with_mock(proba=0.90)
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            X = pd.DataFrame(RNG.normal(0, 1, (50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["high_confidence"] is True

    def test_latency_ms_is_positive(self):
        layer = self._make_layer_with_mock(proba=0.70)
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            X = pd.DataFrame(RNG.normal(0, 1, (50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["latency_ms"] >= 0.0

    def test_inference_exception_returns_neutral(self):
        layer = self._make_layer_with_mock(proba=0.70)
        layer._predictor.predict.side_effect = RuntimeError("GPU OOM")
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            X = pd.DataFrame(RNG.normal(0, 1, (50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "neutral"
        assert result["abstain"] is True

    def test_flat_market_returns_neutral(self):
        """Zero-variance sequence should abstain."""
        layer = self._make_layer_with_mock(proba=0.80)
        ohlcv = _make_ohlcv(50)
        with patch(self._FEAT_PATCH) as mock_feat:
            # All-zero features → std < 1e-6
            X = pd.DataFrame(np.zeros((50, 8)))
            mock_feat.return_value = (X, pd.Series(np.ones(50)))
            result = layer.predict(ohlcv, symbol="XAUUSD")
        assert result["direction"] == "neutral"
        assert result["abstain"] is True


# ===========================================================================
# get_lstm_signal_layer singleton
# ===========================================================================


class TestGetLSTMSignalLayerSingleton:
    def test_returns_same_instance(self):
        import ml.lstm_signal_layer as mod

        # Reset singleton for isolation
        mod._lstm_layer = None
        from ml.lstm_signal_layer import get_lstm_signal_layer

        a = get_lstm_signal_layer()
        b = get_lstm_signal_layer()
        assert a is b
        mod._lstm_layer = None  # clean up
