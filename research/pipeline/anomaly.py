"""
research/pipeline/anomaly.py
==============================
Anomaly detection layer using Isolation Forest.

Role in the pipeline
--------------------
Anomalous bars (flash crashes, data errors, extreme vol spikes, circuit-breaker
halts) are harmful training examples: the model memorises them as signal when
they are actually noise.  This module:

1. Fits an IsolationForest on the training feature matrix.
2. Scores every bar with an anomaly score in [-1, 0] (more negative = more anomalous).
3. Converts scores to sample weights in (0, 1] so anomalous bars contribute
   less to the loss — they are not discarded, just down-weighted.
4. Optionally flags bars as `is_anomaly` (boolean) for inspection / filtering.

The weight function is:
    w = sigmoid(k * (score - threshold))
where k controls sharpness and threshold is the decision boundary.
This gives a smooth, differentiable weight rather than a hard 0/1 mask.

Usage
-----
    from research.pipeline.anomaly import AnomalyWeighter

    aw = AnomalyWeighter(contamination=0.02)
    aw.fit(X_train)
    weights = aw.sample_weights(X_train)   # pass to model.fit(..., sample_weight=weights)
    flags   = aw.flag(X_test)              # boolean Series
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


def _sigmoid(x: np.ndarray, k: float = 5.0) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-k * x))


class AnomalyWeighter:
    """
    Isolation Forest anomaly scorer → smooth sample weights.

    Parameters
    ----------
    contamination : Expected fraction of anomalies in training data.
                    0.01–0.05 is typical for financial data.
    n_estimators  : Number of isolation trees.
    sharpness     : Sigmoid sharpness k — higher = harder boundary.
    random_state  : Reproducibility seed.
    """

    def __init__(
        self,
        contamination: float = 0.02,
        n_estimators: int = 200,
        sharpness: float = 8.0,
        random_state: int = 42,
    ):
        self.contamination = contamination
        self.sharpness = sharpness
        self._scaler = StandardScaler()
        self._iso = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            max_samples="auto",
            random_state=random_state,
            n_jobs=-1,
        )
        self._threshold: float = 0.0   # decision_function threshold (≈0 for IF)
        self._fitted = False

    # ── Fit ───────────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame | np.ndarray) -> "AnomalyWeighter":
        """
        Fit the Isolation Forest on the training feature matrix.

        Parameters
        ----------
        X : (n_samples, n_features) — should be the training split only.
        """
        arr = X.values if isinstance(X, pd.DataFrame) else X
        arr = self._scaler.fit_transform(arr)
        self._iso.fit(arr)
        # decision_function returns positive for inliers, negative for outliers
        scores = self._iso.decision_function(arr)
        # Set threshold at the contamination quantile
        self._threshold = float(np.quantile(scores, self.contamination))
        self._fitted = True
        n_anomalies = int((scores < self._threshold).sum())
        logger.info(
            "AnomalyWeighter fitted: %d/%d bars flagged (%.1f%%)",
            n_anomalies, len(arr), 100 * n_anomalies / len(arr),
        )
        return self

    # ── Score ─────────────────────────────────────────────────────────────────

    def decision_scores(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Raw Isolation Forest decision scores.
        Positive = inlier, negative = outlier.
        """
        self._check_fitted()
        arr = X.values if isinstance(X, pd.DataFrame) else X
        arr = self._scaler.transform(arr)
        return self._iso.decision_function(arr)

    # ── Weights ───────────────────────────────────────────────────────────────

    def sample_weights(
        self,
        X: pd.DataFrame | np.ndarray,
        min_weight: float = 0.05,
    ) -> np.ndarray:
        """
        Convert anomaly scores to sample weights in [min_weight, 1.0].

        Normal bars → weight ≈ 1.0
        Anomalous bars → weight → min_weight

        Parameters
        ----------
        X          : Feature matrix (any split).
        min_weight : Floor weight for the most anomalous bars.
                     Set to 0.0 to fully exclude anomalies.
        """
        scores = self.decision_scores(X)
        # Centre on threshold so inliers → positive, outliers → negative
        centred = scores - self._threshold
        weights = _sigmoid(centred, k=self.sharpness)
        # Rescale to [min_weight, 1.0]
        weights = min_weight + (1.0 - min_weight) * weights
        return weights.astype(np.float32)

    # ── Flag ──────────────────────────────────────────────────────────────────

    def flag(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Boolean array: True = anomalous bar.
        Uses the contamination quantile as the decision boundary.
        """
        scores = self.decision_scores(X)
        return scores < self._threshold

    def annotate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add `anomaly_score` and `is_anomaly` columns to a DataFrame in-place.
        """
        scores = self.decision_scores(df)
        df = df.copy()
        df["anomaly_score"] = scores
        df["is_anomaly"] = scores < self._threshold
        return df

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        import pickle
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)
        logger.info("AnomalyWeighter saved → %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "AnomalyWeighter":
        import pickle
        with open(path, "rb") as f:
            obj = pickle.load(f)
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

    Maintains a rolling window of recent OHLCV bars, fits an IsolationForest
    on that window, and scores each new bar.  When the anomaly score exceeds
    `anomaly_threshold` (default 0.7 on a 0–1 normalised scale), the ML
    probability is down-weighted by `down_weight_factor` (default 0.5).

    The IF score from sklearn's decision_function() is in (-inf, +inf) with
    positive = inlier.  We normalise to [0, 1] where 1 = most anomalous.

    Parameters
    ----------
    window_size       : Number of recent bars used to fit the IF model.
    refit_every       : Refit the IF every N new bars (amortises cost).
    contamination     : Expected anomaly fraction (passed to IsolationForest).
    anomaly_threshold : Normalised score above which a bar is considered anomalous.
    down_weight_factor: Multiplier applied to ML probability on anomalous bars.
    """

    def __init__(
        self,
        window_size: int = 500,
        refit_every: int = 50,
        contamination: float = 0.02,
        anomaly_threshold: float = 0.7,
        down_weight_factor: float = 0.5,
    ) -> None:
        self.window_size = window_size
        self.refit_every = refit_every
        self.anomaly_threshold = anomaly_threshold
        self.down_weight_factor = down_weight_factor
        self._weighter: Optional[AnomalyWeighter] = None
        self._buffer: list = []
        self._bars_since_refit: int = 0
        self._contamination = contamination
        self._fitted = False

    # ── Feature extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_features(ohlcv_df: pd.DataFrame) -> Optional[np.ndarray]:
        """
        Extract a compact anomaly-detection feature vector from OHLCV.

        Features (all stationary):
          - log return
          - high-low range / close (normalised range)
          - volume z-score (rolling 20)
          - ATR(14) / close
          - close vs SMA20 distance
        """
        try:
            c = ohlcv_df["close"]
            h = ohlcv_df["high"]
            lo = ohlcv_df["low"]
            v = ohlcv_df.get("volume", pd.Series(np.ones(len(c)), index=c.index))

            log_ret   = np.log(c / c.shift(1)).fillna(0)
            hl_range  = ((h - lo) / c.replace(0, np.nan)).fillna(0)
            vol_z     = ((v - v.rolling(20).mean()) / v.rolling(20).std().replace(0, np.nan)).fillna(0)
            atr14     = (h - lo).rolling(14).mean() / c.replace(0, np.nan)
            atr14     = atr14.fillna(0)
            sma20_dist = (c - c.rolling(20).mean()) / c.replace(0, np.nan)
            sma20_dist = sma20_dist.fillna(0)

            feat = np.column_stack([
                log_ret.values,
                hl_range.values,
                vol_z.values,
                atr14.values,
                sma20_dist.values,
            ])
            return feat
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
            0.5  = anomalous bar (default down_weight_factor)
        """
        feat = self._extract_features(ohlcv_df)
        if feat is None or len(feat) == 0:
            return 1.0

        # Add latest row to buffer
        self._buffer.append(feat[-1])
        if len(self._buffer) > self.window_size:
            self._buffer = self._buffer[-self.window_size:]

        self._bars_since_refit += 1

        # Refit when due or on first call
        if not self._fitted or self._bars_since_refit >= self.refit_every:
            self._refit()

        if self._weighter is None or not self._weighter._fitted:
            return 1.0

        # Score the latest bar
        try:
            latest = feat[-1:].reshape(1, -1)
            scores = self._weighter.decision_scores(latest)
            # Normalise: decision_function returns positive for inliers.
            # We invert and normalise to [0, 1] where 1 = most anomalous.
            raw = float(scores[0])
            # Typical range is roughly [-0.5, 0.5]; clip and normalise
            normalised = float(np.clip((-raw + 0.5) / 1.0, 0.0, 1.0))

            if normalised >= self.anomaly_threshold:
                logger.debug(
                    "Anomaly detected: score=%.3f (normalised=%.3f) → down-weight %.0f%%",
                    raw, normalised, (1 - self.down_weight_factor) * 100,
                )
                return self.down_weight_factor
            return 1.0
        except Exception as exc:
            logger.debug("AnomalyWeightStore.score failed: %s", exc)
            return 1.0

    def _refit(self) -> None:
        """Refit the IsolationForest on the current buffer."""
        if len(self._buffer) < 50:
            return
        try:
            X = np.array(self._buffer)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            self._weighter = AnomalyWeighter(
                contamination=self._contamination,
                n_estimators=100,
            )
            self._weighter.fit(X)
            self._fitted = True
            self._bars_since_refit = 0
            logger.debug("AnomalyWeightStore: refitted on %d bars", len(X))
        except Exception as exc:
            logger.warning("AnomalyWeightStore refit failed: %s", exc)
