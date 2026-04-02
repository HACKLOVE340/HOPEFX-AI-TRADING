# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/anomaly.py
==============================
Anomaly detection layer: Isolation Forest + Local Outlier Factor ensemble.

Role in the pipeline
--------------------
Anomalous bars (flash crashes, data errors, extreme vol spikes, circuit-breaker
halts) are harmful training examples: the model memorises them as signal when
they are actually noise.  This module:

1. Fits an IsolationForest (global density) + LOF (local density) ensemble.
2. Scores every bar with a combined anomaly score — more negative = more anomalous.
3. Converts scores to sample weights in (0, 1] so anomalous bars contribute
   less to the loss — they are not discarded, just down-weighted.
4. Optionally flags bars as `is_anomaly` (boolean) for inspection / filtering.
5. Persists fitted detectors to disk for warm-start on restart.

The weight function is:
    w = sigmoid(k * (score - threshold))
where k controls sharpness and threshold is the decision boundary.
This gives a smooth, differentiable weight rather than a hard 0/1 mask.

Ensemble scoring
----------------
    combined_score = alpha * IF_score + (1 - alpha) * LOF_score
where alpha=0.6 by default (IF is more robust on high-dimensional data;
LOF catches local density anomalies that IF misses).

Usage
-----
    from research.pipeline.anomaly import AnomalyWeighter

    aw = AnomalyWeighter(contamination=0.02, use_lof=True)
    aw.fit(X_train)
    weights = aw.sample_weights(X_train)   # pass to model.fit(..., sample_weight=weights)
    flags   = aw.flag(X_test)              # boolean array
    aw.save("ml/saved_models/anomaly_weighter.pkl")
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


def _sigmoid(x: np.ndarray, k: float = 5.0) -> np.ndarray:
    """Numerically stable sigmoid."""
    return np.where(
        x >= 0,
        1.0 / (1.0 + np.exp(-k * x)),
        np.exp(k * x) / (1.0 + np.exp(k * x)),
    )


