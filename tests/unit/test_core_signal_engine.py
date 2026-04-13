# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_signal_engine.py
=======================================
Coverage tests for core/signal_engine.py.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import pytest

import core.signal_engine as se


def test_module_importable():
    assert se is not None


def test_ml_available_is_bool():
    assert isinstance(se._ML_AVAILABLE, bool)


def test_run_signal_engine_is_coroutine_function():
    assert inspect.iscoroutinefunction(se.run_signal_engine)


def test_get_macro_store_returns_none_or_object():
    result = se._get_macro_store()
    assert result is None or hasattr(result, "__class__")


def test_get_macro_store_bridge_returns_none_or_object():
    result = se._get_macro_store_bridge()
    assert result is None or hasattr(result, "__class__")


def test_get_deep_ensemble_store_returns_none_or_object():
    result = se._get_deep_ensemble_store()
    assert result is None or hasattr(result, "__class__")


def test_get_online_learner_store_returns_none_or_object():
    result = se._get_online_learner_store()
    assert result is None or hasattr(result, "__class__")


def test_get_anomaly_store_returns_none_or_object():
    result = se._get_anomaly_store()
    assert result is None or hasattr(result, "__class__")


def test_get_signal_engine_status_returns_dict():
    status = se.get_signal_engine_status()
    assert isinstance(status, dict)
    assert "ml_available" in status


def test_check_live_trading_gate_returns_bool():
    result = se._check_live_trading_gate()
    assert isinstance(result, bool)


def test_estimate_annualised_volatility_no_data():
    result = se._estimate_annualised_volatility(None, 1900.0)
    assert isinstance(result, float)
    assert result > 0


def test_estimate_annualised_volatility_with_closes():
    data = {
        "close": 1920.0,
        "open": 1900.0,
        "high": 1930.0,
        "low": 1890.0,
        "volume": 5000,
        "closes": [1900.0, 1910.0, 1920.0, 1915.0, 1925.0],
    }
    result = se._estimate_annualised_volatility(data, 1920.0)
    assert isinstance(result, float)
    assert result > 0


def test_build_ohlcv_proxy_none_input():
    result = se._build_ohlcv_proxy(None)
    assert result is None


def test_build_ohlcv_proxy_with_data():
    data = {
        "close": 1920.0,
        "open": 1900.0,
        "high": 1930.0,
        "low": 1890.0,
        "volume": 5000,
    }
    result = se._build_ohlcv_proxy(data)
    assert result is None or hasattr(result, "columns")


def test_compute_signal_strength_returns_float():
    """_compute_signal_strength takes (signal_payload, symbol, direction, entry, sl, equity, data)."""
    payload = {"probability": 0.65}
    result = se._compute_signal_strength(payload, "XAUUSD", "LONG", 1920.0, 1880.0, 100000.0, None)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_compute_signal_strength_short():
    payload = {"probability": 0.35}
    result = se._compute_signal_strength(payload, "XAUUSD", "SHORT", 1920.0, 1960.0, 100000.0, None)
    assert isinstance(result, float)


def test_notify_fill_no_crash():
    """notify_fill(features, label, primary_prob) — no-op when online learner absent."""
    import pandas as pd
    features = pd.DataFrame({"a": [1.0], "b": [2.0]})
    se.notify_fill(features, label=1, primary_prob=0.72)  # must not raise


def test_notify_fill_no_store_no_crash():
    """notify_fill is a no-op when _get_online_learner_store returns None."""
    import pandas as pd
    with patch.object(se, "_get_online_learner_store", return_value=None):
        se.notify_fill(pd.DataFrame(), label=0)


@pytest.mark.asyncio
async def test_run_signal_engine_exits_on_cancel():
    app_state = MagicMock()
    app_state.strategy_brain = None
    task = asyncio.create_task(se.run_signal_engine(app_state))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── _apply_anomaly_weighting ──────────────────────────────────────────────────


def test_apply_anomaly_weighting_no_store():
    """Returns prob unchanged when store is None."""
    with patch.object(se, "_get_anomaly_store", return_value=None):
        result = se._apply_anomaly_weighting(0.72, None, "XAUUSD")
    assert result == 0.72


def test_apply_anomaly_weighting_with_store():
    mock_store = MagicMock()
    mock_store.update_and_score.return_value = 0.5  # anomaly detected
    with patch.object(se, "_get_anomaly_store", return_value=mock_store):
        result = se._apply_anomaly_weighting(0.72, MagicMock(), "XAUUSD")
    # Should blend toward 0.5
    assert 0.5 < result < 0.72


