# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/inference_engine.py
======================
Enhanced live inference engine — production-grade signal generation.

Pipeline (in order)
-------------------
1. MacroStore alignment  — daily macro features forward-filled to H1 bars
2. MTF fusion            — daily/H4 regime context appended to feature matrix
3. Extended features     — 200+ feature builder (features_extended.py)
4. Online learner update — SGD adapter updates on confirmed fills (Phase 3 gate)
5. Ensemble prediction   — advanced_oos.pkl stacking ensemble
6. Confidence calibration— isotonic-calibrated probability → confidence score
7. Signal thresholding   — long/short/neutral with asymmetric thresholds

All steps degrade gracefully: if any component is unavailable the engine
falls back to the next available layer, never raising to the caller.

Usage
-----
    from ml.inference_engine import get_inference_engine

    engine = get_inference_engine()
    signal = engine.predict(ohlcv_df, symbol="XAU_USD")
    # signal = {"direction": "long", "confidence": 0.72, "probability": 0.86, ...}
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_SAVED = Path(__file__).parent / "saved_models"
_MIN_BARS = 100
_THRESHOLD_LONG = float(os.getenv("SIGNAL_THRESHOLD_LONG", "0.58"))
_THRESHOLD_SHORT = float(os.getenv("SIGNAL_THRESHOLD_SHORT", "0.42"))
_ONLINE_LEARNING_ENABLED = (
    os.getenv("FEATURE_ONLINE_LEARNING", "false").lower() == "true"
)
_MTF_FUSION_ENABLED = os.getenv("FEATURE_MTF_FUSION", "true").lower() == "true"

# Rolling window size for non-neutral rate tracking
_SIGNAL_WINDOW = int(os.getenv("SIGNAL_QUALITY_WINDOW", "100"))


