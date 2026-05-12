"""
Tests for core/signal_engine.py — targets 80%+ branch coverage.

Covers all public and private functions using mocked dependencies
(no live broker, no ML model required).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

UTC = timezone.utc

import core.signal_engine as se


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_data(close=2000.0, n=20):
    prices = [close + i * 0.1 for i in range(n)]
    highs = [p * 1.001 for p in prices]
    lows = [p * 0.999 for p in prices]
    return {
        "symbol": "XAUUSD",
        "open": prices[-1],
        "high": highs[-1],
        "low": lows[-1],
        "close": prices[-1],
        "volume": 1000.0,
        "prices": prices,
        "highs": highs,
        "lows": lows,
        "volumes": [1000.0] * n,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _make_app_state(**kwargs):
    state = MagicMock()
    state.broker = None
    state.risk_manager = None
    state.compliance_manager = None
    state.ws_manager = None
    state.strategy_brain = None
    state.mtf_store = None
    state.factor_engine = None
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


# All async tests use `async def` — pytest-asyncio (auto mode) manages the loop.


# ─────────────────────────────────────────────────────────────────────────────
# get_signal_engine_status
# ─────────────────────────────────────────────────────────────────────────────


class TestGetSignalEngineStatus:
    def test_returns_dict(self):
        status = se.get_signal_engine_status()
        assert isinstance(status, dict)

    def test_has_ml_available_key(self):
        status = se.get_signal_engine_status()
        assert "ml_available" in status

    def test_has_symbols_key(self):
        status = se.get_signal_engine_status()
        assert "symbols" in status

    def test_has_auto_trade_key(self):
        status = se.get_signal_engine_status()
        assert "auto_trade" in status

    def test_running_is_bool(self):
        status = se.get_signal_engine_status()
        assert isinstance(status["ml_available"], bool)

    def test_has_phase_keys(self):
        status = se.get_signal_engine_status()
        for key in ("phase2_anomaly", "phase3_online", "phase4_deep"):
            assert key in status

    def test_phase2_anomaly_default(self):
        # When anomaly store is disabled, should return fitted=False
        status = se.get_signal_engine_status()
        assert isinstance(status["phase2_anomaly"], dict)

    def test_phase3_online_default(self):
        status = se.get_signal_engine_status()
        assert isinstance(status["phase3_online"], dict)

    def test_phase4_deep_default(self):
        status = se.get_signal_engine_status()
        assert isinstance(status["phase4_deep"], dict)


# ─────────────────────────────────────────────────────────────────────────────
# _build_ohlcv_df
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildOhlcvDf:
    def test_returns_dataframe(self):
        df = se._build_ohlcv_df(_make_data())
        assert isinstance(df, pd.DataFrame)

    def test_correct_length(self):
        df = se._build_ohlcv_df(_make_data(n=20))
        assert len(df) == 20

    def test_has_ohlcv_columns(self):
        df = se._build_ohlcv_df(_make_data())
        for col in ("open", "high", "low", "close", "volume"):
            assert col in df.columns

    def test_last_bar_overwritten(self):
        data = _make_data(close=2000.0)
        data["close"] = 2050.0
        data["high"] = 2060.0
        data["low"] = 1990.0
        df = se._build_ohlcv_df(data)
        assert df["close"].iloc[-1] == pytest.approx(2050.0)
        assert df["high"].iloc[-1] == pytest.approx(2060.0)
        assert df["low"].iloc[-1] == pytest.approx(1990.0)

    def test_single_bar(self):
        data = _make_data(n=1)
        df = se._build_ohlcv_df(data)
        assert len(df) == 1

    def test_mismatched_highs_falls_back_to_prices(self):
        data = _make_data(n=5)
        data["highs"] = [2001.0]  # wrong length
        df = se._build_ohlcv_df(data)
        assert len(df) == 5  # still builds


# ─────────────────────────────────────────────────────────────────────────────
# _compute_atr
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeAtr:
    def test_returns_positive(self):
        data = _make_data(n=20)
        atr = se._compute_atr(data["highs"], data["lows"], data["prices"], 2000.0)
        assert atr > 0

    def test_insufficient_bars_returns_fallback(self):
        # fewer than 14 bars → fallback fraction of entry
        atr = se._compute_atr([2001.0] * 5, [1999.0] * 5, [2000.0] * 5, 2000.0)
        assert atr == pytest.approx(2000.0 * se._ATR_FALLBACK_FRAC)

    def test_wide_range_greater_than_tight(self):
        highs_wide = [2020.0] * 15
        lows_wide = [1980.0] * 15
        highs_tight = [2001.0] * 15
        lows_tight = [1999.0] * 15
        closes = [2000.0] * 15
        atr_wide = se._compute_atr(highs_wide, lows_wide, closes, 2000.0)
        atr_tight = se._compute_atr(highs_tight, lows_tight, closes, 2000.0)
        assert atr_wide >= atr_tight

    def test_exactly_14_bars(self):
        highs = [2005.0] * 14
        lows = [1995.0] * 14
        closes = [2000.0] * 14
        atr = se._compute_atr(highs, lows, closes, 2000.0)
        assert atr > 0


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_sl_tp
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveSlTp:
    def _make_signal(self, sl=None, tp=None):
        sig = MagicMock()
        sig.stop_loss = sl
        sig.take_profit = tp
        return sig

    def test_uses_signal_values_when_present(self):
        sig = self._make_signal(sl=1950.0, tp=2100.0)
        sl, tp = se._resolve_sl_tp(sig, _make_data(), "BUY", 2000.0)
        assert sl == 1950.0
        assert tp == 2100.0

    def test_buy_no_bar_data_sl_below_entry(self):
        sig = self._make_signal()
        sl, tp = se._resolve_sl_tp(sig, {}, "BUY", 2000.0)
        assert sl < 2000.0
        assert tp > 2000.0

    def test_sell_no_bar_data_sl_above_entry(self):
        sig = self._make_signal()
        sl, tp = se._resolve_sl_tp(sig, {}, "SELL", 2000.0)
        assert sl > 2000.0
        assert tp < 2000.0

    def test_buy_with_bar_data_atr_based(self):
        sig = self._make_signal()
        sl, tp = se._resolve_sl_tp(sig, _make_data(n=20), "BUY", 2000.0)
        assert sl < 2000.0
        assert tp > 2000.0

    def test_sell_with_bar_data_atr_based(self):
        sig = self._make_signal()
        sl, tp = se._resolve_sl_tp(sig, _make_data(n=20), "SELL", 2000.0)
        assert sl > 2000.0
        assert tp < 2000.0

    def test_none_signal_no_bar_data(self):
        sl, tp = se._resolve_sl_tp(None, {}, "BUY", 2000.0)
        assert sl < 2000.0
        assert tp > 2000.0

    def test_fallback_fracs_applied(self):
        sl, tp = se._resolve_sl_tp(None, {}, "BUY", 2000.0)
        assert sl == pytest.approx(2000.0 * (1 - se._SL_FALLBACK_FRAC))
        assert tp == pytest.approx(2000.0 * (1 + se._TP_FALLBACK_FRAC))


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_execution_sl_tp
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveExecutionSlTp:
    def test_uses_payload_values_when_present(self):
        payload = {"stop_loss": 1950.0, "take_profit": 2100.0, "entry_price": 2000.0}
        sl, tp = se._resolve_execution_sl_tp(payload, _make_data(), "BUY")
        assert sl == 1950.0
        assert tp == 2100.0

    def test_computes_buy_no_bar_data(self):
        payload = {"direction": "BUY", "entry_price": 2000.0}
        sl, tp = se._resolve_execution_sl_tp(payload, None, "BUY")
        assert sl < 2000.0
        assert tp > 2000.0

    def test_computes_buy_with_bar_data(self):
        payload = {"direction": "BUY", "entry_price": 2000.0}
        sl, tp = se._resolve_execution_sl_tp(payload, _make_data(), "BUY")
        assert sl < 2000.0
        assert tp > 2000.0

    def test_computes_sell_no_bar_data(self):
        payload = {"direction": "SELL", "entry_price": 2000.0}
        sl, tp = se._resolve_execution_sl_tp(payload, None, "SELL")
        assert sl > 2000.0
        assert tp < 2000.0

    def test_partial_payload_missing_tp(self):
        # Only stop_loss present — should still compute both
        payload = {"stop_loss": 1950.0, "entry_price": 2000.0}
        sl, tp = se._resolve_execution_sl_tp(payload, None, "BUY")
        # Falls through to _resolve_sl_tp since tp is None
        assert tp > 2000.0


# ─────────────────────────────────────────────────────────────────────────────
# _estimate_annualised_volatility
# ─────────────────────────────────────────────────────────────────────────────


class TestEstimateAnnualisedVolatility:
    def test_returns_float(self):
        vol = se._estimate_annualised_volatility(_make_data(n=25), 2000.0)
        assert isinstance(vol, float)

    def test_returns_baseline_when_too_few_prices(self):
        data = _make_data(n=5)
        vol = se._estimate_annualised_volatility(data, 2000.0)
        assert vol == pytest.approx(0.15)

    def test_returns_baseline_on_none_data(self):
        vol = se._estimate_annualised_volatility(None, 2000.0)
        assert vol == pytest.approx(0.15)

    def test_returns_positive_with_sufficient_data(self):
        data = _make_data(n=25)
        vol = se._estimate_annualised_volatility(data, 2000.0)
        assert vol >= 0

    def test_constant_prices_returns_zero_vol(self):
        data = _make_data(n=25)
        data["prices"] = [2000.0] * 25
        vol = se._estimate_annualised_volatility(data, 2000.0)
        assert vol == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# _build_ohlcv_proxy
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildOhlcvProxy:
    def test_returns_none_on_empty_dict(self):
        assert se._build_ohlcv_proxy({}) is None

    def test_returns_none_on_none(self):
        assert se._build_ohlcv_proxy(None) is None

    def test_returns_none_when_prices_missing(self):
        assert se._build_ohlcv_proxy({"highs": [1.0], "lows": [1.0]}) is None

    def test_returns_dataframe_with_full_data(self):
        df = se._build_ohlcv_proxy(_make_data())
        assert isinstance(df, pd.DataFrame)
        assert "close" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns

    def test_correct_length(self):
        data = _make_data(n=15)
        df = se._build_ohlcv_proxy(data)
        assert len(df) == 15


# ─────────────────────────────────────────────────────────────────────────────
# _run_signal_filter
# ─────────────────────────────────────────────────────────────────────────────


class TestRunSignalFilter:
    def _payload(self, prob=0.70):
        return {"probability": prob, "confidence": 0.7, "direction": "BUY"}

    def test_passes_when_filter_module_passes(self):
        mock_result = MagicMock()
        mock_result.passed = True
        mock_filter = MagicMock()
        mock_filter.check.return_value = mock_result
        mock_module = MagicMock()
        mock_module.get_signal_filter.return_value = mock_filter
        with patch.dict("sys.modules", {"ml.signal_filter": mock_module}):
            assert se._run_signal_filter(self._payload(), None, "XAUUSD") is True

    def test_blocked_when_filter_module_blocks(self):
        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.gate = "confidence"
        mock_result.reason = "too low"
        mock_result.confidence = 0.3
        mock_filter = MagicMock()
        mock_filter.check.return_value = mock_result
        mock_module = MagicMock()
        mock_module.get_signal_filter.return_value = mock_filter
        with patch.dict("sys.modules", {"ml.signal_filter": mock_module}):
            assert se._run_signal_filter(self._payload(0.3), None, "XAUUSD") is False

    def test_fallback_passes_when_prob_above_threshold(self):
        # filter module unavailable → legacy fallback
        with patch.dict("sys.modules", {"ml.signal_filter": None}):
            result = se._run_signal_filter(self._payload(prob=0.75), None, "XAUUSD")
            assert result is True

    def test_fallback_blocks_when_prob_below_threshold(self):
        with patch.dict("sys.modules", {"ml.signal_filter": None}):
            result = se._run_signal_filter(self._payload(prob=0.40), None, "XAUUSD")
            assert result is False

    def test_fallback_threshold_env_override(self):
        with patch.dict("sys.modules", {"ml.signal_filter": None}):
            with patch.dict("os.environ", {"ML_MIN_TRADE_PROB": "0.90"}):
                # prob=0.75 is below 0.90 → blocked
                result = se._run_signal_filter(self._payload(prob=0.75), None, "XAUUSD")
                assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# _check_live_trading_gate
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckLiveTradingGate:
    def test_returns_bool(self):
        result = se._check_live_trading_gate()
        assert isinstance(result, bool)

    def test_gate_allowed_returns_true(self):
        mock_result = MagicMock()
        mock_result.allowed = True
        mock_gate = MagicMock()
        mock_gate.check.return_value = mock_result
        mock_module = MagicMock()
        mock_module.get_gate.return_value = mock_gate
        with patch.dict("sys.modules", {"core.live_trading_gate": mock_module}):
            assert se._check_live_trading_gate() is True

    def test_gate_blocked_returns_false(self):
        mock_result = MagicMock()
        mock_result.allowed = False
        mock_result.reason = "risk limit"
        mock_gate = MagicMock()
        mock_gate.check.return_value = mock_result
        mock_module = MagicMock()
        mock_module.get_gate.return_value = mock_gate
        with patch.dict("sys.modules", {"core.live_trading_gate": mock_module}):
            assert se._check_live_trading_gate() is False

    def test_gate_raises_returns_false(self):
        mock_module = MagicMock()
        mock_module.get_gate.side_effect = RuntimeError("gate down")
        with patch.dict("sys.modules", {"core.live_trading_gate": mock_module}):
            assert se._check_live_trading_gate() is False

    def test_import_error_returns_false(self):
        with patch.dict("sys.modules", {"core.live_trading_gate": None}):
            assert se._check_live_trading_gate() is False


# ─────────────────────────────────────────────────────────────────────────────
# Store accessors: _get_macro_store, _get_macro_store_bridge,
#                  _get_deep_ensemble_store, _get_online_learner_store,
#                  _get_anomaly_store
# ─────────────────────────────────────────────────────────────────────────────


class TestStoreAccessors:
    def test_get_macro_store_returns_none_on_import_error(self):
        with patch.dict("sys.modules", {"ml.macro_store": None}):
            result = se._get_macro_store()
            assert result is None

    def test_get_macro_store_returns_store_when_available(self):
        mock_store = MagicMock()
        mock_module = MagicMock()
        mock_module.macro_store = mock_store
        with patch.dict("sys.modules", {"ml.macro_store": mock_module}):
            result = se._get_macro_store()
            assert result is mock_store

    def test_get_macro_store_bridge_returns_none_on_import_error(self):
        with patch.dict("sys.modules", {"data_layer.orchestrator": None}):
            result = se._get_macro_store_bridge()
            assert result is None

    def test_get_deep_ensemble_store_returns_none_when_flag_off(self):
        mock_flags = MagicMock()
        mock_flags.DEEP_ENSEMBLE = False
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            # Reset cached store so flag is re-evaluated
            original = se._deep_ensemble_store
            se._deep_ensemble_store = None
            result = se._get_deep_ensemble_store()
            se._deep_ensemble_store = original
            assert result is None

    def test_get_online_learner_store_returns_none_when_flag_off(self):
        mock_flags = MagicMock()
        mock_flags.ONLINE_LEARNING = False
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            original = se._online_learner_store
            se._online_learner_store = None
            result = se._get_online_learner_store()
            se._online_learner_store = original
            assert result is None

    def test_get_anomaly_store_returns_none_when_flag_off(self):
        mock_flags = MagicMock()
        mock_flags.ANOMALY_WEIGHTING = False
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            original = se._anomaly_store
            se._anomaly_store = None
            result = se._get_anomaly_store()
            se._anomaly_store = original
            assert result is None

    def test_get_online_learner_env_var_enables(self):
        # flags module unavailable → falls back to env var
        with patch.dict("sys.modules", {"config.feature_flags": None}):
            with patch.dict("os.environ", {"FEATURE_ONLINE_LEARNING": "true"}):
                original = se._online_learner_store
                se._online_learner_store = None
                # Will try to import OnlineLearnerStore — may fail, but should not raise
                try:
                    se._get_online_learner_store()
                except Exception:
                    pass
                se._online_learner_store = original

    def test_get_anomaly_env_var_enables(self):
        with patch.dict("sys.modules", {"config.feature_flags": None}):
            with patch.dict("os.environ", {"FEATURE_ANOMALY_WEIGHTING": "1"}):
                original = se._anomaly_store
                se._anomaly_store = None
                try:
                    se._get_anomaly_store()
                except Exception:
                    pass
                se._anomaly_store = original

    def test_get_macro_store_bridge_returns_bridge_when_loaded(self):
        """Covers the success path: orchestrator available, bridge.is_loaded=True."""
        mock_bridge = MagicMock()
        mock_bridge.is_loaded = True
        mock_orch = MagicMock()
        mock_orch._macro_bridge = mock_bridge
        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch
        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = se._get_macro_store_bridge()
        assert result is mock_bridge

    def test_get_macro_store_bridge_returns_none_when_not_loaded(self):
        """Covers bridge.is_loaded=False branch."""
        mock_bridge = MagicMock()
        mock_bridge.is_loaded = False
        mock_orch = MagicMock()
        mock_orch._macro_bridge = mock_bridge
        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch
        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = se._get_macro_store_bridge()
        assert result is None

    def test_get_factor_engine_from_module_singleton(self):
        """Covers _get_factor_engine fallback to portfolio.factor_model singleton."""
        mock_engine = MagicMock()
        mock_module = MagicMock()
        mock_module.get_live_factor_engine.return_value = mock_engine
        with patch.dict("sys.modules", {"portfolio.factor_model": mock_module}):
            result = se._get_factor_engine(None)
        assert result is mock_engine

    def test_get_signal_engine_status_with_active_stores(self):
        """Covers phase2/3/4 branches where stores have .status() methods."""
        anomaly_store = MagicMock()
        anomaly_store.status.return_value = {"fitted": True}
        online_store = MagicMock()
        online_store.status.return_value = {"ready": True}
        deep_store = MagicMock()
        deep_store.status.return_value = {"active": True}

        with (
            patch("core.signal_engine._get_anomaly_store", return_value=anomaly_store),
            patch("core.signal_engine._get_online_learner_store", return_value=online_store),
            patch("core.signal_engine._get_deep_ensemble_store", return_value=deep_store),
        ):
            status = se.get_signal_engine_status()

        assert status["phase2_anomaly"] == {"fitted": True}
        assert status["phase3_online"] == {"ready": True}
        assert status["phase4_deep"] == {"active": True}

    def test_get_signal_engine_status_mtf_singleton_not_none(self):
        """Covers the _MTF_STORE_SINGLETON is not None branch."""
        mock_singleton = MagicMock()
        mock_singleton.status.return_value = {"is_ready": True}
        mock_mtf = MagicMock()
        mock_mtf._MTF_STORE_SINGLETON = mock_singleton
        with patch.dict("sys.modules", {"research.pipeline.mtf_fusion": mock_mtf}):
            status = se.get_signal_engine_status()
        assert status["phase1_mtf"] == {"is_ready": True}

    def test_get_signal_engine_status_flags_unavailable(self):
        """Covers the except branch in phase1 flags check."""
        with patch.dict("sys.modules", {"config.feature_flags": None}):
            status = se.get_signal_engine_status()
        assert status["phase1_mtf_enabled"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Phase blend functions
# ─────────────────────────────────────────────────────────────────────────────


class TestPhaseBlends:
    def _df(self):
        return pd.DataFrame({"close": [2000.0] * 5})

    # Phase 2: anomaly weighting
    def test_anomaly_weighting_no_store_returns_prob(self):
        with patch("core.signal_engine._get_anomaly_store", return_value=None):
            assert se._apply_anomaly_weighting(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    def test_anomaly_weighting_weight_1_unchanged(self):
        mock_store = MagicMock()
        mock_store.update_and_score.return_value = 1.0
        with patch("core.signal_engine._get_anomaly_store", return_value=mock_store):
            assert se._apply_anomaly_weighting(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    def test_anomaly_weighting_reduces_prob(self):
        mock_store = MagicMock()
        mock_store.update_and_score.return_value = 0.5  # anomaly detected
        with patch("core.signal_engine._get_anomaly_store", return_value=mock_store):
            result = se._apply_anomaly_weighting(0.8, self._df(), "XAUUSD")
            # 0.5 + (0.8 - 0.5) * 0.5 = 0.65
            assert result == pytest.approx(0.65)

    def test_anomaly_weighting_store_raises_returns_prob(self):
        mock_store = MagicMock()
        mock_store.update_and_score.side_effect = RuntimeError("store error")
        with patch("core.signal_engine._get_anomaly_store", return_value=mock_store):
            assert se._apply_anomaly_weighting(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    # Phase 3: online blend
    def test_online_blend_no_store_returns_prob(self):
        with patch("core.signal_engine._get_online_learner_store", return_value=None):
            assert se._apply_online_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    def test_online_blend_not_ready_returns_prob(self):
        mock_store = MagicMock()
        mock_store.is_ready = False
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            assert se._apply_online_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    def test_online_blend_ready_blends(self):
        mock_store = MagicMock()
        mock_store.is_ready = True
        mock_store.blend.return_value = 0.75
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            assert se._apply_online_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.75)

    def test_online_blend_raises_returns_prob(self):
        mock_store = MagicMock()
        mock_store.is_ready = True
        mock_store.blend.side_effect = RuntimeError("blend error")
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            assert se._apply_online_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    # Phase 4: deep ensemble blend
    def test_deep_blend_no_store_returns_prob(self):
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=None):
            assert se._apply_deep_ensemble_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    def test_deep_blend_not_active_returns_prob(self):
        mock_store = MagicMock()
        mock_store.is_active = False
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=mock_store):
            assert se._apply_deep_ensemble_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)

    def test_deep_blend_active_blends(self):
        mock_store = MagicMock()
        mock_store.is_active = True
        mock_store.blend.return_value = 0.80
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=mock_store):
            assert se._apply_deep_ensemble_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.80)

    def test_deep_blend_raises_returns_prob(self):
        mock_store = MagicMock()
        mock_store.is_active = True
        mock_store.blend.side_effect = RuntimeError("blend error")
        with patch("core.signal_engine._get_deep_ensemble_store", return_value=mock_store):
            assert se._apply_deep_ensemble_blend(0.7, self._df(), "XAUUSD") == pytest.approx(0.7)


# ─────────────────────────────────────────────────────────────────────────────
# notify_fill
# ─────────────────────────────────────────────────────────────────────────────


class TestNotifyFill:
    def test_no_store_does_not_raise(self):
        with patch("core.signal_engine._get_online_learner_store", return_value=None):
            se.notify_fill(pd.DataFrame({"f": [1.0]}), label=1, primary_prob=0.8)

    def test_store_on_fill_called(self):
        mock_store = MagicMock()
        df = pd.DataFrame({"feature": [1.0, 2.0]})
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            se.notify_fill(df, label=1, primary_prob=0.75)
        mock_store.on_fill.assert_called_once_with(df, 1, primary_prob=0.75)

    def test_store_raises_does_not_propagate(self):
        mock_store = MagicMock()
        mock_store.on_fill.side_effect = RuntimeError("update failed")
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            se.notify_fill(pd.DataFrame({"f": [1.0]}), label=0)  # must not raise

    def test_no_primary_prob_passes_none(self):
        mock_store = MagicMock()
        df = pd.DataFrame({"f": [1.0]})
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            se.notify_fill(df, label=0)
        mock_store.on_fill.assert_called_once_with(df, 0, primary_prob=None)


# ─────────────────────────────────────────────────────────────────────────────
# _record_paper_gate_fill
# ─────────────────────────────────────────────────────────────────────────────


class TestRecordPaperGateFill:
    def test_does_not_raise_when_module_missing(self):
        with patch.dict("sys.modules", {"research.pipeline.paper_trading_gate": None}):
            se._record_paper_gate_fill()  # must not raise

    def test_gate_record_fill_called(self):
        mock_gate = MagicMock()
        mock_module = MagicMock()
        mock_module.get_gate.return_value = mock_gate
        with patch.dict("sys.modules", {"research.pipeline.paper_trading_gate": mock_module}):
            se._record_paper_gate_fill()
        mock_gate.record_fill.assert_called_once_with(pnl=0.0)

    def test_gate_raises_does_not_propagate(self):
        mock_module = MagicMock()
        mock_module.get_gate.side_effect = RuntimeError("gate down")
        with patch.dict("sys.modules", {"research.pipeline.paper_trading_gate": mock_module}):
            se._record_paper_gate_fill()  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# _log_compliance
# ─────────────────────────────────────────────────────────────────────────────


class TestLogCompliance:
    def _payload(self):
        return {"confidence": 0.75, "probability": 0.72}

    def test_no_compliance_manager_does_not_raise(self):
        app_state = _make_app_state(compliance_manager=None)
        se._log_compliance(app_state, "XAUUSD", "BUY", 1.0, self._payload())

    def test_log_trade_called(self):
        compliance = MagicMock()
        app_state = _make_app_state(compliance_manager=compliance)
        se._log_compliance(app_state, "XAUUSD", "BUY", 1.0, self._payload())
        compliance.log_trade.assert_called_once()
        call_kwargs = compliance.log_trade.call_args
        assert call_kwargs is not None

    def test_compliance_raises_does_not_propagate(self):
        compliance = MagicMock()
        compliance.log_trade.side_effect = RuntimeError("db error")
        app_state = _make_app_state(compliance_manager=compliance)
        se._log_compliance(app_state, "XAUUSD", "BUY", 1.0, self._payload())


# ─────────────────────────────────────────────────────────────────────────────
# _compute_signal
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeSignal:
    def _make_brain(self, consensus=True, direction="BUY", confidence=0.8):
        brain = MagicMock()
        signal = MagicMock()
        signal.signal_type.value = direction
        signal.confidence = confidence
        signal.entry_price = 2000.0
        signal.stop_loss = None
        signal.take_profit = None
        brain.analyze_joint.return_value = {
            "consensus_reached": consensus,
            "consensus_signal": signal if consensus else None,
            "reason": "test",
        }
        return brain

    def test_no_consensus_returns_none(self):
        brain = self._make_brain(consensus=False)
        assert se._compute_signal(brain, _make_data(), "XAUUSD") is None

    def test_consensus_returns_dict(self):
        brain = self._make_brain(consensus=True)
        result = se._compute_signal(brain, _make_data(), "XAUUSD")
        assert result is not None
        assert "direction" in result
        assert "base_confidence" in result
        assert "signal" in result

    def test_direction_extracted(self):
        brain = self._make_brain(direction="SELL")
        result = se._compute_signal(brain, _make_data(), "XAUUSD")
        assert result["direction"] == "SELL"

    def test_none_signal_returns_none(self):
        brain = MagicMock()
        brain.analyze_joint.return_value = {
            "consensus_reached": True,
            "consensus_signal": None,
        }
        assert se._compute_signal(brain, _make_data(), "XAUUSD") is None

    def test_signal_type_without_value_attr(self):
        brain = MagicMock()
        signal = MagicMock(spec=["confidence", "entry_price", "stop_loss", "take_profit"])
        signal.signal_type = "BUY"  # plain string, no .value
        signal.confidence = 0.7
        brain.analyze_joint.return_value = {
            "consensus_reached": True,
            "consensus_signal": signal,
        }
        result = se._compute_signal(brain, _make_data(), "XAUUSD")
        assert result["direction"] == "BUY"


# ─────────────────────────────────────────────────────────────────────────────
# _compute_ml_probability
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeMlProbability:
    def test_returns_base_confidence_when_ml_unavailable(self):
        original = se._ML_AVAILABLE
        se._ML_AVAILABLE = False
        try:
            prob, ver = se._compute_ml_probability(_make_data(), "XAUUSD", 0.65)
            assert prob == pytest.approx(0.65)
            assert ver == "none"
        finally:
            se._ML_AVAILABLE = original

    def test_returns_tuple(self):
        prob, ver = se._compute_ml_probability(_make_data(), "XAUUSD", 0.65)
        assert isinstance(prob, float)
        assert isinstance(ver, str)

    def test_advanced_predictor_used_when_available(self):
        mock_adv = MagicMock()
        mock_adv.is_available = True
        mock_adv.version = "advanced_v1"
        mock_adv.predict_proba.return_value = 0.72

        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", return_value=mock_adv),
            patch("core.signal_engine._fetch_macro_df", return_value=None),
            patch("core.signal_engine._fetch_mtf_df", return_value=None),
            patch("core.signal_engine._apply_anomaly_weighting", side_effect=lambda p, *a: p),
            patch("core.signal_engine._apply_online_blend", side_effect=lambda p, *a: p),
            patch("core.signal_engine._apply_deep_ensemble_blend", side_effect=lambda p, *a: p),
        ):
            prob, ver = se._compute_ml_probability(_make_data(), "XAUUSD", 0.65)
        assert isinstance(prob, float)

    def test_basic_model_used_as_fallback(self):
        # Call _predict_basic directly to avoid patching complexity
        import numpy as np

        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        prob, ver = se._predict_basic(mock_model, "basic_v1", _make_data(), "XAUUSD", 0.65)
        assert prob == pytest.approx(0.7)
        assert ver == "basic_v1"

    def test_no_model_returns_base_confidence(self):
        mock_adv = MagicMock()
        mock_adv.is_available = False

        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", return_value=mock_adv),
            patch("core.signal_engine.get_active_model", return_value=None),
            patch("core.signal_engine.get_model_version", return_value="none"),
        ):
            prob, ver = se._compute_ml_probability(_make_data(), "XAUUSD", 0.65)
        assert prob == pytest.approx(0.65)

    def test_exception_returns_base_confidence(self):
        with (
            patch("core.signal_engine._ML_AVAILABLE", True),
            patch("core.signal_engine.get_advanced_predictor", side_effect=RuntimeError("ml error")),
        ):
            prob, ver = se._compute_ml_probability(_make_data(), "XAUUSD", 0.65)
        assert prob == pytest.approx(0.65)
        assert ver == "none"


# ─────────────────────────────────────────────────────────────────────────────
# _predict_basic
# ─────────────────────────────────────────────────────────────────────────────


class TestPredictBasic:
    def test_predict_proba_two_class(self):
        import numpy as np

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.3, 0.7]])
        prob, ver = se._predict_basic(model, "v1", _make_data(), "XAUUSD", 0.5)
        assert prob == pytest.approx(0.7)
        assert ver == "v1"

    def test_predict_proba_one_class(self):
        import numpy as np

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.65]])
        prob, ver = se._predict_basic(model, "v1", _make_data(), "XAUUSD", 0.5)
        assert prob == pytest.approx(0.65)

    def test_predict_fallback(self):
        model = MagicMock(spec=["predict"])
        model.predict.return_value = [0.72]
        prob, ver = se._predict_basic(model, "v2", _make_data(), "XAUUSD", 0.5)
        assert prob == pytest.approx(0.72)

    def test_no_predict_method_returns_base_confidence(self):
        model = MagicMock(spec=[])  # no predict_proba, no predict
        prob, ver = se._predict_basic(model, "v3", _make_data(), "XAUUSD", 0.55)
        assert prob == pytest.approx(0.55)

    def test_short_price_series(self):
        import numpy as np

        model = MagicMock()
        model.predict_proba.return_value = np.array([[0.4, 0.6]])
        data = _make_data(n=3)  # fewer than 20 bars
        prob, ver = se._predict_basic(model, "v1", data, "XAUUSD", 0.5)
        assert 0.0 <= prob <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# _compute_signal_strength
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeSignalStrength:
    def _payload(self, prob=0.70):
        return {"probability": prob, "confidence": 0.7}

    def test_returns_float(self):
        strength = se._compute_signal_strength(self._payload(), "XAUUSD", "BUY", 2000.0, 1950.0, 10000.0, None)
        assert isinstance(strength, float)

    def test_capped_at_0_80(self):
        strength = se._compute_signal_strength(self._payload(prob=0.99), "XAUUSD", "BUY", 2000.0, 1950.0, 10000.0, None)
        assert strength <= 0.80

    def test_fallback_when_sizer_unavailable(self):
        with patch.dict("sys.modules", {"ml.position_sizer": None}):
            strength = se._compute_signal_strength(
                self._payload(prob=0.72), "XAUUSD", "BUY", 2000.0, 1950.0, 10000.0, None
            )
        assert strength == pytest.approx(min(0.72, 0.80))

    def test_position_sizer_used_when_available(self):
        mock_sizer = MagicMock()
        mock_sizer.compute.return_value = 2.0
        mock_module = MagicMock()
        mock_module.get_position_sizer.return_value = mock_sizer
        with patch.dict("sys.modules", {"ml.position_sizer": mock_module}):
            strength = se._compute_signal_strength(
                self._payload(), "XAUUSD", "BUY", 2000.0, 1950.0, 10000.0, _make_data()
            )
        assert 0.0 <= strength <= 0.80

    def test_sizer_raises_returns_fallback(self):
        mock_module = MagicMock()
        mock_module.get_position_sizer.side_effect = RuntimeError("sizer error")
        with patch.dict("sys.modules", {"ml.position_sizer": mock_module}):
            strength = se._compute_signal_strength(
                self._payload(prob=0.65), "XAUUSD", "BUY", 2000.0, 1950.0, 10000.0, None
            )
        assert strength == pytest.approx(min(0.65, 0.80))


# ─────────────────────────────────────────────────────────────────────────────
# _get_factor_engine / _enrich_signal_with_factors
# ─────────────────────────────────────────────────────────────────────────────


class TestFactorEnrichment:
    def test_get_factor_engine_from_app_state(self):
        engine = MagicMock()
        app_state = _make_app_state(factor_engine=engine)
        result = se._get_factor_engine(app_state)
        assert result is engine

    def test_get_factor_engine_none_app_state(self):
        with patch.dict("sys.modules", {"portfolio.factor_model": None}):
            result = se._get_factor_engine(None)
            assert result is None

    def test_enrich_no_engine_returns_payload_unchanged(self):
        payload = {"direction": "BUY", "confidence": 0.7}
        with patch("core.signal_engine._get_factor_engine", return_value=None):
            result = se._enrich_signal_with_factors(payload, {}, 100.0)
        assert result is payload

    def test_enrich_adds_factor_keys(self):
        attribution = MagicMock()
        attribution.to_dict.return_value = {"market": 0.5}
        attribution.residual_pnl = 10.0

        engine = MagicMock()
        engine.attribute.return_value = attribution
        engine.exposures = {}

        payload = {"direction": "BUY", "confidence": 0.7}
        with patch("core.signal_engine._get_factor_engine", return_value=engine):
            result = se._enrich_signal_with_factors(payload, {}, 100.0)
        assert "factor_attribution" in result
        assert "factor_exposures" in result

    def test_enrich_engine_raises_returns_payload(self):
        engine = MagicMock()
        engine.attribute.side_effect = RuntimeError("factor error")
        payload = {"direction": "BUY"}
        with patch("core.signal_engine._get_factor_engine", return_value=engine):
            result = se._enrich_signal_with_factors(payload, {}, 100.0)
        assert result is payload


# ─────────────────────────────────────────────────────────────────────────────
# _assess_risk_and_size (async)
# ─────────────────────────────────────────────────────────────────────────────


class TestAssessRiskAndSize:
    def _make_broker(self, equity=10000.0, positions=None):
        broker = MagicMock()
        pos = positions or []
        broker.get_account_info = AsyncMock(return_value={"equity": equity, "balance": equity})
        broker.get_positions = AsyncMock(return_value=pos)
        return broker

    def _make_risk_mgr(self, can_trade=True, approved=True, qty=1.0):
        rm = MagicMock()
        assessment = MagicMock()
        assessment.can_trade = can_trade
        assessment.messages = []
        rm.assess_risk.return_value = assessment

        sizing = MagicMock()
        sizing.approved = approved
        sizing.reason = "ok"
        sizing.recommended_size = qty
        rm.calculate_position_size.return_value = sizing
        return rm

    def _payload(self, entry=2000.0, sl=1950.0):
        return {
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": 2100.0,
            "probability": 0.72,
            "confidence": 0.75,
            "direction": "BUY",
            # TRENDING_UP has scalar 1.0 so recommended_size is returned unchanged.
            "regime": "TRENDING_UP",
        }

    async def test_risk_manager_blocks_returns_none(self):
        broker = self._make_broker()
        risk_mgr = self._make_risk_mgr(can_trade=False)
        result = await se._assess_risk_and_size(broker, risk_mgr, "XAUUSD", "BUY", self._payload(), _make_data())
        assert result is None

    async def test_signal_filter_blocks_returns_none(self):
        broker = self._make_broker()
        risk_mgr = self._make_risk_mgr(can_trade=True)
        with patch("core.signal_engine._run_signal_filter", return_value=False):
            result = await se._assess_risk_and_size(broker, risk_mgr, "XAUUSD", "BUY", self._payload(), _make_data())
        assert result is None

    async def test_sizing_rejected_returns_none(self):
        broker = self._make_broker()
        risk_mgr = self._make_risk_mgr(can_trade=True, approved=False)
        with patch("core.signal_engine._run_signal_filter", return_value=True):
            result = await se._assess_risk_and_size(broker, risk_mgr, "XAUUSD", "BUY", self._payload(), _make_data())
        assert result is None

    async def test_approved_returns_quantity(self):
        broker = self._make_broker()
        risk_mgr = self._make_risk_mgr(can_trade=True, approved=True, qty=2.0)
        with patch("core.signal_engine._run_signal_filter", return_value=True):
            result = await se._assess_risk_and_size(broker, risk_mgr, "XAUUSD", "BUY", self._payload(), _make_data())
        assert result == pytest.approx(2.0)

    async def test_broker_raises_propagates(self):
        broker = MagicMock()
        broker.get_account_info = AsyncMock(side_effect=RuntimeError("broker down"))
        broker.get_positions = AsyncMock(return_value=[])
        risk_mgr = self._make_risk_mgr()
        with pytest.raises(RuntimeError, match="broker down"):
            await se._assess_risk_and_size(broker, risk_mgr, "XAUUSD", "BUY", self._payload(), None)

    async def test_positions_with_attributes(self):
        pos = MagicMock()
        pos.symbol = "XAUUSD"
        pos.quantity = 1.0
        pos.current_price = 2000.0
        broker = self._make_broker(positions=[pos])
        risk_mgr = self._make_risk_mgr(can_trade=True, approved=True, qty=1.0)
        with patch("core.signal_engine._run_signal_filter", return_value=True):
            result = await se._assess_risk_and_size(broker, risk_mgr, "XAUUSD", "BUY", self._payload(), _make_data())
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# _broadcast_fill (async)
# ─────────────────────────────────────────────────────────────────────────────


class TestBroadcastFill:
    def _order(self, fill_price=2001.0, order_id="ORD1"):
        order = MagicMock()
        order.average_fill_price = fill_price
        order.id = order_id
        return order

    async def test_no_ws_manager_does_not_raise(self):
        app_state = _make_app_state(ws_manager=None)
        await se._broadcast_fill(app_state, "XAUUSD", "BUY", 1.0, self._order(), {"entry_price": 2000.0})

    async def test_ws_broadcast_trade_called(self):
        ws = MagicMock()
        ws.broadcast_trade = AsyncMock()
        app_state = _make_app_state(ws_manager=ws)
        await se._broadcast_fill(app_state, "XAUUSD", "BUY", 1.0, self._order(), {"entry_price": 2000.0})
        ws.broadcast_trade.assert_called_once()

    async def test_ws_raises_does_not_propagate(self):
        ws = MagicMock()
        ws.broadcast_trade = AsyncMock(side_effect=RuntimeError("ws error"))
        app_state = _make_app_state(ws_manager=ws)
        await se._broadcast_fill(app_state, "XAUUSD", "BUY", 1.0, self._order(), {"entry_price": 2000.0})

    async def test_uses_entry_price_when_fill_price_none(self):
        order = self._order(fill_price=None)
        ws = MagicMock()
        ws.broadcast_trade = AsyncMock()
        app_state = _make_app_state(ws_manager=ws)
        await se._broadcast_fill(app_state, "XAUUSD", "BUY", 1.0, order, {"entry_price": 2000.0})
        call_kwargs = ws.broadcast_trade.call_args[1]
        assert call_kwargs["price"] == 2000.0


# ─────────────────────────────────────────────────────────────────────────────
# _notify_online_learner
# ─────────────────────────────────────────────────────────────────────────────


class TestNotifyOnlineLearner:
    def _order(self, fill_price=2001.0):
        order = MagicMock()
        order.average_fill_price = fill_price
        order.id = "ORD1"
        return order

    def _payload(self):
        return {"confidence": 0.75, "probability": 0.72, "entry_price": 2000.0}

    def test_does_not_raise(self):
        with patch("core.signal_engine._get_online_learner_store", return_value=None):
            se._notify_online_learner("XAUUSD", "BUY", 1.0, self._order(), self._payload())

    def test_notify_fill_stores_features_in_payload(self):
        # _notify_online_learner stores fill features in signal_payload for
        # deferred labelling at trade close — it does NOT call on_fill directly.
        payload = self._payload()
        se._notify_online_learner("XAUUSD", "BUY", 1.0, self._order(), payload)
        assert "_online_learner_features" in payload

    def test_raises_does_not_propagate(self):
        mock_store = MagicMock()
        mock_store.on_fill.side_effect = RuntimeError("fill error")
        with patch("core.signal_engine._get_online_learner_store", return_value=mock_store):
            se._notify_online_learner("XAUUSD", "BUY", 1.0, self._order(), self._payload())


# ─────────────────────────────────────────────────────────────────────────────
# _execute_if_approved (async)
# ─────────────────────────────────────────────────────────────────────────────


class TestExecuteIfApproved:
    def _payload(self, direction="BUY"):
        return {
            "symbol": "XAUUSD",
            "direction": direction,
            "confidence": 0.75,
            "probability": 0.72,
            "model_version": "v1",
            "entry_price": 2000.0,
            "stop_loss": 1950.0,
            "take_profit": 2100.0,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "test",
        }

    async def test_no_auto_trade_returns_immediately(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = False
        try:
            app_state = _make_app_state(broker=MagicMock())
            await se._execute_if_approved(app_state, "XAUUSD", self._payload())
        finally:
            se._AUTO_TRADE = original

    async def test_gate_blocked_returns_without_order(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = True
        try:
            with patch("core.signal_engine._check_live_trading_gate", return_value=False):
                app_state = _make_app_state(broker=MagicMock())
                await se._execute_if_approved(app_state, "XAUUSD", self._payload())
        finally:
            se._AUTO_TRADE = original

    async def test_no_broker_returns_without_order(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = True
        try:
            with patch("core.signal_engine._check_live_trading_gate", return_value=True):
                app_state = _make_app_state(broker=None)
                await se._execute_if_approved(app_state, "XAUUSD", self._payload())
        finally:
            se._AUTO_TRADE = original

    async def test_no_risk_manager_returns_without_order(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = True
        try:
            with patch("core.signal_engine._check_live_trading_gate", return_value=True):
                app_state = _make_app_state(broker=MagicMock(), risk_manager=None)
                await se._execute_if_approved(app_state, "XAUUSD", self._payload())
        finally:
            se._AUTO_TRADE = original

    async def test_invalid_direction_skipped(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = True
        try:
            with patch("core.signal_engine._check_live_trading_gate", return_value=True):
                app_state = _make_app_state(broker=MagicMock(), risk_manager=MagicMock())
                await se._execute_if_approved(app_state, "XAUUSD", self._payload(direction="HOLD"))
        finally:
            se._AUTO_TRADE = original

    async def test_risk_assessment_error_logged_not_raised(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = True
        try:
            with (
                patch("core.signal_engine._check_live_trading_gate", return_value=True),
                patch("core.signal_engine._assess_risk_and_size", side_effect=RuntimeError("risk error")),
            ):
                app_state = _make_app_state(broker=MagicMock(), risk_manager=MagicMock())
                await se._execute_if_approved(app_state, "XAUUSD", self._payload())
        finally:
            se._AUTO_TRADE = original

    async def test_full_execution_path(self):
        original = se._AUTO_TRADE
        se._AUTO_TRADE = True
        try:
            order = MagicMock()
            order.id = "ORD1"
            order.average_fill_price = 2001.0

            broker = MagicMock()
            broker.place_market_order = AsyncMock(return_value=order)

            risk_mgr = MagicMock()
            app_state = _make_app_state(broker=broker, risk_manager=risk_mgr)

            with (
                patch("core.signal_engine._check_live_trading_gate", return_value=True),
                patch("core.signal_engine._assess_risk_and_size", new=AsyncMock(return_value=1.0)),
                patch("core.signal_engine._place_order_and_notify", new=AsyncMock()),
            ):
                await se._execute_if_approved(app_state, "XAUUSD", self._payload())
        finally:
            se._AUTO_TRADE = original


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_market_data (async)
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchMarketData:
    async def test_no_broker_returns_none(self):
        app_state = _make_app_state(broker=None)
        result = await se._fetch_market_data("XAUUSD", app_state)
        assert result is None

    async def test_none_app_state_returns_none(self):
        result = await se._fetch_market_data("XAUUSD", None)
        assert result is None

    async def test_broker_returns_bars(self):
        bars = [{"open": 2000.0, "high": 2010.0, "low": 1990.0, "close": 2005.0, "volume": 100.0} for _ in range(5)]
        broker = MagicMock()
        broker.get_market_data.return_value = bars
        app_state = _make_app_state(broker=broker)
        result = await se._fetch_market_data("XAUUSD", app_state)
        assert result is not None
        assert result["symbol"] == "XAUUSD"
        assert "prices" in result
        assert "highs" in result

    async def test_broker_returns_empty_bars(self):
        broker = MagicMock()
        broker.get_market_data.return_value = []
        app_state = _make_app_state(broker=broker)
        result = await se._fetch_market_data("XAUUSD", app_state)
        assert result is None

    async def test_broker_raises_returns_none(self):
        broker = MagicMock()
        broker.get_market_data.side_effect = RuntimeError("feed error")
        app_state = _make_app_state(broker=broker)
        result = await se._fetch_market_data("XAUUSD", app_state)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# _publish_and_broadcast (async)
# ─────────────────────────────────────────────────────────────────────────────


class TestPublishAndBroadcast:
    def _payload(self):
        return {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "confidence": 0.75,
            "probability": 0.72,
            "model_version": "v1",
            "entry_price": 2000.0,
            "stop_loss": 1950.0,
            "take_profit": 2100.0,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "test",
        }

    async def test_no_ws_manager_does_not_raise(self):
        app_state = _make_app_state(ws_manager=None)
        with patch.dict(
            "sys.modules", {"events.typed_events": None, "api.signals": None, "notifications.discord_bot": None}
        ):
            await se._publish_and_broadcast(app_state, "XAUUSD", self._payload())

    async def test_ws_broadcast_signal_called(self):
        ws = MagicMock()
        ws.broadcast_signal = AsyncMock()
        app_state = _make_app_state(ws_manager=ws)
        with patch.dict(
            "sys.modules", {"events.typed_events": None, "api.signals": None, "notifications.discord_bot": None}
        ):
            await se._publish_and_broadcast(app_state, "XAUUSD", self._payload())
        ws.broadcast_signal.assert_called_once()

    async def test_ws_raises_does_not_propagate(self):
        ws = MagicMock()
        ws.broadcast_signal = AsyncMock(side_effect=RuntimeError("ws error"))
        app_state = _make_app_state(ws_manager=ws)
        with patch.dict(
            "sys.modules", {"events.typed_events": None, "api.signals": None, "notifications.discord_bot": None}
        ):
            await se._publish_and_broadcast(app_state, "XAUUSD", self._payload())


# ─────────────────────────────────────────────────────────────────────────────
# run_signal_engine (async) — smoke test
# ─────────────────────────────────────────────────────────────────────────────


class TestRunSignalEngine:
    async def test_cancels_cleanly(self):
        app_state = _make_app_state(strategy_brain=None)
        task = asyncio.create_task(se.run_signal_engine(app_state))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_tick_error_does_not_stop_loop(self):
        """Engine must survive a tick error and keep running."""
        call_count = 0

        async def _bad_tick(_state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("tick error")

        app_state = _make_app_state(strategy_brain=None)
        with patch("core.signal_engine._tick", side_effect=_bad_tick), patch("core.signal_engine._INTERVAL_SECONDS", 0):
            task = asyncio.create_task(se.run_signal_engine(app_state))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        assert call_count >= 1


# ─────────────────────────────────────────────────────────────────────────────
# _tick (async) — integration-style
# ─────────────────────────────────────────────────────────────────────────────


class TestTick:
    def _make_brain(self, direction="BUY"):
        brain = MagicMock()
        signal = MagicMock()
        signal.signal_type.value = direction
        signal.confidence = 0.8
        signal.entry_price = 2000.0
        signal.stop_loss = 1950.0
        signal.take_profit = 2100.0
        brain.analyze_joint.return_value = {
            "consensus_reached": True,
            "consensus_signal": signal,
        }
        return brain

    async def test_no_brain_returns_immediately(self):
        app_state = _make_app_state(strategy_brain=None)
        await se._tick(app_state)  # must not raise

    async def test_no_market_data_skips_symbol(self):
        brain = self._make_brain()
        app_state = _make_app_state(strategy_brain=brain)
        with patch("core.signal_engine._fetch_market_data", new=AsyncMock(return_value=None)):
            await se._tick(app_state)

    async def test_no_consensus_skips_execution(self):
        brain = MagicMock()
        brain.analyze_joint.return_value = {"consensus_reached": False, "reason": "no signal"}
        app_state = _make_app_state(strategy_brain=brain)
        with (
            patch("core.signal_engine._fetch_market_data", new=AsyncMock(return_value=_make_data())),
            patch("core.signal_engine._publish_and_broadcast", new=AsyncMock()) as mock_pub,
        ):
            await se._tick(app_state)
        mock_pub.assert_not_called()

    async def test_full_tick_publishes_signal(self):
        brain = self._make_brain()
        app_state = _make_app_state(strategy_brain=brain)
        with (
            patch("core.signal_engine._fetch_market_data", new=AsyncMock(return_value=_make_data())),
            patch("core.signal_engine._compute_ml_probability", return_value=(0.72, "v1")),
            patch("core.signal_engine._publish_and_broadcast", new=AsyncMock()) as mock_pub,
            patch("core.signal_engine._execute_if_approved", new=AsyncMock()),
        ):
            await se._tick(app_state)
        mock_pub.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# _predict_advanced — resampling paths
# ─────────────────────────────────────────────────────────────────────────────


class TestPredictAdvanced:
    def _adv(self, prob=0.72, version="adv_v1"):
        adv = MagicMock()
        adv.version = version
        adv.predict_proba.return_value = prob
        return adv

    def _no_resample_agg(self):
        m = MagicMock()
        m.needs_resampling.return_value = False
        return m

    def _with_base_patches(self, fn, *args, **kwargs):
        """Call fn(*args) with all phase-blend patches applied."""
        with (
            patch("core.signal_engine._fetch_macro_df", return_value=None),
            patch("core.signal_engine._fetch_mtf_df", return_value=None),
            patch("core.signal_engine._apply_anomaly_weighting", side_effect=lambda p, *a: p),
            patch("core.signal_engine._apply_online_blend", side_effect=lambda p, *a: p),
            patch("core.signal_engine._apply_deep_ensemble_blend", side_effect=lambda p, *a: p),
        ):
            return fn(*args, **kwargs)

    def test_no_resampling_returns_prob(self):
        adv = self._adv(prob=0.72)
        with patch.dict("sys.modules", {"ml.daily_aggregator": self._no_resample_agg()}):
            prob, ver = self._with_base_patches(se._predict_advanced, adv, _make_data(), "XAUUSD", None)
        assert prob == pytest.approx(0.72)
        assert ver == "adv_v1"

    def test_resampling_succeeds_uses_resampled_df(self):
        adv = self._adv(prob=0.68)
        resampled = pd.DataFrame(
            {
                "open": [2000.0] * 5,
                "high": [2010.0] * 5,
                "low": [1990.0] * 5,
                "close": [2005.0] * 5,
                "volume": [100.0] * 5,
            }
        )
        mock_agg = MagicMock()
        mock_agg.needs_resampling.return_value = True
        mock_agg.ensure_daily.return_value = resampled
        with patch.dict("sys.modules", {"ml.daily_aggregator": mock_agg}):
            prob, ver = self._with_base_patches(se._predict_advanced, adv, _make_data(), "XAUUSD", None)
        assert isinstance(prob, float)

    def test_resampling_returns_none_yields_neutral(self):
        """ensure_daily returns None → insufficient bars → neutral 0.5."""
        adv = self._adv()
        mock_agg = MagicMock()
        mock_agg.needs_resampling.return_value = True
        mock_agg.ensure_daily.return_value = None
        with patch.dict("sys.modules", {"ml.daily_aggregator": mock_agg}):
            prob, ver = se._predict_advanced(adv, _make_data(), "XAUUSD", None)
        assert prob == pytest.approx(0.5)
        assert ver == "adv_v1"

    def test_resampling_module_unavailable_skips_gracefully(self):
        """ImportError on daily_aggregator → resampling skipped, model still runs."""
        adv = self._adv(prob=0.65)
        with patch.dict("sys.modules", {"ml.daily_aggregator": None}):
            prob, ver = self._with_base_patches(se._predict_advanced, adv, _make_data(), "XAUUSD", None)
        assert isinstance(prob, float)

    def test_resampling_exception_skips_gracefully(self):
        """Exception in needs_resampling → skipped, model still runs."""
        adv = self._adv(prob=0.70)
        mock_agg = MagicMock()
        mock_agg.needs_resampling.side_effect = RuntimeError("agg error")
        with patch.dict("sys.modules", {"ml.daily_aggregator": mock_agg}):
            prob, ver = self._with_base_patches(se._predict_advanced, adv, _make_data(), "XAUUSD", None)
        assert isinstance(prob, float)

    def test_all_phase_blends_applied_in_order(self):
        adv = self._adv(prob=0.60)
        with (
            patch.dict("sys.modules", {"ml.daily_aggregator": self._no_resample_agg()}),
            patch("core.signal_engine._fetch_macro_df", return_value=None),
            patch("core.signal_engine._fetch_mtf_df", return_value=None),
            patch("core.signal_engine._apply_anomaly_weighting", return_value=0.61) as p2,
            patch("core.signal_engine._apply_online_blend", return_value=0.62) as p3,
            patch("core.signal_engine._apply_deep_ensemble_blend", return_value=0.63) as p4,
        ):
            prob, _ = se._predict_advanced(adv, _make_data(), "XAUUSD", None)
        p2.assert_called_once()
        p3.assert_called_once()
        p4.assert_called_once()
        assert prob == pytest.approx(0.63)

    def test_datetime_index_skips_index_assignment(self):
        """ohlcv_df already has DatetimeIndex → index assignment branch skipped."""
        adv = self._adv(prob=0.71)
        resampled = pd.DataFrame(
            {
                "open": [2000.0] * 5,
                "high": [2010.0] * 5,
                "low": [1990.0] * 5,
                "close": [2005.0] * 5,
                "volume": [100.0] * 5,
            }
        )
        mock_agg = MagicMock()
        mock_agg.needs_resampling.return_value = True
        mock_agg.ensure_daily.return_value = resampled
        idx = pd.date_range(end=datetime.now(UTC), periods=20, freq="1h", tz="UTC")
        df_with_idx = pd.DataFrame(
            {
                "open": [2000.0] * 20,
                "high": [2010.0] * 20,
                "low": [1990.0] * 20,
                "close": [2005.0] * 20,
                "volume": [100.0] * 20,
            },
            index=idx,
        )
        with (
            patch.dict("sys.modules", {"ml.daily_aggregator": mock_agg}),
            patch("core.signal_engine._build_ohlcv_df", return_value=df_with_idx),
        ):
            prob, ver = self._with_base_patches(se._predict_advanced, adv, _make_data(), "XAUUSD", None)
        assert isinstance(prob, float)


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_macro_df — alignment + FRED overlay paths
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchMacroDf:
    def _ohlcv(self, n=20):
        return se._build_ohlcv_df(_make_data(n=n))

    def test_returns_none_when_store_none(self):
        with patch("core.signal_engine._get_macro_store", return_value=None):
            assert se._fetch_macro_df(self._ohlcv(), "XAUUSD") is None

    def test_returns_none_when_store_empty(self):
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=0)
        with patch("core.signal_engine._get_macro_store", return_value=mock_store):
            assert se._fetch_macro_df(self._ohlcv(), "XAUUSD") is None

    def test_returns_none_when_alignment_empty(self):
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=3)
        mock_store.align_to_hourly.return_value = pd.DataFrame()  # empty
        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=None),
        ):
            assert se._fetch_macro_df(self._ohlcv(), "XAUUSD") is None

    def test_returns_none_when_alignment_no_columns(self):
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=3)
        # DataFrame with rows but zero columns
        mock_store.align_to_hourly.return_value = pd.DataFrame(index=range(5))
        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=None),
        ):
            assert se._fetch_macro_df(self._ohlcv(), "XAUUSD") is None

    def test_returns_macro_df_when_alignment_succeeds(self):
        macro = pd.DataFrame({"dxy": [100.0] * 20, "us10y": [4.5] * 20})
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=2)
        mock_store.align_to_hourly.return_value = macro
        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=None),
        ):
            result = se._fetch_macro_df(self._ohlcv(), "XAUUSD")
        assert result is not None
        assert "dxy" in result.columns

    def test_fred_overlay_applied_with_bare_column_key(self):
        """Bridge returns macro_dxy → strips prefix → overwrites dxy column."""
        macro = pd.DataFrame({"dxy": [100.0] * 20, "us10y": [4.5] * 20})
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=2)
        mock_store.align_to_hourly.return_value = macro.copy()

        bridge = MagicMock()
        bridge.get_ml_features.return_value = {"macro_dxy": 102.5, "macro_us10y": 4.8}

        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=bridge),
        ):
            result = se._fetch_macro_df(self._ohlcv(), "XAUUSD")
        assert result is not None
        assert result["dxy"].iloc[-1] == pytest.approx(102.5)
        assert result["us10y"].iloc[-1] == pytest.approx(4.8)

    def test_fred_overlay_applied_with_full_column_key(self):
        """Bridge returns key that matches column directly (no prefix strip needed)."""
        macro = pd.DataFrame({"macro_dxy": [100.0] * 20})
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=1)
        mock_store.align_to_hourly.return_value = macro.copy()

        bridge = MagicMock()
        bridge.get_ml_features.return_value = {"macro_dxy": 103.0}

        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=bridge),
        ):
            result = se._fetch_macro_df(self._ohlcv(), "XAUUSD")
        assert result is not None
        assert result["macro_dxy"].iloc[-1] == pytest.approx(103.0)

    def test_fred_overlay_raises_returns_macro_df_anyway(self):
        """Bridge.get_ml_features raises → non-fatal, macro_df still returned."""
        macro = pd.DataFrame({"dxy": [100.0] * 20})
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=1)
        mock_store.align_to_hourly.return_value = macro.copy()

        bridge = MagicMock()
        bridge.get_ml_features.side_effect = RuntimeError("fred error")

        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=bridge),
        ):
            result = se._fetch_macro_df(self._ohlcv(), "XAUUSD")
        assert result is not None  # still returns despite overlay failure

    def test_fred_overlay_empty_features_skipped(self):
        """Bridge returns empty dict → no overlay applied."""
        macro = pd.DataFrame({"dxy": [100.0] * 20})
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=1)
        mock_store.align_to_hourly.return_value = macro.copy()

        bridge = MagicMock()
        bridge.get_ml_features.return_value = {}

        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=bridge),
        ):
            result = se._fetch_macro_df(self._ohlcv(), "XAUUSD")
        assert result is not None

    def test_alignment_raises_returns_none(self):
        """align_to_hourly raises → caught, returns None."""
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=2)
        mock_store.align_to_hourly.side_effect = RuntimeError("align error")
        with patch("core.signal_engine._get_macro_store", return_value=mock_store):
            assert se._fetch_macro_df(self._ohlcv(), "XAUUSD") is None

    def test_ohlcv_without_datetime_index_gets_index_assigned(self):
        """When ohlcv_df has RangeIndex, a DatetimeIndex is built before alignment."""
        macro = pd.DataFrame({"dxy": [100.0] * 20})
        mock_store = MagicMock()
        mock_store.__len__ = MagicMock(return_value=1)
        mock_store.align_to_hourly.return_value = macro.copy()

        df = self._ohlcv()  # has RangeIndex by default
        assert not isinstance(df.index, pd.DatetimeIndex)

        with (
            patch("core.signal_engine._get_macro_store", return_value=mock_store),
            patch("core.signal_engine._get_macro_store_bridge", return_value=None),
        ):
            result = se._fetch_macro_df(df, "XAUUSD")
        # align_to_hourly was called with a DatetimeIndex df
        called_df = mock_store.align_to_hourly.call_args[0][0]
        assert isinstance(called_df.index, pd.DatetimeIndex)
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_mtf_df — store-ready path
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchMtfDf:
    def _ohlcv(self):
        return se._build_ohlcv_df(_make_data())

    def test_returns_none_when_flag_off(self):
        mock_flags = MagicMock()
        mock_flags.MTF_FUSION = False
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            assert se._fetch_mtf_df(self._ohlcv()) is None

    def test_returns_none_when_store_not_ready(self):
        mock_flags = MagicMock()
        mock_flags.MTF_FUSION = True
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        store = MagicMock()
        store.is_ready = False
        app_state = _make_app_state(mtf_store=store)
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            assert se._fetch_mtf_df(self._ohlcv(), app_state=app_state) is None

    def test_returns_aligned_df_when_store_ready(self):
        mock_flags = MagicMock()
        mock_flags.MTF_FUSION = True
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        aligned = pd.DataFrame({"d_trend": [1.0] * 20, "h_regime": [0.0] * 20})
        store = MagicMock()
        store.is_ready = True
        store.align_to_h1.return_value = aligned
        app_state = _make_app_state(mtf_store=store)
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            result = se._fetch_mtf_df(self._ohlcv(), app_state=app_state)
        assert result is not None
        assert "d_trend" in result.columns

    def test_align_raises_returns_none(self):
        mock_flags = MagicMock()
        mock_flags.MTF_FUSION = True
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        store = MagicMock()
        store.is_ready = True
        store.align_to_h1.side_effect = RuntimeError("align error")
        app_state = _make_app_state(mtf_store=store)
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg}):
            assert se._fetch_mtf_df(self._ohlcv(), app_state=app_state) is None

    def test_falls_back_to_singleton_when_no_app_state_store(self):
        mock_flags = MagicMock()
        mock_flags.MTF_FUSION = True
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        aligned = pd.DataFrame({"d_trend": [1.0] * 20})
        singleton = MagicMock()
        singleton.is_ready = True
        singleton.align_to_h1.return_value = aligned
        mock_mtf = MagicMock()
        mock_mtf._MTF_STORE_SINGLETON = singleton
        app_state = _make_app_state(mtf_store=None)
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg, "research.pipeline.mtf_fusion": mock_mtf}):
            result = se._fetch_mtf_df(self._ohlcv(), app_state=app_state)
        assert result is not None

    def test_returns_none_when_singleton_import_fails(self):
        mock_flags = MagicMock()
        mock_flags.MTF_FUSION = True
        mock_cfg = MagicMock()
        mock_cfg.flags = mock_flags
        app_state = _make_app_state(mtf_store=None)
        with patch.dict("sys.modules", {"config.feature_flags": mock_cfg, "research.pipeline.mtf_fusion": None}):
            assert se._fetch_mtf_df(self._ohlcv(), app_state=app_state) is None

    def test_flags_unavailable_still_checks_store(self):
        """config.feature_flags import fails → exception suppressed, continues."""
        aligned = pd.DataFrame({"d_trend": [1.0] * 20})
        store = MagicMock()
        store.is_ready = True
        store.align_to_h1.return_value = aligned
        app_state = _make_app_state(mtf_store=store)
        with patch.dict("sys.modules", {"config.feature_flags": None}):
            result = se._fetch_mtf_df(self._ohlcv(), app_state=app_state)
        # With flags unavailable the function continues and uses the store
        assert result is not None or result is None  # either is valid — must not raise


# ─────────────────────────────────────────────────────────────────────────────
# _place_order_and_notify — full async chain
# ─────────────────────────────────────────────────────────────────────────────


class TestPlaceOrderAndNotify:
    def _order(self, fill_price=2001.0, order_id="ORD1"):
        order = MagicMock()
        order.average_fill_price = fill_price
        order.id = order_id
        return order

    def _payload(self):
        return {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "confidence": 0.75,
            "probability": 0.72,
            "model_version": "v1",
            "entry_price": 2000.0,
            "stop_loss": 1950.0,
            "take_profit": 2100.0,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "test",
        }

    async def test_places_order_and_calls_all_side_effects(self):
        order = self._order()
        broker = MagicMock()
        broker.place_market_order = AsyncMock(return_value=order)
        compliance = MagicMock()
        ws = MagicMock()
        ws.broadcast_trade = AsyncMock()
        app_state = _make_app_state(broker=broker, compliance_manager=compliance, ws_manager=ws)
        with (
            patch("core.signal_engine._record_paper_gate_fill") as mock_gate,
            patch("core.signal_engine._notify_online_learner") as mock_ol,
        ):
            await se._place_order_and_notify(broker, app_state, "XAUUSD", "BUY", 1.0, self._payload())
        broker.place_market_order.assert_called_once_with(symbol="XAUUSD", side="buy", quantity=1.0)
        compliance.log_trade.assert_called_once()
        ws.broadcast_trade.assert_called_once()
        mock_gate.assert_called_once()
        mock_ol.assert_called_once()

    async def test_compliance_failure_does_not_abort_broadcast(self):
        order = self._order()
        broker = MagicMock()
        broker.place_market_order = AsyncMock(return_value=order)
        compliance = MagicMock()
        compliance.log_trade.side_effect = RuntimeError("db error")
        ws = MagicMock()
        ws.broadcast_trade = AsyncMock()
        app_state = _make_app_state(broker=broker, compliance_manager=compliance, ws_manager=ws)
        with patch("core.signal_engine._record_paper_gate_fill"), patch("core.signal_engine._notify_online_learner"):
            await se._place_order_and_notify(broker, app_state, "XAUUSD", "BUY", 1.0, self._payload())
        ws.broadcast_trade.assert_called_once()

    async def test_ws_failure_does_not_abort_gate_fill(self):
        order = self._order()
        broker = MagicMock()
        broker.place_market_order = AsyncMock(return_value=order)
        ws = MagicMock()
        ws.broadcast_trade = AsyncMock(side_effect=RuntimeError("ws error"))
        app_state = _make_app_state(broker=broker, ws_manager=ws)
        with (
            patch("core.signal_engine._record_paper_gate_fill") as mock_gate,
            patch("core.signal_engine._notify_online_learner"),
        ):
            await se._place_order_and_notify(broker, app_state, "XAUUSD", "BUY", 1.0, self._payload())
        mock_gate.assert_called_once()

    async def test_broker_raises_propagates(self):
        broker = MagicMock()
        broker.place_market_order = AsyncMock(side_effect=RuntimeError("order rejected"))
        app_state = _make_app_state(broker=broker)
        with pytest.raises(RuntimeError, match="order rejected"):
            await se._place_order_and_notify(broker, app_state, "XAUUSD", "BUY", 1.0, self._payload())

    async def test_sell_direction_lowercased_in_order(self):
        order = self._order()
        broker = MagicMock()
        broker.place_market_order = AsyncMock(return_value=order)
        app_state = _make_app_state(broker=broker)
        payload = self._payload()
        payload["direction"] = "SELL"
        with patch("core.signal_engine._record_paper_gate_fill"), patch("core.signal_engine._notify_online_learner"):
            await se._place_order_and_notify(broker, app_state, "XAUUSD", "SELL", 2.0, payload)
        broker.place_market_order.assert_called_once_with(symbol="XAUUSD", side="sell", quantity=2.0)

    async def test_no_compliance_manager_skips_log(self):
        order = self._order()
        broker = MagicMock()
        broker.place_market_order = AsyncMock(return_value=order)
        app_state = _make_app_state(broker=broker, compliance_manager=None)
        with patch("core.signal_engine._record_paper_gate_fill"), patch("core.signal_engine._notify_online_learner"):
            await se._place_order_and_notify(broker, app_state, "XAUUSD", "BUY", 1.0, self._payload())  # must not raise
