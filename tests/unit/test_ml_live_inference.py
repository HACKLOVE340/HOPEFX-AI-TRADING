# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/live_inference.py.
Covers _FeatureCache, AdvancedModelPredictor, LiveInferenceLoop.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _ohlcv(n: int = 120) -> pd.DataFrame:
    np.random.seed(11)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    c = 2000.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        "open": c - 0.5, "high": c + 1.0,
        "low": c - 1.0, "close": c,
        "volume": np.ones(n) * 500,
    }, index=idx)


# ── _FeatureCache ─────────────────────────────────────────────────────────────

class TestFeatureCache:
    def _make_cache(self):
        from ml.live_inference import _FeatureCache
        c = _FeatureCache()
        c._connected = True  # skip real Redis connect
        return c

    def test_get_returns_none_on_miss(self):
        cache = self._make_cache()
        result = cache.get("XAUUSD", "2024-01-01")
        assert result is None

    def test_set_and_get_roundtrip(self):
        cache = self._make_cache()
        df = pd.DataFrame({"f1": [1.0], "f2": [2.0]})
        cache.set("XAUUSD", "2024-01-01", df)
        result = cache.get("XAUUSD", "2024-01-01")
        assert result is not None
        assert "f1" in result.columns

    def test_expired_entry_returns_none(self):
        cache = self._make_cache()
        df = pd.DataFrame({"f1": [1.0]})
        key = cache._make_key("XAUUSD", "ts1")
        # Set with already-expired time
        cache._mem[key] = (time.monotonic() - 1.0, '{"f1": 1.0}')
        result = cache.get("XAUUSD", "ts1")
        assert result is None
        assert key not in cache._mem  # evicted

    def test_evicts_oldest_when_at_capacity(self):
        cache = self._make_cache()
        cache._MAX_MEM = 2
        df = pd.DataFrame({"f1": [1.0]})
        cache.set("XAUUSD", "ts1", df)
        cache.set("XAUUSD", "ts2", df)
        cache.set("XAUUSD", "ts3", df)  # triggers eviction
        assert len(cache._mem) <= 2

    def test_invalidate_clears_memory(self):
        cache = self._make_cache()
        df = pd.DataFrame({"f1": [1.0]})
        cache.set("XAUUSD", "ts1", df)
        cache.set("XAUUSD", "ts2", df)
        deleted = cache.invalidate("XAUUSD")
        assert deleted == 2
        assert len(cache._mem) == 0

    def test_backend_property_memory(self):
        cache = self._make_cache()
        assert cache.backend == "memory"

    def test_backend_property_redis(self):
        cache = self._make_cache()
        cache._redis = MagicMock()
        assert cache.backend == "redis"

    def test_redis_get_returns_cached_value(self):
        cache = self._make_cache()
        mock_redis = MagicMock()
        mock_redis.get.return_value = b'{"f1": 1.0}'
        cache._redis = mock_redis
        result = cache.get("XAUUSD", "ts1")
        assert result is not None

    def test_redis_set_calls_setex(self):
        cache = self._make_cache()
        mock_redis = MagicMock()
        cache._redis = mock_redis
        df = pd.DataFrame({"f1": [1.0]})
        cache.set("XAUUSD", "ts1", df)
        mock_redis.setex.assert_called_once()

    def test_redis_invalidate_deletes_keys(self):
        cache = self._make_cache()
        mock_redis = MagicMock()
        mock_redis.keys.return_value = [b"key1", b"key2"]
        mock_redis.delete.return_value = 2
        cache._redis = mock_redis
        deleted = cache.invalidate("XAUUSD")
        assert deleted == 2

    def test_handles_get_exception(self):
        cache = self._make_cache()
        cache._redis = MagicMock()
        cache._redis.get.side_effect = RuntimeError("redis down")
        result = cache.get("XAUUSD", "ts1")
        assert result is None

    def test_handles_set_exception(self):
        cache = self._make_cache()
        cache._redis = MagicMock()
        cache._redis.setex.side_effect = RuntimeError("redis down")
        df = pd.DataFrame({"f1": [1.0]})
        cache.set("XAUUSD", "ts1", df)  # must not raise

    def test_make_key_is_deterministic(self):
        k1 = _FeatureCache_make_key("XAUUSD", "ts1")
        k2 = _FeatureCache_make_key("XAUUSD", "ts1")
        assert k1 == k2

    def test_try_connect_handles_redis_unavailable(self):
        from ml.live_inference import _FeatureCache
        cache = _FeatureCache()
        with patch.dict("sys.modules", {"redis": None}):
            cache._try_connect()
        assert cache._connected is True  # connected flag set even on failure