class AnomalyWeighter:
    """
    Isolation Forest + LOF ensemble anomaly scorer → smooth sample weights.

    Parameters
    ----------
    contamination : Expected fraction of anomalies in training data.
                    0.01–0.05 is typical for financial data.
    n_estimators  : Number of isolation trees.
    sharpness     : Sigmoid sharpness k — higher = harder boundary.
    random_state  : Reproducibility seed.
    use_lof       : Whether to include Local Outlier Factor in the ensemble.
    lof_neighbors : Number of neighbours for LOF.
    if_weight     : Weight for Isolation Forest score in ensemble (LOF gets 1-if_weight).
    """

    def __init__(
        self,
        contamination: float = 0.02,
        n_estimators: int = 200,
        sharpness: float = 8.0,
        random_state: int = 42,
        use_lof: bool = True,
        lof_neighbors: int = 20,
        if_weight: float = 0.6,
    ):
        self.contamination = contamination
        self.sharpness = sharpness
        self.use_lof = use_lof
        self.if_weight = float(np.clip(if_weight, 0.0, 1.0))
        self._scaler = StandardScaler()
        self._iso = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            max_samples="auto",
            random_state=random_state,
            n_jobs=-1,
        )
        self._lof: LocalOutlierFactor | None = None
        if use_lof:
            self._lof = LocalOutlierFactor(
                n_neighbors=lof_neighbors,
                contamination=contamination,
                novelty=True,  # novelty=True allows predict() on new data
                n_jobs=-1,
            )
        self._threshold: float = 0.0  # decision_function threshold (≈0 for IF)
        self._lof_threshold: float = 0.0
        self._fitted = False

    # ── Fit ───────────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame | np.ndarray) -> AnomalyWeighter:
        """
        Fit the Isolation Forest (and optionally LOF) on the training feature matrix.

        Parameters
        ----------
        X : (n_samples, n_features) — should be the training split only.
        """
        arr = X.values if isinstance(X, pd.DataFrame) else np.asarray(X)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        arr = self._scaler.fit_transform(arr)

        # Isolation Forest
        self._iso.fit(arr)
        if_scores = self._iso.decision_function(arr)
        self._threshold = float(np.quantile(if_scores, self.contamination))

        # LOF (optional)
        if self._lof is not None:
            try:
                self._lof.fit(arr)
                lof_scores = self._lof.decision_function(arr)
                self._lof_threshold = float(np.quantile(lof_scores, self.contamination))
            except Exception as exc:
                logger.warning("LOF fit failed, falling back to IF-only: %s", exc)
                self._lof = None

        self._fitted = True
        n_anomalies = int((if_scores < self._threshold).sum())
        logger.info(
            "AnomalyWeighter fitted: %d/%d bars flagged (%.1f%%) [IF%s]",
            n_anomalies,
            len(arr),
            100 * n_anomalies / len(arr),
            "+LOF" if self._lof is not None else "",
        )
        return self

    # ── Score ─────────────────────────────────────────────────────────────────

    def decision_scores(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Ensemble anomaly scores (IF + LOF blend).
        Positive = inlier, negative = outlier.
        """
        self._check_fitted()
        arr = X.values if isinstance(X, pd.DataFrame) else np.asarray(X)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        arr = self._scaler.transform(arr)

        if_scores = self._iso.decision_function(arr)

        if self._lof is not None:
            try:
                lof_scores = self._lof.decision_function(arr)
                # Normalise both to comparable scale before blending
                if_norm = if_scores - self._threshold
                lof_norm = lof_scores - self._lof_threshold
                return self.if_weight * if_norm + (1.0 - self.if_weight) * lof_norm
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)  # fall through to IF-only

        return if_scores - self._threshold

    def if_scores_raw(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """Raw Isolation Forest decision_function scores (before LOF blend)."""
        self._check_fitted()
        arr = X.values if isinstance(X, pd.DataFrame) else np.asarray(X)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        arr = self._scaler.transform(arr)
        return self._iso.decision_function(arr)

    # ── Weights ───────────────────────────────────────────────────────────────

    def sample_weights(
        self,
        X: pd.DataFrame | np.ndarray,
        min_weight: float = 0.05,
    ) -> np.ndarray:
        """
        Convert ensemble anomaly scores to sample weights in [min_weight, 1.0].

        Normal bars → weight ≈ 1.0
        Anomalous bars → weight → min_weight

        Parameters
        ----------
        X          : Feature matrix (any split).
        min_weight : Floor weight for the most anomalous bars.
                     Set to 0.0 to fully exclude anomalies.
        """
        # decision_scores() already centres on threshold (positive = inlier)
        scores = self.decision_scores(X)
        weights = _sigmoid(scores, k=self.sharpness)
        # Rescale to [min_weight, 1.0]
        weights = min_weight + (1.0 - min_weight) * weights
        return weights.astype(np.float32)

    # ── Flag ──────────────────────────────────────────────────────────────────

    def flag(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Boolean array: True = anomalous bar.
        decision_scores() is already centred on threshold; negative = anomalous.
        """
        scores = self.decision_scores(X)
        return scores < 0.0

    def annotate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add `anomaly_score`, `is_anomaly`, and `anomaly_weight` columns.
        """
        scores = self.decision_scores(df)
        weights = self.sample_weights(df)
        out = df.copy()
        out["anomaly_score"] = scores
        out["is_anomaly"] = scores < 0.0
        out["anomaly_weight"] = weights
        return out

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        import joblib

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path, compress=3)
        logger.info("AnomalyWeighter saved → %s", path)

    @classmethod
    def load(cls, path: str | Path) -> AnomalyWeighter:
        import joblib
        import pickle  # nosec B403 - joblib tried first; pickle only for legacy fallback

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"AnomalyWeighter model not found: {path}")
        try:
            obj = joblib.load(path)  # nosec B301 - path set by class constructor from saved_models
        except Exception:
            with open(path, "rb") as f:
                obj = pickle.load(f)  # nosec B301 - joblib failed; legacy pickle fallback
        if not isinstance(obj, cls):
            raise TypeError(f"Expected AnomalyWeighter, got {type(obj)}")
        logger.info("AnomalyWeighter loaded ← %s", path)
        return obj

    def _check_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError("Call fit() before scoring")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def anomaly_report(self, X: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        """
        Return the top-N most anomalous rows with their scores.
        Useful for inspecting what the model considers unusual.
        """
        scores = self.decision_scores(X)
        idx = np.argsort(scores)[:top_n]
        report = X.iloc[idx].copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X[idx])
        report["anomaly_score"] = scores[idx]
        return report


# ─────────────────────────────────────────────────────────────────────────────
# AnomalyWeightStore — live inference store for signal engine
# ─────────────────────────────────────────────────────────────────────────────


class AnomalyWeightStore:
    """
    Production anomaly weighting store for the signal engine (Phase 2).

    Maintains a rolling window of recent OHLCV bars, fits an IF+LOF ensemble
    on that window, and scores each new bar.  When the combined anomaly score
    indicates an anomalous bar, the ML probability is blended toward neutral
    (0.5) by `down_weight_factor`.

    Thread-safe: refit runs under a lock so concurrent ticks never see a
    partially-fitted model.

    Parameters
    ----------
    window_size       : Number of recent bars used to fit the detector.
    refit_every       : Refit every N new bars (amortises cost).
    contamination     : Expected anomaly fraction (passed to IF and LOF).
    anomaly_threshold : Normalised score below which a bar is anomalous.
                        decision_scores() is centred on 0; negative = anomalous.
                        Default -0.05 (slightly below inlier boundary).
    down_weight_factor: Multiplier applied to ML probability on anomalous bars.
    use_lof           : Include LOF in the ensemble (more accurate, slower).
    persist_path      : If set, save/load the fitted weighter to this path.
    """

    MIN_FIT_BARS = 50  # minimum buffer size before first fit

    def __init__(
        self,
        window_size: int = 500,
        refit_every: int = 50,
        contamination: float = 0.02,
        anomaly_threshold: float = -0.05,
        down_weight_factor: float = 0.5,
        use_lof: bool = True,
        persist_path: str | None = None,
    ) -> None:
        self.window_size = window_size
        self.refit_every = refit_every
        self.anomaly_threshold = anomaly_threshold
        self.down_weight_factor = down_weight_factor
        self.use_lof = use_lof
        self.persist_path = Path(persist_path) if persist_path else None
        self._contamination = contamination
        self._weighter: AnomalyWeighter | None = None
        self._buffer: list = []
        self._bars_since_refit: int = 0
        self._fitted = False
        self._lock = threading.Lock()
        self._anomaly_count: int = 0
        self._total_scored: int = 0

        # Attempt warm-start from persisted model
        if self.persist_path and self.persist_path.exists():
            self._load_persisted()

    # ── Feature extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_features(ohlcv_df: pd.DataFrame) -> np.ndarray | None:
        """
        Extract a compact, stationary anomaly-detection feature vector from OHLCV.

        Features (7 dimensions, all stationary):
          0. log return
          1. high-low range / close (normalised bar range)
          2. volume z-score (rolling 20)
          3. ATR(14) / close
          4. close vs SMA20 distance
          5. squared log return (GARCH-proxy for vol clustering)
          6. close location within bar: (close-low)/(high-low)
        """
        try:
            c = ohlcv_df["close"]
            h = ohlcv_df["high"]
            lo = ohlcv_df["low"]
            v = ohlcv_df.get("volume", pd.Series(np.ones(len(c)), index=c.index))

            log_ret = np.log(c / c.shift(1)).fillna(0)
            hl_range = ((h - lo) / c.replace(0, np.nan)).fillna(0)
            vol_mean = v.rolling(20).mean()
            vol_std = v.rolling(20).std().replace(0, np.nan)
            vol_z = ((v - vol_mean) / vol_std).fillna(0)
            atr14 = ((h - lo).rolling(14).mean() / c.replace(0, np.nan)).fillna(0)
            sma20_dist = ((c - c.rolling(20).mean()) / c.replace(0, np.nan)).fillna(0)
            sq_ret = log_ret**2
            close_loc = ((c - lo) / (h - lo).replace(0, np.nan)).fillna(0.5)

            feat = np.column_stack(
                [
                    log_ret.values,
                    hl_range.values,
                    vol_z.values,
                    atr14.values,
                    sma20_dist.values,
                    sq_ret.values,
                    close_loc.values,
                ]
            )
            return np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
        except Exception:
            return None

    # ── Update + score ────────────────────────────────────────────────────────

    def update_and_score(self, ohlcv_df: pd.DataFrame) -> float:
        """
        Ingest new OHLCV bars, refit if due, and return the anomaly weight
        for the most recent bar.

        Returns
        -------
        weight : float in [down_weight_factor, 1.0]
            1.0  = normal bar (no down-weighting)
            down_weight_factor = anomalous bar (default 0.5)
        """
        feat = self._extract_features(ohlcv_df)
        if feat is None or len(feat) == 0:
            return 1.0

        with self._lock:
            # Append latest row to rolling buffer
            self._buffer.append(feat[-1].copy())
            if len(self._buffer) > self.window_size:
                self._buffer = self._buffer[-self.window_size :]

            self._bars_since_refit += 1

            # Refit when due or on first call with enough data
            if (not self._fitted or self._bars_since_refit >= self.refit_every) and len(
                self._buffer
            ) >= self.MIN_FIT_BARS:
                self._refit()

            if self._weighter is None or not self._weighter._fitted:
                return 1.0

            # Score the latest bar
            try:
                latest = feat[-1:].reshape(1, -1)
                score = float(self._weighter.decision_scores(latest)[0])
                self._total_scored += 1

                if score < self.anomaly_threshold:
                    self._anomaly_count += 1
                    logger.debug(
                        "Anomaly detected: score=%.4f (threshold=%.4f) → down-weight %.0f%% [%d/%d total]",
                        score,
                        self.anomaly_threshold,
                        (1 - self.down_weight_factor) * 100,
                        self._anomaly_count,
                        self._total_scored,
                    )
                    return self.down_weight_factor
                return 1.0
            except Exception as exc:
                logger.debug("AnomalyWeightStore.score failed: %s", exc)
                return 1.0

    def _refit(self) -> None:
        """Refit the IF+LOF ensemble on the current buffer (called under lock)."""
        try:
            X = np.array(self._buffer)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            weighter = AnomalyWeighter(
                contamination=self._contamination,
                n_estimators=100,
                use_lof=self.use_lof and len(X) >= 100,  # LOF needs enough neighbours
                lof_neighbors=min(20, len(X) // 5),
            )
            weighter.fit(X)
            self._weighter = weighter
            self._fitted = True
            self._bars_since_refit = 0
            logger.debug(
                "AnomalyWeightStore: refitted on %d bars (LOF=%s)",
                len(X),
                self.use_lof and len(X) >= 100,
            )
            # Persist after successful refit
            if self.persist_path:
                self._save_persisted()
        except Exception as exc:
            logger.warning("AnomalyWeightStore refit failed: %s", exc)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_persisted(self) -> None:
        """Save the fitted weighter to disk for warm-start on restart."""
        if self.persist_path is None or self._weighter is None:
            return
        try:
            self._weighter.save(self.persist_path)
        except Exception as exc:
            logger.debug("AnomalyWeightStore persist save failed: %s", exc)

    def _load_persisted(self) -> None:
        """Load a previously saved weighter from disk."""
        if self.persist_path is None:
            return
        try:
            self._weighter = AnomalyWeighter.load(self.persist_path)
            self._fitted = True
            logger.info("AnomalyWeightStore: warm-started from %s", self.persist_path)
        except Exception as exc:
            logger.debug("AnomalyWeightStore warm-start failed: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    @property
    def anomaly_rate(self) -> float:
        """Fraction of scored bars flagged as anomalous."""
        if self._total_scored == 0:
            return 0.0
        return self._anomaly_count / self._total_scored

    def status(self) -> dict:
        """Return a status dict for health-check endpoints."""
        return {
            "fitted": self._fitted,
            "buffer_size": len(self._buffer),
            "bars_since_refit": self._bars_since_refit,
            "anomaly_count": self._anomaly_count,
            "total_scored": self._total_scored,
            "anomaly_rate": round(self.anomaly_rate, 4),
            "use_lof": self.use_lof,
            "down_weight_factor": self.down_weight_factor,
        }
