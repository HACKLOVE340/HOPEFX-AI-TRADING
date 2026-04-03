# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_signal_engine_functions.py
==========================================
Unit tests for the pure helper functions inside core/signal_engine.py.

Coverage targets:
- ``_compute_signal()`` — consensus reached / not reached / None signal
- ``_compute_ml_probability()`` — advanced path, basic fallback, no model
- ``_predict_basic()`` — predict_proba, predict scalar, confidence fallback
- ``_apply_anomaly_weighting()`` — weight<1 blends, weight=1 passes, error
- ``_apply_online_blend()`` — ready/not-ready store, error path
- ``_apply_deep_ensemble_blend()`` — active/inactive store, error path
- ``_run_signal_filter()`` — pass, block, legacy fallback gate
- ``_compute_signal_strength()`` — position sizer path, fallback to ML prob
- ``_compute_atr()`` — enough bars, not enough bars
- ``_resolve_sl_tp()`` — signal has SL/TP, ATR path, fixed fallback
- ``get_signal_engine_status()`` — returns dict with all Phase keys
- ``_build_ohlcv_df()`` — correct DataFrame shape and last-bar overwrite
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_data(n: int = 30, close: float = 2000.0) -> dict:
    """Return a minimal data dict with n price bars."""
    prices = [close + float(i) * 0.1 for i in range(n)]
    return {
        "close": prices[-1],
        "open": prices[0],
        "high": max(prices),
        "low": min(prices),
        "volume": 100.0,
        "prices": prices,
        "highs": [p + 1.0 for p in prices],
        "lows": [p - 1.0 for p in prices],
        "volumes": [100.0] * n,
    }


def _make_strategy_brain(consensus: bool = True, direction: str = "BUY", confidence: float = 0.75):
    brain = MagicMock()
    if consensus:
        signal = MagicMock()
        signal.signal_type = MagicMock()
        signal.signal_type.value = direction
        signal.confidence = confidence
        brain.analyze_joint.return_value = {
            "consensus_reached": True,
            "consensus_signal": signal,
        }
    else:
        brain.analyze_joint.return_value = {
            "consensus_reached": False,
            "reason": "no_consensus",
        }
    return brain


# ─────────────────────────────────────────────────────────────────────────────
# _compute_signal
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeSignal:
    def test_consensus_reached_returns_dict(self):
        from core.signal_engine import _compute_signal

        brain = _make_strategy_brain(consensus=True, direction="BUY", confidence=0.75)
        result = _compute_signal(brain, _make_data(), "XAUUSD")
        assert result is not None
        assert result["direction"] == "BUY"
        assert abs(result["base_confidence"] - 0.75) < 1e-9
        assert result["signal"] is not None

    def test_no_consensus_returns_none(self):
        from core.signal_engine import _compute_signal

        brain = _make_strategy_brain(consensus=False)
        result = _compute_signal(brain, _make_data(), "XAUUSD")
        assert result is None

    def test_consensus_with_none_signal_returns_none(self):
        from core.signal_engine import _compute_signal

        brain = MagicMock()
        brain.analyze_joint.return_value = {
            "consensus_reached": True,
            "consensus_signal": None,
        }
        result = _compute_signal(brain, _make_data(), "XAUUSD")
        assert result is None

    def test_signal_type_without_value_attr(self):
        """Signal type that is a plain string (no .value) should still work."""
        from core.signal_engine import _compute_signal

        brain = MagicMock()
        signal = MagicMock(spec=["signal_type", "confidence"])
        signal.signal_type = "SELL"  # plain string, no .value
        signal.confidence = 0.6
        brain.analyze_joint.return_value = {
            "consensus_reached": True,
            "consensus_signal": signal,
        }
        result = _compute_signal(brain, _make_data(), "XAUUSD")
        assert result["direction"] == "SELL"


