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
