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

import contextlib
import hashlib
import json
import math
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from ml.model_paths import model_dir as _model_dir
from ml.model_paths import packaged_model_dir as _packaged_model_dir

# This used to be the packaged path computed from __file__, which ignored
# ML_MODEL_DIR — so retrained artifacts were never the ones served.
_SAVED = _model_dir()


# The directory the environment named at import, so a deliberate reassignment
# of _SAVED can be told apart from the configured default.
_ENV_RESOLVED = _model_dir()
_PACKAGED = _packaged_model_dir()


def _saved(name: str) -> Path:
    """Resolve artifact *name* under `_SAVED`, falling back to the packaged copy.

    `_SAVED` is a seam callers reassign to isolate a directory; the fallback
    applies only while it is still the environment-configured value. See the
    fuller note on `ml.__init__._saved`.
    """
    candidate = _SAVED / name
    if candidate.exists():
        return candidate

    if _SAVED == _ENV_RESOLVED and _SAVED != _PACKAGED:
        fallback = _PACKAGED / name
        if fallback.exists():
            logger.warning(
                "%r is not in the configured model directory %s; using the packaged copy.",
                name,
                _SAVED,
            )
            return fallback

    return candidate


_MIN_BARS = 100
_THRESHOLD_LONG = float(os.getenv("SIGNAL_THRESHOLD_LONG", "0.58"))
_THRESHOLD_SHORT = float(os.getenv("SIGNAL_THRESHOLD_SHORT", "0.42"))
_ONLINE_LEARNING_ENABLED = os.getenv("FEATURE_ONLINE_LEARNING", "false").lower() == "true"
_MTF_FUSION_ENABLED = os.getenv("FEATURE_MTF_FUSION", "true").lower() == "true"

# Rolling window size for non-neutral rate tracking
_SIGNAL_WINDOW = int(os.getenv("SIGNAL_QUALITY_WINDOW", "100"))

# ── Stale model detection ─────────────────────────────────────────────────────
# Block inference when the model file is older than MODEL_MAX_AGE_DAYS.
# Default: 30 days.  Set to 0 to disable the check.
_MODEL_MAX_AGE_DAYS = float(os.getenv("MODEL_MAX_AGE_DAYS", "30"))

# STALE_MODEL_BLOCK controls what happens when the model is stale:
#   true  (default in production) — raise RuntimeError, block all inference.
#         The pre-trade gate catches this and blocks the trade.
#   false — degrade to neutral signal (warn-only, legacy behaviour).
#
# In production a stale model is a known-bad state: the operator must retrain
# or explicitly set STALE_MODEL_BLOCK=false to acknowledge the risk.
_STALE_MODEL_BLOCK: bool = os.getenv("STALE_MODEL_BLOCK", "true").lower() == "true"

# ── Feature drift guard ───────────────────────────────────────────────────────
# Warn (and optionally block) when live feature means deviate from training
# means by more than DRIFT_Z_THRESHOLD standard deviations.
# Default: 4.0 (warn only).  Set DRIFT_BLOCK=true to block on drift.
_DRIFT_Z_THRESHOLD = float(os.getenv("DRIFT_Z_THRESHOLD", "4.0"))
_DRIFT_BLOCK = os.getenv("DRIFT_BLOCK", "false").lower() == "true"

# ── Model quality gate ────────────────────────────────────────────────────────
# `ml/model_quality_gate.py` is consulted on every predict(). It was built
# fail-closed, tested, and called by nothing — while predict() made the same
# three judgements inline, as strings in the evidence blob, against a bare
# 0.3 literal. These are that literal and its siblings, named once so the
# boundary has a single definition rather than one per read site.
#
# The floor below is the value predict() already used to call data quality
# "valid" rather than "degraded"; the drift ceiling is _DRIFT_Z_THRESHOLD, the
# constant the drift guard already enforces. Neither is a new number.
_MIN_DATA_QUALITY = float(os.getenv("MIN_DATA_QUALITY", "0.3"))
# 1.0 requires a fitted isotonic calibrator; 0.0 tolerates a raw probability,
# which is the current deployment's actual state — isotonic_calibrator.pkl is
# absent, so every prediction today is served uncalibrated. Defaulting to 0.0
# keeps that tolerated and *recorded* rather than silently unnoticed.
_MIN_CALIBRATION = float(os.getenv("MIN_CALIBRATION", "0.0"))
# Advisory by default, exactly like _DRIFT_BLOCK. Wiring a gate in must not
# silently change when this system declines to trade; that is the owner's
# decision, and it is tracked with the DRIFT_BLOCK default.
_MODEL_QUALITY_BLOCK = os.getenv("MODEL_QUALITY_BLOCK", "false").lower() == "true"
# Rolling window of recent feature vectors for drift detection
_DRIFT_WINDOW = int(os.getenv("DRIFT_WINDOW", "50"))
# Fraction of the live feature vector that must be present in the training
# stats before the guard counts as running. `_check_feature_drift` skips any
# live feature it has no training stats for; if that skips most of them, the
# guard produces a clean result from measuring almost nothing while still
# reporting itself active — the S4-05 mistake one level down. Coverage below
# this floor is treated as "guard off", not "no drift".
_DRIFT_MIN_COVERAGE = float(os.getenv("DRIFT_MIN_COVERAGE", "0.5"))

# ── Prometheus metrics (optional — degrades gracefully if not installed) ──────


def _prefix_counts(names: list[str]) -> dict[str, int]:
    """Group feature names by their leading token, most common first.

    Feature names in this codebase are prefixed by origin (``dl_`` for
    data-layer injections, ``cot_`` for positioning, ``im_`` for intermarket…),
    so the prefix is what tells an operator whether a coverage gap is one block
    of features from a single source or scattered noise.
    """
    from collections import Counter

    counts = Counter(name.split("_")[0] for name in names)
    return dict(counts.most_common())


def _init_prometheus():
    """
    Initialise Prometheus counters/gauges/histograms with dedup guard.

    Returns a metrics namespace, or a no-op stub when prometheus_client
    is not installed or metrics are already registered (hot-reload safe).
    """

    class _Noop:
        class _C:
            def labels(self, **_kw):
                return self

            def inc(self, *a, **kw):
                pass

            def observe(self, *a, **kw):
                pass

            def set(self, *a, **kw):
                pass

        def __getattr__(self, _name):
            return self._C()

    try:
        from prometheus_client import REGISTRY, Counter, Gauge, Histogram

        def _counter(name, doc, labels=None):
            try:
                return Counter(name, doc, labels or [])
            except ValueError:
                return REGISTRY._names_to_collectors.get(name)

        def _histogram(name, doc, labels=None, buckets=None):
            kw = {"labelnames": labels or []}
            if buckets:
                kw["buckets"] = buckets
            try:
                return Histogram(name, doc, **kw)
            except ValueError:
                return REGISTRY._names_to_collectors.get(name)

        def _gauge(name, doc, labels=None):
            try:
                return Gauge(name, doc, labels or [])
            except ValueError:
                return REGISTRY._names_to_collectors.get(name)

        class _Metrics:
            predict_total = _counter(
                "hopefx_inference_predict_total",
                "Total inference predictions",
                ["symbol", "direction"],
            )
            predict_latency = _histogram(
                "hopefx_inference_predict_latency_seconds",
                "Inference prediction latency in seconds",
                ["symbol"],
                buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
            )
            fallback_total = _counter(
                "hopefx_inference_fallback_total",
                "Fallback (non-model) predictions",
                ["symbol", "reason"],
            )
            confidence_gauge = _gauge(
                "hopefx_inference_last_confidence",
                "Last prediction confidence score",
                ["symbol"],
            )
            data_quality_gauge = _gauge(
                "hopefx_inference_data_quality",
                "Last orchestrator data quality score",
                ["symbol"],
            )
            model_version_info = _gauge(
                "hopefx_inference_model_version_info",
                "Active model version (label only)",
                ["model_id"],
            )
            rollback_total = _counter(
                "hopefx_inference_rollback_total",
                "Model rollback count",
                ["reason"],
            )

        return _Metrics()

    except ImportError:
        logger.debug(
            "prometheus_client not installed — inference metrics disabled. Install with: pip install prometheus-client"
        )
        return _Noop()
    except Exception as exc:
        logger.debug("Prometheus init error (inference_engine): %s", exc)
        return _Noop()