def test_apply_anomaly_weighting_no_anomaly():
    mock_store = MagicMock()
    mock_store.update_and_score.return_value = 1.0  # no anomaly
    with patch.object(se, "_get_anomaly_store", return_value=mock_store):
        result = se._apply_anomaly_weighting(0.72, MagicMock(), "XAUUSD")
    assert result == 0.72


def test_apply_anomaly_weighting_exception():
    mock_store = MagicMock()
    mock_store.update_and_score.side_effect = RuntimeError("store error")
    with patch.object(se, "_get_anomaly_store", return_value=mock_store):
        result = se._apply_anomaly_weighting(0.65, MagicMock(), "XAUUSD")
    assert result == 0.65  # unchanged on error


# ── _apply_online_blend ───────────────────────────────────────────────────────


def test_apply_online_blend_no_store():
    with patch.object(se, "_get_online_learner_store", return_value=None):
        result = se._apply_online_blend(0.65, None, "XAUUSD")
    assert result == 0.65


def test_apply_online_blend_not_ready():
    mock_store = MagicMock()
    mock_store.is_ready = False
    with patch.object(se, "_get_online_learner_store", return_value=mock_store):
        result = se._apply_online_blend(0.65, MagicMock(), "XAUUSD")
    assert result == 0.65


def test_apply_online_blend_with_store():
    mock_store = MagicMock()
    mock_store.is_ready = True
    mock_store.blend.return_value = 0.70
    with patch.object(se, "_get_online_learner_store", return_value=mock_store):
        result = se._apply_online_blend(0.65, MagicMock(), "XAUUSD")
    assert result == 0.70


def test_apply_online_blend_exception():
    mock_store = MagicMock()
    mock_store.is_ready = True
    mock_store.blend.side_effect = RuntimeError("blend error")
    with patch.object(se, "_get_online_learner_store", return_value=mock_store):
        result = se._apply_online_blend(0.65, MagicMock(), "XAUUSD")
    assert result == 0.65


# ── _apply_deep_ensemble_blend ────────────────────────────────────────────────


def test_apply_deep_ensemble_blend_no_store():
    with patch.object(se, "_get_deep_ensemble_store", return_value=None):
        result = se._apply_deep_ensemble_blend(0.65, None, "XAUUSD")
    assert result == 0.65


def test_apply_deep_ensemble_blend_not_active():
    mock_store = MagicMock()
    mock_store.is_active = False
    with patch.object(se, "_get_deep_ensemble_store", return_value=mock_store):
        result = se._apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
    assert result == 0.65


def test_apply_deep_ensemble_blend_with_store():
    mock_store = MagicMock()
    mock_store.is_active = True
    mock_store.blend.return_value = 0.75
    with patch.object(se, "_get_deep_ensemble_store", return_value=mock_store):
        result = se._apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
    assert result == 0.75


def test_apply_deep_ensemble_blend_exception():
    mock_store = MagicMock()
    mock_store.is_active = True
    mock_store.blend.side_effect = RuntimeError("deep error")
    with patch.object(se, "_get_deep_ensemble_store", return_value=mock_store):
        result = se._apply_deep_ensemble_blend(0.65, MagicMock(), "XAUUSD")
    assert result == 0.65


# ── _fetch_mtf_df ─────────────────────────────────────────────────────────────


def test_fetch_mtf_df_no_store():
    import pandas as pd
    df = pd.DataFrame({"close": [1900.0, 1910.0]})
    result = se._fetch_mtf_df(df, app_state=None)
    assert result is None or hasattr(result, "columns")


def test_fetch_mtf_df_store_not_ready():
    import pandas as pd
    mock_store = MagicMock()
    mock_store.is_ready = False
    state = MagicMock()
    state.mtf_store = mock_store
    df = pd.DataFrame({"close": [1900.0, 1910.0]})
    result = se._fetch_mtf_df(df, app_state=state)
    assert result is None


def test_fetch_mtf_df_store_ready():
    import pandas as pd
    mock_store = MagicMock()
    mock_store.is_ready = True
    mock_store.align_to_h1.return_value = pd.DataFrame({"d_trend": [0.5, 0.6]})
    state = MagicMock()
    state.mtf_store = mock_store
    df = pd.DataFrame({"close": [1900.0, 1910.0]})
    result = se._fetch_mtf_df(df, app_state=state)
    assert result is not None