# ─────────────────────────────────────────────────────────────────────────────
# _build_ohlcv_df
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildOhlcvDf:
    def test_returns_dataframe_with_correct_shape(self):
        from core.signal_engine import _build_ohlcv_df

        data = _make_data(n=20)
        df = _build_ohlcv_df(data)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 20
        assert {"open", "high", "low", "close", "volume"}.issubset(df.columns)

    def test_last_bar_overwritten_with_actual_ohlcv(self):
        from core.signal_engine import _build_ohlcv_df

        data = _make_data(n=10, close=2100.0)
        data["open"] = 2090.0
        data["high"] = 2110.0
        data["low"] = 2085.0
        df = _build_ohlcv_df(data)
        assert df.iloc[-1]["close"] == 2100.0
        assert df.iloc[-1]["open"] == 2090.0
        assert df.iloc[-1]["high"] == 2110.0
        assert df.iloc[-1]["low"] == 2085.0

    def test_mismatched_highs_fallback_to_prices(self):
        from core.signal_engine import _build_ohlcv_df

        data = _make_data(n=5)
        data["highs"] = [1.0]  # wrong length
        df = _build_ohlcv_df(data)
        assert len(df) == 5


# ─────────────────────────────────────────────────────────────────────────────
# _compute_atr
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeAtr:
    def test_returns_fallback_when_insufficient_bars(self):
        from core.signal_engine import _ATR_FALLBACK_FRAC, _compute_atr

        atr = _compute_atr(highs=[1.0] * 5, lows=[0.9] * 5, closes=[0.95] * 5, entry_price=2000.0)
        assert abs(atr - 2000.0 * _ATR_FALLBACK_FRAC) < 1e-9

    def test_computes_positive_atr_with_enough_bars(self):
        from core.signal_engine import _compute_atr

        import numpy as np

        rng = np.random.default_rng(42)
        n = 30
        closes = (2000.0 + rng.standard_normal(n) * 10).tolist()
        highs = [c + 5 for c in closes]
        lows = [c - 5 for c in closes]
        atr = _compute_atr(highs, lows, closes, entry_price=closes[-1])
        assert atr > 0


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_sl_tp
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveSlTp:
    def test_uses_signal_provided_values_when_present(self):
        from core.signal_engine import _resolve_sl_tp

        signal = MagicMock()
        signal.stop_loss = 1980.0
        signal.take_profit = 2040.0
        sl, tp = _resolve_sl_tp(signal, {}, "BUY", 2000.0)
        assert sl == 1980.0
        assert tp == 2040.0

    def test_buy_sl_below_entry_tp_above_entry(self):
        from core.signal_engine import _resolve_sl_tp

        signal = MagicMock(spec=[])  # no stop_loss / take_profit
        sl, tp = _resolve_sl_tp(signal, _make_data(n=30), "BUY", 2000.0)
        assert sl < 2000.0
        assert tp > 2000.0

    def test_sell_sl_above_entry_tp_below_entry(self):
        from core.signal_engine import _resolve_sl_tp

        signal = MagicMock(spec=[])
        sl, tp = _resolve_sl_tp(signal, _make_data(n=30), "SELL", 2000.0)
        assert sl > 2000.0
        assert tp < 2000.0

    def test_fixed_fallback_used_on_empty_data(self):
        from core.signal_engine import _SL_FALLBACK_FRAC, _TP_FALLBACK_FRAC, _resolve_sl_tp

        signal = MagicMock(spec=[])
        sl, tp = _resolve_sl_tp(signal, {}, "BUY", 2000.0)
        # Fixed fallback: sl = entry * (1 - SL_FALLBACK_FRAC), tp = entry * (1 + TP_FALLBACK_FRAC)
        assert abs(sl - 2000.0 * (1 - _SL_FALLBACK_FRAC)) < 1e-3
        assert abs(tp - 2000.0 * (1 + _TP_FALLBACK_FRAC)) < 1e-3


