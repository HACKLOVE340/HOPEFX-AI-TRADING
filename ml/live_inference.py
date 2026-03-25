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
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_SAVED = Path(__file__).parent / "saved_models"
_MIN_BARS = 100  # minimum bars for reliable feature computation


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
        model_path: Optional[Path] = None,
        min_bars: int = _MIN_BARS,
    ) -> None:
        self.model_path = model_path or (_SAVED / "advanced_oos.pkl")
        self.min_bars = min_bars
        self._model: Optional[Any] = None
        self._feature_names: Optional[list] = None
        self._version = "advanced_oos_v1"

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
        macro_df: Optional[pd.DataFrame] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Build the advanced feature matrix from a rolling OHLCV window.

        Returns the last row as a single-row DataFrame, or None if
        feature building fails.
        """
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
            return X.iloc[[-1]]  # last bar only
        except Exception as exc:
            logger.warning("Feature build failed: %s", exc)
            return None

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict_proba(
        self,
        ohlcv: pd.DataFrame,
        macro_df: Optional[pd.DataFrame] = None,
    ) -> float:
        """
        Return the probability that the next bar closes higher (0–1).

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

        X = self._build_features(ohlcv, macro_df=macro_df)
        if X is None or X.empty:
            return 0.5

        try:
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
        macro_df: Optional[pd.DataFrame] = None,
        threshold_long: float = 0.58,
        threshold_short: float = 0.42,
    ) -> Dict[str, Any]:
        """
        Return a signal dict for the signal engine.

        Direction is 'long' when prob >= threshold_long,
        'short' when prob <= threshold_short, else 'neutral'.

        Parameters
        ----------
        threshold_long  : Minimum probability to generate a long signal
        threshold_short : Maximum probability to generate a short signal
        """
        prob = self.predict_proba(ohlcv, macro_df=macro_df)
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
_predictor: Optional[AdvancedModelPredictor] = None


def get_advanced_predictor() -> AdvancedModelPredictor:
    """Return the module-level AdvancedModelPredictor singleton."""
    global _predictor
    if _predictor is None:
        _predictor = AdvancedModelPredictor()
    return _predictor