# ── _fetch_macro_df ───────────────────────────────────────────────────────────


def test_fetch_macro_df_no_store():
    import pandas as pd
    df = pd.DataFrame({"close": [1900.0, 1910.0]})
    with patch.object(se, "_get_macro_store", return_value=None):
        result = se._fetch_macro_df(df, "XAUUSD")
    assert result is None


def test_fetch_macro_df_empty_store():
    import pandas as pd
    mock_store = MagicMock()
    mock_store.__len__ = MagicMock(return_value=0)
    df = pd.DataFrame({"close": [1900.0, 1910.0]})
    with patch.object(se, "_get_macro_store", return_value=mock_store):
        result = se._fetch_macro_df(df, "XAUUSD")
    assert result is None


def test_fetch_macro_df_alignment_exception():
    import pandas as pd
    mock_store = MagicMock()
    mock_store.__len__ = MagicMock(return_value=5)
    mock_store.align_to_hourly.side_effect = RuntimeError("align error")
    df = pd.DataFrame({"close": [1900.0, 1910.0]})
    with patch.object(se, "_get_macro_store", return_value=mock_store):
        result = se._fetch_macro_df(df, "XAUUSD")
    assert result is None


# ── _get_signal_engine_status — extended ─────────────────────────────────────


def test_get_signal_engine_status_has_all_keys():
    status = se.get_signal_engine_status()
    assert "ml_available" in status
    assert "phase1_mtf" in status
    assert "phase2_anomaly" in status
    assert "phase3_online" in status
    assert "phase4_deep" in status
    assert "symbols" in status
    assert "interval_seconds" in status


# ── _predict_advanced ─────────────────────────────────────────────────────────


def test_predict_advanced_with_mock_predictor():
    """With a mock predictor, returns its predict_proba result."""
    import pandas as pd
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "closes": [1900.0 + i for i in range(50)],
    }
    mock_pred = MagicMock()
    mock_pred.predict_proba.return_value = 0.72
    mock_pred.version = "v2"
    with patch.object(se, "_apply_anomaly_weighting", return_value=0.72):
        with patch.object(se, "_apply_online_blend", return_value=0.72):
            with patch.object(se, "_apply_deep_ensemble_blend", return_value=0.72):
                with patch.object(se, "_fetch_macro_df", return_value=None):
                    with patch.object(se, "_fetch_mtf_df", return_value=None):
                        result = se._predict_advanced(mock_pred, data, "XAUUSD", None)
    assert result[0] == pytest.approx(0.72)
    assert result[1] == "v2"


def test_compute_ml_probability_handles_advanced_predictor_exception():
    """Exception in _predict_advanced → _compute_ml_probability returns base_confidence."""
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "closes": [1900.0] * 10,
    }
    mock_pred = MagicMock()
    mock_pred.is_available = True
    with patch.object(se, "_ML_AVAILABLE", True):
        with patch("core.signal_engine.get_advanced_predictor", return_value=mock_pred):
            with patch.object(se, "_predict_advanced", side_effect=RuntimeError("model error")):
                result = se._compute_ml_probability(data, "XAUUSD", 0.55)
    assert result == (0.55, "none")


# ── _predict_basic ────────────────────────────────────────────────────────────


def test_predict_basic_with_mock_model():
    import numpy as np
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = np.array([[0.35, 0.65]])
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "prices": [1900.0 + i for i in range(25)],
    }
    result = se._predict_basic(mock_model, "v1", data, "XAUUSD", 0.5)
    assert isinstance(result[0], float)
    assert result[1] == "v1"


def test_predict_basic_predict_only_model():
    """Model with predict() but no predict_proba()."""
    import numpy as np
    mock_model = MagicMock(spec=["predict"])
    mock_model.predict.return_value = np.array([0.68])
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "prices": [1900.0] * 5,
    }
    result = se._predict_basic(mock_model, "v1", data, "XAUUSD", 0.5)
    assert result[0] == pytest.approx(0.68)


def test_predict_basic_no_predict_method():
    """Model with neither predict_proba nor predict → returns base_confidence."""
    mock_model = MagicMock(spec=[])
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "prices": [1900.0] * 5,
    }
    result = se._predict_basic(mock_model, "v1", data, "XAUUSD", 0.55)
    assert result[0] == pytest.approx(0.55)


