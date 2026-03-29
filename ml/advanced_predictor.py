# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/advanced_predictor.py
========================
Dedicated inference class for advanced_oos.pkl.

Responsibilities
----------------
- Load advanced_oos.pkl (sklearn Pipeline: StandardScaler → CalibratedXGB)
- Apply the identical 176-feature pipeline used during training
- Return calibrated probability, confidence score, and abstain decision
- Online incremental update via SGD adapter (feature-space partial_fit)
- Thread-safe singleton access via get_predictor()

Abstain logic
-------------
The predictor abstains (returns direction="neutral") when:
  1. Probability is within the dead-band [abstain_low, abstain_high]
  2. Feature variance is too low (flat market / no data)
  3. Fewer than MIN_BARS bars are available
  4. Model is unavailable (graceful degradation)

Confidence score
----------------
  confidence = |prob - 0.5| * 2   →  0.0 (50/50) … 1.0 (certain)
  high_confidence = confidence >= HIGH_CONF_THRESHOLD (default 0.60)

Online update
-------------
After a confirmed fill closes with a known outcome (1=up, 0=down), call
  predictor.update(feature_row, label)
This updates an SGD meta-learner that blends with the base model probability.
The base model is never mutated — only the lightweight adapter is updated.

Usage
-----
    from ml.advanced_predictor import get_predictor

    pred = get_predictor()
    result = pred.predict(ohlcv_df, symbol="XAU_USD")
    # result = {
    #   "direction": "long" | "short" | "neutral",
    #   "probability": 0.72,
    #   "confidence": 0.44,
    #   "high_confidence": False,
    #   "abstain": False,
    #   "model_version": "advanced_oos_v1",
    #   "bars_used": 200,
    #   "last_close": 2341.5,
    #   "feature_count": 176,
    #   "latency_ms": 12.3,
    # }
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_SAVED = Path(__file__).parent / "saved_models"
_MODEL_FILE = _SAVED / "advanced_oos.pkl"
_META_FILE = _SAVED / "advanced_oos_meta.json"
_SCALER_FILE = _SAVED / "feature_scaler.pkl"

MIN_BARS: int = int(os.getenv("PREDICTOR_MIN_BARS", "100"))
THRESHOLD_LONG: float = float(os.getenv("SIGNAL_THRESHOLD_LONG", "0.58"))
THRESHOLD_SHORT: float = float(os.getenv("SIGNAL_THRESHOLD_SHORT", "0.42"))
# Dead-band inside which we abstain even if direction is technically set
ABSTAIN_LOW: float = float(os.getenv("SIGNAL_ABSTAIN_LOW", "0.46"))
ABSTAIN_HIGH: float = float(os.getenv("SIGNAL_ABSTAIN_HIGH", "0.54"))
HIGH_CONF_THRESHOLD: float = float(os.getenv("SIGNAL_HIGH_CONF", "0.60"))
# Online learning gate: only update adapter when enabled
ONLINE_LEARNING_ENABLED: bool = (
    os.getenv("FEATURE_ONLINE_LEARNING", "false").lower() == "true"
)
# SGD adapter blend weight (0 = base model only, 1 = adapter only)
ADAPTER_BLEND: float = float(os.getenv("PREDICTOR_ADAPTER_BLEND", "0.15"))


# ── SGD online adapter ────────────────────────────────────────────────────────


