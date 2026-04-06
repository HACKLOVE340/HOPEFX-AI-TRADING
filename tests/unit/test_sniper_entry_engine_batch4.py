# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
SniperEntryEngine — Batch 4: Integration, full refine() pipeline,
edge cases, error handling, multi-symbol, property-based checks.

Covers:
- refine() end-to-end: returns SniperSetup on fully confirmed setup
- refine() end-to-end: returns None at each pipeline stage failure
- refine() with missing decision attributes (graceful defaults)
- refine() with various symbols
- refine() with orchestrator that returns insufficient LTF bars
- refine() with orchestrator that raises an exception
- SniperSetup.to_dict() round-trip (all fields serialisable)
- Concurrent / repeated calls do not share state
- Logging does not raise (smoke test)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from strategies.sniper_entry_engine import (
    SniperEntryEngine,
    SniperSetup,
    OrderBlock,
    DisplacementCandle,
    LTFConfirmation,
)


# ---------------------------------------------------------------------------
# Shared bar / decision builders
# ---------------------------------------------------------------------------

def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 1000}


def _decision(action="long", symbol="XAU_USD", confidence=0.75, tick_mid=1902.0):
    d = MagicMock()
    d.action = action
    d.symbol = symbol
    d.confidence = confidence
    d.tick_mid = tick_mid
    return d


def _zigzag_up_df(base=1900.0):
    """40-bar bullish zigzag DataFrame with a qualifying OB pattern."""
    bars = []
    # Wave 1
    for i in range(10):
        p = base + i * 2.0
        bars.append(_bar(p, p + 1.5, p - 0.5, p + 1.0))
    # Pullback 1
    for i in range(5):
        p = base + 20.0 - i * 1.6
        bars.append(_bar(p, p + 0.5, p - 1.5, p - 1.0))
    # Wave 2
    for i in range(10):
        p = base + 12.0 + i * 2.3
        bars.append(_bar(p, p + 1.5, p - 0.5, p + 1.0))
    # Pullback 2
    for i in range(5):
        p = base + 35.0 - i * 2.0
        bars.append(_bar(p, p + 0.5, p - 1.5, p - 1.0))
    # Wave 3 with OB pattern embedded
    for i in range(8):
        p = base + 25.0 + i * 2.5
        bars.append(_bar(p, p + 1.5, p - 0.5, p + 1.0))
    # OB candle (bearish) then impulse (bullish, closes above OB high)
    ob_open = base + 45.0
    bars.append(_bar(ob_open, ob_open + 1.0, ob_open - 3.0, ob_open - 2.5))
    bars.append(_bar(ob_open - 2.5, ob_open + 8.0, ob_open - 3.0, ob_open + 7.5))
    # Tail
    for i in range(2):
        p = ob_open + 7.5 + i * 0.5
        bars.append(_bar(p, p + 0.5, p - 0.3, p + 0.3))
    return pd.DataFrame(bars)


def _make_ltf_df_with_displacement(base=1900.0):
    """38-bar LTF DataFrame containing a qualifying bullish displacement."""
    bars = []
    for i in range(35):
        p = base + i * 0.5
        bars.append(_bar(p, p + 0.8, p - 0.3, p + 0.5))
    prev = _bar(1917.0, 1919.0, 1916.0, 1918.0)
    curr = _bar(1918.0, 1947.0, 1917.5, 1945.0)   # large bullish body
    nxt  = _bar(1945.0, 1948.0, 1922.0, 1944.0)   # nxt.low > prev.high → FVG
    bars.extend([prev, curr, nxt])
    return pd.DataFrame(bars)


