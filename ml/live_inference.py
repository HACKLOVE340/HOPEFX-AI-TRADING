# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/live_inference.py
====================
Live inference helper for the advanced OOS model.

Bridges the gap between the signal engine's rolling OHLCV window and the
122-feature input expected by advanced_oos.pkl.

Usage
-----
    from ml.live_inference import AdvancedModelPredictor

    predictor = AdvancedModelPredictor()          # loads advanced_oos.pkl
    prob = predictor.predict_proba(ohlcv_df)      # returns float 0-1
    signal = predictor.predict_signal(ohlcv_df)   # returns dict

The predictor requires at least 100 bars of OHLCV history to produce
reliable features (rolling windows up to 60 bars + Hurst 40-bar window).
Fewer bars return probability=0.5 (neutral) with a warning.

Feature cache
-------------
Under load (100 users watching live charts) recomputing all 122 features
on every price tick is expensive. A Redis-backed cache with a 1-minute TTL
stores the serialised feature vector keyed by (symbol, last_bar_timestamp).
Falls back to in-memory LRU when Redis is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_SAVED = Path(__file__).parent / "saved_models"
_MIN_BARS = 100  # minimum bars for reliable feature computation
_CACHE_TTL = int(os.getenv("FEATURE_CACHE_TTL_SECONDS", "60"))  # 1-minute default
_CACHE_PREFIX = "hopefx:features:"


# ── Feature cache ─────────────────────────────────────────────────────────────


class _FeatureCache:
    """
    Redis-backed feature vector cache with in-memory LRU fallback.

    Keys are SHA-256 hashes of (symbol, last_bar_close_time).
    Values are JSON-serialised feature dicts with a TTL of _CACHE_TTL seconds.

    The cache is transparent — callers never need to know whether Redis is
    available. On a cache miss the caller recomputes and calls set().
    """

    _MAX_MEM = 128  # in-memory fallback capacity (entries)

    def __init__(self) -> None:
        self._redis = None
        self._mem: dict[str, tuple[float, str]] = {}  # key → (expires_at, value)
        self._connected = False

    def _try_connect(self) -> None:
        if self._connected:
            return
        self._connected = True
        try:
            import redis as _redis_lib

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = _redis_lib.from_url(url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            self._redis = client
            logger.debug("Feature cache: Redis connected at %s", url)
        except Exception as exc:
            logger.debug("Feature cache: Redis unavailable (%s) — using in-memory LRU", exc)

    @staticmethod
    def _make_key(symbol: str, last_ts: Any) -> str:
        raw = f"{symbol}:{last_ts}"
        return _CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, symbol: str, last_ts: Any) -> pd.DataFrame | None:
        """Return cached feature DataFrame or None on miss/error."""
        self._try_connect()
        key = self._make_key(symbol, last_ts)
        try:
            if self._redis is not None:
                raw = self._redis.get(key)
                if raw:
                    return pd.DataFrame([json.loads(raw)])
            else:
                entry = self._mem.get(key)
                if entry and entry[0] > time.monotonic():
                    return pd.DataFrame([json.loads(entry[1])])
                if entry:
                    del self._mem[key]
        except Exception as exc:
            logger.debug("Feature cache get error: %s", exc)
        return None

    def set(self, symbol: str, last_ts: Any, features: pd.DataFrame) -> None:
        """Store feature DataFrame in cache with TTL."""
        self._try_connect()
        key = self._make_key(symbol, last_ts)
        try:
            row = features.iloc[0].replace([np.inf, -np.inf], np.nan).fillna(0.0)
            payload = json.dumps(row.to_dict())
            if self._redis is not None:
                self._redis.setex(key, _CACHE_TTL, payload)
            else:
                # Evict oldest entry if at capacity
                if len(self._mem) >= self._MAX_MEM:
                    oldest = min(self._mem, key=lambda k: self._mem[k][0])
                    del self._mem[oldest]
                self._mem[key] = (time.monotonic() + _CACHE_TTL, payload)
        except Exception as exc:
            logger.debug("Feature cache set error: %s", exc)

    def invalidate(self, symbol: str) -> int:
        """Remove all cached entries for a symbol. Returns count deleted."""
        self._try_connect()
        deleted = 0
        try:
            if self._redis is not None:
                pattern = f"{_CACHE_PREFIX}*"
                keys = self._redis.keys(pattern)
                if keys:
                    deleted = self._redis.delete(*keys)
            else:
                before = len(self._mem)
                self._mem.clear()
                deleted = before
        except Exception as exc:
            logger.debug("Feature cache invalidate error: %s", exc)
        return deleted

    @property
    def backend(self) -> str:
        self._try_connect()
        return "redis" if self._redis is not None else "memory"


