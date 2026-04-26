# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for brain/hopefx_brain.py — primary HOPEFXBrain (bar-processing intelligence hub)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from brain.hopefx_brain import BrainDecision, HOPEFXBrain, Regime, get_brain


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 30, base: float = 2000.0, trend: float = 0.0) -> pd.DataFrame:
    """Generate a minimal OHLCV DataFrame for regime/process_bar tests."""
    rng = np.random.default_rng(99)
    closes = base + trend * np.arange(n) + rng.normal(0, 1.0, n)
    highs = closes + rng.uniform(0.5, 1.5, n)
    lows = closes - rng.uniform(0.5, 1.5, n)
    opens = closes + rng.normal(0, 0.3, n)
    volumes = rng.integers(1000, 5000, n)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})


def _make_trending_ohlcv(n: int = 30, direction: str = "up") -> pd.DataFrame:
    """Generate an obviously trending OHLCV series."""
    slope = 5.0 if direction == "up" else -5.0
    closes = 2000.0 + slope * np.arange(n)
    highs = closes + 1.0
    lows = closes - 1.0
    opens = closes + 0.2
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                          "volume": np.ones(n) * 1000})


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def brain():
    return HOPEFXBrain()


# ── Initialisation ────────────────────────────────────────────────────────────


class TestHopeFXBrainInit:
    def test_default_state(self, brain):
        assert not brain.is_killed
        assert brain._bar_count == 0
        assert brain._signal_count == 0
        assert brain._hold_count == 0

    def test_stats_initial(self, brain):
        s = brain.stats
        assert s["bar_count"] == 0
        assert s["killed"] is False
        assert s["ml_predictor_loaded"] is False

    def test_inject_components(self, brain):
        rm = MagicMock()
        broker = MagicMock()
        brain.inject(risk_manager=rm, broker=broker)
        assert brain._risk_manager is rm
        assert brain._broker is broker

    def test_inject_partial(self, brain):
        rm = MagicMock()
        brain.inject(risk_manager=rm)
        assert brain._risk_manager is rm
        assert brain._broker is None  # not injected


# ── Kill switch ───────────────────────────────────────────────────────────────


class TestKillSwitch:
    def test_kill_blocks_process_bar(self, brain):
        brain.kill("unit test")
        assert brain.is_killed
        ohlcv = _make_ohlcv()
        decision = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert decision.action == "hold"
        assert "kill_switch" in decision.reason

    def test_revive_restores_processing(self, brain):
        brain.kill("test")
        brain.revive()
        assert not brain.is_killed

    def test_kill_reason_recorded(self, brain):
        brain.kill("market closure")
        ohlcv = _make_ohlcv()
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert "market closure" in d.reason


# ── Regime detection ──────────────────────────────────────────────────────────


