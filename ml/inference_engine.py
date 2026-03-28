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

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

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
        """Align MacroStore to the OHLCV index, deduplicating the result index."""
        try:
            from ml.macro_store import macro_store

            if len(macro_store) == 0:
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

        # Step 1: MacroStore
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
        }

    def health(self) -> Dict[str, Any]:
        """Return engine health metrics for the status endpoint."""
        predictor = self._get_predictor()
        return {
            "model_available": predictor is not None and predictor.is_available,
            "model_version": predictor.version if predictor else "none",
            "calibrator_available": self._load_calibrator() is not None,
            "online_learning_enabled": _ONLINE_LEARNING_ENABLED,
            "mtf_fusion_enabled": _MTF_FUSION_ENABLED,
            "predict_count": self._predict_count,
            "fallback_count": self._fallback_count,
            "last_latency_ms": self._last_predict_ms,
            "threshold_long": _THRESHOLD_LONG,
            "threshold_short": _THRESHOLD_SHORT,
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: Optional[InferenceEngine] = None


def get_inference_engine() -> InferenceEngine:
    """Return the module-level InferenceEngine singleton."""
    global _engine
    if _engine is None:
        _engine = InferenceEngine()
    return _engine