# ─────────────────────────────────────────────────────────────────────────────
# _apply_anomaly_weighting (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyAnomalyWeighting:
    def test_returns_unchanged_when_store_is_none(self):
        from core.signal_engine import _apply_anomaly_weighting

        with patch("core.signal_engine._get_anomaly_store", return_value=None):
            result = _apply_anomaly_weighting(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65

    def test_blends_toward_neutral_when_weight_below_one(self):
        from core.signal_engine import _apply_anomaly_weighting

        store = MagicMock()
        store.update_and_score.return_value = 0.5  # half weight
        with patch("core.signal_engine._get_anomaly_store", return_value=store):
            result = _apply_anomaly_weighting(0.70, MagicMock(), "XAUUSD")
        # adjusted = 0.5 + (0.70 - 0.5) * 0.5 = 0.60
        assert abs(result - 0.60) < 1e-9

    def test_passes_through_when_weight_is_one(self):
        from core.signal_engine import _apply_anomaly_weighting

        store = MagicMock()
        store.update_and_score.return_value = 1.0
        with patch("core.signal_engine._get_anomaly_store", return_value=store):
            result = _apply_anomaly_weighting(0.70, MagicMock(), "XAUUSD")
        assert result == 0.70

    def test_exception_returns_original_prob(self):
        from core.signal_engine import _apply_anomaly_weighting

        store = MagicMock()
        store.update_and_score.side_effect = RuntimeError("store down")
        with patch("core.signal_engine._get_anomaly_store", return_value=store):
            result = _apply_anomaly_weighting(0.70, MagicMock(), "XAUUSD")
        assert result == 0.70


# ─────────────────────────────────────────────────────────────────────────────
# _apply_online_blend (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyOnlineBlend:
    def test_returns_unchanged_when_store_is_none(self):
        from core.signal_engine import _apply_online_blend

        with patch("core.signal_engine._get_online_learner_store", return_value=None):
            result = _apply_online_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65

    def test_returns_unchanged_when_store_not_ready(self):
        from core.signal_engine import _apply_online_blend

        store = MagicMock()
        store.is_ready = False
        with patch("core.signal_engine._get_online_learner_store", return_value=store):
            result = _apply_online_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65

    def test_blends_when_store_ready(self):
        from core.signal_engine import _apply_online_blend

        store = MagicMock()
        store.is_ready = True
        store.blend.return_value = 0.72
        with patch("core.signal_engine._get_online_learner_store", return_value=store):
            result = _apply_online_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.72

    def test_exception_returns_original_prob(self):
        from core.signal_engine import _apply_online_blend

        store = MagicMock()
        store.is_ready = True
        store.blend.side_effect = RuntimeError("blend down")
        with patch("core.signal_engine._get_online_learner_store", return_value=store):
            result = _apply_online_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65


# ─────────────────────────────────────────────────────────────────────────────
# _apply_deep_ensemble_blend (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyDeepEnsembleBlend:
    def test_returns_unchanged_when_store_is_none(self):
        from core.signal_engine import _apply_deep_ensemble_blend

        with patch("core.signal_engine._get_deep_ensemble_store", return_value=None):
            result = _apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65

    def test_returns_unchanged_when_store_not_active(self):
        from core.signal_engine import _apply_deep_ensemble_blend

        store = MagicMock()
        store.is_active = False
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=store):
            result = _apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65

    def test_blends_when_store_active(self):
        from core.signal_engine import _apply_deep_ensemble_blend

        store = MagicMock()
        store.is_active = True
        store.blend.return_value = 0.68
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=store):
            result = _apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.68

    def test_exception_returns_original_prob(self):
        from core.signal_engine import _apply_deep_ensemble_blend

        store = MagicMock()
        store.is_active = True
        store.blend.side_effect = RuntimeError("ensemble down")
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=store):
            result = _apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
        assert result == 0.65


# ─────────────────────────────────────────────────────────────────────────────
# _predict_basic
# ─────────────────────────────────────────────────────────────────────────────