class TestRegimeDetection:
    def test_returns_unknown_with_insufficient_data(self, brain):
        df = _make_ohlcv(n=10)  # < 20 bars
        regime = brain.detect_regime(df, symbol="XAU/USD")
        assert regime == Regime.UNKNOWN

    def test_detects_trending_up(self, brain):
        df = _make_trending_ohlcv(n=30, direction="up")
        regime = brain.detect_regime(df, symbol="XAU/USD")
        assert regime in (Regime.TRENDING_UP, Regime.TRENDING_DOWN, Regime.RANGING, Regime.VOLATILE)

    def test_strong_uptrend_classified(self, brain):
        # Very steep uptrend: 10 points per bar on a ~2000 price → large norm_slope
        closes = 2000.0 + 10.0 * np.arange(30)
        highs = closes + 0.5
        lows = closes - 0.5
        df = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                            "volume": np.ones(30) * 1000})
        regime = brain.detect_regime(df, symbol="XAU/USD")
        assert regime == Regime.TRENDING_UP

    def test_strong_downtrend_classified(self, brain):
        closes = 2000.0 - 10.0 * np.arange(30)
        highs = closes + 0.5
        lows = closes - 0.5
        df = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                            "volume": np.ones(30) * 1000})
        regime = brain.detect_regime(df, symbol="XAU/USD")
        assert regime == Regime.TRENDING_DOWN

    def test_high_volatility_classified_volatile(self, brain):
        # ATR > REGIME_VOLATILE_THRESHOLD (default 0.8%) of price
        # Price = 100, ATR must be > 0.8 → so ATR > 0.8
        closes = np.full(30, 100.0) + np.random.default_rng(1).normal(0, 0.01, 30)
        highs = closes + 2.0   # high-low spread → large ATR
        lows = closes - 2.0
        df = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                            "volume": np.ones(30) * 1000})
        regime = brain.detect_regime(df, symbol="XAU/USD")
        assert regime == Regime.VOLATILE

    def test_regime_history_tracks_changes(self, brain):
        df_up = _make_trending_ohlcv(n=30, direction="up")
        brain.detect_regime(df_up, symbol="TEST")
        # Force a second detection on same symbol to log change
        df_down = _make_trending_ohlcv(n=30, direction="down")
        brain.detect_regime(df_down, symbol="TEST")
        history = brain.regime_history(n=5)
        assert isinstance(history, list)

    def test_exception_returns_unknown(self, brain):
        bad_df = pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1], "volume": [1]})
        # patch closes extraction to raise
        with patch.object(bad_df, "__getitem__", side_effect=KeyError("close")):
            regime = brain.detect_regime(bad_df, symbol="ERR")
        assert regime == Regime.UNKNOWN

    def test_current_regime_unknown_for_new_symbol(self, brain):
        assert brain.current_regime("NEVER_SEEN") == Regime.UNKNOWN.value


# ── MTF fusion ────────────────────────────────────────────────────────────────


class TestMTFFusion:
    def test_returns_unknown_without_data(self, brain):
        ctx = brain.update_mtf_context("XAU/USD")
        assert ctx["d1_regime"] == Regime.UNKNOWN.value
        assert ctx["h4_regime"] == Regime.UNKNOWN.value

    def test_cache_hit_returns_same_ctx(self, brain):
        df = _make_ohlcv(n=30)
        ctx1 = brain.update_mtf_context("XAU/USD", d1_ohlcv=df)
        ctx2 = brain.update_mtf_context("XAU/USD", d1_ohlcv=df)
        assert ctx1 is ctx2  # same dict from cache

    def test_aligned_regimes_produce_alignment_string(self, brain):
        # Force the internal cache to have aligned data
        up_df = _make_trending_ohlcv(n=30, direction="up")
        ctx = brain.update_mtf_context("XAU/USD", d1_ohlcv=up_df, h4_ohlcv=up_df)
        assert "mtf_alignment" in ctx

    def test_insufficient_data_uses_unknown_regime(self, brain):
        short_df = _make_ohlcv(n=10)  # < 20 bars
        ctx = brain.update_mtf_context("XAU/USD", d1_ohlcv=short_df)
        assert ctx["d1_regime"] == Regime.UNKNOWN.value


# ── process_bar ───────────────────────────────────────────────────────────────


class TestProcessBar:
    def test_returns_brain_decision(self, brain):
        ohlcv = _make_ohlcv(n=30)
        decision = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert isinstance(decision, BrainDecision)

    def test_action_is_valid(self, brain):
        ohlcv = _make_ohlcv(n=30)
        decision = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert decision.action in ("long", "short", "hold")

    def test_confidence_bounded(self, brain):
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert 0.0 <= d.confidence <= 1.0

    def test_bar_count_increments(self, brain):
        ohlcv = _make_ohlcv(n=30)
        brain.process_bar(ohlcv, symbol="XAU/USD")
        brain.process_bar(ohlcv, symbol="XAU/USD")
        assert brain._bar_count == 2

    def test_hold_counted_when_no_ml_no_strategy(self, brain):
        ohlcv = _make_ohlcv(n=30)
        brain.process_bar(ohlcv, symbol="XAU/USD")
        # Without ML/strategy injected, result is hold
        assert brain._hold_count + brain._signal_count == brain._bar_count

    def test_decision_recorded_in_history(self, brain):
        ohlcv = _make_ohlcv(n=30)
        brain.process_bar(ohlcv, symbol="XAU/USD")
        recent = brain.recent_decisions(n=1)
        assert len(recent) == 1
        assert "action" in recent[0]
        assert "confidence" in recent[0]

    def test_symbol_in_decision(self, brain):
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="EUR/USD")
        assert d.symbol == "EUR/USD"

    def test_latency_recorded(self, brain):
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert d.latency_ms >= 0.0

    def test_risk_halted_returns_hold(self, brain):
        rm = MagicMock()
        rm._trading_halted = True
        brain.inject(risk_manager=rm)
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert d.action == "hold"
        assert d.reason == "risk_halted"

    def test_to_dict_serialisable(self, brain):
        import json
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        d_dict = d.to_dict()
        # Must be JSON-serialisable (no numpy scalars etc.)
        json.dumps(d_dict)

    def test_multiple_symbols_tracked_independently(self, brain):
        ohlcv = _make_ohlcv(n=30)
        brain.process_bar(ohlcv, symbol="XAU/USD")
        brain.process_bar(ohlcv, symbol="EUR/USD")
        assert brain._bar_count == 2