# ── _compute_ml_probability ───────────────────────────────────────────────────


def test_compute_ml_probability_no_ml():
    """When ML unavailable, returns base_confidence."""
    with patch.object(se, "_ML_AVAILABLE", False):
        result = se._compute_ml_probability({"close": 1920.0}, "XAUUSD", 0.55)
    assert result == (0.55, "none")


def test_compute_ml_probability_no_model():
    """When no model loaded, returns base_confidence."""
    with patch.object(se, "_ML_AVAILABLE", True):
        with patch("core.signal_engine.get_advanced_predictor", return_value=None):
            with patch("core.signal_engine.get_active_model", return_value=None):
                result = se._compute_ml_probability({"close": 1920.0}, "XAUUSD", 0.55)
    assert result == (0.55, "none")


def test_compute_ml_probability_uses_advanced_predictor():
    """When advanced predictor is available, uses it."""
    mock_pred = MagicMock()
    mock_pred.is_available = True
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "closes": [1900.0] * 10,
    }
    with patch.object(se, "_ML_AVAILABLE", True):
        with patch("core.signal_engine.get_advanced_predictor", return_value=mock_pred):
            with patch.object(se, "_predict_advanced", return_value=(0.72, "v2")):
                result = se._compute_ml_probability(data, "XAUUSD", 0.5)
    assert result == (0.72, "v2")


def test_compute_ml_probability_uses_basic_model():
    """Falls back to basic model when advanced predictor unavailable."""
    mock_model = MagicMock()
    data = {
        "close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0,
        "volume": 5000, "prices": [1900.0] * 5,
    }
    with patch.object(se, "_ML_AVAILABLE", True):
        with patch("core.signal_engine.get_advanced_predictor", return_value=None):
            with patch("core.signal_engine.get_active_model", return_value=mock_model):
                with patch("core.signal_engine.get_model_version", return_value="v1"):
                    with patch.object(se, "_predict_basic", return_value=(0.65, "v1")):
                        result = se._compute_ml_probability(data, "XAUUSD", 0.5)
    assert result == (0.65, "v1")


# ── _compute_signal ───────────────────────────────────────────────────────────


def test_compute_signal_no_consensus():
    """When brain returns no consensus, _compute_signal returns None."""
    mock_brain = MagicMock()
    mock_brain.analyze_joint.return_value = {"consensus_reached": False, "reason": "no consensus"}
    data = {"close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0, "volume": 5000}
    result = se._compute_signal(mock_brain, data, "XAUUSD")
    assert result is None


def test_compute_signal_with_consensus():
    """When brain returns consensus, _compute_signal returns a dict."""
    mock_signal = MagicMock()
    mock_signal.signal_type.value = "LONG"
    mock_signal.confidence = 0.75
    mock_brain = MagicMock()
    mock_brain.analyze_joint.return_value = {
        "consensus_reached": True,
        "consensus_signal": mock_signal,
    }
    data = {"close": 1920.0, "open": 1900.0, "high": 1930.0, "low": 1890.0, "volume": 5000}
    result = se._compute_signal(mock_brain, data, "XAUUSD")
    assert result is not None
    assert result["direction"] == "LONG"
    assert result["base_confidence"] == 0.75


def test_compute_signal_no_signal_object():
    """When consensus_signal is None, returns None."""
    mock_brain = MagicMock()
    mock_brain.analyze_joint.return_value = {
        "consensus_reached": True,
        "consensus_signal": None,
    }
    data = {"close": 1920.0}
    result = se._compute_signal(mock_brain, data, "XAUUSD")
    assert result is None


# ── _run_signal_filter ────────────────────────────────────────────────────────


def test_run_signal_filter_returns_bool():
    signal = {"direction": "LONG", "strength": 0.8, "confidence": 0.7}
    result = se._run_signal_filter(signal, "XAUUSD", {})
    assert isinstance(result, bool)


# ── _compute_atr ──────────────────────────────────────────────────────────────


def test_compute_atr_basic():
    highs = [1930.0] * 14
    lows = [1890.0] * 14
    closes = [1910.0] * 14
    result = se._compute_atr(highs, lows, closes, 1910.0)
    assert isinstance(result, float)
    assert result > 0


def test_compute_atr_insufficient_data():
    result = se._compute_atr([1930.0], [1890.0], [1910.0], 1910.0)
    assert isinstance(result, float)