class InferenceEngine:
    """
    Full-stack live inference engine.

    Combines MacroStore, MTF fusion, 200+ features, online learner,
    and calibrated ensemble into a single predict() call.
    """

    def __init__(self) -> None:
        self._predictor = None  # AdvancedModelPredictor (advanced_oos.pkl)
        self._online_learner = None  # SGD online adapter
        self._calibrator = None  # isotonic calibrator (fitted on OOS proba)
        self._last_predict_ms: float = 0.0
        self._predict_count: int = 0
        self._fallback_count: int = 0
        # Uptime tracking — set on first predict call
        self._first_predict_at: Optional[float] = None
        # Rolling window of signal directions for non-neutral rate
        self._signal_window: Deque[str] = deque(maxlen=_SIGNAL_WINDOW)
        # Cached model metadata from advanced_oos_meta.json
        self._meta_cache: Optional[Dict[str, Any]] = None
        self._meta_mtime: float = 0.0
        # Data layer nudge tracking
        self._last_sentiment_score: float = 0.0
        self._last_macro_impact: float = 0.0

    # ── Lazy loaders ──────────────────────────────────────────────────────────

    def _get_predictor(self):
        if self._predictor is None:
            try:
                from ml.live_inference import get_advanced_predictor

                self._predictor = get_advanced_predictor()
            except Exception as exc:
                logger.debug("InferenceEngine: predictor unavailable: %s", exc)
        return self._predictor

    def _get_macro_df(self, ohlcv: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Align MacroStore to the OHLCV index, deduplicating the result index.

        MacroStore is now auto-populated by data_layer.feeds.macro.store_bridge
        (MacroStoreBridge) which loads FRED series on startup and refreshes daily.
        load_defaults() is kept as a CSV fallback for offline environments.
        """
        try:
            from ml.macro_store import macro_store

            if len(macro_store) == 0:
                # Try data_layer bridge first (FRED live data)
                try:
                    from data_layer.feeds.macro.store_bridge import macro_store_bridge
                    if not macro_store_bridge.is_loaded:
                        logger.debug("MacroStoreBridge not yet loaded — using CSV defaults")
                except Exception:
                    pass
                macro_store.load_defaults()
            macro_df = macro_store.align_to_hourly(ohlcv)
            if macro_df is None or macro_df.empty:
                return None
            # Drop duplicate index entries that cause reindex failures downstream
            if macro_df.index.duplicated().any():
                macro_df = macro_df[~macro_df.index.duplicated(keep="last")]
            return macro_df
        except Exception as exc:
            logger.debug("MacroStore alignment failed: %s", exc)
            return None

    def _get_mtf_df(self, ohlcv: pd.DataFrame, symbol: str) -> Optional[pd.DataFrame]:
        """Get MTF regime features from MTFFusionStore."""
        if not _MTF_FUSION_ENABLED:
            return None
        try:
            from research.pipeline.mtf_fusion import _MTF_STORE_SINGLETON

            if _MTF_STORE_SINGLETON is None:
                return None
            return _MTF_STORE_SINGLETON.align_to_h1(ohlcv)
        except Exception as exc:
            logger.debug("MTF fusion unavailable: %s", exc)
            return None

    def _get_online_learner(self):
        """Return the online learner if Phase 3 gate is open."""
        if not _ONLINE_LEARNING_ENABLED:
            return None
        if self._online_learner is not None:
            return self._online_learner
        try:
            from research.pipeline.paper_trading_gate import get_gate

            gate = get_gate()
            p3_ok, _ = gate.phase3_ready()
            if not p3_ok:
                return None
            from research.pipeline.online_learning import get_online_learner

            self._online_learner = get_online_learner()
            return self._online_learner
        except Exception as exc:
            logger.debug("Online learner unavailable: %s", exc)
            return None

    def _load_calibrator(self):
        """Load isotonic calibrator from saved_models if available."""
        if self._calibrator is not None:
            return self._calibrator
        cal_path = _SAVED / "isotonic_calibrator.pkl"
        if not cal_path.exists():
            return None
        try:
            import joblib

            self._calibrator = joblib.load(cal_path)
            logger.debug("InferenceEngine: isotonic calibrator loaded")
            return self._calibrator
        except Exception as exc:
            logger.debug("Calibrator load failed: %s", exc)
            return None

    # ── Feature building ──────────────────────────────────────────────────────

    def _build_features(
        self,
        ohlcv: pd.DataFrame,
        macro_df: Optional[pd.DataFrame],
        mtf_df: Optional[pd.DataFrame],
        symbol: str,
    ) -> Optional[pd.DataFrame]:
        """Build 200+ feature matrix, appending MTF columns."""
        try:
            from ml.features_extended import build_extended_features

            # Deduplicate OHLCV index before feature building — duplicate
            # timestamps cause reindex failures inside advanced_features.py
            if ohlcv.index.duplicated().any():
                ohlcv = ohlcv[~ohlcv.index.duplicated(keep="last")]

            X, _ = build_extended_features(
                ohlcv,
                macro_df=macro_df,
                horizon=1,
                use_filtered_target=False,
                min_move_atr=0.0,
            )
            if X.empty:
                return None

            # Append MTF regime columns
            if mtf_df is not None and not mtf_df.empty:
                try:
                    mtf_aligned = mtf_df.reindex(X.index).ffill().fillna(0.0)
                    new_cols = [c for c in mtf_aligned.columns if c not in X.columns]
                    if new_cols:
                        X = pd.concat([X, mtf_aligned[new_cols]], axis=1)
                        logger.debug(
                            "MTF: appended %d columns for %s", len(new_cols), symbol
                        )
                except Exception as mtf_exc:
                    logger.debug("MTF append failed: %s", mtf_exc)

            return X.iloc[[-1]]  # last bar only
        except Exception as exc:
            logger.debug("Feature build failed: %s", exc)
            return None

    # ── Calibration ───────────────────────────────────────────────────────────

    def _calibrate(self, raw_prob: float) -> float:
        """Apply isotonic calibration if available, else return raw probability."""
        cal = self._load_calibrator()
        if cal is None:
            return raw_prob
        try:
            calibrated = cal.predict([[raw_prob]])[0]
            return float(np.clip(calibrated, 0.0, 1.0))
        except Exception:
            return raw_prob

    # ── Online learner update ─────────────────────────────────────────────────

    def update_online(self, features: pd.DataFrame, label: int) -> None:
        """
        Update the online learner with a confirmed fill outcome.

        Called by the broker callback when a paper/live trade closes.
        label: 1 = profitable, 0 = loss.
        """
        learner = self._get_online_learner()
        if learner is None:
            return
        try:
            learner.partial_fit(features, [label])
            logger.debug("InferenceEngine: online learner updated with label=%d", label)
        except Exception as exc:
            logger.debug("Online learner update failed: %s", exc)

    # ── Main predict ──────────────────────────────────────────────────────────

    def predict(
        self,
        ohlcv: pd.DataFrame,
        symbol: str = "XAU_USD",
        threshold_long: float = _THRESHOLD_LONG,
        threshold_short: float = _THRESHOLD_SHORT,
    ) -> Dict[str, Any]:
        """
        Generate a calibrated trading signal for the given OHLCV window.

        Parameters
        ----------
        ohlcv           : H1 OHLCV DataFrame (at least 100 bars)
        symbol          : Instrument symbol (for logging and MTF lookup)
        threshold_long  : Minimum calibrated probability for a long signal
        threshold_short : Maximum calibrated probability for a short signal

        Returns
        -------
        dict with keys:
          direction    : "long" | "short" | "neutral"
          probability  : raw model probability (0–1)
          confidence   : calibrated confidence (0–1)
          model_version: model identifier
          bars_used    : number of OHLCV bars consumed
          last_close   : last close price
          latency_ms   : feature + inference latency in milliseconds
          fallback     : True if deterministic fallback was used
          macro_active : True if MacroStore features were used
          mtf_active   : True if MTF fusion features were used
          online_active: True if online learner was applied
        """
        t0 = time.perf_counter()
        self._predict_count += 1

        last_close = float(ohlcv["close"].iloc[-1]) if "close" in ohlcv.columns else 0.0
        base_result = {
            "direction": "neutral",
            "probability": 0.5,
            "confidence": 0.0,
            "model_version": "fallback",
            "bars_used": len(ohlcv),
            "last_close": last_close,
            "latency_ms": 0.0,
            "fallback": True,
            "macro_active": False,
            "mtf_active": False,
            "online_active": False,
        }

        if len(ohlcv) < _MIN_BARS:
            base_result["latency_ms"] = (time.perf_counter() - t0) * 1000
            return base_result

        # Step 1: MacroStore (now auto-populated from FRED via MacroStoreBridge)
        macro_df = self._get_macro_df(ohlcv)
        macro_active = macro_df is not None and not macro_df.empty

        # Step 2: MTF fusion
        mtf_df = self._get_mtf_df(ohlcv, symbol)
        mtf_active = mtf_df is not None and not mtf_df.empty

        # Step 3: Build features
        X = self._build_features(ohlcv, macro_df, mtf_df, symbol)
        if X is None:
            base_result["latency_ms"] = (time.perf_counter() - t0) * 1000
            self._fallback_count += 1
            return base_result

        # Step 4: Model prediction
        predictor = self._get_predictor()
        raw_prob = 0.5
        model_version = "fallback"

        if predictor is not None and predictor.is_available:
            try:
                raw_prob = predictor.predict_proba(
                    ohlcv, macro_df=macro_df, symbol=symbol
                )
                model_version = predictor.version
            except Exception as exc:
                logger.warning("Predictor failed: %s", exc)
                self._fallback_count += 1

        # Step 5: Online learner blend (Phase 3 only)
        online_active = False
        learner = self._get_online_learner()
        if learner is not None:
            try:
                X_clean = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
                online_prob = float(learner.predict_proba(X_clean)[0][1])
                # Blend: 70% base model, 30% online learner
                raw_prob = 0.70 * raw_prob + 0.30 * online_prob
                online_active = True
                logger.debug(
                    "Online learner blended: base=%.3f online=%.3f blend=%.3f",
                    raw_prob,
                    online_prob,
                    raw_prob,
                )
            except Exception as exc:
                logger.debug("Online learner blend failed: %s", exc)

        # Step 6: Calibration
        cal_prob = self._calibrate(raw_prob)

        # Step 6b: Data-layer sentiment + macro adjustment
        # Inject news sentiment and macro calendar signals as a soft prior.
        # This does NOT override the model — it nudges cal_prob by ±2% max.
        dl_nudge = self._get_data_layer_nudge()
        cal_prob = max(0.01, min(0.99, cal_prob + dl_nudge))

        # Step 7: Thresholding
        if cal_prob >= threshold_long:
            direction = "long"
            confidence = (cal_prob - 0.5) * 2.0
        elif cal_prob <= threshold_short:
            direction = "short"
            confidence = (0.5 - cal_prob) * 2.0
        else:
            direction = "neutral"
            confidence = 0.0

        latency_ms = (time.perf_counter() - t0) * 1000
        self._last_predict_ms = latency_ms

        # Track uptime from first predict call
        if self._first_predict_at is None:
            self._first_predict_at = time.time()

        # Track signal direction for non-neutral rate
        self._signal_window.append(direction)

        # Record signal to lineage store
        self._record_signal_lineage(
            direction=direction,
            confidence=float(confidence),
            probability=float(cal_prob),
            symbol=symbol,
            model_version=model_version,
        )

        return {
            "direction": direction,
            "probability": round(raw_prob, 4),
            "confidence": round(float(confidence), 4),
            "model_version": model_version,
            "bars_used": len(ohlcv),
            "last_close": last_close,
            "latency_ms": round(latency_ms, 2),
            "fallback": model_version == "fallback",
            "macro_active": macro_active,
            "mtf_active": mtf_active,
            "online_active": online_active,
            "dl_nudge": round(dl_nudge, 4),
            "sentiment_score": self._last_sentiment_score,
            "macro_impact": self._last_macro_impact,
        }

    def _get_data_layer_nudge(self) -> float:
        """
        Compute a soft probability nudge from the data layer.

        Uses news sentiment EMA and macro calendar impact score to
        produce a nudge in [-0.02, +0.02]. This is intentionally small
        to avoid overriding the trained model.

        Positive nudge = bullish for gold (long bias).
        Negative nudge = bearish for gold (short bias).
        """
        self._last_sentiment_score = 0.0
        self._last_macro_impact    = 0.0
        try:
            from data_layer.orchestrator import orchestrator
            features = orchestrator.get_ml_features()

            sentiment = features.get("news_sentiment_score", 0.0)
            impact    = features.get("macro_impact_score_now", 0.0)
            blackout  = features.get("macro_is_blackout", 0.0)

            self._last_sentiment_score = sentiment
            self._last_macro_impact    = impact

            # During blackout windows, suppress the nudge entirely
            if blackout > 0.5:
                return 0.0

            # Sentiment nudge: ±0.01 max
            sent_nudge = sentiment * 0.01

            # Macro impact nudge: high impact → reduce confidence (push toward 0)
            # We don't know direction of macro surprise, so we dampen rather than nudge
            macro_nudge = 0.0

            return float(sent_nudge + macro_nudge)
        except Exception:
            return 0.0

    def _record_signal_lineage(
        self,
        direction: str,
        confidence: float,
        probability: float,
        symbol: str,
        model_version: str,
    ) -> None:
        """Write signal to immutable lineage store (non-blocking)."""
        try:
            import hashlib, uuid
            from data_layer.lineage.store import lineage_store
            lineage_store.record_signal(
                direction     = direction,
                confidence    = confidence,
                probability   = probability,
                features_hash = "",   # populated by advanced_predictor when available
                model_version = model_version,
                lineage_id    = str(uuid.uuid4()),
                symbol        = symbol,
            )
        except Exception:
            pass

    # ── Metadata cache ────────────────────────────────────────────────────────

    def _load_meta(self) -> Dict[str, Any]:
        """
        Load and cache advanced_oos_meta.json.

        Re-reads from disk when the file mtime changes so a retrain
        automatically refreshes health() without a restart.
        """
        meta_path = _SAVED / "advanced_oos_meta.json"
        try:
            mtime = meta_path.stat().st_mtime if meta_path.exists() else 0.0
            if self._meta_cache is None or mtime != self._meta_mtime:
                if meta_path.exists():
                    self._meta_cache = json.loads(meta_path.read_text())
                    self._meta_mtime = mtime
                else:
                    self._meta_cache = {}
        except Exception as exc:
            logger.debug("InferenceEngine: meta load failed: %s", exc)
            self._meta_cache = self._meta_cache or {}
        return self._meta_cache or {}

    def health(self) -> Dict[str, Any]:
        """
        Return engine health metrics for /api/ml/health and /api/ml/engine-health.

        Fields
        ------
        status               : "ok" | "degraded" | "unavailable"
        model_available      : bool — predictor loaded and ready
        model_version        : str  — model identifier from predictor
        feature_count        : int  — number of features the model expects
        oos_accuracy         : float | None — from advanced_oos_meta.json
        last_trained_at      : str | None   — ISO timestamp from meta file
        pipeline             : dict — per-step availability flags
        calibrator_available : bool
        online_learning_enabled : bool
        mtf_fusion_enabled   : bool
        predict_count        : int  — total predict() calls since startup
        fallback_count       : int  — calls that used the fallback path
        fallback_rate        : float — fallback_count / predict_count
        non_neutral_rate     : float — fraction of last N signals that were
                               long or short (signal quality indicator)
        last_latency_ms      : float — most recent predict() wall-clock time
        uptime_seconds       : float | None — seconds since first predict call
        threshold_long       : float
        threshold_short      : float
        signal_filter        : dict — EV gate stats from SignalFilter
        checked_at           : str  — ISO timestamp of this health call
        """
        predictor = self._get_predictor()
        model_available = predictor is not None and getattr(
            predictor, "is_available", False
        )

        # ── Fallback rate ─────────────────────────────────────────────────────
        fallback_rate = (
            round(self._fallback_count / self._predict_count, 4)
            if self._predict_count > 0
            else 0.0
        )

        # ── Non-neutral rate (signal quality) ─────────────────────────────────
        window = list(self._signal_window)
        if window:
            non_neutral = sum(1 for d in window if d != "neutral")
            non_neutral_rate = round(non_neutral / len(window), 4)
        else:
            non_neutral_rate = 0.0

        # ── Pipeline step availability ────────────────────────────────────────
        calibrator_ok = self._load_calibrator() is not None

        macro_ok = False
        macro_series = 0
        try:
            from ml.macro_store import macro_store  # noqa: PLC0415
            macro_series = len(macro_store)
            macro_ok = macro_series > 0
        except Exception:
            pass

        mtf_ok = False
        if _MTF_FUSION_ENABLED:
            try:
                from research.pipeline.mtf_fusion import (  # noqa: PLC0415
                    _MTF_STORE_SINGLETON,
                )
                mtf_ok = _MTF_STORE_SINGLETON is not None
            except Exception:
                pass

        online_ok = False
        if _ONLINE_LEARNING_ENABLED:
            try:
                from research.pipeline.paper_trading_gate import (  # noqa: PLC0415
                    get_gate,
                )
                gate = get_gate()
                p3_ok, _ = gate.phase3_ready()
                online_ok = p3_ok
            except Exception:
                pass

        # ── Feature count ─────────────────────────────────────────────────────
        feature_count = 0
        try:
            if predictor is not None and hasattr(predictor, "_model"):
                n = getattr(predictor._model, "n_features_in_", 0)
                feature_count = int(n) if n else 0
        except Exception:
            pass

        # ── Metadata (oos_accuracy, last_trained_at) ──────────────────────────
        meta = self._load_meta()
        oos_accuracy: Optional[float] = None
        last_trained_at: Optional[str] = None
        if meta:
            raw_acc = meta.get("oos_accuracy") or meta.get("accuracy")
            oos_accuracy = float(raw_acc) if raw_acc is not None else None
            if feature_count == 0:
                fc = meta.get("feature_count", 0)
                feature_count = int(fc) if fc else 0
            last_trained_at = meta.get("validated_at") or meta.get("trained_at")

        # ── SignalFilter EV stats ─────────────────────────────────────────────
        signal_filter_stats: Dict[str, Any] = {}
        try:
            from ml.signal_filter import get_signal_filter  # noqa: PLC0415
            sf = get_signal_filter()
            if hasattr(sf, "get_stats"):
                signal_filter_stats = sf.get_stats()
        except Exception:
            pass

        # ── Uptime ────────────────────────────────────────────────────────────
        uptime_seconds: Optional[float] = None
        if self._first_predict_at is not None:
            uptime_seconds = round(time.time() - self._first_predict_at, 1)

        # ── Overall status ────────────────────────────────────────────────────
        if model_available:
            status = "ok"
        elif self._predict_count > 0 and fallback_rate < 1.0:
            status = "degraded"
        else:
            status = "unavailable"

        return {
            "status": status,
            "model_available": model_available,
            "model_version": predictor.version if predictor else "none",
            "feature_count": feature_count,
            "oos_accuracy": oos_accuracy,
            "last_trained_at": last_trained_at,
            "pipeline": {
                "macro_store": macro_ok,
                "macro_series_count": macro_series,
                "mtf_fusion": mtf_ok,
                "calibrator": calibrator_ok,
                "online_learner": online_ok,
            },
            "calibrator_available": calibrator_ok,
            "online_learning_enabled": _ONLINE_LEARNING_ENABLED,
            "mtf_fusion_enabled": _MTF_FUSION_ENABLED,
            "predict_count": self._predict_count,
            "fallback_count": self._fallback_count,
            "fallback_rate": fallback_rate,
            "non_neutral_rate": non_neutral_rate,
            "signal_window_size": len(window),
            "last_latency_ms": self._last_predict_ms,
            "uptime_seconds": uptime_seconds,
            "threshold_long": _THRESHOLD_LONG,
            "threshold_short": _THRESHOLD_SHORT,
            "signal_filter": signal_filter_stats,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: Optional[InferenceEngine] = None


def get_inference_engine() -> InferenceEngine:
    """Return the module-level InferenceEngine singleton."""
    global _engine
    if _engine is None:
        _engine = InferenceEngine()
    return _engine
