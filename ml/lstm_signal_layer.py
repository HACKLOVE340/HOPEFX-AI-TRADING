# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
ml/lstm_signal_layer.py
=======================
Optional LSTM signal layer that wraps research/pipeline/models_deep.py
(DeepPredictor, architecture='lstm') into the same predict() interface
as ml/advanced_predictor.py (AdvancedPredictor).

Purpose
-------
The XGBoost model (advanced_oos.pkl) is the primary signal source.
This LSTM layer is an *optional* secondary signal that can be blended
with the XGBoost probability when:
  1. A trained LSTM model exists at LSTM_MODEL_PATH
  2. The feature flag LSTM_SIGNAL_ENABLED=true is set
  3. Enough OHLCV bars are available (>= seq_len + min_bars)

Blending is controlled by LSTM_SIGNAL_WEIGHT (default 0.0 = disabled).
When weight=0.3, the final probability is:
  prob = 0.7 * xgb_prob + 0.3 * lstm_prob

Interface
---------
LSTMSignalLayer.predict(ohlcv, macro_df, symbol) → dict

Return dict matches AdvancedPredictor.predict() exactly:
  direction       : "long" | "short" | "neutral"
  probability     : float 0–1
  confidence      : float 0–1
  high_confidence : bool
  abstain         : bool
  model_version   : str
  bars_used       : int
  last_close      : float
  feature_count   : int
  latency_ms      : float

Training
--------
Train the LSTM using research/pipeline/models_deep.py:

    from research.pipeline.models_deep import DeepPredictor, make_sequences
    from ml.advanced_features import build_advanced_features

    X, y = build_advanced_features(ohlcv_df, horizon=1)
    X_seq, y_seq = make_sequences(X.values, y.values, seq_len=60)
    X_train, X_val = X_seq[:split], X_seq[split:]
    y_train, y_val = y_seq[:split], y_seq[split:]

    predictor = DeepPredictor(architecture='lstm', n_features=X.shape[1], seq_len=60)
    predictor.fit(X_train, y_train, X_val, y_val)
    predictor.save('ml/saved_models/lstm_signal.pt')

Then set LSTM_SIGNAL_ENABLED=true and LSTM_SIGNAL_WEIGHT=0.3 in .env.

Environment variables
---------------------
  LSTM_MODEL_PATH       path to saved DeepPredictor checkpoint
                        (default: ml/saved_models/lstm_signal.pt)
  LSTM_SEQ_LEN          sequence length used during training (default: 60)
  LSTM_MIN_BARS         minimum OHLCV bars required (default: 120)
  LSTM_ABSTAIN_LOW      lower dead-band boundary (default: 0.46)
  LSTM_ABSTAIN_HIGH     upper dead-band boundary (default: 0.54)
  LSTM_HIGH_CONF        high-confidence threshold (default: 0.60)
  LSTM_SIGNAL_WEIGHT    blend weight in brain (0.0 = disabled, default: 0.0)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
LSTM_MODEL_PATH: Path = Path(os.getenv("LSTM_MODEL_PATH", "ml/saved_models/lstm_signal.pt"))
LSTM_SEQ_LEN: int = int(os.getenv("LSTM_SEQ_LEN", "60"))
LSTM_MIN_BARS: int = int(os.getenv("LSTM_MIN_BARS", "120"))
LSTM_ABSTAIN_LOW: float = float(os.getenv("LSTM_ABSTAIN_LOW", "0.46"))
LSTM_ABSTAIN_HIGH: float = float(os.getenv("LSTM_ABSTAIN_HIGH", "0.54"))
LSTM_HIGH_CONF: float = float(os.getenv("LSTM_HIGH_CONF", "0.60"))
LSTM_SIGNAL_WEIGHT: float = float(os.getenv("LSTM_SIGNAL_WEIGHT", "0.0"))

# Threshold for long/short direction (mirrors AdvancedPredictor defaults)
_THRESHOLD_LONG: float = float(os.getenv("SIGNAL_ABSTAIN_HIGH", "0.54"))
_THRESHOLD_SHORT: float = float(os.getenv("SIGNAL_ABSTAIN_LOW", "0.46"))