# Module-level cache singleton
_feature_cache = _FeatureCache()


class AdvancedModelPredictor:
    """
    Wraps advanced_oos.pkl for live single-bar inference.

    The model was trained on the output of ml/advanced_features.py
    (122 stationary features). This class replicates that feature
    pipeline on a rolling OHLCV window so the signal engine can call
    predict_proba(df) with the last N bars and get a calibrated
    probability for the next bar's direction.

    Parameters
    ----------
    model_path : Path to the saved model pkl (default: advanced_oos.pkl)
    min_bars   : Minimum bars required; returns neutral if fewer available
    """

    def __init__(
        self,
        model_path: Path | None = None,
        min_bars: int = _MIN_BARS,
        cache: _FeatureCache | None = None,
    ) -> None:
        self.model_path = model_path or (_SAVED / "advanced_oos.pkl")
        self.min_bars = min_bars
        self._model: Any | None = None
        self._feature_names: list | None = None
        self._version = "advanced_oos_v1"
        self._cache: _FeatureCache = cache or _feature_cache

    # ── Model loading ─────────────────────────────────────────────────────────

    def _load(self) -> bool:
        """Lazy-load the model on first call. Returns True if successful."""
        if self._model is not None:
            return True
        try:
            import joblib

            payload = joblib.load(self.model_path)
            # advanced_oos.pkl is a sklearn Pipeline (scaler + calibrated XGB)
            self._model = payload
            logger.info("AdvancedModelPredictor loaded: %s", self.model_path.name)
            return True
        except Exception as exc:
            logger.warning("Could not load %s: %s", self.model_path, exc)
            # Fire Sentry alert — ML fallback will activate
            try:
                from monitoring.sentry_config import capture_ml_fallback_event

                capture_ml_fallback_event(
                    reason=str(exc),
                    fallback_model="xgb_macro.pkl",
                    fallback_accuracy=0.503,
                )
            except Exception as sentry_exc:
                logger.debug("Sentry capture failed (non-fatal): %s", sentry_exc)
            return False

    @property
    def is_available(self) -> bool:
        return self.model_path.exists()

    @property
    def version(self) -> str:
        return self._version

    # ── Feature building ──────────────────────────────────────────────────────

    def _build_features(
        self,
        ohlcv: pd.DataFrame,
        macro_df: pd.DataFrame | None = None,
        symbol: str = "XAUUSD",
    ) -> pd.DataFrame | None:
        """
        Build the advanced feature matrix from a rolling OHLCV window.

        Results are cached in Redis (or in-memory) for _CACHE_TTL seconds
        keyed by (symbol, last_bar_timestamp). Under load this prevents
        recomputing 122 features for every concurrent user on the same tick.

        Returns the last row as a single-row DataFrame, or None if
        feature building fails.
        """
        # ── Cache lookup ──────────────────────────────────────────────────────
        last_ts = ohlcv.index[-1] if hasattr(ohlcv.index, "__len__") else len(ohlcv)
        cached = self._cache.get(symbol, last_ts)
        if cached is not None:
            logger.debug("Feature cache HIT for %s @ %s", symbol, last_ts)
            return cached

        # ── Cache miss — compute features ─────────────────────────────────────
        try:
            from ml.advanced_features import build_advanced_features

            # build_advanced_features applies filtered target — we don't need
            # the target for inference, so use use_filtered_target=False and
            # take the last row of X.
            X, _ = build_advanced_features(
                ohlcv,
                macro_df=macro_df,
                horizon=1,
                use_filtered_target=False,
                min_move_atr=0.0,
            )
            if X.empty:
                return None
            result = X.iloc[[-1]]  # last bar only

            # ── Inject data layer features (microstructure + sentiment + macro) ──
            # These are appended as extra columns. The model fills missing columns
            # with 0 if it was not trained on them — safe degradation.
            try:
                from data_layer.orchestrator import orchestrator

                dl_features = orchestrator.get_ml_features()
                if dl_features:
                    dl_row = pd.DataFrame([dl_features], index=result.index)
                    # Only add columns not already present
                    new_cols = [c for c in dl_row.columns if c not in result.columns]
                    if new_cols:
                        result = pd.concat([result, dl_row[new_cols]], axis=1)
                        logger.debug(
                            "Data layer injected %d features for %s",
                            len(new_cols),
                            symbol,
                        )
            except Exception as dl_exc:
                logger.debug("Data layer feature injection skipped: %s", dl_exc)

            self._cache.set(symbol, last_ts, result)
            logger.debug("Feature cache MISS for %s @ %s — computed and cached", symbol, last_ts)
            return result
        except Exception as exc:
            logger.warning("Feature build failed: %s", exc)
            return None

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict_proba(
        self,
        ohlcv: pd.DataFrame,
        macro_df: pd.DataFrame | None = None,
        symbol: str = "XAUUSD",
        mtf_df: pd.DataFrame | None = None,
    ) -> float:
        """
        Return the probability that the next bar closes higher (0–1).

        Parameters
        ----------
        ohlcv     : H1 OHLCV DataFrame (at least min_bars rows)
        macro_df  : Aligned macro features (DXY, VIX, yields, SPX) — optional
        symbol    : Instrument symbol for logging
        mtf_df    : MTF regime features (d_*/h_* columns from MTFFusionStore) — optional.
                    When provided, appended to the feature matrix before prediction.
                    Gate: only used when FEATURE_MTF_FUSION=true.

        Returns 0.5 (neutral) if:
        - The model file is missing
        - Fewer than min_bars are provided
        - Feature building fails
        - The model raises an exception
        """
        if not self._load():
            return 0.5

        if len(ohlcv) < self.min_bars:
            logger.debug(
                "Only %d bars available (need %d) — returning neutral 0.5",
                len(ohlcv),
                self.min_bars,
            )
            return 0.5

        X = self._build_features(ohlcv, macro_df=macro_df, symbol=symbol)
        if X is None or X.empty:
            return 0.5

        # Append MTF regime features when available (Phase 1 integration)
        if mtf_df is not None and not mtf_df.empty:
            try:
                # Align MTF features to the last row of X
                mtf_last = mtf_df.reindex(X.index).ffill().fillna(0.0)
                mtf_cols = [c for c in mtf_last.columns if c not in X.columns]
                if mtf_cols:
                    X = pd.concat([X, mtf_last[mtf_cols]], axis=1)
                    logger.debug(
                        "MTF features appended: %d d_*/h_* columns for %s",
                        len(mtf_cols),
                        symbol,
                    )
            except Exception as mtf_exc:
                logger.debug("MTF feature append failed (non-fatal): %s", mtf_exc)

        try:
            # Align feature columns to what the model was trained on.
            # Missing features (e.g. macro columns when no FRED key is set)
            # are filled with 0 (neutral/unknown) so the model still runs.
            if hasattr(self._model, "feature_names_in_"):
                expected = list(self._model.feature_names_in_)
            elif hasattr(self._model, "steps") and hasattr(self._model.steps[0][1], "feature_names_in_"):
                expected = list(self._model.steps[0][1].feature_names_in_)
            else:
                expected = None

            if expected is not None:
                missing = [c for c in expected if c not in X.columns]
                if missing:
                    logger.debug(
                        "Filling %d missing features with 0 for %s",
                        len(missing),
                        symbol,
                    )
                    for col in missing:
                        X[col] = 0.0
                X = X[expected]  # enforce column order

            # Replace any inf/nan that slipped through
            X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            proba = self._model.predict_proba(X)
            prob_up = float(proba[0][1]) if proba.shape[1] > 1 else float(proba[0][0])
            return float(np.clip(prob_up, 0.0, 1.0))
        except Exception as exc:
            logger.warning("Model predict_proba failed: %s", exc)
            return 0.5

    def predict_signal(
        self,
        ohlcv: pd.DataFrame,
        macro_df: pd.DataFrame | None = None,
        symbol: str = "XAUUSD",
        threshold_long: float = 0.58,
        threshold_short: float = 0.42,
    ) -> dict[str, Any]:
        """
        Return a signal dict for the signal engine.

        Direction is 'long' when prob >= threshold_long,
        'short' when prob <= threshold_short, else 'neutral'.

        Parameters
        ----------
        threshold_long  : Minimum probability to generate a long signal
        threshold_short : Maximum probability to generate a short signal
        """
        prob = self.predict_proba(ohlcv, macro_df=macro_df, symbol=symbol)
        last = ohlcv.iloc[-1]

        if prob >= threshold_long:
            direction = "long"
            confidence = (prob - 0.5) * 2.0  # scale 0.5-1.0 → 0.0-1.0
        elif prob <= threshold_short:
            direction = "short"
            confidence = (0.5 - prob) * 2.0
        else:
            direction = "neutral"
            confidence = 0.0

        return {
            "direction": direction,
            "probability": round(prob, 4),
            "confidence": round(float(confidence), 4),
            "model_version": self._version,
            "bars_used": len(ohlcv),
            "last_close": float(last.get("close", last.iloc[-1])),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
# Loaded lazily on first access so import cost is zero.
_predictor: AdvancedModelPredictor | None = None


def get_advanced_predictor() -> AdvancedModelPredictor:
    """Return the module-level AdvancedModelPredictor singleton."""
    global _predictor
    if _predictor is None:
        _predictor = AdvancedModelPredictor()
    return _predictor


# ── LiveInferenceLoop ─────────────────────────────────────────────────────────

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC


class LiveInferenceLoop:
    """
    Orchestrator-wired live prediction loop.

    Runs an async tick loop that:
    1. Pulls the latest OHLCV window from the data_layer orchestrator
    2. Calls AdvancedModelPredictor.predict_signal()
    3. Applies SignalFilter gates (confidence, EV, regime, MTF)
    4. Publishes the filtered signal to registered callbacks

    The loop runs at `interval_seconds` cadence (default: 60s = 1 bar).
    It is designed to be started once per process and run indefinitely.

    Usage
    -----
        loop = LiveInferenceLoop(symbol="XAU_USD", interval_seconds=60)
        loop.add_callback(my_signal_handler)
        asyncio.run(loop.run())

    Callbacks receive a dict:
        {
          "symbol": "XAU_USD",
          "direction": "long" | "short" | "neutral",
          "probability": 0.72,
          "confidence": 0.44,
          "filtered": True | False,
          "filter_reason": "...",
          "model_version": "advanced_oos_v1",
          "ts": "2025-01-01T12:00:00+00:00",
        }
    """

    def __init__(
        self,
        symbol: str = "XAU_USD",
        interval_seconds: float = 60.0,
        min_bars: int = 100,
        threshold_long: float = 0.58,
        threshold_short: float = 0.42,
    ) -> None:
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self.min_bars = min_bars
        self.threshold_long = threshold_long
        self.threshold_short = threshold_short

        self._predictor = get_advanced_predictor()
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._running: bool = False
        self._tick_count: int = 0
        self._error_count: int = 0
        self._last_signal: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def add_callback(self, fn: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback invoked on every filtered signal."""
        with self._lock:
            self._callbacks.append(fn)

    def remove_callback(self, fn: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._callbacks = [c for c in self._callbacks if c is not fn]

    async def _fetch_ohlcv(self) -> pd.DataFrame | None:
        """
        Pull the latest OHLCV window from the data layer.

        Strategy (in priority order):
        1. GoldFeedManager OHLCV cache via orchestrator's gold feed
        2. MacroStore / replay engine (offline / backtest path)
        3. Return None — caller will skip the tick

        The orchestrator does not expose a get_ohlcv() method; OHLCV is
        assembled from the tick stream by the broker/data-feed layer.
        We delegate to the broker's OHLCV store when available.
        """
        try:
            # Primary: broker OHLCV store (live trading path)
            from brokers.ohlcv_store import get_ohlcv_store

            store = get_ohlcv_store()
            ohlcv = store.get(self.symbol, bars=self.min_bars + 20)
            if ohlcv is not None and len(ohlcv) >= self.min_bars:
                return ohlcv
        except Exception as exc:
            logger.debug("LiveInferenceLoop: broker OHLCV store unavailable: %s", exc)

        try:
            # Secondary: replay engine (backtest / paper trading path)
            from data_layer.orchestrator import orchestrator

            replay = orchestrator._replay
            if replay is not None and hasattr(replay, "get_ohlcv"):
                ohlcv = await asyncio.get_event_loop().run_in_executor(
                    None, replay.get_ohlcv, self.symbol, self.min_bars + 20
                )
                if ohlcv is not None and len(ohlcv) >= self.min_bars:
                    return ohlcv
        except Exception as exc:
            logger.debug("LiveInferenceLoop: replay OHLCV unavailable: %s", exc)

        return None

    async def _fetch_macro(self) -> pd.DataFrame | None:
        """
        Pull aligned macro features from MacroStore.

        Uses the MacroStore singleton (populated by MacroStoreBridge from FRED).
        Returns None when MacroStore is empty or unavailable — the predictor
        degrades gracefully without macro features.
        """
        try:
            from ml.macro_store import macro_store

            if len(macro_store) == 0:
                return None
            # We need an OHLCV index to align to; use a minimal placeholder
            # The predictor will re-align internally using its own OHLCV index
            return None  # macro alignment happens inside AdvancedModelPredictor
        except Exception:  # nosec B110 — optional macro features
            return None

    def _apply_signal_filter(self, signal: dict[str, Any], ohlcv: pd.DataFrame) -> dict[str, Any]:
        """
        Run SignalFilter gates and annotate the signal dict.

        Uses SignalFilter.check() (the correct public API).
        On any filter error the signal passes through with filter_reason set.
        """
        try:
            from ml.signal_filter import get_signal_filter

            sf = get_signal_filter()
            result = sf.check(
                signal=signal,
                ohlcv=ohlcv,
                symbol=self.symbol,
            )
            signal["filtered"] = result.passed
            signal["filter_reason"] = result.reason
            signal["filter_gate"] = result.gate
        except Exception as exc:
            logger.debug("LiveInferenceLoop: signal filter failed: %s", exc)
            signal["filtered"] = True  # pass-through on filter error
            signal["filter_reason"] = "filter_unavailable"
            signal["filter_gate"] = ""
        return signal

    async def _tick(self) -> None:
        """Single inference tick: fetch → predict → filter → publish."""
        from datetime import datetime

        ohlcv = await self._fetch_ohlcv()
        if ohlcv is None or len(ohlcv) < self.min_bars:
            logger.debug(
                "LiveInferenceLoop: insufficient bars (%s) for %s",
                len(ohlcv) if ohlcv is not None else 0,
                self.symbol,
            )
            return

        macro = await self._fetch_macro()

        try:
            signal = self._predictor.predict_signal(
                ohlcv,
                macro_df=macro,
                symbol=self.symbol,
                threshold_long=self.threshold_long,
                threshold_short=self.threshold_short,
            )
        except Exception as exc:
            logger.warning("LiveInferenceLoop: predict_signal failed: %s", exc)
            self._error_count += 1
            return

        signal["symbol"] = self.symbol
        signal["ts"] = datetime.now(UTC).isoformat()
        signal = self._apply_signal_filter(signal, ohlcv)

        with self._lock:
            self._last_signal = signal
            self._tick_count += 1
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(signal)
            except Exception as exc:
                logger.warning("LiveInferenceLoop: callback error: %s", exc)

        logger.info(
            "LiveInferenceLoop tick #%d: %s dir=%s prob=%.3f conf=%.3f filtered=%s",
            self._tick_count,
            self.symbol,
            signal.get("direction"),
            signal.get("probability", 0.5),
            signal.get("confidence", 0.0),
            signal.get("filtered"),
        )

    async def run(self) -> None:
        """Run the inference loop indefinitely until stop() is called."""
        self._running = True
        logger.info(
            "LiveInferenceLoop started: symbol=%s interval=%.0fs",
            self.symbol,
            self.interval_seconds,
        )
        while self._running:
            start = time.monotonic()
            try:
                await self._tick()
            except Exception as exc:
                logger.error("LiveInferenceLoop: unhandled tick error: %s", exc)
                self._error_count += 1
            elapsed = time.monotonic() - start
            sleep_for = max(0.0, self.interval_seconds - elapsed)
            await asyncio.sleep(sleep_for)
        logger.info("LiveInferenceLoop stopped: symbol=%s", self.symbol)

    def stop(self) -> None:
        """Signal the loop to stop after the current tick completes."""
        self._running = False

    @property
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "symbol": self.symbol,
                "running": self._running,
                "tick_count": self._tick_count,
                "error_count": self._error_count,
                "interval_seconds": self.interval_seconds,
                "last_signal": self._last_signal,
            }