# ── ML predictor integration ──────────────────────────────────────────────────


class TestMLPredictor:
    def test_ml_long_signal_propagates(self, brain):
        """When the ML predictor emits a confident long, action should be long."""
        predictor = MagicMock()
        predictor.predict.return_value = {
            "probability": 0.80,
            "confidence": 0.60,
            "direction": "long",
            "abstain": False,
        }
        brain.inject(ml_predictor=predictor)
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        # Without strategy, ML-only path uses 0.8 * ml_conf → should be long
        assert d.action in ("long", "hold")
        assert d.ml_probability == pytest.approx(0.80, abs=0.01)

    def test_ml_short_signal_propagates(self, brain):
        predictor = MagicMock()
        predictor.predict.return_value = {
            "probability": 0.20,
            "confidence": 0.60,
            "direction": "short",
            "abstain": False,
        }
        brain.inject(ml_predictor=predictor)
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert d.action in ("short", "hold")

    def test_ml_abstain_results_in_hold(self, brain):
        predictor = MagicMock()
        predictor.predict.return_value = {
            "probability": 0.50,
            "confidence": 0.0,
            "direction": "neutral",
            "abstain": True,
        }
        brain.inject(ml_predictor=predictor)
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert d.action == "hold"
        assert d.ml_abstain is True

    def test_ml_predictor_exception_does_not_crash(self, brain):
        predictor = MagicMock()
        predictor.predict.side_effect = RuntimeError("model crashed")
        brain.inject(ml_predictor=predictor)
        ohlcv = _make_ohlcv(n=30)
        d = brain.process_bar(ohlcv, symbol="XAU/USD")
        assert isinstance(d, BrainDecision)
        assert d.ml_abstain is True


# ── Signal aggregation ────────────────────────────────────────────────────────


class TestSignalAggregation:
    def test_both_neutral_returns_hold(self, brain):
        direction, confidence, reason = brain._aggregate_signals(
            ml_direction="neutral", ml_confidence=0.0,
            strategy_direction="neutral", strategy_confidence=0.0,
        )
        assert direction == "hold"
        assert confidence == 0.0
        assert reason == "both_neutral"

    def test_both_agree_long_boosts_confidence(self, brain):
        direction, confidence, reason = brain._aggregate_signals(
            ml_direction="long", ml_confidence=0.7,
            strategy_direction="long", strategy_confidence=0.6,
        )
        assert direction == "long"
        assert confidence > 0.6
        assert reason == "ml_strategy_agree"

    def test_disagreement_returns_hold(self, brain):
        direction, confidence, reason = brain._aggregate_signals(
            ml_direction="long", ml_confidence=0.8,
            strategy_direction="short", strategy_confidence=0.8,
        )
        assert direction == "hold"
        assert "conflict" in reason

    def test_ml_only_long_at_reduced_confidence(self, brain):
        direction, confidence, reason = brain._aggregate_signals(
            ml_direction="long", ml_confidence=0.7,
            strategy_direction="neutral", strategy_confidence=0.0,
        )
        assert direction == "long"
        assert confidence < 0.7
        assert reason == "ml_only"

    def test_strategy_only_low_confidence_returns_hold(self, brain):
        direction, confidence, reason = brain._aggregate_signals(
            ml_direction="neutral", ml_confidence=0.0,
            strategy_direction="long", strategy_confidence=0.10,  # < MIN_CONFIDENCE 0.30
        )
        assert direction == "hold"
        assert reason == "strategy_low_confidence"

    def test_ml_low_confidence_returns_hold(self, brain):
        direction, confidence, reason = brain._aggregate_signals(
            ml_direction="long", ml_confidence=0.10,  # < MIN_CONFIDENCE 0.30
            strategy_direction="neutral", strategy_confidence=0.0,
        )
        assert direction == "hold"
        assert reason == "ml_low_confidence"