class TestPredictBasic:
    def test_uses_predict_proba_when_available(self):
        from core.signal_engine import _predict_basic

        import numpy as np

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.35, 0.65]])
        prob, ver = _predict_basic(model, "v1", _make_data(), "XAUUSD", 0.5)
        assert abs(prob - 0.65) < 1e-9
        assert ver == "v1"

    def test_uses_predict_when_no_proba(self):
        from core.signal_engine import _predict_basic

        import numpy as np

        model = MagicMock(spec=["predict"])
        model.predict.return_value = np.array([0.72])
        prob, ver = _predict_basic(model, "v2", _make_data(), "XAUUSD", 0.5)
        assert abs(prob - 0.72) < 1e-9

    def test_falls_back_to_confidence_when_no_predict(self):
        from core.signal_engine import _predict_basic

        model = MagicMock(spec=[])  # no predict or predict_proba
        prob, ver = _predict_basic(model, "v3", _make_data(), "XAUUSD", 0.62)
        assert prob == 0.62

    def test_handles_short_price_series_gracefully(self):
        """Very short series (< 20 bars) must not raise."""
        from core.signal_engine import _predict_basic

        import numpy as np

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.4, 0.6]])
        data = _make_data(n=3)
        prob, _ = _predict_basic(model, "v1", data, "XAUUSD", 0.5)
        assert 0.0 <= prob <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# _compute_ml_probability
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeMlProbability:
    def test_returns_base_confidence_when_ml_unavailable(self):
        from core.signal_engine import _compute_ml_probability

        with patch("core.signal_engine._ML_AVAILABLE", False):
            prob, ver = _compute_ml_probability(_make_data(), "XAUUSD", 0.66)
        assert prob == 0.66
        assert ver == "none"

    def test_uses_advanced_predictor_when_available(self):
        from core.signal_engine import _compute_ml_probability

        adv = MagicMock()
        adv.is_available = True
        adv.version = "advanced_oos_v1"
        adv.predict_proba.return_value = 0.71

        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", return_value=adv),
        ):
            prob, ver = _compute_ml_probability(_make_data(n=120), "XAUUSD", 0.5)
        # We got a prob from the advanced path
        assert 0.0 <= prob <= 1.0

    def test_falls_back_to_basic_when_advanced_unavailable(self):
        from core.signal_engine import _compute_ml_probability

        import numpy as np

        adv = MagicMock()
        adv.is_available = False

        active = MagicMock()
        active.predict_proba.return_value = np.array([[0.4, 0.6]])

        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", return_value=adv),
            patch("core.signal_engine.get_active_model", return_value=active),
            patch("core.signal_engine.get_model_version", return_value="basic_v1"),
        ):
            prob, ver = _compute_ml_probability(_make_data(), "XAUUSD", 0.5)
        assert abs(prob - 0.6) < 1e-9
        assert ver == "basic_v1"

    def test_returns_base_confidence_when_no_model(self):
        from core.signal_engine import _compute_ml_probability

        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", return_value=None),
            patch("core.signal_engine.get_active_model", return_value=None),
            patch("core.signal_engine.get_model_version", return_value="none"),
        ):
            prob, ver = _compute_ml_probability(_make_data(), "XAUUSD", 0.55)
        assert prob == 0.55

    def test_exception_returns_base_confidence(self):
        from core.signal_engine import _compute_ml_probability

        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", side_effect=RuntimeError("model error")),
        ):
            prob, ver = _compute_ml_probability(_make_data(), "XAUUSD", 0.58)
        assert prob == 0.58
        assert ver == "none"


# ─────────────────────────────────────────────────────────────────────────────
# _run_signal_filter
# ─────────────────────────────────────────────────────────────────────────────