class _SGDAdapter:
    """
    Lightweight SGD logistic regression that adapts on confirmed trade outcomes.

    Trained on the same 176-feature space as the base model.
    Its probability is blended with the base model at weight ADAPTER_BLEND.
    Uses warm_start so each partial_fit call continues from the previous state.
    """

    def __init__(self, n_features: int) -> None:
        self._n = n_features
        self._clf = None
        self._n_updates: int = 0
        self._lock = threading.Lock()
        self._init_clf()

    def _init_clf(self) -> None:
        try:
            from sklearn.linear_model import SGDClassifier

            # class_weight="balanced" is incompatible with partial_fit;
            # use equal weights and rely on balanced training data instead.
            self._clf = SGDClassifier(
                loss="log_loss",
                penalty="l2",
                alpha=1e-4,
                max_iter=1,
                warm_start=True,
                random_state=42,
            )
            # Prime with two dummy samples so partial_fit knows the classes
            dummy_X = np.zeros((2, self._n))
            dummy_y = np.array([0, 1])
            self._clf.partial_fit(dummy_X, dummy_y, classes=[0, 1])
            logger.debug("SGD adapter initialised with %d features", self._n)
        except Exception as exc:
            logger.warning("SGD adapter init failed: %s", exc)
            self._clf = None

    def update(self, X: np.ndarray, y: int) -> None:
        """Incremental update on a single confirmed outcome."""
        if not ONLINE_LEARNING_ENABLED or self._clf is None:
            return
        with self._lock:
            try:
                self._clf.partial_fit(X.reshape(1, -1), [y], classes=[0, 1])
                self._n_updates += 1
                logger.debug("SGD adapter updated (n=%d)", self._n_updates)
            except Exception as exc:
                logger.warning("SGD adapter update failed: %s", exc)

    def predict_proba(self, X: np.ndarray) -> Optional[float]:
        """Return P(up) from adapter, or None if not ready."""
        if self._clf is None or self._n_updates < 10:
            return None
        with self._lock:
            try:
                proba = self._clf.predict_proba(X.reshape(1, -1))
                return float(proba[0][1])
            except Exception:
                return None

    @property
    def n_updates(self) -> int:
        return self._n_updates


# ── Main predictor ────────────────────────────────────────────────────────────


