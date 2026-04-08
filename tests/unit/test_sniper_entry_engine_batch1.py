# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
SniperEntryEngine — Batch 1: Initialization, config loading, dataclass validation.

Covers:
- SniperEntryEngine.__init__ with default env vars
- SniperEntryEngine.__init__ with custom env vars
- _env_float / _env_int / _env_bool helpers
- OrderBlock, DisplacementCandle, LTFConfirmation, SniperSetup dataclasses
- SniperSetup.to_dict() serialisation
- Engine disabled path (SNIPER_ENABLED=false)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from strategies.sniper_entry_engine import (
    DisplacementCandle,
    LTFConfirmation,
    OrderBlock,
    SniperEntryEngine,
    SniperSetup,
    _env_bool,
    _env_float,
    _env_int,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_sniper_env(monkeypatch):
    """Remove all SNIPER_* env vars so defaults are exercised cleanly."""
    keys = [
        "SNIPER_ENABLED",
        "SNIPER_HTF_TIMEFRAME",
        "SNIPER_LTF_TIMEFRAME",
        "SNIPER_LTF_BARS",
        "SNIPER_OB_LOOKBACK",
        "SNIPER_PIVOT_N",
        "SNIPER_DISPLACEMENT_MULT",
        "SNIPER_SL_ATR_BUFFER",
        "SNIPER_TP_RR",
        "SNIPER_MAX_SPREAD_POINTS",
        "SNIPER_CONFIDENCE_BOOST",
    ]
    for k in keys:
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# _env_* helper tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvHelpers:
    """Unit tests for the private env-var parsing helpers."""

    def test_env_float_default(self, monkeypatch):
        monkeypatch.delenv("_TEST_FLOAT", raising=False)
        assert _env_float("_TEST_FLOAT", 3.14) == pytest.approx(3.14)

    def test_env_float_from_env(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLOAT", "2.718")
        assert _env_float("_TEST_FLOAT", 0.0) == pytest.approx(2.718)

    def test_env_float_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("_TEST_FLOAT", "not_a_number")
        assert _env_float("_TEST_FLOAT", 9.99) == pytest.approx(9.99)

    def test_env_int_default(self, monkeypatch):
        monkeypatch.delenv("_TEST_INT", raising=False)
        assert _env_int("_TEST_INT", 42) == 42

    def test_env_int_from_env(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "100")
        assert _env_int("_TEST_INT", 0) == 100

    def test_env_int_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("_TEST_INT", "abc")
        assert _env_int("_TEST_INT", 7) == 7

    @pytest.mark.parametrize(
        "val,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
        ],
    )
    def test_env_bool_truthy_falsy(self, monkeypatch, val, expected):
        monkeypatch.setenv("_TEST_BOOL", val)
        assert _env_bool("_TEST_BOOL", not expected) is expected

    def test_env_bool_default_true(self, monkeypatch):
        monkeypatch.delenv("_TEST_BOOL", raising=False)
        assert _env_bool("_TEST_BOOL", True) is True

    def test_env_bool_default_false(self, monkeypatch):
        monkeypatch.delenv("_TEST_BOOL", raising=False)
        assert _env_bool("_TEST_BOOL", False) is False

    def test_env_bool_unknown_value_uses_default(self, monkeypatch):
        monkeypatch.setenv("_TEST_BOOL", "maybe")
        assert _env_bool("_TEST_BOOL", True) is True


# ---------------------------------------------------------------------------
# SniperEntryEngine initialisation — defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSniperEngineInitDefaults:
    """Engine reads correct defaults when no env vars are set."""

    def test_default_enabled(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.enabled is True

    def test_default_htf_timeframe(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.htf_timeframe == "H1"

    def test_default_ltf_timeframe(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.ltf_timeframe == "M5"

    def test_default_ltf_bars(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.ltf_bars == 100

    def test_default_ob_lookback(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.ob_lookback == 20

    def test_default_pivot_n(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.pivot_n == 3

    def test_default_displacement_mult(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.displacement_mult == pytest.approx(1.5)

    def test_default_sl_atr_buffer(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.sl_atr_buffer == pytest.approx(0.5)

    def test_default_tp_rr(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.tp_rr == pytest.approx(2.0)

    def test_default_max_spread_points(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.max_spread_points == pytest.approx(30.0)

    def test_default_confidence_boost(self, monkeypatch):
        _clean_sniper_env(monkeypatch)
        engine = SniperEntryEngine()
        assert engine.confidence_boost == pytest.approx(1.20)


# ---------------------------------------------------------------------------
# SniperEntryEngine initialisation — custom env vars
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSniperEngineInitCustom:
    """Engine correctly reads custom env var overrides."""

    def test_custom_enabled_false(self, monkeypatch):
        monkeypatch.setenv("SNIPER_ENABLED", "false")
        engine = SniperEntryEngine()
        assert engine.enabled is False

    def test_custom_htf_h4(self, monkeypatch):
        monkeypatch.setenv("SNIPER_HTF_TIMEFRAME", "H4")
        engine = SniperEntryEngine()
        assert engine.htf_timeframe == "H4"

    def test_custom_ltf_m15(self, monkeypatch):
        monkeypatch.setenv("SNIPER_LTF_TIMEFRAME", "M15")
        engine = SniperEntryEngine()
        assert engine.ltf_timeframe == "M15"

    def test_custom_ltf_bars(self, monkeypatch):
        monkeypatch.setenv("SNIPER_LTF_BARS", "200")
        engine = SniperEntryEngine()
        assert engine.ltf_bars == 200

    def test_custom_ob_lookback(self, monkeypatch):
        monkeypatch.setenv("SNIPER_OB_LOOKBACK", "50")
        engine = SniperEntryEngine()
        assert engine.ob_lookback == 50

    def test_custom_pivot_n(self, monkeypatch):
        monkeypatch.setenv("SNIPER_PIVOT_N", "5")
        engine = SniperEntryEngine()
        assert engine.pivot_n == 5

    def test_custom_displacement_mult(self, monkeypatch):
        monkeypatch.setenv("SNIPER_DISPLACEMENT_MULT", "2.0")
        engine = SniperEntryEngine()
        assert engine.displacement_mult == pytest.approx(2.0)

    def test_custom_sl_atr_buffer(self, monkeypatch):
        monkeypatch.setenv("SNIPER_SL_ATR_BUFFER", "1.0")
        engine = SniperEntryEngine()
        assert engine.sl_atr_buffer == pytest.approx(1.0)

    def test_custom_tp_rr(self, monkeypatch):
        monkeypatch.setenv("SNIPER_TP_RR", "3.0")
        engine = SniperEntryEngine()
        assert engine.tp_rr == pytest.approx(3.0)

    def test_custom_max_spread(self, monkeypatch):
        monkeypatch.setenv("SNIPER_MAX_SPREAD_POINTS", "15")
        engine = SniperEntryEngine()
        assert engine.max_spread_points == pytest.approx(15.0)

    def test_custom_confidence_boost(self, monkeypatch):
        monkeypatch.setenv("SNIPER_CONFIDENCE_BOOST", "1.50")
        engine = SniperEntryEngine()
        assert engine.confidence_boost == pytest.approx(1.50)

    def test_htf_timeframe_uppercased(self, monkeypatch):
        """Timeframe strings are always stored uppercase."""
        monkeypatch.setenv("SNIPER_HTF_TIMEFRAME", "h4")
        engine = SniperEntryEngine()
        assert engine.htf_timeframe == "H4"

    def test_ltf_timeframe_uppercased(self, monkeypatch):
        monkeypatch.setenv("SNIPER_LTF_TIMEFRAME", "m15")
        engine = SniperEntryEngine()
        assert engine.ltf_timeframe == "M15"


# ---------------------------------------------------------------------------
# Dataclass: OrderBlock
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrderBlock:
    """OrderBlock dataclass field validation."""

    def test_bullish_ob_fields(self):
        ob = OrderBlock(direction="bullish", top=1900.0, bottom=1895.0, origin_index=5)
        assert ob.direction == "bullish"
        assert ob.top == pytest.approx(1900.0)
        assert ob.bottom == pytest.approx(1895.0)
        assert ob.origin_index == 5
        assert ob.mitigated is False

    def test_bearish_ob_fields(self):
        ob = OrderBlock(direction="bearish", top=2010.0, bottom=2005.0, origin_index=12)
        assert ob.direction == "bearish"
        assert ob.mitigated is False

    def test_ob_mitigated_flag(self):
        ob = OrderBlock(direction="bullish", top=1900.0, bottom=1895.0, origin_index=3, mitigated=True)
        assert ob.mitigated is True

    def test_ob_top_greater_than_bottom(self):
        ob = OrderBlock(direction="bullish", top=1900.0, bottom=1895.0, origin_index=0)
        assert ob.top > ob.bottom


# ---------------------------------------------------------------------------
# Dataclass: DisplacementCandle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDisplacementCandle:
    """DisplacementCandle dataclass field validation."""

    def test_bullish_displacement_fields(self):
        dc = DisplacementCandle(
            direction="bullish",
            open=1890.0,
            high=1910.0,
            low=1888.0,
            close=1908.0,
            fvg_top=1912.0,
            fvg_bottom=1905.0,
            ce_level=1908.5,
            bar_index=10,
        )
        assert dc.direction == "bullish"
        assert dc.ce_level == pytest.approx(1908.5)
        assert dc.fvg_top > dc.fvg_bottom

    def test_bearish_displacement_fields(self):
        dc = DisplacementCandle(
            direction="bearish",
            open=2010.0,
            high=2012.0,
            low=1990.0,
            close=1992.0,
            fvg_top=1988.0,
            fvg_bottom=1982.0,
            ce_level=1985.0,
            bar_index=7,
        )
        assert dc.direction == "bearish"
        assert dc.ce_level == pytest.approx(1985.0)

    def test_ce_level_is_midpoint(self):
        fvg_top = 1912.0
        fvg_bottom = 1905.0
        expected_ce = (fvg_top + fvg_bottom) / 2.0
        dc = DisplacementCandle(
            direction="bullish",
            open=1890.0,
            high=1910.0,
            low=1888.0,
            close=1908.0,
            fvg_top=fvg_top,
            fvg_bottom=fvg_bottom,
            ce_level=expected_ce,
            bar_index=5,
        )
        assert dc.ce_level == pytest.approx(expected_ce)

    def test_default_fields_are_zero(self):
        dc = DisplacementCandle(
            direction="bullish",
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
        )
        assert dc.fvg_top == pytest.approx(0.0)
        assert dc.fvg_bottom == pytest.approx(0.0)
        assert dc.ce_level == pytest.approx(0.0)
        assert dc.bar_index == 0


# ---------------------------------------------------------------------------
# Dataclass: LTFConfirmation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLTFConfirmation:
    """LTFConfirmation dataclass field validation."""

    def test_confirmed_true(self):
        dc = DisplacementCandle(
            direction="bullish",
            open=1890.0,
            high=1910.0,
            low=1888.0,
            close=1908.0,
            fvg_top=1912.0,
            fvg_bottom=1905.0,
            ce_level=1908.5,
            bar_index=5,
        )
        conf = LTFConfirmation(
            confirmed=True,
            event="BOS_bullish",
            displacement=dc,
            last_sh=1915.0,
            last_sl=1880.0,
            bars_analysed=100,
        )
        assert conf.confirmed is True
        assert conf.event == "BOS_bullish"
        assert conf.displacement is dc
        assert conf.bars_analysed == 100

    def test_not_confirmed(self):
        conf = LTFConfirmation(
            confirmed=False,
            event="none",
            displacement=None,
            last_sh=None,
            last_sl=None,
        )
        assert conf.confirmed is False
        assert conf.displacement is None
        assert conf.bars_analysed == 0

    @pytest.mark.parametrize("event", ["BOS_bullish", "BOS_bearish", "CHoCH_bullish", "CHoCH_bearish", "none"])
    def test_valid_event_strings(self, event):
        conf = LTFConfirmation(
            confirmed=False,
            event=event,
            displacement=None,
            last_sh=None,
            last_sl=None,
        )
        assert conf.event == event


# ---------------------------------------------------------------------------
# Dataclass: SniperSetup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSniperSetup:
    """SniperSetup dataclass and to_dict() serialisation."""

    def _make_setup(self, direction="long", entry=1900.0, sl=1890.0, tp=1920.0):
        ob = OrderBlock(direction="bullish", top=1895.0, bottom=1890.0, origin_index=5)
        dc = DisplacementCandle(
            direction="bullish",
            open=1888.0,
            high=1905.0,
            low=1886.0,
            close=1903.0,
            fvg_top=1905.0,
            fvg_bottom=1898.0,
            ce_level=entry,
            bar_index=8,
        )
        ltf = LTFConfirmation(
            confirmed=True,
            event="BOS_bullish",
            displacement=dc,
            last_sh=1910.0,
            last_sl=1880.0,
            bars_analysed=100,
        )
        return SniperSetup(
            symbol="XAU_USD",
            direction=direction,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            confidence=0.85,
            order_type="LIMIT",
            htf_ob=ob,
            ltf_confirmation=ltf,
            reason="sniper:long|test",
        )

    def test_setup_fields(self):
        setup = self._make_setup()
        assert setup.symbol == "XAU_USD"
        assert setup.direction == "long"
        assert setup.entry_price == pytest.approx(1900.0)
        assert setup.stop_loss == pytest.approx(1890.0)
        assert setup.take_profit == pytest.approx(1920.0)
        assert setup.confidence == pytest.approx(0.85)
        assert setup.order_type == "LIMIT"

    def test_setup_has_timestamp(self):
        setup = self._make_setup()
        # Timestamp must be a non-empty ISO string
        assert isinstance(setup.timestamp, str)
        assert len(setup.timestamp) > 10
        # Must be parseable
        dt = datetime.fromisoformat(setup.timestamp)
        assert dt.tzinfo is not None

    def test_to_dict_keys(self):
        setup = self._make_setup()
        d = setup.to_dict()
        expected_keys = {
            "symbol",
            "direction",
            "entry_price",
            "stop_loss",
            "take_profit",
            "confidence",
            "order_type",
            "reason",
            "timestamp",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_values(self):
        setup = self._make_setup(entry=1900.12345, sl=1890.12345, tp=1920.12345)
        d = setup.to_dict()
        assert d["symbol"] == "XAU_USD"
        assert d["direction"] == "long"
        assert d["order_type"] == "LIMIT"
        # Prices rounded to 5 decimal places
        assert d["entry_price"] == round(1900.12345, 5)
        assert d["stop_loss"] == round(1890.12345, 5)
        assert d["take_profit"] == round(1920.12345, 5)

    def test_to_dict_confidence_rounded(self):
        setup = self._make_setup()
        setup.confidence = 0.856789
        d = setup.to_dict()
        assert d["confidence"] == round(0.856789, 4)

    def test_short_setup(self):
        setup = self._make_setup(direction="short", entry=2000.0, sl=2010.0, tp=1980.0)
        assert setup.direction == "short"
        assert setup.stop_loss > setup.entry_price
        assert setup.take_profit < setup.entry_price

    def test_default_order_type_is_limit(self):
        setup = SniperSetup(
            symbol="EUR_USD",
            direction="long",
            entry_price=1.0850,
            stop_loss=1.0820,
            take_profit=1.0910,
            confidence=0.75,
        )
        assert setup.order_type == "LIMIT"


# ---------------------------------------------------------------------------
# Engine disabled path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSniperEngineDisabled:
    """When SNIPER_ENABLED=false, refine() always returns None."""

    def test_refine_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("SNIPER_ENABLED", "false")
        engine = SniperEntryEngine()
        assert engine.enabled is False

        decision = MagicMock()
        decision.action = "long"
        decision.symbol = "XAU_USD"
        decision.confidence = 0.8
        decision.tick_mid = 1900.0

        import pandas as pd

        htf_df = pd.DataFrame()

        result = engine.refine(decision, htf_df, orchestrator=None)
        assert result is None

    def test_refine_returns_none_for_hold_action(self, monkeypatch):
        monkeypatch.setenv("SNIPER_ENABLED", "true")
        engine = SniperEntryEngine()

        decision = MagicMock()
        decision.action = "hold"
        decision.symbol = "XAU_USD"
        decision.confidence = 0.8
        decision.tick_mid = 1900.0

        import pandas as pd

        result = engine.refine(decision, pd.DataFrame(), orchestrator=None)
        assert result is None

    def test_refine_returns_none_for_zero_tick_mid(self, monkeypatch):
        monkeypatch.setenv("SNIPER_ENABLED", "true")
        engine = SniperEntryEngine()

        decision = MagicMock()
        decision.action = "long"
        decision.symbol = "XAU_USD"
        decision.confidence = 0.8
        decision.tick_mid = 0.0

        import pandas as pd

        result = engine.refine(decision, pd.DataFrame(), orchestrator=None)
        assert result is None

    def test_refine_returns_none_for_negative_tick_mid(self, monkeypatch):
        monkeypatch.setenv("SNIPER_ENABLED", "true")
        engine = SniperEntryEngine()

        decision = MagicMock()
        decision.action = "long"
        decision.symbol = "XAU_USD"
        decision.confidence = 0.8
        decision.tick_mid = -1.0

        import pandas as pd

        result = engine.refine(decision, pd.DataFrame(), orchestrator=None)
        assert result is None