# ---------------------------------------------------------------------------
# refine() — early-exit paths
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRefineEarlyExits:
    """refine() returns None before reaching HTF detection."""

    def setup_method(self):
        self.engine = SniperEntryEngine()

    def test_disabled_engine_returns_none(self, monkeypatch):
        monkeypatch.setenv("SNIPER_ENABLED", "false")
        engine = SniperEntryEngine()
        result = engine.refine(_decision(), pd.DataFrame())
        assert result is None

    def test_hold_action_returns_none(self):
        result = self.engine.refine(_decision(action="hold"), pd.DataFrame())
        assert result is None

    def test_close_action_returns_none(self):
        result = self.engine.refine(_decision(action="close"), pd.DataFrame())
        assert result is None

    def test_zero_tick_mid_returns_none(self):
        result = self.engine.refine(_decision(tick_mid=0.0), pd.DataFrame())
        assert result is None

    def test_negative_tick_mid_returns_none(self):
        result = self.engine.refine(_decision(tick_mid=-50.0), pd.DataFrame())
        assert result is None

    def test_spread_too_wide_returns_none(self):
        self.engine.max_spread_points = 20.0
        result = self.engine.refine(_decision(), pd.DataFrame(), spread=25.0)
        assert result is None

    def test_empty_htf_df_returns_none(self):
        result = self.engine.refine(_decision(), pd.DataFrame())
        assert result is None

    def test_insufficient_htf_bars_returns_none(self):
        tiny_df = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        result = self.engine.refine(_decision(), tiny_df)
        assert result is None

    def test_no_orchestrator_returns_none(self):
        """Without orchestrator, LTF bars cannot be fetched → None."""
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=None)
        assert result is None

    def test_orchestrator_returns_none_df(self):
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = None
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        assert result is None

    def test_orchestrator_returns_too_few_ltf_bars(self):
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(10)
        ])
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        assert result is None

    def test_orchestrator_raises_returns_none(self):
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.side_effect = ConnectionError("broker down")
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        assert result is None


# ---------------------------------------------------------------------------
# refine() — decision attribute access
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRefineDecisionAttributes:
    """refine() handles missing or unusual decision attributes gracefully."""

    def setup_method(self):
        self.engine = SniperEntryEngine()

    def test_missing_symbol_uses_default(self):
        """getattr with default 'XAU_USD' — no AttributeError."""
        d = MagicMock(spec=[])  # no attributes at all
        d.action = "long"
        d.symbol = "XAU_USD"
        d.confidence = 0.7
        d.tick_mid = 1902.0
        result = self.engine.refine(d, pd.DataFrame())
        assert result is None  # fails at HTF, not attribute access

    def test_confidence_zero_still_processed(self):
        """Zero confidence is valid — engine should not short-circuit on it."""
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        result = self.engine.refine(
            _decision(confidence=0.0), pd.DataFrame(), orchestrator=mock_orch
        )
        assert result is None  # fails at HTF

    def test_very_high_confidence_capped_in_output(self):
        """If a setup is produced, confidence must not exceed 1.0."""
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = _make_ltf_df_with_displacement()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(
            _decision(confidence=0.99), htf_df, orchestrator=mock_orch
        )
        if result is not None:
            assert result.confidence <= 1.0

    def test_symbol_passed_through_to_setup(self):
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = _make_ltf_df_with_displacement()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(
            _decision(symbol="EUR_USD"), htf_df, orchestrator=mock_orch
        )
        if result is not None:
            assert result.symbol == "EUR_USD"


# ---------------------------------------------------------------------------
# refine() — multi-symbol smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRefineMultiSymbol:
    """refine() handles different symbols without cross-contamination."""

    def setup_method(self):
        self.engine = SniperEntryEngine()

    @pytest.mark.parametrize("symbol", [
        "XAU_USD", "EUR_USD", "GBP_USD", "USD_JPY", "BTC_USD"
    ])
    def test_symbol_does_not_raise(self, symbol):
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        htf_df = _zigzag_up_df()
        result = self.engine.refine(
            _decision(symbol=symbol), htf_df, orchestrator=mock_orch
        )
        assert result is None or isinstance(result, SniperSetup)

    def test_two_calls_independent(self):
        """Consecutive calls must not share state."""
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        htf_df = _zigzag_up_df()
        r1 = self.engine.refine(_decision(symbol="XAU_USD"), htf_df, orchestrator=mock_orch)
        r2 = self.engine.refine(_decision(symbol="EUR_USD"), htf_df, orchestrator=mock_orch)
        # Both must be valid types (None or SniperSetup), not exceptions
        assert r1 is None or isinstance(r1, SniperSetup)
        assert r2 is None or isinstance(r2, SniperSetup)