# ─────────────────────────────────────────────────────────────────────────────
# LSTMSignalLayer
# ─────────────────────────────────────────────────────────────────────────────


class LSTMSignalLayer:
    """
    Wraps DeepPredictor (LSTM) into the AdvancedPredictor.predict() interface.

    Thread-safe: model is loaded once at first predict() call (lazy init).
    Falls back to neutral on any error — never raises to the caller.
    """

    def __init__(
        self,
        model_path: Path = LSTM_MODEL_PATH,
        seq_len: int = LSTM_SEQ_LEN,
        min_bars: int = LSTM_MIN_BARS,
    ) -> None:
        self._model_path = Path(model_path)
        self._seq_len = seq_len
        self._min_bars = max(min_bars, seq_len + 1)
        self._predictor: object | None = None  # DeepPredictor, lazy-loaded
        self._loaded: bool = False
        self._load_attempted: bool = False
        self._n_features: int = 0
        self._predict_count: int = 0
        self._abstain_count: int = 0

    # ── Model loading ─────────────────────────────────────────────────────────

    def _load(self) -> bool:
        """Attempt to load the LSTM model. Returns True if ready."""
        if self._loaded:
            return True
        if self._load_attempted:
            return False  # already failed — don't retry every bar

        self._load_attempted = True

        if not self._model_path.exists():
            logger.info(
                "LSTM model not found at %s — layer inactive. "
                "Train with research/pipeline/models_deep.py and save to this path.",
                self._model_path,
            )
            return False

        try:
            from research.pipeline.models_deep import DeepPredictor

            self._predictor = DeepPredictor.load(str(self._model_path))
            self._n_features = self._predictor.n_features
            self._loaded = True
            logger.info(
                "LSTMSignalLayer loaded ← %s  (seq_len=%d n_features=%d)",
                self._model_path,
                self._seq_len,
                self._n_features,
            )
            return True
        except Exception as exc:
            logger.warning("LSTMSignalLayer load failed: %s", exc)
            return False

    # ── Feature building ──────────────────────────────────────────────────────

    def _build_sequence(
        self,
        ohlcv,
        macro_df=None,
        symbol: str = "XAUUSD",
    ):
        """
        Build a (1, seq_len, n_features) numpy array from the OHLCV window.

        Uses the same build_advanced_features() pipeline as AdvancedPredictor
        so the feature space is identical. Takes the last seq_len rows.

        Returns None on any failure.
        """
        try:
            from ml.advanced_features import build_advanced_features

            X, _ = build_advanced_features(
                ohlcv,
                macro_df=macro_df,
                horizon=1,
                use_filtered_target=False,
                min_move_atr=0.0,
            )
            if X is None or X.empty or len(X) < self._seq_len:
                return None

            # Take the last seq_len rows
            X_window = X.iloc[-self._seq_len :].values.astype(np.float32)

            # Replace inf/nan with 0
            X_window = np.where(np.isfinite(X_window), X_window, 0.0)

            # Shape: (1, seq_len, n_features)
            return X_window[np.newaxis, :, :]

        except Exception as exc:
            logger.warning("LSTMSignalLayer feature build failed for %s: %s", symbol, exc)
            return None

    # ── Neutral response ──────────────────────────────────────────────────────

    def _neutral(self, ohlcv, reason: str, t0: float) -> dict[str, Any]:
        self._abstain_count += 1
        last_close = 0.0
        try:
            last_close = float(ohlcv.iloc[-1].get("close", ohlcv.iloc[-1].iloc[-1]))
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        return {
            "direction": "neutral",
            "probability": 0.5,
            "confidence": 0.0,
            "high_confidence": False,
            "abstain": True,
            "model_version": "lstm_signal_layer:unavailable",
            "bars_used": len(ohlcv) if ohlcv is not None else 0,
            "last_close": last_close,
            "feature_count": self._n_features,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "reason": reason,
        }

    # ── Main predict ──────────────────────────────────────────────────────────

    def predict(
        self,
        ohlcv,
        macro_df=None,
        symbol: str = "XAUUSD",
        **_kwargs,
    ) -> dict[str, Any]:
        """
        Run LSTM inference on the OHLCV window.

        Parameters
        ----------
        ohlcv    : H1 OHLCV DataFrame (at least LSTM_MIN_BARS rows)
        macro_df : Aligned macro features — optional, passed to feature builder
        symbol   : Instrument symbol for logging

        Returns
        -------
        dict matching AdvancedPredictor.predict() output:
          direction, probability, confidence, high_confidence, abstain,
          model_version, bars_used, last_close, feature_count, latency_ms
        """
        t0 = time.perf_counter()
        self._predict_count += 1

        # ── Model availability ────────────────────────────────────────────────
        if not self._load():
            return self._neutral(ohlcv, reason="model_unavailable", t0=t0)

        # ── Sufficient bars ───────────────────────────────────────────────────
        if ohlcv is None or len(ohlcv) < self._min_bars:
            return self._neutral(
                ohlcv,
                reason=f"insufficient_bars_{len(ohlcv) if ohlcv is not None else 0}_need_{self._min_bars}",
                t0=t0,
            )

        # ── Build sequence ────────────────────────────────────────────────────
        X_seq = self._build_sequence(ohlcv, macro_df=macro_df, symbol=symbol)
        if X_seq is None:
            return self._neutral(ohlcv, reason="sequence_build_failed", t0=t0)

        # ── Flat-market abstain ───────────────────────────────────────────────
        if X_seq.std() < 1e-6:
            return self._neutral(ohlcv, reason="flat_market_low_variance", t0=t0)

        # ── LSTM inference ────────────────────────────────────────────────────
        try:
            proba_arr = self._predictor.predict(X_seq)
            prob = float(np.clip(proba_arr[0], 0.0, 1.0))
        except Exception as exc:
            logger.warning("LSTMSignalLayer inference failed for %s: %s", symbol, exc)
            return self._neutral(ohlcv, reason="inference_failed", t0=t0)

        # ── Confidence & abstain ──────────────────────────────────────────────
        confidence = abs(prob - 0.5) * 2.0
        high_confidence = confidence >= LSTM_HIGH_CONF
        abstain = LSTM_ABSTAIN_LOW <= prob <= LSTM_ABSTAIN_HIGH

        if abstain:
            self._abstain_count += 1
            direction = "neutral"
        elif prob >= _THRESHOLD_LONG:
            direction = "long"
        elif prob <= _THRESHOLD_SHORT:
            direction = "short"
        else:
            direction = "neutral"
            abstain = True
            self._abstain_count += 1

        last_close = 0.0
        try:
            last_close = float(ohlcv.iloc[-1].get("close", ohlcv.iloc[-1].iloc[-1]))
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        return {
            "direction": direction,
            "probability": round(prob, 4),
            "confidence": round(confidence, 4),
            "high_confidence": high_confidence,
            "abstain": abstain,
            "model_version": f"lstm_signal_layer:{self._model_path.name}",
            "bars_used": len(ohlcv),
            "last_close": last_close,
            "feature_count": self._n_features,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return {
            "loaded": self._loaded,
            "model_path": str(self._model_path),
            "seq_len": self._seq_len,
            "min_bars": self._min_bars,
            "n_features": self._n_features,
            "predict_count": self._predict_count,
            "abstain_count": self._abstain_count,
            "abstain_rate": (round(self._abstain_count / self._predict_count, 3) if self._predict_count > 0 else 0.0),
            "signal_weight": LSTM_SIGNAL_WEIGHT,
        }

    def is_available(self) -> bool:
        """True if the model is loaded and ready for inference."""
        return self._loaded


# ── Module-level singleton ────────────────────────────────────────────────────

_lstm_layer: LSTMSignalLayer | None = None


def get_lstm_signal_layer(
    model_path: Path | None = None,
    seq_len: int = LSTM_SEQ_LEN,
    min_bars: int = LSTM_MIN_BARS,
) -> LSTMSignalLayer:
    """
    Return the module-level LSTMSignalLayer singleton.

    The layer is created on first call and reused thereafter.
    Pass model_path only on the first call to override the default path.
    """
    global _lstm_layer
    if _lstm_layer is None:
        _lstm_layer = LSTMSignalLayer(
            model_path=model_path or LSTM_MODEL_PATH,
            seq_len=seq_len,
            min_bars=min_bars,
        )
    return _lstm_layer