class TestRunSignalFilter:
    def _make_payload(self, probability: float = 0.70) -> dict:
        return {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "confidence": 0.72,
            "probability": probability,
        }

    def test_passing_filter_returns_true(self):
        from core.signal_engine import _run_signal_filter

        mock_result = MagicMock()
        mock_result.passed = True

        mock_filter = MagicMock()
        mock_filter.check.return_value = mock_result

        mock_module = MagicMock()
        mock_module.get_signal_filter.return_value = mock_filter

        with patch.dict("sys.modules", {"ml.signal_filter": mock_module}):
            result = _run_signal_filter(self._make_payload(), None, "XAUUSD")
        assert result is True

    def test_failing_filter_returns_false(self):
        from core.signal_engine import _run_signal_filter

        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.gate = "confidence"
        mock_result.reason = "below threshold"
        mock_result.confidence = 0.3

        mock_filter = MagicMock()
        mock_filter.check.return_value = mock_result

        mock_module = MagicMock()
        mock_module.get_signal_filter.return_value = mock_filter

        with patch.dict("sys.modules", {"ml.signal_filter": mock_module}):
            result = _run_signal_filter(self._make_payload(), None, "XAUUSD")
        assert result is False

    def test_fallback_gate_blocks_low_prob(self):
        """When signal_filter module is unavailable, use legacy ML prob gate."""
        from core.signal_engine import _run_signal_filter

        with (
            patch.dict("sys.modules", {"ml.signal_filter": None}),
            patch.dict(os.environ, {"ML_MIN_TRADE_PROB": "0.58"}),
        ):
            result = _run_signal_filter(self._make_payload(probability=0.40), None, "XAUUSD")
        assert result is False

    def test_fallback_gate_passes_high_prob(self):
        from core.signal_engine import _run_signal_filter

        with (
            patch.dict("sys.modules", {"ml.signal_filter": None}),
            patch.dict(os.environ, {"ML_MIN_TRADE_PROB": "0.58"}),
        ):
            result = _run_signal_filter(self._make_payload(probability=0.70), None, "XAUUSD")
        assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# _compute_signal_strength
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeSignalStrength:
    def _args(self, probability: float = 0.70):
        return dict(
            signal_payload={"probability": probability, "stop_loss": 1980.0},
            symbol="XAUUSD",
            direction="BUY",
            entry=2000.0,
            sl_price=1980.0,
            equity=100_000.0,
            data=_make_data(),
        )

    def test_position_sizer_lots_used(self):
        from core.signal_engine import _compute_signal_strength

        mock_sizer = MagicMock()
        mock_sizer.compute.return_value = 2.5

        mock_module = MagicMock()
        mock_module.get_position_sizer.return_value = mock_sizer

        with (
            patch.dict("sys.modules", {"ml.position_sizer": mock_module}),
            patch.dict(os.environ, {"MAX_LOTS": "10.0"}),
        ):
            strength = _compute_signal_strength(**self._args(probability=0.72))
        # lots / MAX_LOTS = 2.5 / 10 = 0.25
        assert abs(strength - 0.25) < 1e-9

    def test_fallback_when_position_sizer_unavailable(self):
        from core.signal_engine import _compute_signal_strength

        with patch.dict("sys.modules", {"ml.position_sizer": None}):
            strength = _compute_signal_strength(**self._args(probability=0.72))
        # fallback = min(ml_prob, 0.80) = 0.72
        assert abs(strength - 0.72) < 1e-9

    def test_fallback_caps_at_080(self):
        from core.signal_engine import _compute_signal_strength

        with patch.dict("sys.modules", {"ml.position_sizer": None}):
            strength = _compute_signal_strength(**self._args(probability=0.99))
        assert strength == 0.80

    def test_exception_in_sizer_falls_back(self):
        from core.signal_engine import _compute_signal_strength

        mock_sizer = MagicMock()
        mock_sizer.compute.side_effect = RuntimeError("sizer down")

        mock_module = MagicMock()
        mock_module.get_position_sizer.return_value = mock_sizer

        with patch.dict("sys.modules", {"ml.position_sizer": mock_module}):
            strength = _compute_signal_strength(**self._args(probability=0.65))
        assert abs(strength - 0.65) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# get_signal_engine_status
# ─────────────────────────────────────────────────────────────────────────────


class TestGetSignalEngineStatus:
    def test_returns_dict_with_required_keys(self):
        from core.signal_engine import get_signal_engine_status

        status = get_signal_engine_status()
        assert isinstance(status, dict)
        assert "ml_available" in status
        assert "symbols" in status
        assert "interval_seconds" in status
        assert "auto_trade" in status

    def test_phase_keys_present(self):
        from core.signal_engine import get_signal_engine_status

        status = get_signal_engine_status()
        # Phase 1–4 sections should be present (even if all fallback to "not ready")
        assert "phase2_anomaly" in status
        assert "phase3_online" in status
        assert "phase4_deep" in status

    def test_phase2_fallback_when_store_none(self):
        from core.signal_engine import get_signal_engine_status

        with patch("core.signal_engine._get_anomaly_store", return_value=None):
            status = get_signal_engine_status()
        assert status["phase2_anomaly"] == {"fitted": False}

    def test_phase3_fallback_when_store_none(self):
        from core.signal_engine import get_signal_engine_status

        with patch("core.signal_engine._get_online_learner_store", return_value=None):
            status = get_signal_engine_status()
        assert status["phase3_online"] == {"ready": False}

    def test_phase4_fallback_when_store_none(self):
        from core.signal_engine import get_signal_engine_status

        with patch("core.signal_engine._get_deep_ensemble_store", return_value=None):
            status = get_signal_engine_status()
        assert status["phase4_deep"] == {"active": False}

    def test_phase2_status_method_called_when_store_available(self):
        from core.signal_engine import get_signal_engine_status

        store = MagicMock()
        store.status.return_value = {"fitted": True, "n_samples": 500}

        with patch("core.signal_engine._get_anomaly_store", return_value=store):
            status = get_signal_engine_status()
        assert status["phase2_anomaly"]["fitted"] is True