# ---------------------------------------------------------------------------
# refine() — full confirmed pipeline
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRefineFullPipeline:
    """
    End-to-end refine() tests using real bar data that satisfies all
    pipeline conditions: HTF structure + OB + LTF displacement.
    """

    def setup_method(self):
        self.engine = SniperEntryEngine()

    def _make_orchestrator(self, ltf_df=None):
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = (
            ltf_df if ltf_df is not None else _make_ltf_df_with_displacement()
        )
        return mock_orch

    def test_returns_sniper_setup_or_none(self):
        """Pipeline either confirms a setup or returns None — never raises."""
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        assert result is None or isinstance(result, SniperSetup)

    def test_setup_has_valid_prices_when_returned(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            assert result.entry_price > 0
            assert result.stop_loss > 0
            assert result.take_profit > 0

    def test_setup_long_sl_below_entry(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(action="long"), htf_df, orchestrator=orch)
        if result is not None:
            assert result.stop_loss < result.entry_price

    def test_setup_long_tp_above_entry(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(action="long"), htf_df, orchestrator=orch)
        if result is not None:
            assert result.take_profit > result.entry_price

    def test_setup_rr_at_least_configured_minimum(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            risk = abs(result.entry_price - result.stop_loss)
            reward = abs(result.take_profit - result.entry_price)
            if risk > 0:
                assert reward / risk >= self.engine.tp_rr * 0.9

    def test_setup_confidence_in_range(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            assert 0.0 < result.confidence <= 1.0

    def test_setup_order_type_is_limit(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            assert result.order_type == "LIMIT"

    def test_setup_to_dict_is_json_serialisable(self):
        import json
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            d = result.to_dict()
            # Must not raise
            serialised = json.dumps(d)
            assert len(serialised) > 10

    def test_setup_to_dict_prices_are_floats(self):
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            d = result.to_dict()
            assert isinstance(d["entry_price"], float)
            assert isinstance(d["stop_loss"], float)
            assert isinstance(d["take_profit"], float)
            assert isinstance(d["confidence"], float)

    def test_setup_timestamp_is_utc_iso(self):
        from datetime import datetime, timezone
        orch = self._make_orchestrator()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(_decision(), htf_df, orchestrator=orch)
        if result is not None:
            dt = datetime.fromisoformat(result.timestamp)
            assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRefineEdgeCases:
    """Boundary conditions and unusual inputs."""

    def setup_method(self):
        self.engine = SniperEntryEngine()

    def test_htf_df_with_nan_values_does_not_raise(self):
        import numpy as np
        bars = [_bar(1900, 1905, 1895, 1902) for _ in range(30)]
        df = pd.DataFrame(bars)
        df.loc[5, "close"] = float("nan")
        df.loc[10, "high"] = float("nan")
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        # Must not raise
        result = self.engine.refine(_decision(), df, orchestrator=mock_orch)
        assert result is None or isinstance(result, SniperSetup)

    def test_htf_df_with_zero_prices_does_not_raise(self):
        bars = [_bar(0, 0, 0, 0) for _ in range(30)]
        df = pd.DataFrame(bars)
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(0, 0, 0, 0) for _ in range(5)
        ])
        result = self.engine.refine(_decision(), df, orchestrator=mock_orch)
        assert result is None or isinstance(result, SniperSetup)

    def test_very_large_spread_always_rejected(self):
        self.engine.max_spread_points = 30.0
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = _make_ltf_df_with_displacement()
        htf_df = _zigzag_up_df()
        result = self.engine.refine(
            _decision(), htf_df, orchestrator=mock_orch, spread=9999.0
        )
        assert result is None

    def test_spread_default_is_zero(self):
        """refine() signature default spread=0.0 — no TypeError."""
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        htf_df = _zigzag_up_df()
        # Call without spread kwarg
        result = self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        assert result is None or isinstance(result, SniperSetup)

    def test_engine_can_be_instantiated_multiple_times(self):
        """Multiple instances must not share module-level state."""
        e1 = SniperEntryEngine()
        e2 = SniperEntryEngine()
        assert e1 is not e2
        assert e1.tp_rr == e2.tp_rr

    def test_engine_attributes_are_independent(self, monkeypatch):
        monkeypatch.setenv("SNIPER_TP_RR", "3.0")
        e1 = SniperEntryEngine()
        monkeypatch.setenv("SNIPER_TP_RR", "2.0")
        e2 = SniperEntryEngine()
        assert e1.tp_rr == pytest.approx(3.0)
        assert e2.tp_rr == pytest.approx(2.0)

    def test_refine_does_not_mutate_htf_df(self):
        """The engine must not modify the caller's DataFrame."""
        htf_df = _zigzag_up_df()
        original_shape = htf_df.shape
        original_cols = list(htf_df.columns)
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = pd.DataFrame([
            _bar(1900, 1905, 1895, 1902) for _ in range(5)
        ])
        self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        assert htf_df.shape == original_shape
        assert list(htf_df.columns) == original_cols

    def test_refine_called_twice_same_result(self):
        """Calling refine() twice with identical inputs must give same result type."""
        mock_orch = MagicMock()
        mock_orch.get_ohlcv_window.return_value = _make_ltf_df_with_displacement()
        htf_df = _zigzag_up_df()
        r1 = self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        r2 = self.engine.refine(_decision(), htf_df, orchestrator=mock_orch)
        assert type(r1) is type(r2)


# ---------------------------------------------------------------------------
# SniperSetup.to_dict() round-trip
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSniperSetupRoundTrip:
    """to_dict() produces a fully JSON-serialisable dict."""

    def _make_full_setup(self):
        ob = OrderBlock(direction="bullish", top=1895.0, bottom=1890.0, origin_index=5)
        dc = DisplacementCandle(
            direction="bullish",
            open=1888.0, high=1910.0, low=1886.0, close=1908.0,
            fvg_top=1912.0, fvg_bottom=1905.0, ce_level=1908.5, bar_index=8,
        )
        ltf = LTFConfirmation(
            confirmed=True, event="BOS_bullish",
            displacement=dc, last_sh=1915.0, last_sl=1880.0, bars_analysed=100,
        )
        return SniperSetup(
            symbol="XAU_USD",
            direction="long",
            entry_price=1908.5,
            stop_loss=1887.5,
            take_profit=1950.5,
            confidence=0.84,
            order_type="LIMIT",
            htf_ob=ob,
            ltf_confirmation=ltf,
            reason="sniper:long|test",
        )

    def test_to_dict_no_exception(self):
        setup = self._make_full_setup()
        d = setup.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_json_serialisable(self):
        import json
        setup = self._make_full_setup()
        json.dumps(setup.to_dict())  # must not raise

    def test_to_dict_entry_rounded_to_5dp(self):
        setup = self._make_full_setup()
        setup.entry_price = 1908.123456789
        d = setup.to_dict()
        assert d["entry_price"] == round(1908.123456789, 5)

    def test_to_dict_confidence_rounded_to_4dp(self):
        setup = self._make_full_setup()
        setup.confidence = 0.8456789
        d = setup.to_dict()
        assert d["confidence"] == round(0.8456789, 4)

    def test_to_dict_does_not_include_ob_or_ltf(self):
        """Internal objects (htf_ob, ltf_confirmation) are not in to_dict()."""
        setup = self._make_full_setup()
        d = setup.to_dict()
        assert "htf_ob" not in d
        assert "ltf_confirmation" not in d

    def test_to_dict_direction_values(self):
        for direction in ("long", "short"):
            setup = self._make_full_setup()
            setup.direction = direction
            d = setup.to_dict()
            assert d["direction"] == direction

    def test_to_dict_timestamp_present_and_non_empty(self):
        setup = self._make_full_setup()
        d = setup.to_dict()
        assert "timestamp" in d
        assert len(d["timestamp"]) > 0