_PROM = _init_prometheus()


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
        # Whether feature-drift detection has usable training stats.
        # False means the guard is DISABLED, which _check_feature_drift
        # otherwise reports indistinguishably from 'no drift' (S4-05).
        self._drift_stats_available: bool = False
        self._drift_stats_warned: bool = False
        # How much of the live feature vector the training stats actually cover.
        # A stats file whose feature names do not match what the model produces
        # leaves the guard measuring nothing while looking healthy, so coverage
        # is part of "active" rather than a separate diagnostic.
        self._drift_covered: int = 0
        self._drift_total: int = 0
        self._drift_reason: str = "no_training_stats"
        self._drift_coverage_warned: bool = False
        # Names of the live features with no training stats, so an operator can
        # see *which* are unwatched rather than only how many.
        self._drift_uncovered: list[str] = []
        self._drift_uncovered_logged: bool = False
        # Uptime tracking — set on first predict call
        self._first_predict_at: float | None = None
        # Rolling window of signal directions for non-neutral rate
        self._signal_window: deque[str] = deque(maxlen=_SIGNAL_WINDOW)
        # Cached model metadata from advanced_oos_meta.json
        self._meta_cache: dict[str, Any] | None = None
        self._meta_mtime: float = 0.0
        # Data layer nudge tracking
        self._last_sentiment_score: float = 0.0
        self._last_macro_impact: float = 0.0
        # Rollback support — stores path to previous model for emergency revert
        self._active_model_path: Path | None = None
        self._previous_model_path: Path | None = None
        self._rollback_count: int = 0

        # ── Stale model detection ──────────────────────────────────────────
        # Cached result of the last staleness check (re-evaluated each call).
        self._model_stale: bool = False
        self._model_age_days: float | None = None

        # ── Live accuracy monitoring (rolling 50-prediction window) ────────
        # Tracks (predicted_direction, actual_outcome) pairs; compared against
        # training OOS accuracy to detect silent model degradation.
        self._live_pred_window: deque[tuple[int, int]] = deque(maxlen=50)
        self._live_accuracy_alert_sent: bool = False

        # ── Feature drift guard ────────────────────────────────────────────
        # Rolling buffer of recent feature vectors (last _DRIFT_WINDOW rows).
        # Used to compute live feature means for KS-test drift detection.
        self._drift_buffer: deque[np.ndarray] = deque(maxlen=_DRIFT_WINDOW)
        # Warn once if drift has to fall back to the engine's own vector (S4-01).
        self._drift_scope_warned: bool = False
        # Training feature stats loaded from saved_models/feature_stats.json
        # Format: {feature_name: {"mean": float, "std": float}}
        self._train_stats: dict[str, dict] | None = None
        self._drift_detected: bool = False
        self._drift_z_max: float = 0.0  # max z-score across features (last check)

    # ── Lazy loaders ──────────────────────────────────────────────────────────

    def _get_predictor(self):
        if self._predictor is None:
            try:
                from ml.live_inference import get_advanced_predictor

                self._predictor = get_advanced_predictor()
            except Exception as exc:
                logger.debug("InferenceEngine: predictor unavailable: %s", exc)
        return self._predictor

    def _get_macro_df(self, ohlcv: pd.DataFrame) -> pd.DataFrame | None:
        """Align MacroStore to the OHLCV index, deduplicating the result index.

        MacroStore is now auto-populated by data_layer.feeds.macro.store_bridge
        (MacroStoreBridge) which loads FRED series on startup and refreshes daily.
        load_defaults() is kept as a CSV fallback for offline environments.
        """
        try:
            from ml.macro_store import macro_store

            if len(macro_store) == 0:
                # Check bridge via orchestrator (single entry point — never import
                # data_layer sub-modules directly from outside data_layer/).
                try:
                    from data_layer.orchestrator import orchestrator

                    if not orchestrator._macro_bridge.is_loaded:
                        logger.debug("MacroStoreBridge not yet loaded — using CSV defaults")
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
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

    def _get_mtf_df(self, ohlcv: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
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
        """
        Return the SklearnOnlineLearner singleton if online learning is enabled.

        Phase gate: when FEATURE_ONLINE_LEARNING=true the learner is always
        returned (no paper-trading gate required — the gate is enforced by the
        caller deciding whether to call update_online()).

        Falls back gracefully to None when ml.online_learner is unavailable.
        """
        if not _ONLINE_LEARNING_ENABLED:
            return None
        if self._online_learner is not None:
            return self._online_learner
        try:
            from ml.online_learner import get_online_learner

            self._online_learner = get_online_learner()
            return self._online_learner
        except Exception as exc:
            logger.debug("Online learner unavailable: %s", exc)
            return None

    def _load_calibrator(self):
        """Load isotonic calibrator from saved_models if available."""
        if self._calibrator is not None:
            return self._calibrator
        cal_path = _saved("isotonic_calibrator.pkl")
        if not cal_path.exists():
            return None
        try:
            import joblib

            self._calibrator = joblib.load(cal_path)  # nosec B301 - cal_path derived from saved_models
            logger.debug("InferenceEngine: isotonic calibrator loaded")
            return self._calibrator
        except Exception as exc:
            logger.debug("Calibrator load failed: %s", exc)
            return None

    #: Where training writes the measured calibration of the deployed model.
    CALIBRATION_REPORT_FILE = "calibration_report.json"

    def _recorded_calibration_score(self) -> float | None:
        """The calibration score training measured, or ``None`` if it did not.

        `ml/calibration_metrics.py` computes 1 - ECE on held-out predictions and
        training writes it to ``saved_models/calibration_report.json``. This
        reads it back.

        ``None`` means nobody measured — which is NOT a pass. This used to be
        ``1.0 if self._calibrator is not None else 0.0``, i.e. whether a pickle
        had loaded: a badly-fitted calibrator scored a perfect 1.0 and cleared
        any threshold, and a well-calibrated raw model scored 0.0 and failed
        every threshold above zero. `ModelQualityGate.evaluate` already fails
        closed on a missing score, so absence stays absent.

        A report flagged `single_class` is treated as absent too: Brier is
        computable on one-class held-out data, but it says nothing about
        whether a 70% forecast happens 70% of the time.
        """
        path = _saved(self.CALIBRATION_REPORT_FILE)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # ERROR, not debug: this is a safety-gate input failing to load, and
            # the caller cannot tell a broken file from an unmeasured model
            # unless someone says so.
            logger.error("InferenceEngine: calibration report unreadable at %s: %s", path, exc)
            return None

        if payload.get("single_class"):
            logger.warning("InferenceEngine: calibration report is single-class — treating as unmeasured")
            return None

        score = payload.get("calibration_score")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            logger.error("InferenceEngine: calibration_score missing or non-finite in %s", path)
            return None
        return float(score)

    # ── Feature building ──────────────────────────────────────────────────────

    def _build_features(
        self,
        ohlcv: pd.DataFrame,
        macro_df: pd.DataFrame | None,
        mtf_df: pd.DataFrame | None,
        symbol: str,
    ) -> pd.DataFrame | None:
        """
        Build 200+ feature matrix with real-time data layer injection.

        Uses build_extended_features_with_data_layer() which injects
        microstructure, sentiment, and macro calendar features from the
        orchestrator at the last bar's timestamp (causal, no look-ahead).

        Falls back to build_extended_features() if the data layer is
        unavailable (e.g. during backtesting without a live orchestrator).

        Validation gates applied after building:
          1. Empty / None result → return None with WARNING.
          2. NaN/Inf in any feature → impute with 0 and log WARNING.
          3. Feature count mismatch vs expected → log WARNING.
        """
        try:
            # Deduplicate OHLCV index before feature building — duplicate
            # timestamps cause reindex failures inside advanced_features.py
            if ohlcv.index.duplicated().any():
                ohlcv = ohlcv[~ohlcv.index.duplicated(keep="last")]

            # Prefer the data-layer-aware builder (live inference path)
            try:
                from ml.features_extended import build_extended_features_with_data_layer

                X, _ = build_extended_features_with_data_layer(
                    ohlcv=ohlcv,
                    macro_df=macro_df,
                    horizon=1,
                    use_filtered_target=False,
                    min_move_atr=0.0,
                )
                logger.debug(
                    "InferenceEngine: built %d features via data_layer path for %s",
                    len(X.columns) if X is not None and not X.empty else 0,
                    symbol,
                )
            except Exception as dl_exc:
                # WARNING, not debug: this switches to a REDUCED feature set
                # (no microstructure/sentiment/macro injection). If the model
                # was trained with those families, scoring without them is
                # train/serve skew — and at debug level a permanent switch was
                # invisible at production log level.
                # See docs/HARDENING_BACKLOG.md S4-06.
                logger.warning(
                    "InferenceEngine: data-layer feature builder unavailable (%s) — falling back to "
                    "build_extended_features WITHOUT microstructure/sentiment/macro features. "
                    "Predictions are being made on a reduced feature set.",
                    dl_exc,
                )
                with contextlib.suppress(Exception):
                    _PROM.fallback_total.labels(symbol=symbol, reason="reduced_feature_set").inc()
                from ml.features_extended import build_extended_features

                X, _ = build_extended_features(
                    ohlcv,
                    macro_df=macro_df,
                    horizon=1,
                    use_filtered_target=False,
                    min_move_atr=0.0,
                )

            if X is None or X.empty:
                logger.warning(
                    "InferenceEngine._build_features: feature builder returned empty/None for %s — "
                    "falling back to neutral signal",
                    symbol,
                )
                return None

            # Append MTF regime columns — shift by 1 bar to enforce causal alignment
            # (prevents the current in-progress D1/H4 bar from leaking into H1 features)
            if mtf_df is not None and not mtf_df.empty:
                try:
                    mtf_causal = mtf_df.shift(1)  # use prior completed bar only
                    mtf_aligned = mtf_causal.reindex(X.index).ffill().fillna(0.0)
                    new_cols = [c for c in mtf_aligned.columns if c not in X.columns]
                    if new_cols:
                        X = pd.concat([X, mtf_aligned[new_cols]], axis=1)
                        logger.debug("MTF: appended %d causal columns for %s", len(new_cols), symbol)
                except Exception as mtf_exc:
                    logger.debug("MTF append failed: %s", mtf_exc)

            X = X.iloc[[-1]]  # last bar only

            # ── Feature validation ────────────────────────────────────────────
            # Gate 1: NaN / Inf check — garbage features → garbage predictions.
            # Gates 1 and 2 now ABSTAIN rather than impute-and-trade.
            #
            # Imputing NaN with 0.0 is not neutral in this feature space: a
            # z-score of 0 means "exactly average", an RSI-derived feature at 0
            # means "maximally oversold". Filling a broken feed with zeros does
            # not produce an uncertain prediction — it produces a *confident*
            # one, drawn from a region the model was trained to read as a strong
            # signal. A feed outage therefore yielded high-confidence trades
            # rather than abstention. Likewise the >95%-zero check diagnosed a
            # "possible silent upstream data failure" and then returned the
            # vector for trading. See docs/HARDENING_BACKLOG.md S4-02/S4-03.
            if self._features_are_unusable(X, symbol=symbol):
                return None

            return X

        except Exception as exc:
            logger.warning(
                "InferenceEngine._build_features: failed for %s: %s — returning neutral",
                symbol,
                exc,
            )
            return None

    def _features_are_unusable(self, X: pd.DataFrame, symbol: str = "?") -> bool:
        """True when the feature vector must not be scored.

        Two conditions, both previously logged and then ignored:

        * any NaN/Inf value — see the note in ``_build_features`` on why
          imputing zero produces confident wrong predictions rather than
          uncertain ones;
        * a vector that is >95% zeros, which the code itself describes as a
          "possible silent upstream data failure".

        Returning True routes the caller to its existing neutral/abstain path.
        """
        try:
            if X is None or X.empty:
                return True

            numeric = X.select_dtypes(include=[np.number])
            if numeric.empty:
                logger.warning("InferenceEngine: no numeric features for %s — abstaining", symbol)
                return True

            nan_cols = numeric.columns[numeric.isnull().any()].tolist()
            inf_cols = numeric.columns[np.isinf(numeric).any()].tolist()
            bad_cols = sorted(set(nan_cols + inf_cols))
            if bad_cols:
                logger.warning(
                    "InferenceEngine: %d features contain NaN/Inf for %s: %s — ABSTAINING. "
                    "Zero-imputing these would produce a confident prediction from corrupt input.",
                    len(bad_cols),
                    symbol,
                    bad_cols[:10],
                )
                self._fallback_count += 1
                with contextlib.suppress(Exception):
                    _PROM.fallback_total.labels(symbol=symbol, reason="nan_features").inc()
                return True

            non_zero_pct = float((numeric != 0).values.mean())
            if non_zero_pct < 0.05:
                logger.warning(
                    "InferenceEngine: feature vector for %s is >95%% zeros (non_zero_pct=%.3f) — "
                    "ABSTAINING. Probable silent upstream data failure; check gold feed and macro pipeline.",
                    symbol,
                    non_zero_pct,
                )
                self._fallback_count += 1
                with contextlib.suppress(Exception):
                    _PROM.fallback_total.labels(symbol=symbol, reason="all_zero_features").inc()
                return True

            return False
        except Exception as exc:
            # Fail closed: if usability cannot be established, do not score.
            logger.warning("InferenceEngine: feature usability check failed for %s: %s — abstaining", symbol, exc)
            return True

    def drift_guard_active(self) -> bool:
        """Whether feature-drift detection is actually running.

        ``_check_feature_drift`` returns ``False`` ("no drift") when the
        training-stats file is absent, which is indistinguishable from a clean
        result. Exposing this lets health checks and operators see that the
        guard is disabled rather than passing. See S4-05.

        "Running" requires both halves: stats that loaded, *and* stats that
        cover enough of the live feature vector to be measuring the model. A
        file describing a stale feature schema satisfies the first and not the
        second, and would otherwise report a clean result from comparing
        nothing.
        """
        return bool(getattr(self, "_drift_stats_available", False))

    def drift_status(self) -> dict[str, Any]:
        """Why the drift guard is or is not running.

        ``drift_guard_active()`` answers yes/no; the fixes for the two "no"
        cases are different. ``no_training_stats`` means the artifact is absent
        — regenerate it by retraining. ``insufficient_coverage`` means the
        artifact is present but describes features the model no longer
        produces — the schema moved and the stats were not regenerated with it.
        """
        return {
            "active": self.drift_guard_active(),
            "reason": self._drift_reason,
            "covered": self._drift_covered,
            "total": self._drift_total,
            "min_coverage": _DRIFT_MIN_COVERAGE,
            "drift_detected": bool(getattr(self, "_drift_detected", False)),
            "z_max": float(getattr(self, "_drift_z_max", 0.0) or 0.0),
            # Which features are unwatched. "170 of 229 covered" does not tell
            # an operator whether the gap is one stale block or scattered
            # across the vector, and the two have different remedies.
            "uncovered": sorted(getattr(self, "_drift_uncovered", [])),
            "uncovered_by_prefix": _prefix_counts(getattr(self, "_drift_uncovered", [])),
        }

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

    def update_online(
        self,
        ohlcv: pd.DataFrame,
        label: int,
        predicted_direction: int | None = None,
    ) -> None:
        """
        Update the online learner with a confirmed fill outcome.

        Called by the broker callback when a paper/live trade closes.

        Parameters
        ----------
        ohlcv               : OHLCV DataFrame for the bars that produced the signal
        label               : 1 = profitable outcome, 0 = loss
        predicted_direction : The model's predicted direction (1/0) at signal time.
                              When provided, recorded in the live accuracy window.
        """
        # Record prediction vs outcome for live accuracy monitoring
        if predicted_direction is not None:
            self._live_pred_window.append((predicted_direction, label))
            self._check_live_accuracy_degradation()

        learner = self._get_online_learner()
        if learner is None:
            return
        try:
            # SklearnOnlineLearner.partial_fit() accepts raw OHLCV bars and
            # derives its own label from close[0] vs close[-1].  When we have
            # an explicit outcome label we override by constructing a synthetic
            # two-row frame where the last close is higher (label=1) or lower
            # (label=0) than the first.
            if label == 1:
                # Ensure last close > first close so the learner sees a win
                bars = ohlcv.copy()
                if "close" in bars.columns and bars["close"].iloc[-1] <= bars["close"].iloc[0]:
                    bars.loc[bars.index[-1], "close"] = bars["close"].iloc[0] * 1.001
            else:
                bars = ohlcv.copy()
                if "close" in bars.columns and bars["close"].iloc[-1] >= bars["close"].iloc[0]:
                    bars.loc[bars.index[-1], "close"] = bars["close"].iloc[0] * 0.999

            ok = learner.partial_fit(bars)
            if ok:
                logger.debug("InferenceEngine: online learner updated with label=%d", label)
        except Exception as exc:
            logger.debug("Online learner update failed: %s", exc)

    def _check_live_accuracy_degradation(self) -> None:
        """Compare rolling live accuracy against training OOS baseline; warn if degraded."""
        if len(self._live_pred_window) < 20:
            return
        correct = sum(1 for pred, actual in self._live_pred_window if pred == actual)
        live_acc = correct / len(self._live_pred_window)

        meta = self._load_meta()
        oos_acc_raw = meta.get("oos_accuracy") or meta.get("accuracy") if meta else None
        if oos_acc_raw is None:
            return
        try:
            oos_acc = float(oos_acc_raw)
        except (TypeError, ValueError):
            return

        degradation = oos_acc - live_acc
        if degradation > 0.05:  # live accuracy dropped >5pp below training OOS
            if not self._live_accuracy_alert_sent:
                logger.warning(
                    "InferenceEngine: live accuracy degradation detected — "
                    "live=%.1f%% vs OOS=%.1f%% (delta=%.1f%%) over last %d predictions",
                    live_acc * 100,
                    oos_acc * 100,
                    degradation * 100,
                    len(self._live_pred_window),
                )
                self._live_accuracy_alert_sent = True
        else:
            self._live_accuracy_alert_sent = False  # reset when accuracy recovers

    # ── Stale model detection ─────────────────────────────────────────────────

    def _check_model_staleness(self) -> bool:
        """
        Return True when the active model file is older than MODEL_MAX_AGE_DAYS.

        Uses the mtime of advanced_oos.pkl (or the active model path if set).
        When MODEL_MAX_AGE_DAYS=0 the check is disabled and always returns False.

        When STALE_MODEL_BLOCK=true (default) the caller raises RuntimeError
        so the pre-trade gate blocks the trade.  When false, the caller
        degrades to a neutral signal (warn-only legacy mode).

        Side-effects: updates self._model_stale and self._model_age_days.
        """
        if _MODEL_MAX_AGE_DAYS <= 0:
            self._model_stale = False
            self._model_age_days = None
            return False

        model_path = self._active_model_path or (_saved("advanced_oos.pkl"))
        if not model_path.exists():
            # No model file — not stale (just unavailable; handled elsewhere)
            self._model_stale = False
            self._model_age_days = None
            return False

        try:
            age_seconds = time.time() - model_path.stat().st_mtime
            age_days = age_seconds / 86_400.0
            self._model_age_days = round(age_days, 2)
            self._model_stale = age_days > _MODEL_MAX_AGE_DAYS
            if self._model_stale:
                logger.warning(
                    "STALE MODEL: %s is %.1f days old (max=%s days). Retrain or set MODEL_MAX_AGE_DAYS=0 to suppress.",
                    model_path.name,
                    age_days,
                    _MODEL_MAX_AGE_DAYS,
                )
            return self._model_stale
        except Exception as exc:
            # Fail CLOSED: if model age cannot be determined, treat the model as
            # stale so the STALE_MODEL_BLOCK gate (when enabled) blocks rather
            # than trading on a model of unknown freshness.
            logger.warning("Staleness check failed; treating model as STALE: %s", exc)
            self._model_stale = True
            return True

    # ── Feature drift guard ───────────────────────────────────────────────────

    def _load_train_stats(self) -> dict[str, dict] | None:
        """
        Load training feature statistics from saved_models/feature_stats.json.

        Format expected:
            {
              "feature_name": {"mean": 0.123, "std": 0.045},
              ...
            }

        Generated by the training pipeline (train_advanced.py) after fitting.
        Returns None when the file does not exist (drift guard disabled).
        """
        if self._train_stats is not None:
            return self._train_stats
        stats_path = _saved("feature_stats.json")
        if not stats_path.exists():
            return None
        try:
            self._train_stats = json.loads(stats_path.read_text())
            logger.info(
                "InferenceEngine: loaded feature stats for %d features from %s",
                len(self._train_stats),
                stats_path,
            )
            return self._train_stats
        except Exception as exc:
            logger.warning("feature_stats.json load failed: %s", exc)
            return None

    def _features_for_drift_check(
        self,
        scored: pd.DataFrame | None,
        fallback: pd.DataFrame | None,
    ) -> pd.DataFrame | None:
        """Choose which feature vector the drift guard should watch (S4-01).

        ``predict()`` builds its own feature matrix and the predictor builds a
        second one internally; only the predictor's reaches the model. Watching
        the engine's copy meant the guard reported on a distribution nothing
        scored — internally consistent, and blind to drift in the features that
        actually drive predictions.

        Prefer what the model saw. Fall back to the engine's own vector only
        when the predictor exposes nothing (older predictor, or a call that
        returned neutral without scoring), and say so, because that is degraded
        coverage rather than clean coverage.
        """
        if scored is not None and not scored.empty:
            return scored

        if not self._drift_scope_warned:
            logger.warning(
                "InferenceEngine: predictor did not expose the features it scored — "
                "drift is being measured on the engine's own feature vector, which "
                "the model never sees. Treat drift telemetry as indicative only "
                "(docs/HARDENING_BACKLOG.md S4-01)."
            )
            self._drift_scope_warned = True
        return fallback

    def _model_quality_gate(self):
        """The gate, configured from the constants this file already enforced.

        Built per call rather than cached: the thresholds are module-level and
        a test that monkeypatches one must not be defeated by an instance that
        captured the old value at construction time.
        """
        from ml.model_quality_gate import ModelQualityGate

        return ModelQualityGate(
            minimum_calibration=_MIN_CALIBRATION,
            maximum_drift=_DRIFT_Z_THRESHOLD,
            minimum_data_quality=_MIN_DATA_QUALITY,
        )

    def _evaluate_model_quality(self, *, drift_z: float | None, data_quality: float | None):
        """Score this prediction's calibration, drift and data quality.

        Returns the snapshot, or ``None`` if the gate could not be evaluated at
        all — which is NOT the same as a pass, and `_enforce_model_quality`
        treats it accordingly.

        `drift_z` is passed through as ``None`` when drift was never measured.
        Substituting 0.0 there would report "no drift" for a guard that did not
        run, which is Rule 2's unmeasured-is-absent-never-zero, and the gate
        already fails closed on a missing score.

        Calibration is now the number training measured — 1 - ECE on held-out
        predictions, via `ml/calibration_metrics.py`, read from
        ``saved_models/calibration_report.json``.

        It used to be a *presence* signal: 1.0 if an isotonic calibrator object
        had loaded, 0.0 otherwise. That measured whether a file existed, so a
        badly-fitted calibrator passed any threshold and a well-calibrated raw
        model failed every threshold above zero.

        When no report exists, the score is ``None`` — unmeasured, not passed.
        The gate fails closed on a missing score, which is the behaviour this
        depends on rather than working around.
        """
        try:
            calibration_score = self._recorded_calibration_score()
            return self._model_quality_gate().evaluate(
                calibration_score=calibration_score,
                drift_score=drift_z,
                data_quality_score=data_quality,
            )
        except Exception:
            # Logged at ERROR, not debug: this is a safety control failing to
            # evaluate, and a handler that whispers is how the last one stayed
            # invisible. The caller decides what an unevaluable gate means.
            logger.error("InferenceEngine: model quality gate could not be evaluated", exc_info=True)
            return None

    def _enforce_model_quality(self, snapshot) -> None:
        """Refuse the prediction when the gate says so and blocking is enabled.

        Raises ``RuntimeError`` specifically: `HOPEFXDecisionEngine._phase2_ml`
        treats that type as a hard ML filter and declines the trade, where any
        other exception falls back to the brain's non-ML confidence. A quality
        refusal must not degrade into "trade on less information".
        """
        if not _MODEL_QUALITY_BLOCK:
            return
        if snapshot is None:
            raise RuntimeError(
                "model quality gate could not be evaluated and MODEL_QUALITY_BLOCK=true — "
                "an unmeasured gate is not a passed gate"
            )
        if not snapshot.passed:
            raise RuntimeError("model quality gate failed: " + ", ".join(snapshot.reason_codes))

    def _check_feature_drift(self, X_row: pd.DataFrame | None) -> bool:
        """
        Detect feature distribution drift using z-score comparison.

        Appends the current feature vector to the rolling drift buffer.
        When the buffer is full, computes the mean of each feature over the
        last _DRIFT_WINDOW predictions and compares it to the training mean
        using a z-score: z = |live_mean - train_mean| / max(train_std, 1e-9).

        Returns True when any feature's z-score exceeds _DRIFT_Z_THRESHOLD.

        Side-effects: updates self._drift_detected and self._drift_z_max.
        """
        if X_row is None or X_row.empty:
            # Nothing was scored, so there is nothing to measure. Reporting
            # "no drift" here would be the S4-05 mistake again.
            return False

        train_stats = self._load_train_stats()
        if train_stats is None:
            # No training stats → the guard is DISABLED, not "no drift".
            # Returning False here is indistinguishable from a clean result, so
            # a missing or unreadable stats file silently switched drift
            # detection off. Record it and say so once, loudly, so the condition
            # is visible in logs and via drift_guard_active().
            # See docs/HARDENING_BACKLOG.md S4-05.
            if self._drift_stats_available or not self._drift_stats_warned:
                logger.warning(
                    "InferenceEngine: feature-drift guard DISABLED — no training stats available. "
                    "Drift will not be detected until the stats file is restored."
                )
                self._drift_stats_warned = True
            self._drift_stats_available = False
            self._drift_reason = "no_training_stats"
            self._drift_covered = 0
            self._drift_total = len(X_row.columns)
            return False

        # Coverage check, before anything else. `_check_feature_drift` skips
        # every live feature it has no training stats for. If that skips most of
        # them the loop below still completes, max_z stays 0.0 and the result is
        # "no drift" — computed from almost nothing. Stats that describe a
        # different feature schema (an older artifact, a renamed block) are not
        # a working guard, and reporting one as active is the same error as
        # reporting a missing file as "no drift".
        col_names = list(X_row.columns)
        self._drift_total = len(col_names)
        uncovered = [name for name in col_names if name not in train_stats]
        self._drift_covered = self._drift_total - len(uncovered)
        self._drift_uncovered = uncovered
        coverage = self._drift_covered / self._drift_total if self._drift_total else 0.0

        # Which features are unwatched, not just how many. Measured on the
        # shipped stats: 59 of 229 are uncovered, from two different causes with
        # two different remedies —
        #
        #   36 dl_*  data-layer injections (microstructure, macro, sentiment)
        #            added after this model was fitted, so the training
        #            distribution genuinely has no entry for them. Only a
        #            retrain can cover these.
        #   23 others (im_, cot_, oi_, of_, ri_, inst_, amihud) which ARE in the
        #            scaler but were dropped as zero-variance: constant across
        #            the whole training set, so a z-score against them is either
        #            0 or 1e9 and never a signal.
        #
        # Reporting the count alone made those look like one problem.
        if uncovered and not self._drift_uncovered_logged:
            from collections import Counter

            groups = Counter(name.split("_")[0] for name in uncovered)
            logger.info(
                "InferenceEngine: %d/%d features are not drift-monitored (no training stats). "
                "By prefix: %s. Features added since the last retrain cannot be covered until "
                "the next one.",
                len(uncovered),
                self._drift_total,
                dict(groups.most_common(8)),
            )
            self._drift_uncovered_logged = True

        if coverage < _DRIFT_MIN_COVERAGE:
            if not self._drift_coverage_warned:
                logger.warning(
                    "InferenceEngine: feature-drift guard DISABLED — training stats cover only "
                    "%d of %d live features (%.0f%%, floor %.0f%%). The stats file describes a "
                    "different feature schema than the model produces; retrain to regenerate "
                    "ml/saved_models/feature_stats.json.",
                    self._drift_covered,
                    self._drift_total,
                    coverage * 100,
                    _DRIFT_MIN_COVERAGE * 100,
                )
                self._drift_coverage_warned = True
            self._drift_stats_available = False
            self._drift_reason = "insufficient_coverage"
            return False

        self._drift_stats_available = True
        self._drift_reason = "ok"
        self._drift_coverage_warned = False

        try:
            row_values = X_row.values[0].astype(float)
            self._drift_buffer.append(row_values)

            if len(self._drift_buffer) < _DRIFT_WINDOW:
                # Not enough data yet — skip check
                return False

            buffer_arr = np.array(self._drift_buffer)  # shape: (window, n_features)
            live_means = buffer_arr.mean(axis=0)

            max_z = 0.0
            drifted_features: list[str] = []

            for i, feat_name in enumerate(col_names):
                if feat_name not in train_stats:
                    continue
                train_mean = float(train_stats[feat_name].get("mean", 0.0))
                train_std = float(train_stats[feat_name].get("std", 1.0))
                z = abs(live_means[i] - train_mean) / max(train_std, 1e-9)
                max_z = max(max_z, z)
                if z > _DRIFT_Z_THRESHOLD:
                    drifted_features.append(f"{feat_name}(z={z:.1f})")

            self._drift_z_max = round(max_z, 3)
            self._drift_detected = len(drifted_features) > 0

            if self._drift_detected:
                logger.warning(
                    "FEATURE DRIFT detected: %d features exceed z=%.1f threshold. Top drifted: %s. max_z=%.2f. %s",
                    len(drifted_features),
                    _DRIFT_Z_THRESHOLD,
                    ", ".join(drifted_features[:5]),
                    max_z,
                    "BLOCKING inference (DRIFT_BLOCK=true)."
                    if _DRIFT_BLOCK
                    else "Continuing (set DRIFT_BLOCK=true to block).",
                )
            return self._drift_detected

        except Exception as exc:
            # Fail CLOSED: if drift cannot be computed, flag drift so the
            # DRIFT_BLOCK gate (when enabled) abstains rather than trading on an
            # unverified live feature distribution.
            logger.warning("Feature drift check failed; flagging drift: %s", exc)
            self._drift_detected = True
            return True

    # ── Main predict ──────────────────────────────────────────────────────────

    def predict(
        self,
        ohlcv: pd.DataFrame,
        symbol: str = "XAU_USD",
        threshold_long: float = _THRESHOLD_LONG,
        threshold_short: float = _THRESHOLD_SHORT,
    ) -> dict[str, Any]:
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
        sym_label = symbol or "unknown"

        def _abstain(result: dict, reason: str, detail: str = "") -> dict:
            """Record an abstention once, where every consumer can see it.

            Each of these paths used to do three separate things: increment the
            Prometheus counter with a `reason` label, log at DEBUG (off in
            production), and return a result carrying no reason at all. So the
            cause was recorded in a metric label and nowhere the caller could
            read it — HOPEFXDecisionEngine, core/signal_engine.py and the
            dashboards all saw a flat neutral with no explanation, and the only
            way to find out why was to read it back out of the metrics registry.

            A neutral signal is the system declining to trade. An operator who
            cannot tell a short data window from a drifting model from a stale
            artifact cannot act on it.
            """
            result["reason"] = reason
            result["latency_ms"] = (time.perf_counter() - t0) * 1000
            _PROM.fallback_total.labels(symbol=sym_label, reason=reason).inc()
            logger.info(
                "InferenceEngine: abstaining for %s — %s%s",
                sym_label,
                reason,
                f" ({detail})" if detail else "",
            )
            return result

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
            return _abstain(base_result, "insufficient_bars", f"{len(ohlcv)} < {_MIN_BARS}")

        # Step 0: Timeframe alignment — resample intraday bars to daily when
        # the model was trained on daily data (INFERENCE_TIMEFRAME=daily, default).
        # This prevents the regime mismatch where rolling windows span minutes
        # instead of months and volatility features are scaled to intraday noise.
        try:
            from ml.daily_aggregator import ensure_daily, needs_resampling

            if needs_resampling(ohlcv):
                daily_ohlcv = ensure_daily(ohlcv, min_bars=_MIN_BARS)
                if daily_ohlcv is None:
                    logger.debug(
                        "InferenceEngine: insufficient daily bars after resampling "
                        "(%d intraday → too few daily) — abstaining for %s",
                        len(ohlcv),
                        sym_label,
                    )
                    base_result["direction"] = "neutral"
                    return _abstain(
                        base_result,
                        "insufficient_daily_bars",
                        f"{len(ohlcv)} intraday bars resampled to too few daily",
                    )
                logger.debug(
                    "InferenceEngine: resampled %d intraday → %d daily bars for %s",
                    len(ohlcv),
                    len(daily_ohlcv),
                    sym_label,
                )
                ohlcv = daily_ohlcv
                base_result["bars_used"] = len(ohlcv)
        except Exception as _resample_exc:
            logger.debug("Daily resampling skipped: %s", _resample_exc)

        # Step 1: MacroStore (now auto-populated from FRED via MacroStoreBridge)
        macro_df = self._get_macro_df(ohlcv)
        macro_active = macro_df is not None and not macro_df.empty

        # Step 2: MTF fusion
        mtf_df = self._get_mtf_df(ohlcv, symbol)
        mtf_active = mtf_df is not None and not mtf_df.empty

        # Step 3: Build features
        X = self._build_features(ohlcv, macro_df, mtf_df, symbol)
        if X is None:
            self._fallback_count += 1
            return _abstain(base_result, "feature_build_failed")

        # Step 3-validation: Block NaN/Inf/label-leakage in feature matrix
        # before it reaches the model. A NaN in features causes silent
        # prediction errors that are harder to detect than an explicit failure.
        try:
            from data_layer.validation import validate_features as _vf

            X = _vf(X, strict=True, label_col="y")
        except Exception as _val_exc:
            logger.warning(
                "InferenceEngine: feature validation failed for %s: %s — returning neutral",
                sym_label,
                _val_exc,
            )
            base_result["fallback"] = True
            base_result["validation_error"] = str(_val_exc)
            self._fallback_count += 1
            return _abstain(base_result, "feature_validation_failed", str(_val_exc)[:120])

        # Step 3a: Stale model detection
        # Check whether the model file is older than MODEL_MAX_AGE_DAYS.
        # STALE_MODEL_BLOCK=true (default): raise RuntimeError — the pre-trade
        # gate catches this and blocks the trade.  This is the correct
        # production behaviour: a stale model is a known-bad state.
        # STALE_MODEL_BLOCK=false: degrade to neutral (legacy warn-only mode).
        stale = self._check_model_staleness()
        if stale:
            base_result["latency_ms"] = (time.perf_counter() - t0) * 1000
            base_result["model_version"] = "stale"
            base_result["stale_model"] = True
            base_result["model_age_days"] = self._model_age_days
            self._fallback_count += 1
            base_result["reason"] = "stale_model"
            _PROM.fallback_total.labels(symbol=sym_label, reason="stale_model").inc()
            logger.warning(
                "InferenceEngine: model for %s is %.1f days old (max %.0f) — %s",
                sym_label,
                self._model_age_days,
                _MODEL_MAX_AGE_DAYS,
                "blocking" if _STALE_MODEL_BLOCK else "abstaining",
            )
            if _STALE_MODEL_BLOCK:
                raise RuntimeError(
                    f"STALE MODEL BLOCKED: {sym_label} model is {self._model_age_days:.1f} days old "
                    f"(max={_MODEL_MAX_AGE_DAYS:.0f} days). "
                    "Retrain the model, or set STALE_MODEL_BLOCK=false to allow stale inference "
                    "(not recommended in production)."
                )
            logger.warning(
                "STALE MODEL: returning neutral for %s (age=%.1f days > max=%.0f). "
                "Set STALE_MODEL_BLOCK=true to block inference on stale models.",
                sym_label,
                self._model_age_days or 0,
                _MODEL_MAX_AGE_DAYS,
            )
            return base_result

        # Step 3b: Feature drift guard — deferred until after scoring.
        # The guard used to run here, on `X`. But `X` is never given to the
        # model: the predictor rebuilds its own features from the raw OHLCV
        # frame, so the guard measured a distribution nothing scored while
        # drift in the features that actually drive predictions went unseen
        # (docs/HARDENING_BACKLOG.md S4-01). It now runs below, on the matrix
        # the predictor reports it handed to the model. The cost is one
        # already-computed prediction discarded when drift blocks, which is
        # nothing next to gating on the wrong vector.

        # Step 3c: Look-ahead bias guard — validate that the latest feature
        # timestamp is not in the future relative to the decision timestamp.
        # This catches data pipeline bugs where future bars leak into features.
        try:
            from risk.lookahead_guard import feature_guard as _fg

            if hasattr(ohlcv.index, "max") and len(ohlcv) > 0:
                latest_feature_ts = ohlcv.index.max()
                decision_ts = pd.Timestamp.now(tz="UTC")
                _fg.validate(
                    features_ts=latest_feature_ts,
                    decision_ts=decision_ts,
                    context=f"inference:{sym_label}",
                )
        except Exception as _lag_exc:
            # Re-raise LookAheadBiasError — critical data integrity violation.
            # Swallow other guard failures (e.g. timezone mismatch) gracefully.
            try:
                from risk.lookahead_guard import LookAheadBiasError as _LABCheck

                if isinstance(_lag_exc, _LABCheck):
                    raise
            except ImportError:  # nosec B110 — lookahead guard is optional; skip check
                pass
            logger.debug("InferenceEngine: look-ahead guard check skipped: %s", _lag_exc)

        # Step 4: Model prediction
        predictor = self._get_predictor()
        raw_prob = 0.5
        model_version = "fallback"

        if predictor is not None and predictor.is_available:
            try:
                # predict_proba is synchronous — call directly.
                # Circuit breaker state is updated via the sync record_* helpers
                # so this path is safe in both async and sync contexts.
                raw_prob = predictor.predict_proba(ohlcv, macro_df=macro_df, symbol=symbol)
                model_version = predictor.version
                # Record success in ML circuit breaker (sync-safe)
                try:
                    from resilience.service_circuit_breakers import ml_breaker as _ml_cb

                    _ml_cb.record_success()
                except Exception:  # nosec B110 — circuit breaker is non-fatal  # noqa: S110
                    pass
            except Exception as exc:
                logger.warning("Predictor failed: %s", exc)
                self._fallback_count += 1
                # Record failure in ML circuit breaker (sync-safe)
                try:
                    from resilience.service_circuit_breakers import ml_breaker as _ml_cb

                    _ml_cb.record_failure(exc)
                except Exception:  # nosec B110 — circuit breaker is non-fatal  # noqa: S110
                    pass

        # Step 4b: Feature drift guard (deferred from step 3b — see S4-01).
        # Measure drift on the matrix the predictor actually scored, falling
        # back to the engine's own vector only when it exposes none.
        drift = self._check_feature_drift(
            self._features_for_drift_check(
                getattr(predictor, "last_scored_features", None),
                fallback=X,
            )
        )
        if drift and _DRIFT_BLOCK:
            base_result["model_version"] = "drift_blocked"
            base_result["feature_drift"] = True
            base_result["drift_z_max"] = self._drift_z_max
            self._fallback_count += 1
            return _abstain(base_result, "feature_drift", f"z_max={self._drift_z_max}")

        # Step 5: Online learner blend
        # SklearnOnlineLearner.predict_proba() accepts the raw OHLCV DataFrame
        # (it extracts its own features internally).  Returns float P(up) or None.
        online_active = False
        learner = self._get_online_learner()
        if learner is not None:
            try:
                online_prob = learner.predict_proba(ohlcv)
                if online_prob is not None and np.isfinite(online_prob) and 0.0 <= online_prob <= 1.0:
                    base_before = raw_prob
                    # Blend: 70% base model, 30% online learner
                    raw_prob = 0.70 * raw_prob + 0.30 * online_prob
                    online_active = True
                    logger.debug(
                        "Online learner blended: base=%.3f online=%.3f blend=%.3f",
                        base_before,
                        online_prob,
                        raw_prob,
                    )
                elif online_prob is not None:
                    # Out-of-range / NaN probability would corrupt the signal —
                    # skip the blend rather than poison raw_prob.
                    logger.warning(
                        "Online learner returned invalid probability %r; skipping blend.",
                        online_prob,
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

        # Record signal to lineage store (with features hash for audit trail)
        self._record_signal_lineage(
            direction=direction,
            confidence=float(confidence),
            probability=float(cal_prob),
            symbol=symbol,
            model_version=model_version,
            features_df=X,
        )

        # Data quality from orchestrator (for downstream gating)
        #
        # `data_quality` stays None when the orchestrator has no tick to speak
        # for. It used to default to 1.0 — a perfect score for a measurement
        # that never happened, handed straight to the gauge and, once this gate
        # was wired, to the gate. Rule 2: unmeasured is absent, never best case.
        data_quality: float | None = None
        try:
            from data_layer.orchestrator import orchestrator

            tick = orchestrator.get_latest_tick()
            if tick is not None:
                data_quality = tick.confidence
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        # ── Model quality gate ────────────────────────────────────────────────
        # Consulted here rather than at registry promotion: the gate's own
        # docstring scopes it to "before a candidate reaches paper or live
        # execution", and this is that point. Advisory unless
        # MODEL_QUALITY_BLOCK=true, in which case it raises RuntimeError, which
        # HOPEFXDecisionEngine._phase2_ml treats as a hard ML filter.
        quality = self._evaluate_model_quality(
            drift_z=getattr(self, "_drift_z_max", None),
            data_quality=data_quality,
        )
        self._enforce_model_quality(quality)

        # ── Prometheus instrumentation ────────────────────────────────────────
        _PROM.predict_total.labels(symbol=sym_label, direction=direction).inc()
        _PROM.predict_latency.labels(symbol=sym_label).observe(latency_ms / 1000.0)
        _PROM.confidence_gauge.labels(symbol=sym_label).set(float(confidence))
        # Only reported when actually measured. A gauge that reads 1.0 because
        # nothing was measured is the dashboard telling you the feed is perfect
        # while it is silent.
        if data_quality is not None:
            _PROM.data_quality_gauge.labels(symbol=sym_label).set(data_quality)
        if model_version and model_version != "fallback":
            _PROM.model_version_info.labels(model_id=model_version).set(1)
        served_reason = ""
        if model_version == "fallback":
            served_reason = "model_fallback"
            _PROM.fallback_total.labels(symbol=sym_label, reason="model_fallback").inc()
            logger.info("InferenceEngine: abstaining for %s — model_fallback", sym_label)

        decision_id = f"{sym_label}:{self._predict_count}:{time.time_ns()}"
        feature_schema_hash = hashlib.sha256(json.dumps(list(X.columns), separators=(",", ":")).encode()).hexdigest()
        evidence_payload = {
            "decision_id": decision_id,
            "model_version": model_version,
            "model_checksum": hashlib.sha256(model_version.encode()).hexdigest(),
            "feature_schema_hash": feature_schema_hash,
            "data_snapshot_at": datetime.now(UTC).isoformat(),
            "regime": "unknown",
            # These three used to be judged inline here, against a bare 0.3.
            # They are now the model quality gate's verdict, so the evidence
            # blob and the gate cannot disagree about the same prediction.
            # `unmeasured` is a third state the string form could not express:
            # it previously read "valid" for a data quality nobody measured.
            "calibration_state": "isotonic" if self._calibrator is not None else "raw",
            "drift_state": ("clear" if quality.drift_ok else "detected") if quality else "unmeasured",
            "data_quality_state": ("valid" if quality.data_quality_ok else "degraded") if quality else "unmeasured",
            "model_quality_passed": bool(quality.passed) if quality else None,
            "model_quality_reasons": list(quality.reason_codes) if quality else [],
        }
        evidence_hash = hashlib.sha256(
            json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        return {
            "direction": direction,
            "probability": round(raw_prob, 4),
            "confidence": round(float(confidence), 4),
            "model_version": model_version,
            "bars_used": len(ohlcv),
            "last_close": last_close,
            "latency_ms": round(latency_ms, 2),
            "fallback": model_version == "fallback",
            # Empty on a served prediction; the abstention cause otherwise. It
            # used to exist only as a Prometheus label, so a caller saw a flat
            # neutral and could not tell a short window from a drifting model.
            "reason": served_reason,
            "macro_active": macro_active,
            "mtf_active": mtf_active,
            "online_active": online_active,
            "dl_nudge": round(dl_nudge, 4),
            "sentiment_score": self._last_sentiment_score,
            "macro_impact": self._last_macro_impact,
            # None when the orchestrator had no tick — reported as unmeasured
            # rather than as a perfect 1.0 nobody measured.
            "data_quality": round(data_quality, 4) if data_quality is not None else None,
            "is_safe": self.is_safe_to_trade(),
            "decision_id": decision_id,
            "evidence_hash": evidence_hash,
            "evidence": evidence_payload,
        }

    def _get_data_layer_nudge(self) -> float:
        """
        Compute a soft probability nudge from the data layer.

        Combines three signals from the orchestrator:
          1. News sentiment EMA       → ±0.010 max
          2. Order flow imbalance     → ±0.008 max (microstructure direction)
          3. Trade pressure           → ±0.004 max

        Total nudge range: [-0.022, +0.022].
        Intentionally small — does not override the trained model.

        Positive nudge = bullish for gold (long bias).
        Negative nudge = bearish for gold (short bias).

        Suppressed entirely during macro blackout windows.
        """
        self._last_sentiment_score = 0.0
        self._last_macro_impact = 0.0
        try:
            from data_layer.orchestrator import orchestrator

            # Data quality gate — refuse to nudge on bad data
            tick = orchestrator.get_latest_tick()
            if tick is not None and tick.confidence < 0.30:
                logger.debug(
                    "InferenceEngine: data quality %.3f too low — suppressing nudge",
                    tick.confidence,
                )
                return 0.0

            features = orchestrator.get_ml_features()

            sentiment = float(features.get("news_sentiment_score", 0.0))
            impact = float(features.get("macro_impact_score_now", 0.0))
            blackout = float(features.get("macro_is_blackout", 0.0))
            ofi = float(features.get("micro_ofi", 0.0))
            trade_pressure = float(features.get("micro_trade_pressure", 0.0))

            self._last_sentiment_score = sentiment
            self._last_macro_impact = impact

            # Hard suppress during blackout windows
            if blackout > 0.5:
                return 0.0

            # Dampen all nudges proportional to macro impact uncertainty
            # High impact = we don't know direction → reduce nudge magnitude
            impact_dampen = max(0.0, 1.0 - impact * 1.5)

            # 1. Sentiment nudge: ±0.010
            sent_nudge = sentiment * 0.010

            # 2. OFI nudge: ±0.008 (OFI is already normalised to [-1, +1])
            ofi_nudge = ofi * 0.008

            # 3. Trade pressure nudge: ±0.004
            pressure_nudge = trade_pressure * 0.004

            total = (sent_nudge + ofi_nudge + pressure_nudge) * impact_dampen
            return float(max(-0.022, min(0.022, total)))

        except Exception:
            return 0.0

    def get_data_layer_tick(self):
        """
        Return the latest validated GoldTick from the orchestrator.

        Used by callers that need the current price alongside the signal.
        Returns None if orchestrator is unavailable or no tick exists.
        """
        try:
            from data_layer.orchestrator import orchestrator

            return orchestrator.get_latest_tick()
        except Exception:
            return None

    def get_data_layer_features(self) -> dict[str, float]:
        """
        Return the full orchestrator ML feature set.

        Includes microstructure, sentiment, macro calendar, and FRED features.
        Returns empty dict if orchestrator is unavailable.
        """
        try:
            from data_layer.orchestrator import orchestrator

            return orchestrator.get_ml_features()
        except Exception:
            return {}

    def is_safe_to_trade(self) -> bool:
        """
        Delegate to orchestrator.is_safe_to_trade().

        Returns True if:
          - At least one gold feed is alive
          - Not in a macro event blackout window
          - Data quality confidence > 0.3
        """
        try:
            from data_layer.orchestrator import orchestrator

            return orchestrator.is_safe_to_trade()
        except Exception:
            # fail-closed: block trading when the safety state cannot be determined
            logger.warning(
                "is_safe_to_trade: orchestrator unavailable; failing CLOSED (not safe).",
                exc_info=True,
            )
            return False

    def _record_signal_lineage(
        self,
        direction: str,
        confidence: float,
        probability: float,
        symbol: str,
        model_version: str,
        features_df: pd.DataFrame | None = None,
    ) -> None:
        """
        Write signal to immutable lineage store (non-blocking).

        features_hash: SHA-256 of the feature vector for deduplication
        and audit trail. Computed from the last-bar feature values.
        """
        try:
            import hashlib
            import uuid

            # Access lineage store via orchestrator — single entry point rule.
            # Never import data_layer.lineage.store directly from outside data_layer/.
            from data_layer.orchestrator import orchestrator

            lineage_store = orchestrator._lineage

            # Compute features hash for audit trail
            features_hash = ""
            if features_df is not None and not features_df.empty:
                try:
                    feat_dict = features_df.iloc[-1].replace([float("inf"), float("-inf")], 0.0).fillna(0.0).to_dict()
                    # Round to 4dp to avoid float noise in hash
                    feat_dict = {k: round(float(v), 4) for k, v in feat_dict.items()}
                    blob = json.dumps(feat_dict, sort_keys=True, separators=(",", ":"))
                    features_hash = hashlib.sha256(blob.encode()).hexdigest()[:16]
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

            lineage_store.record_signal(
                direction=direction,
                confidence=confidence,
                probability=probability,
                features_hash=features_hash,
                model_version=model_version,
                lineage_id=str(uuid.uuid4()),
                symbol=symbol,
            )
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    # ── Metadata cache ────────────────────────────────────────────────────────

    def _load_meta(self) -> dict[str, Any]:
        """
        Load and cache advanced_oos_meta.json.

        Re-reads from disk when the file mtime changes so a retrain
        automatically refreshes health() without a restart.
        """
        meta_path = _saved("advanced_oos_meta.json")
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

    def health(self) -> dict[str, Any]:
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
        model_available = predictor is not None and getattr(predictor, "is_available", False)

        # ── Fallback rate ─────────────────────────────────────────────────────
        fallback_rate = round(self._fallback_count / self._predict_count, 4) if self._predict_count > 0 else 0.0

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
            from ml.macro_store import macro_store

            macro_series = len(macro_store)
            macro_ok = macro_series > 0
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        mtf_ok = False
        if _MTF_FUSION_ENABLED:
            try:
                from research.pipeline.mtf_fusion import (
                    _MTF_STORE_SINGLETON,
                )

                mtf_ok = _MTF_STORE_SINGLETON is not None
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        online_ok = False
        if _ONLINE_LEARNING_ENABLED:
            try:
                from research.pipeline.paper_trading_gate import (
                    get_gate,
                )

                gate = get_gate()
                p3_ok, _ = gate.phase3_ready()
                online_ok = p3_ok
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # ── Feature count ─────────────────────────────────────────────────────
        feature_count = 0
        try:
            if predictor is not None and hasattr(predictor, "_model"):
                n = getattr(predictor._model, "n_features_in_", 0)
                feature_count = int(n) if n else 0
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        # ── Metadata (oos_accuracy, last_trained_at) ──────────────────────────
        meta = self._load_meta()
        oos_accuracy: float | None = None
        last_trained_at: str | None = None
        if meta:
            raw_acc = meta.get("oos_accuracy") or meta.get("accuracy")
            oos_accuracy = float(raw_acc) if raw_acc is not None else None
            if feature_count == 0:
                fc = meta.get("feature_count", 0)
                feature_count = int(fc) if fc else 0
            last_trained_at = meta.get("validated_at") or meta.get("trained_at")

        # ── SignalFilter EV stats ─────────────────────────────────────────────
        signal_filter_stats: dict[str, Any] = {}
        try:
            from ml.signal_filter import get_signal_filter

            sf = get_signal_filter()
            if hasattr(sf, "get_stats"):
                signal_filter_stats = sf.get_stats()
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        # ── Uptime ────────────────────────────────────────────────────────────
        uptime_seconds: float | None = None
        if self._first_predict_at is not None:
            uptime_seconds = round(time.time() - self._first_predict_at, 1)

        # ── Overall status ────────────────────────────────────────────────────
        if model_available:
            status = "ok"
        elif self._predict_count > 0 and fallback_rate < 1.0:
            status = "degraded"
        else:
            status = "unavailable"

        # ── Stale model ───────────────────────────────────────────────────────
        # Re-run the staleness check so health() always reflects current state.
        self._check_model_staleness()

        # ── Feature drift ─────────────────────────────────────────────────────
        train_stats_available = self._load_train_stats() is not None

        # Degrade status when model is stale or drift is blocking
        if self._model_stale or (self._drift_detected and _DRIFT_BLOCK):
            status = "degraded"

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
            "rollback_count": self._rollback_count,
            "active_model_path": str(self._active_model_path) if self._active_model_path else None,
            # ── Stale model ────────────────────────────────────────────────
            "stale_model": self._model_stale,
            "model_age_days": self._model_age_days,
            "model_max_age_days": _MODEL_MAX_AGE_DAYS if _MODEL_MAX_AGE_DAYS > 0 else None,
            "stale_model_block": _STALE_MODEL_BLOCK,
            # ── Feature drift ──────────────────────────────────────────────
            "feature_drift_detected": self._drift_detected,
            "feature_drift_z_max": self._drift_z_max,
            "feature_drift_threshold": _DRIFT_Z_THRESHOLD,
            "feature_drift_blocking": _DRIFT_BLOCK,
            "feature_drift_buffer_size": len(self._drift_buffer),
            "feature_drift_window": _DRIFT_WINDOW,
            "train_stats_available": train_stats_available,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    # ── Model reload / rollback ───────────────────────────────────────────────

    def reload_model(self, model_path: Path | None = None) -> bool:
        """
        Hot-reload the predictor from disk without restarting the process.

        Saves the current model path as the rollback target before loading
        the new one.  If loading fails the engine stays on the current model.

        Parameters
        ----------
        model_path : Path to the new model file.  Defaults to the standard
                     advanced_oos.pkl location.

        Returns True on success, False on failure.
        """
        target = model_path or (_saved("advanced_oos.pkl"))
        if not target.exists():
            logger.error("reload_model: path does not exist: %s", target)
            return False

        # Preserve current model as rollback target
        if self._predictor is not None:
            try:
                self._previous_model_path = (
                    Path(self._predictor._model_path)
                    if hasattr(self._predictor, "_model_path")
                    else self._active_model_path
                )
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        try:
            from ml.live_inference import AdvancedModelPredictor

            new_predictor = AdvancedModelPredictor(model_path=target)
            if not new_predictor.is_available:
                logger.error("reload_model: new predictor not available after load")
                return False
            # Force-load the model now so failures surface here, not at predict time
            if not new_predictor._load():
                logger.error("reload_model: model file exists but failed to load: %s", target)
                return False
            self._predictor = new_predictor
            self._active_model_path = target
            self._meta_cache = None  # invalidate meta cache
            logger.info("reload_model: loaded %s", target)
            _PROM.model_version_info.labels(model_id=str(target.stem)).set(1)
            return True
        except Exception as exc:
            logger.error("reload_model: failed to load %s: %s", target, exc)
            return False

    def rollback_model(self) -> bool:
        """
        Revert to the previously loaded model.

        Used when a newly deployed model degrades signal quality or accuracy.
        Returns True on success, False when no previous model is available.
        """
        if self._previous_model_path is None:
            logger.warning("rollback_model: no previous model to roll back to")
            return False

        logger.warning(
            "rollback_model: reverting from %s to %s",
            self._active_model_path,
            self._previous_model_path,
        )
        success = self.reload_model(self._previous_model_path)
        if success:
            self._rollback_count += 1
            _PROM.rollback_total.labels(reason="manual_rollback").inc()
            logger.warning("rollback_model: rollback complete (count=%d)", self._rollback_count)
        return success


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: InferenceEngine | None = None


def get_inference_engine() -> InferenceEngine:
    """Return the module-level InferenceEngine singleton."""
    global _engine
    if _engine is None:
        _engine = InferenceEngine()
    return _engine