class AdvancedPredictor:
    """
    Production inference wrapper for advanced_oos.pkl.

    Thread-safe. Lazy-loads the model on first predict() call.
    Maintains an SGD adapter for online incremental updates.
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        min_bars: int = MIN_BARS,
    ) -> None:
        self._model_path = model_path or _MODEL_FILE
        self._min_bars = min_bars
        self._model: Optional[Any] = None
        self._feature_names: Optional[list] = None
        self._n_features: int = 176
        self._adapter: Optional[_SGDAdapter] = None
        self._meta: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._predict_count: int = 0
        self._abstain_count: int = 0
        self._version: str = "advanced_oos_v1"
        # Integrity state: None = unchecked, True = passed, False = failed
        self._integrity_ok: Optional[bool] = None
        self._integrity_msg: str = ""
        self._load_meta()

    # ── Integrity check ───────────────────────────────────────────────────────

    def _verify_integrity(self) -> bool:
        """
        Verify the model artifact's SHA-256 digest before loading.

        Strategy (in order):
          1. Ask ModelRegistry for the registered digest of the active version.
          2. Fall back to scanning registry.json directly if the registry
             singleton is unavailable.
          3. If no digest is recorded anywhere, emit a warning and allow load
             (fail-open so a fresh deploy without a registry still works).

        Sets ``self._integrity_ok`` and ``self._integrity_msg``.
        Returns True when the check passes or is skipped (no digest on record).
        Returns False only when a digest IS recorded and does NOT match.
        """
        if not self._model_path.exists():
            self._integrity_ok = False
            self._integrity_msg = f"Artifact missing: {self._model_path}"
            return False

        # ── Attempt registry lookup ───────────────────────────────────────────
        expected_digest: Optional[str] = None
        source = "unknown"
        try:
            from ml.model_registry import get_registry, sha256_file as _sha256

            reg = get_registry()
            # Check active version first
            active = reg.active_version()
            if active:
                artifact = Path(active["file"])
                if artifact.resolve() == self._model_path.resolve():
                    expected_digest = active.get("sha256", "")
                    source = f"registry[active={active['name']}]"
            # Fall back: scan all versions for a matching file path
            if not expected_digest:
                for entry in reg.list_versions().values():
                    if Path(entry["file"]).resolve() == self._model_path.resolve():
                        expected_digest = entry.get("sha256", "")
                        source = f"registry[{entry['name']}]"
                        break
        except Exception as exc:
            logger.debug("Integrity check: registry lookup failed (%s)", exc)

        # ── No digest on record — warn and allow ──────────────────────────────
        if not expected_digest:
            self._integrity_ok = True
            self._integrity_msg = (
                f"No SHA-256 on record for {self._model_path.name}; "
                "skipping integrity check. Register the model via ModelRegistry."
            )
            logger.warning("AdvancedPredictor: %s", self._integrity_msg)
            return True

        # ── Compute actual digest ─────────────────────────────────────────────
        try:
            from ml.model_registry import sha256_file as _sha256
            actual = _sha256(self._model_path)
        except Exception as exc:
            self._integrity_ok = False
            self._integrity_msg = f"SHA-256 computation failed: {exc}"
            logger.error("AdvancedPredictor: %s", self._integrity_msg)
            return False

        if actual != expected_digest:
            self._integrity_ok = False
            self._integrity_msg = (
                f"SHA-256 MISMATCH for {self._model_path.name} "
                f"(source={source}): "
                f"expected {expected_digest[:16]}… got {actual[:16]}…"
            )
            logger.critical(
                "AdvancedPredictor: INTEGRITY FAILURE — %s", self._integrity_msg
            )
            # Fire Sentry alert if available
            try:
                import sentry_sdk
                sentry_sdk.capture_message(
                    f"Model integrity failure: {self._integrity_msg}",
                    level="fatal",
                )
            except Exception:
                pass
            return False

        self._integrity_ok = True
        self._integrity_msg = (
            f"Integrity OK ({source}): {self._model_path.name} "
            f"sha256={actual[:16]}…"
        )
        logger.info("AdvancedPredictor: %s", self._integrity_msg)
        return True

    # ── Meta ──────────────────────────────────────────────────────────────────

    def _load_meta(self) -> None:
        try:
            if _META_FILE.exists():
                with open(_META_FILE) as f:
                    self._meta = json.load(f)
                logger.debug(
                    "Model meta loaded: OOS accuracy=%.4f, AUC=%.4f",
                    self._meta.get("oos_accuracy", 0),
                    self._meta.get("oos_auc", 0),
                )
        except Exception as exc:
            logger.debug("Meta load failed (non-fatal): %s", exc)

    # ── Model loading ─────────────────────────────────────────────────────────

    def _load(self) -> bool:
        """
        Lazy-load model. Returns True on success.

        Runs a SHA-256 integrity check before deserialising the artifact.
        A recorded digest mismatch is treated as a hard failure — the model
        is not loaded and predict() returns neutral for every call.
        """
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True

            # ── Pre-load integrity check ──────────────────────────────────────
            if not self._verify_integrity():
                logger.error(
                    "AdvancedPredictor: refusing to load — integrity check failed: %s",
                    self._integrity_msg,
                )
                return False

            try:
                import joblib

                payload = joblib.load(self._model_path)
                self._model = payload
                # Extract feature names from the pipeline
                if hasattr(payload, "feature_names_in_"):
                    self._feature_names = list(payload.feature_names_in_)
                    self._n_features = len(self._feature_names)
                elif hasattr(payload, "steps"):
                    for _, step in payload.steps:
                        if hasattr(step, "feature_names_in_"):
                            self._feature_names = list(step.feature_names_in_)
                            self._n_features = len(self._feature_names)
                            break
                self._adapter = _SGDAdapter(self._n_features)
                logger.info(
                    "AdvancedPredictor loaded: %s  features=%d  OOS_acc=%.4f",
                    self._model_path.name,
                    self._n_features,
                    self._meta.get("oos_accuracy", 0),
                )
                return True
            except Exception as exc:
                logger.error("AdvancedPredictor load failed: %s", exc)
                self._model = None
                return False

    @property
    def is_available(self) -> bool:
        return self._model_path.exists()

    @property
    def version(self) -> str:
        return self._version

    @property
    def meta(self) -> Dict[str, Any]:
        return dict(self._meta)

    # ── Feature building ──────────────────────────────────────────────────────

    def _build_features(
        self,
        ohlcv: pd.DataFrame,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "XAUUSD",
    ) -> Optional[pd.DataFrame]:
        """
        Build the 176-feature matrix from a rolling OHLCV window.
        Returns the last row as a single-row DataFrame, or None on failure.
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
            if X is None or X.empty:
                return None
            return X.iloc[[-1]]
        except Exception as exc:
            logger.warning("Feature build failed for %s: %s", symbol, exc)
            return None

    def _align_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Align feature columns to the model's expected order.
        Missing columns are filled with 0 (neutral/unknown).
        Extra columns are dropped.
        """
        if self._feature_names is None:
            return X
        missing = [c for c in self._feature_names if c not in X.columns]
        if missing:
            logger.debug("Filling %d missing features with 0", len(missing))
            for col in missing:
                X[col] = 0.0
        return X[self._feature_names]

    # ── Core prediction ───────────────────────────────────────────────────────

    def predict(
        self,
        ohlcv: pd.DataFrame,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "XAUUSD",
        mtf_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Full inference pipeline. Returns a signal dict.

        Parameters
        ----------
        ohlcv    : H1 OHLCV DataFrame (at least MIN_BARS rows)
        macro_df : Aligned macro features (DXY, VIX, yields, SPX) — optional
        symbol   : Instrument symbol for logging/caching
        mtf_df   : MTF regime features (d_*/h_* columns) — optional

        Returns
        -------
        dict with keys:
          direction       : "long" | "short" | "neutral"
          probability     : float 0–1
          confidence      : float 0–1  (|prob-0.5|*2)
          high_confidence : bool
          abstain         : bool
          model_version   : str
          bars_used       : int
          last_close      : float
          feature_count   : int
          latency_ms      : float
          adapter_updates : int
        """
        t0 = time.perf_counter()
        self._predict_count += 1

        # ── Unavailable / insufficient data ──────────────────────────────────
        if not self._load():
            return self._neutral(ohlcv, reason="model_unavailable", t0=t0)

        if len(ohlcv) < self._min_bars:
            return self._neutral(
                ohlcv,
                reason=f"insufficient_bars_{len(ohlcv)}_need_{self._min_bars}",
                t0=t0,
            )

        # ── Build features ────────────────────────────────────────────────────
        X = self._build_features(ohlcv, macro_df=macro_df, symbol=symbol)
        if X is None or X.empty:
            return self._neutral(ohlcv, reason="feature_build_failed", t0=t0)

        # ── Append MTF regime features ────────────────────────────────────────
        if mtf_df is not None and not mtf_df.empty:
            try:
                mtf_last = mtf_df.reindex(X.index).ffill().fillna(0.0)
                mtf_cols = [c for c in mtf_last.columns if c not in X.columns]
                if mtf_cols:
                    X = pd.concat([X, mtf_last[mtf_cols]], axis=1)
            except Exception as exc:
                logger.debug("MTF append failed (non-fatal): %s", exc)

        # ── Align to model feature space ──────────────────────────────────────
        X = self._align_features(X)
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # ── Flat-market abstain: if feature variance is near zero ─────────────
        feat_std = float(X.values.std())
        if feat_std < 1e-6:
            self._abstain_count += 1
            return self._neutral(ohlcv, reason="flat_market_low_variance", t0=t0)

        # ── Base model probability ────────────────────────────────────────────
        try:
            proba = self._model.predict_proba(X)
            base_prob = float(
                proba[0][1] if proba.shape[1] > 1 else proba[0][0]
            )
            base_prob = float(np.clip(base_prob, 0.0, 1.0))
        except Exception as exc:
            logger.warning("Model predict_proba failed: %s", exc)
            return self._neutral(ohlcv, reason="predict_failed", t0=t0)

        # ── Blend with SGD adapter ────────────────────────────────────────────
        prob = base_prob
        if self._adapter is not None and ONLINE_LEARNING_ENABLED:
            adapter_prob = self._adapter.predict_proba(X.values[0])
            if adapter_prob is not None:
                prob = (1.0 - ADAPTER_BLEND) * base_prob + ADAPTER_BLEND * adapter_prob

        # ── Confidence & abstain ──────────────────────────────────────────────
        confidence = abs(prob - 0.5) * 2.0  # 0.0 → 1.0
        high_confidence = confidence >= HIGH_CONF_THRESHOLD

        # Dead-band abstain: too close to 50/50
        abstain = ABSTAIN_LOW <= prob <= ABSTAIN_HIGH
        if abstain:
            self._abstain_count += 1

        # ── Direction ─────────────────────────────────────────────────────────
        if abstain or (ABSTAIN_LOW < prob < ABSTAIN_HIGH):
            direction = "neutral"
        elif prob >= THRESHOLD_LONG:
            direction = "long"
        elif prob <= THRESHOLD_SHORT:
            direction = "short"
        else:
            direction = "neutral"
            abstain = True
            self._abstain_count += 1

        last_close = float(ohlcv.iloc[-1].get("close", ohlcv.iloc[-1].iloc[-1]))
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "direction": direction,
            "probability": round(prob, 4),
            "base_probability": round(base_prob, 4),
            "confidence": round(confidence, 4),
            "high_confidence": high_confidence,
            "abstain": abstain,
            "model_version": self._version,
            "bars_used": len(ohlcv),
            "last_close": last_close,
            "feature_count": X.shape[1],
            "latency_ms": round(latency_ms, 2),
            "adapter_updates": self._adapter.n_updates if self._adapter else 0,
            "oos_accuracy": self._meta.get("oos_accuracy"),
            "oos_auc": self._meta.get("oos_auc"),
        }

    def _neutral(
        self,
        ohlcv: pd.DataFrame,
        reason: str = "unknown",
        t0: float = 0.0,
    ) -> Dict[str, Any]:
        last_close = 0.0
        try:
            last_close = float(ohlcv.iloc[-1].get("close", ohlcv.iloc[-1].iloc[-1]))
        except Exception:
            pass
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "direction": "neutral",
            "probability": 0.5,
            "base_probability": 0.5,
            "confidence": 0.0,
            "high_confidence": False,
            "abstain": True,
            "abstain_reason": reason,
            "model_version": self._version,
            "bars_used": len(ohlcv) if ohlcv is not None else 0,
            "last_close": last_close,
            "feature_count": 0,
            "latency_ms": round(latency_ms, 2),
            "adapter_updates": self._adapter.n_updates if self._adapter else 0,
        }

    # ── Online update ─────────────────────────────────────────────────────────

    def update(
        self,
        ohlcv: pd.DataFrame,
        label: int,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "XAUUSD",
    ) -> bool:
        """
        Incremental update on a confirmed trade outcome.

        Parameters
        ----------
        ohlcv  : The OHLCV window that was used for the original prediction
        label  : 1 if the trade was profitable (price went up), 0 otherwise
        macro_df : Macro features at prediction time (optional)
        symbol : Instrument symbol

        Returns True if the adapter was updated successfully.
        """
        if not ONLINE_LEARNING_ENABLED:
            return False
        if not self._load():
            return False
        if len(ohlcv) < self._min_bars:
            return False

        X = self._build_features(ohlcv, macro_df=macro_df, symbol=symbol)
        if X is None or X.empty:
            return False

        X = self._align_features(X)
        X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        if self._adapter is not None:
            self._adapter.update(X.values[0], int(label))
            return True
        return False

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "predict_count": self._predict_count,
            "abstain_count": self._abstain_count,
            "abstain_rate": (
                self._abstain_count / self._predict_count
                if self._predict_count > 0
                else 0.0
            ),
            "adapter_updates": self._adapter.n_updates if self._adapter else 0,
            "online_learning_enabled": ONLINE_LEARNING_ENABLED,
            "model_loaded": self._model is not None,
            "model_path": str(self._model_path),
            "n_features": self._n_features,
            "oos_accuracy": self._meta.get("oos_accuracy"),
            "oos_auc": self._meta.get("oos_auc"),
            "sharpe_gate": self._meta.get("sharpe_gate", {}),
            # Integrity check result (None = not yet checked)
            "integrity_ok": self._integrity_ok,
            "integrity_msg": self._integrity_msg,
        }


# ── Module-level singleton ────────────────────────────────────────────────────
_predictor: Optional[AdvancedPredictor] = None
_predictor_lock = threading.Lock()


def get_predictor() -> AdvancedPredictor:
    """Return the module-level AdvancedPredictor singleton (thread-safe)."""
    global _predictor
    if _predictor is None:
        with _predictor_lock:
            if _predictor is None:
                _predictor = AdvancedPredictor()
    return _predictor
