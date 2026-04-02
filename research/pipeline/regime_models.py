# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/regime_models.py
=====================================
Regime-conditional model routing.

Concept
-------
A single model trained on all regimes must learn contradictory patterns:
  - In low-vol trending markets, momentum features dominate.
  - In high-vol crash regimes, mean-reversion and safe-haven flows dominate.
  - In range-bound markets, oscillators (RSI, Stochastic) are most predictive.

Training one model per regime and routing inference through the detected regime
lets each specialist focus on the patterns that matter in its context.

Architecture
------------
1. RegimeClassifier  — lightweight 3-class classifier (low/medium/high vol)
                       trained on the feature matrix.  Uses the existing
                       ml/regime.py HMM as a prior; falls back to vol-quantile
                       bucketing if hmmlearn is unavailable.

2. RegimeRouter      — dict of {regime_id → EnsemblePredictor}.
                       At train time: splits data by regime, trains one model
                       per regime.
                       At infer time: classifies the current bar's regime,
                       routes to the matching specialist, returns its probability.

3. Soft routing      — instead of hard switching, blends specialist predictions
                       weighted by the regime posterior probabilities.  This
                       prevents cliff-edges at regime boundaries.

Usage
-----
    from research.pipeline.regime_models import RegimeRouter

    router = RegimeRouter(n_regimes=3)
    router.fit(X_train, y_train)
    probs = router.predict_proba(X_test)   # soft-routed ensemble output