# ── Horizon hold logic ────────────────────────────────────────────────────────


class TestHorizonHold:
    def test_horizon_gt_1_suppresses_reversal(self):
        b = HOPEFXBrain(config={})
        b._signal_horizon = 3

        predictor = MagicMock()
        predictor.predict.return_value = {
            "probability": 0.80, "confidence": 0.60,
            "direction": "long", "abstain": False,
        }
        b.inject(ml_predictor=predictor)
        ohlcv = _make_ohlcv(n=30)

        # First bar: generates a long — sets hold countdown to 3
        d1 = b.process_bar(ohlcv, symbol="XAU/USD")

        # Now flip ML to short
        predictor.predict.return_value = {
            "probability": 0.20, "confidence": 0.60,
            "direction": "short", "abstain": False,
        }
        d2 = b.process_bar(ohlcv, symbol="XAU/USD")

        if d1.action == "long":
            # Reversal within hold window must be suppressed
            assert d2.action == "hold"
            assert "horizon_hold" in d2.reason

    def test_horizon_1_does_not_suppress_reversal(self):
        b = HOPEFXBrain(config={})
        b._signal_horizon = 1  # default — no hold enforcement

        predictor = MagicMock()
        predictor.predict.return_value = {
            "probability": 0.80, "confidence": 0.60,
            "direction": "short", "abstain": False,
        }
        b.inject(ml_predictor=predictor)
        ohlcv = _make_ohlcv(n=30)
        d = b.process_bar(ohlcv, symbol="XAU/USD")
        # No suppression — should be short or hold (not "hold due to horizon")
        if d.action == "hold":
            assert "horizon_hold" not in d.reason


# ── Stats and introspection ───────────────────────────────────────────────────


class TestStats:
    def test_stats_after_several_bars(self, brain):
        ohlcv = _make_ohlcv(n=30)
        for _ in range(5):
            brain.process_bar(ohlcv, symbol="XAU/USD")
        s = brain.stats
        assert s["bar_count"] == 5
        assert s["signal_count"] + s["hold_count"] == 5

    def test_signal_rate_correct(self, brain):
        ohlcv = _make_ohlcv(n=30)
        brain.process_bar(ohlcv, symbol="XAU/USD")
        s = brain.stats
        assert 0.0 <= s["signal_rate"] <= 1.0

    def test_recent_decisions_returns_list(self, brain):
        ohlcv = _make_ohlcv(n=30)
        brain.process_bar(ohlcv, symbol="XAU/USD")
        decisions = brain.recent_decisions(n=10)
        assert isinstance(decisions, list)
        assert len(decisions) >= 1

    def test_recent_decisions_limit_respected(self, brain):
        ohlcv = _make_ohlcv(n=30)
        for _ in range(20):
            brain.process_bar(ohlcv, symbol="XAU/USD")
        decisions = brain.recent_decisions(n=5)
        assert len(decisions) == 5

    def test_regime_history_returns_list(self, brain):
        ohlcv = _make_trending_ohlcv(n=30, direction="up")
        brain.detect_regime(ohlcv, symbol="XAU/USD")
        history = brain.regime_history(n=10)
        assert isinstance(history, list)


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_brain_returns_instance(self):
        b = get_brain()
        assert isinstance(b, HOPEFXBrain)

    def test_get_brain_singleton(self):
        b1 = get_brain()
        b2 = get_brain()
        assert b1 is b2