def _FeatureCache_make_key(symbol, ts):
    from ml.live_inference import _FeatureCache
    return _FeatureCache._make_key(symbol, ts)


# ── AdvancedModelPredictor ────────────────────────────────────────────────────

class TestAdvancedModelPredictor:
    def _make(self, tmp_path, connected=False):
        from ml.live_inference import _FeatureCache, AdvancedModelPredictor
        cache = _FeatureCache()
        cache._connected = True
        p = AdvancedModelPredictor(
            model_path=tmp_path / "model.pkl",
            min_bars=10,
            cache=cache,
        )
        return p

    def test_is_available_false_when_no_file(self, tmp_path):
        p = self._make(tmp_path)
        assert p.is_available is False

    def test_is_available_true_when_file_exists(self, tmp_path):
        (tmp_path / "model.pkl").write_bytes(b"fake")
        p = self._make(tmp_path)
        assert p.is_available is True

    def test_version_property(self, tmp_path):
        p = self._make(tmp_path)
        assert isinstance(p.version, str)

    def test_load_returns_false_when_file_missing(self, tmp_path):
        p = self._make(tmp_path)
        assert p._load() is False

    def test_load_returns_false_on_bad_pickle(self, tmp_path):
        (tmp_path / "model.pkl").write_bytes(b"not a pickle")
        p = self._make(tmp_path)
        assert p._load() is False

    def test_load_handles_sentry_failure(self, tmp_path):
        p = self._make(tmp_path)
        with patch.dict("sys.modules", {"monitoring.sentry_config": None}):
            result = p._load()
        assert result is False  # file missing

    def test_predict_proba_returns_half_when_model_missing(self, tmp_path):
        p = self._make(tmp_path)
        assert p.predict_proba(_ohlcv(120)) == pytest.approx(0.5)

    def test_predict_proba_returns_half_when_insufficient_bars(self, tmp_path):
        p = self._make(tmp_path)
        p._model = MagicMock()
        assert p.predict_proba(_ohlcv(5)) == pytest.approx(0.5)

    def test_predict_proba_returns_half_when_feature_build_fails(self, tmp_path):
        p = self._make(tmp_path)
        p._model = MagicMock()
        with patch.object(p, "_build_features", return_value=None):
            assert p.predict_proba(_ohlcv(120)) == pytest.approx(0.5)

    def test_predict_proba_returns_float_on_success(self, tmp_path):
        p = self._make(tmp_path)
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        p._model = mock_model
        X = pd.DataFrame(np.random.randn(1, 5), columns=[f"f{i}" for i in range(5)])
        with patch.object(p, "_build_features", return_value=X):
            result = p.predict_proba(_ohlcv(120))
        assert 0.0 <= result <= 1.0

    def test_predict_proba_handles_model_exception(self, tmp_path):
        p = self._make(tmp_path)
        mock_model = MagicMock()
        mock_model.predict_proba.side_effect = RuntimeError("fail")
        p._model = mock_model
        X = pd.DataFrame(np.random.randn(1, 5), columns=[f"f{i}" for i in range(5)])
        with patch.object(p, "_build_features", return_value=X):
            result = p.predict_proba(_ohlcv(120))
        assert result == pytest.approx(0.5)

    def test_predict_proba_aligns_features_to_model(self, tmp_path):
        p = self._make(tmp_path)
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.4, 0.6]])
        mock_model.feature_names_in_ = np.array(["f0", "f1", "f2"])
        p._model = mock_model
        # X has extra column "extra" and is missing "f2"
        X = pd.DataFrame({"f0": [1.0], "f1": [2.0], "extra": [99.0]})
        with patch.object(p, "_build_features", return_value=X):
            result = p.predict_proba(_ohlcv(120))
        assert 0.0 <= result <= 1.0

    def test_predict_proba_with_mtf_features(self, tmp_path):
        p = self._make(tmp_path)
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        p._model = mock_model
        X = pd.DataFrame(np.random.randn(1, 5), columns=[f"f{i}" for i in range(5)])
        mtf = pd.DataFrame({"d_trend": [1.0]}, index=X.index)
        with patch.object(p, "_build_features", return_value=X):
            result = p.predict_proba(_ohlcv(120), mtf_df=mtf)
        assert 0.0 <= result <= 1.0

    def test_predict_signal_long(self, tmp_path):
        p = self._make(tmp_path)
        with patch.object(p, "predict_proba", return_value=0.75):
            sig = p.predict_signal(_ohlcv(120), threshold_long=0.58)
        assert sig["direction"] == "long"
        assert sig["confidence"] > 0

    def test_predict_signal_short(self, tmp_path):
        p = self._make(tmp_path)
        with patch.object(p, "predict_proba", return_value=0.25):
            sig = p.predict_signal(_ohlcv(120), threshold_short=0.42)
        assert sig["direction"] == "short"

    def test_predict_signal_neutral(self, tmp_path):
        p = self._make(tmp_path)
        with patch.object(p, "predict_proba", return_value=0.50):
            sig = p.predict_signal(_ohlcv(120))
        assert sig["direction"] == "neutral"
        assert sig["confidence"] == 0.0

    def test_predict_signal_has_required_keys(self, tmp_path):
        p = self._make(tmp_path)
        with patch.object(p, "predict_proba", return_value=0.60):
            sig = p.predict_signal(_ohlcv(120))
        for k in ["direction", "probability", "confidence", "model_version",
                   "bars_used", "last_close"]:
            assert k in sig

    def test_build_features_uses_cache(self, tmp_path):
        p = self._make(tmp_path)
        ohlcv = _ohlcv(120)
        cached_X = pd.DataFrame({"f1": [1.0]})
        p._cache.set("XAUUSD", ohlcv.index[-1], cached_X)
        result = p._build_features(ohlcv, symbol="XAUUSD")
        assert result is not None
        assert "f1" in result.columns

    def test_build_features_returns_none_on_exception(self, tmp_path):
        p = self._make(tmp_path)
        with patch.dict("sys.modules", {"ml.advanced_features": None}):
            result = p._build_features(_ohlcv(120))
        assert result is None