"""

from __future__ import annotations

import logging
import pickle  # nosec B403 - joblib tried first; pickle only for legacy fallback
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

try:
    from research.pipeline.models_ensemble import EnsemblePredictor  # noqa: F401

    ENSEMBLE_AVAILABLE = True
except ImportError:
    ENSEMBLE_AVAILABLE = False

try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Regime classifier
# ─────────────────────────────────────────────────────────────────────────────


class RegimeClassifier:
    """
    Classifies each bar into one of n_regimes volatility/trend regimes.

    Primary method: quantile-based vol bucketing (always available).
    Optional upgrade: HMM posterior probabilities (requires hmmlearn).

    The classifier outputs:
      - hard labels  : argmax regime per bar
      - soft weights : posterior probability vector per bar (for soft routing)
    """

    def __init__(self, n_regimes: int = 3, use_hmm: bool = True):
        self.n_regimes = n_regimes
        self.use_hmm = use_hmm and HMM_AVAILABLE
        self._scaler = StandardScaler()
        self._hmm: GaussianHMM | None = None
        self._vol_quantiles: np.ndarray | None = None
        self._fitted = False

    # ── Feature extraction for regime classification ───────────────────────

    @staticmethod
    def _regime_features(X: pd.DataFrame) -> np.ndarray:
        """
        Extract a compact feature set for regime classification.
        Uses volatility, momentum, and trend columns if present;
        falls back to computing them from close price.
        """
        cols = []
        for col in [
            "realvol_20",
            "realvol_5",
            "vol_ratio_5_20",
            "ret_20",
            "ret_5",
            "rsi_14",
            "bb_width",
            "atr_pct",
            "roll_std_20",
        ]:
            if col in X.columns:
                cols.append(col)

        # Minimal fallback: use first 5 numeric columns when no cols specified
        arr = X[cols].fillna(0).values if cols else X.select_dtypes(include=[np.number]).fillna(0).values[:, :5]

        return arr.astype(np.float32)

    # ── Fit ───────────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame) -> RegimeClassifier:
        feats = self._regime_features(X)
        feats_sc = self._scaler.fit_transform(feats)

        if self.use_hmm:
            try:
                self._hmm = GaussianHMM(
                    n_components=self.n_regimes,
                    covariance_type="diag",
                    n_iter=100,
                    random_state=42,
                )
                self._hmm.fit(feats_sc)
                logger.info("RegimeClassifier: HMM fitted (%d regimes)", self.n_regimes)
            except Exception as exc:
                logger.warning("HMM fit failed (%s) — falling back to vol quantiles", exc)
                self._hmm = None
                self.use_hmm = False

        if not self.use_hmm:
            # Fallback: quantile-based on first feature (realvol or similar)
            self._vol_quantiles = np.quantile(
                feats_sc[:, 0],
                np.linspace(0, 1, self.n_regimes + 1)[1:-1],
            )
            logger.info("RegimeClassifier: vol-quantile bucketing (%d regimes)", self.n_regimes)

        self._fitted = True
        return self

    # ── Predict ───────────────────────────────────────────────────────────────

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Hard regime labels, shape (n_samples,)."""
        return self.predict_proba(X).argmax(axis=1)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Soft regime posteriors, shape (n_samples, n_regimes).
        Rows sum to 1.
        """
        if not self._fitted:
            raise RuntimeError("Call fit() first")

        feats = self._regime_features(X)
        feats_sc = self._scaler.transform(feats)

        if self.use_hmm and self._hmm is not None:
            try:
                posteriors = self._hmm.predict_proba(feats_sc)
                return posteriors.astype(np.float32)
            except Exception as exc:
                logger.warning("HMM predict_proba failed: %s", exc)

        # Fallback: soft assignment via distance to quantile boundaries
        v = feats_sc[:, 0]
        boundaries = np.concatenate([[-np.inf], self._vol_quantiles, [np.inf]])
        probs = np.zeros((len(v), self.n_regimes), dtype=np.float32)
        for i in range(self.n_regimes):
            in_bin = (v >= boundaries[i]) & (v < boundaries[i + 1])
            probs[in_bin, i] = 1.0
        # Smooth with a small epsilon to avoid hard zeros
        probs = probs * 0.9 + 0.1 / self.n_regimes
        probs /= probs.sum(axis=1, keepdims=True)
        return probs


# ─────────────────────────────────────────────────────────────────────────────
# Per-regime specialist model
# ─────────────────────────────────────────────────────────────────────────────


class _RegimeSpecialist:
    """
    Lightweight gradient-boosted classifier for a single regime.
    Uses GradientBoostingClassifier (sklearn) — no xgboost dependency.
    Swapped for EnsemblePredictor if available.
    """

    # Minimum samples needed to train a specialist reliably
    _MIN_SAMPLES = 80

    def __init__(self, regime_id: int, n_estimators: int = 200):
        self.regime_id = regime_id
        self._is_ensemble = False
        self._model = GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )
        self._fitted = False

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> _RegimeSpecialist:
        if len(np.unique(y)) < 2:  # noqa: PLR2004
            logger.warning("Regime %d: only one class — skipping", self.regime_id)
            return self
        if len(y) < self._MIN_SAMPLES:
            logger.warning(
                "Regime %d: only %d samples (< %d) — skipping specialist",
                self.regime_id,
                len(y),
                self._MIN_SAMPLES,
            )
            return self
        self._model.fit(X.values, y)
        self._fitted = True
        logger.info("Regime %d specialist fitted on %d samples", self.regime_id, len(y))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            return np.full(len(X), 0.5, dtype=np.float32)
        return self._model.predict_proba(X.values)[:, 1]


# ─────────────────────────────────────────────────────────────────────────────
# Regime router
# ─────────────────────────────────────────────────────────────────────────────


class RegimeRouter:
    """
    Train one specialist model per regime; route inference via soft regime weights.

    Parameters
    ----------
    n_regimes        : Number of volatility regimes (default 3)
    min_regime_frac  : Minimum fraction of training data a regime must have
                       to train a specialist (regimes below this use the
                       global fallback model)
    soft_routing     : If True, blend specialist outputs weighted by regime
                       posteriors.  If False, use hard argmax routing.
    """

    def __init__(
        self,
        n_regimes: int = 3,
        min_regime_frac: float = 0.05,
        soft_routing: bool = True,
    ):
        self.n_regimes = n_regimes
        self.min_regime_frac = min_regime_frac
        self.soft_routing = soft_routing

        self.regime_clf = RegimeClassifier(n_regimes=n_regimes)
        self.specialists: dict[int, _RegimeSpecialist] = {}
        self._fallback: _RegimeSpecialist | None = None
        self._fitted = False

    # ── Fit ───────────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> RegimeRouter:
        """
        1. Fit the regime classifier.
        2. Split training data by regime.
        3. Train one specialist per regime (skip if too few samples).
        4. Train a global fallback on all data.
        """
        # Fit regime classifier
        self.regime_clf.fit(X)
        hard_labels = self.regime_clf.predict(X)

        # Global fallback
        self._fallback = _RegimeSpecialist(regime_id=-1)
        self._fallback.fit(X, y)

        # Per-regime specialists
        n_total = len(y)
        for r in range(self.n_regimes):
            mask = hard_labels == r
            frac = mask.sum() / n_total
            if frac < self.min_regime_frac:
                logger.info(
                    "Regime %d: %.1f%% of data — below threshold, using fallback",
                    r,
                    100 * frac,
                )
                continue
            spec = _RegimeSpecialist(regime_id=r)
            spec.fit(X[mask], y[mask])
            self.specialists[r] = spec

        logger.info(
            "RegimeRouter fitted: %d/%d specialists trained",
            len(self.specialists),
            self.n_regimes,
        )
        self._fitted = True
        return self

    # ── Predict ───────────────────────────────────────────────────────────────

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Soft-routed prediction probabilities.

        For each bar:
          final_prob = Σ_r  posterior(r) * specialist_r.predict_proba(bar)
        """
        if not self._fitted:
            raise RuntimeError("Call fit() first")

        regime_posteriors = self.regime_clf.predict_proba(X)  # (N, n_regimes)

        if self.soft_routing:
            # Collect specialist predictions for each regime
            spec_probs = np.zeros((len(X), self.n_regimes), dtype=np.float32)
            for r in range(self.n_regimes):
                if r in self.specialists:
                    spec_probs[:, r] = self.specialists[r].predict_proba(X)
                else:
                    spec_probs[:, r] = self._fallback.predict_proba(X)

            # Weighted blend
            final = (regime_posteriors * spec_probs).sum(axis=1)
        else:
            # Hard routing: use argmax regime
            hard = regime_posteriors.argmax(axis=1)
            final = np.zeros(len(X), dtype=np.float32)
            for r in range(self.n_regimes):
                mask = hard == r
                if mask.any():
                    model = self.specialists.get(r, self._fallback)
                    final[mask] = model.predict_proba(X[mask])

        return final.astype(np.float32)

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)

    def regime_breakdown(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Return a DataFrame showing regime distribution and specialist confidence.
        Useful for monitoring regime shifts in live data.
        """
        posteriors = self.regime_clf.predict_proba(X)
        hard = posteriors.argmax(axis=1)
        df = pd.DataFrame(
            posteriors,
            columns=[f"regime_{r}_prob" for r in range(self.n_regimes)],
            index=X.index if hasattr(X, "index") else None,
        )
        df["dominant_regime"] = hard
        df["regime_confidence"] = posteriors.max(axis=1)
        return df

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path, compress=3)
        logger.info("RegimeRouter saved → %s", path)

    @classmethod
    def load(cls, path: str | Path) -> RegimeRouter:
        try:
            obj = joblib.load(path)  # nosec B301 - path set by class constructor from saved_models
        except Exception:
            with open(path, "rb") as f:
                obj = pickle.load(f)  # nosec B301 - joblib failed; legacy pickle fallback
        logger.info("RegimeRouter loaded ← %s", path)
        return obj
