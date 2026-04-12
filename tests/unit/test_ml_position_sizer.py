# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/position_sizer.py.
Covers all three sizing methods, edge cases, and singleton.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

import ml.position_sizer as ps_mod
from ml.position_sizer import PositionSizer, get_position_sizer


def _ohlcv(n: int = 20) -> pd.DataFrame:
    np.random.seed(7)
    c = 2000.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame(
        {
            "open": c - 0.5,
            "high": c + 1.0,
            "low": c - 1.0,
            "close": c,
            "volume": np.ones(n) * 1000,
        }
    )


class TestPositionSizerVolatility:
    def test_returns_min_lots_on_zero_equity(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"):
            result = s.compute("XAUUSD", "BUY", 2000.0, 1980.0, 0.0)
        assert result == ps_mod._MIN_LOTS

    def test_returns_min_lots_on_zero_price(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"):
            result = s.compute("XAUUSD", "BUY", 0.0, None, 100_000.0)
        assert result == ps_mod._MIN_LOTS

    def test_volatility_with_stop_loss(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"):
            result = s.compute("XAUUSD", "BUY", 2000.0, 1980.0, 100_000.0)
        assert ps_mod._MIN_LOTS <= result <= ps_mod._MAX_LOTS

    def test_volatility_without_stop_loss_uses_atr(self):
        s = PositionSizer()
        ohlcv = _ohlcv(20)
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"):
            result = s.compute("XAUUSD", "BUY", 2000.0, None, 100_000.0, ohlcv=ohlcv)
        assert ps_mod._MIN_LOTS <= result <= ps_mod._MAX_LOTS

    def test_volatility_fallback_when_sl_distance_zero(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"):
            # stop_loss == entry_price → sl_distance = 0 → fallback to ATR
            result = s.compute("XAUUSD", "BUY", 2000.0, 2000.0, 100_000.0)
        assert result >= ps_mod._MIN_LOTS

    def test_result_clamped_to_max_lots(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"), patch.object(ps_mod, "_MAX_LOTS", 0.05):
            result = s.compute("XAUUSD", "BUY", 2000.0, 1999.0, 10_000_000.0)
        assert result <= 0.05

    def test_result_clamped_to_min_lots(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "volatility"), patch.object(ps_mod, "_MIN_LOTS", 0.5):
            result = s.compute("XAUUSD", "BUY", 2000.0, 1980.0, 1.0)
        assert result >= 0.5


class TestPositionSizerKelly:
    def test_kelly_with_signal_filter_stats(self):
        s = PositionSizer()
        mock_filter = MagicMock()
        mock_filter.ev_stats.return_value = {"win_rate": 0.55, "avg_win": 0.02, "avg_loss": 0.01}
        mock_sf_module = MagicMock(get_signal_filter=MagicMock(return_value=mock_filter))
        with (
            patch.object(ps_mod, "_SIZING_METHOD", "kelly"),
            patch.dict("sys.modules", {"ml.signal_filter": mock_sf_module}),
        ):
            result = s.compute("XAUUSD", "BUY", 2000.0, None, 100_000.0, confidence=0.55)
        assert result >= ps_mod._MIN_LOTS

    def test_kelly_falls_back_when_signal_filter_unavailable(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "kelly"), patch.dict("sys.modules", {"ml.signal_filter": None}):
            result = s.compute("XAUUSD", "BUY", 2000.0, None, 100_000.0, confidence=0.6)
        assert result >= ps_mod._MIN_LOTS

    def test_kelly_negative_fraction_returns_fixed(self):
        s = PositionSizer()
        # win_rate=0.3 → negative Kelly → falls back to fixed
        mock_filter = MagicMock()
        mock_filter.ev_stats.return_value = {"win_rate": 0.30, "avg_win": 0.01, "avg_loss": 0.02}
        mock_sf_module = MagicMock(get_signal_filter=MagicMock(return_value=mock_filter))
        with (
            patch.object(ps_mod, "_SIZING_METHOD", "kelly"),
            patch.dict("sys.modules", {"ml.signal_filter": mock_sf_module}),
        ):
            result = s.compute("XAUUSD", "BUY", 2000.0, None, 100_000.0, confidence=0.3)
        assert result >= ps_mod._MIN_LOTS


class TestPositionSizerFixed:
    def test_fixed_sizing(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "fixed"):
            result = s.compute("XAUUSD", "BUY", 2000.0, None, 100_000.0)
        assert result >= ps_mod._MIN_LOTS

    def test_fixed_sizing_unknown_method_falls_back(self):
        s = PositionSizer()
        with patch.object(ps_mod, "_SIZING_METHOD", "unknown_method"):
            result = s.compute("XAUUSD", "BUY", 2000.0, None, 100_000.0)
        assert result >= ps_mod._MIN_LOTS


class TestAtrDistance:
    def test_atr_with_sufficient_ohlcv(self):
        ohlcv = _ohlcv(20)
        dist = PositionSizer._atr_distance(2000.0, ohlcv)
        assert dist > 0

    def test_atr_fallback_when_ohlcv_none(self):
        dist = PositionSizer._atr_distance(2000.0, None)
        assert dist > 0

    def test_atr_fallback_when_ohlcv_too_short(self):
        ohlcv = _ohlcv(5)
        dist = PositionSizer._atr_distance(2000.0, ohlcv)
        assert dist > 0


class TestSingleton:
    def test_get_position_sizer_returns_same_instance(self):
        ps_mod._SIZER_SINGLETON = None
        a = get_position_sizer()
        b = get_position_sizer()
        assert a is b
        assert isinstance(a, PositionSizer)