# ── LiveInferenceLoop ─────────────────────────────────────────────────────────

class TestLiveInferenceLoop:
    def _make_loop(self):
        from ml.live_inference import LiveInferenceLoop
        loop = LiveInferenceLoop(symbol="XAUUSD", interval_seconds=0.01, min_bars=10)
        mock_pred = MagicMock()
        mock_pred.predict_signal.return_value = {
            "direction": "long", "probability": 0.70,
            "confidence": 0.40, "model_version": "v1",
            "bars_used": 120, "last_close": 2000.0,
        }
        loop._predictor = mock_pred
        return loop

    def test_add_and_remove_callback(self):
        loop = self._make_loop()
        cb = MagicMock()
        loop.add_callback(cb)
        assert cb in loop._callbacks
        loop.remove_callback(cb)
        assert cb not in loop._callbacks

    def test_status_returns_expected_keys(self):
        loop = self._make_loop()
        s = loop.status
        assert "symbol" in s
        assert "running" in s
        assert "tick_count" in s
        assert "error_count" in s
        assert "last_signal" in s

    def test_stop_sets_running_false(self):
        loop = self._make_loop()
        loop._running = True
        loop.stop()
        assert loop._running is False

    @pytest.mark.asyncio
    async def test_tick_skips_when_no_ohlcv(self):
        loop = self._make_loop()
        with patch.object(loop, "_fetch_ohlcv", return_value=None):
            await loop._tick()
        assert loop._tick_count == 0

    @pytest.mark.asyncio
    async def test_tick_skips_when_insufficient_bars(self):
        loop = self._make_loop()
        with patch.object(loop, "_fetch_ohlcv", return_value=_ohlcv(3)):
            await loop._tick()
        assert loop._tick_count == 0

    @pytest.mark.asyncio
    async def test_tick_calls_callbacks(self):
        loop = self._make_loop()
        cb = MagicMock()
        loop.add_callback(cb)
        with patch.object(loop, "_fetch_ohlcv", return_value=_ohlcv(120)), \
             patch.object(loop, "_fetch_macro", return_value=None), \
             patch.object(loop, "_apply_signal_filter", side_effect=lambda s, o: s):
            await loop._tick()
        cb.assert_called_once()
        assert loop._tick_count == 1

    @pytest.mark.asyncio
    async def test_tick_handles_predict_exception(self):
        loop = self._make_loop()
        loop._predictor.predict_signal.side_effect = RuntimeError("model crash")
        with patch.object(loop, "_fetch_ohlcv", return_value=_ohlcv(120)), \
             patch.object(loop, "_fetch_macro", return_value=None):
            await loop._tick()
        assert loop._error_count == 1

    @pytest.mark.asyncio
    async def test_tick_handles_callback_exception(self):
        loop = self._make_loop()
        bad_cb = MagicMock(side_effect=RuntimeError("cb crash"))
        loop.add_callback(bad_cb)
        with patch.object(loop, "_fetch_ohlcv", return_value=_ohlcv(120)), \
             patch.object(loop, "_fetch_macro", return_value=None), \
             patch.object(loop, "_apply_signal_filter", side_effect=lambda s, o: s):
            await loop._tick()  # must not raise
        assert loop._tick_count == 1

    @pytest.mark.asyncio
    async def test_run_stops_on_stop_call(self):
        loop = self._make_loop()
        call_count = 0

        async def fake_tick():
            nonlocal call_count
            call_count += 1
            loop.stop()

        with patch.object(loop, "_tick", side_effect=fake_tick), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await loop.run()

        assert call_count >= 1
        assert loop._running is False

    @pytest.mark.asyncio
    async def test_run_handles_tick_exception(self):
        loop = self._make_loop()
        call_count = 0

        async def boom():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("tick error")
            loop.stop()

        with patch.object(loop, "_tick", side_effect=boom), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await loop.run()

        assert loop._error_count == 1

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_from_broker_store(self):
        loop = self._make_loop()
        mock_store = MagicMock()
        mock_store.get.return_value = _ohlcv(120)
        mock_module = MagicMock(get_ohlcv_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"brokers.ohlcv_store": mock_module}):
            result = await loop._fetch_ohlcv()
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_returns_none_when_all_fail(self):
        loop = self._make_loop()
        with patch.dict("sys.modules", {
            "brokers.ohlcv_store": None,
            "data_layer.orchestrator": None,
        }):
            result = await loop._fetch_ohlcv()
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_macro_returns_none(self):
        loop = self._make_loop()
        result = await loop._fetch_macro()
        assert result is None

    def test_apply_signal_filter_passes_through_on_error(self):
        loop = self._make_loop()
        signal = {"direction": "long", "probability": 0.7}
        with patch.dict("sys.modules", {"ml.signal_filter": None}):
            result = loop._apply_signal_filter(signal, _ohlcv(120))
        assert result["filtered"] is True
        assert result["filter_reason"] == "filter_unavailable"

    def test_apply_signal_filter_uses_signal_filter(self):
        loop = self._make_loop()
        signal = {"direction": "long", "probability": 0.7}
        mock_result = MagicMock(passed=True, reason="ok", gate="confidence")
        mock_sf = MagicMock()
        mock_sf.check.return_value = mock_result
        mock_module = MagicMock(get_signal_filter=MagicMock(return_value=mock_sf))
        with patch.dict("sys.modules", {"ml.signal_filter": mock_module}):
            result = loop._apply_signal_filter(signal, _ohlcv(120))
        assert result["filtered"] is True
        assert result["filter_reason"] == "ok"


# ── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_advanced_predictor_returns_same_instance(self):
        import ml.live_inference as li
        li._predictor = None
        from ml.live_inference import get_advanced_predictor, AdvancedModelPredictor
        a = get_advanced_predictor()
        b = get_advanced_predictor()
        assert a is b
        assert isinstance(a, AdvancedModelPredictor)
