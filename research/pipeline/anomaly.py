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
