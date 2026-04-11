"""
ml/drift_monitor.py

Production-grade feature drift monitor using PSI and KS-test.

Replaces the simple z-score check in ml/inference_engine.py with a
two-layer statistical framework:

  Layer 1 — z-score (fast, per-feature, O(n_features)):
      Already implemented in inference_engine.py.

  Layer 2 — PSI + KS-test (rigorous, per-feature, per drift window):
      This module.  Called by the scheduled drift report endpoint and
      by the ML retraining CI to gate model promotion.

Drift thresholds (industry standard):
    PSI < 0.10   → No significant drift (green)
    PSI 0.10–0.25 → Moderate drift — investigate (yellow)
    PSI > 0.25   → Significant drift — retrain (red)

    KS p-value < 0.05 → Distributions significantly different (red)

Usage:
    from ml.drift_monitor import DriftMonitor, DriftReport

    monitor = DriftMonitor.from_feature_stats(stats_path)
    report  = monitor.compute(live_df)         # DriftReport
    if report.requires_retrain:
        trigger_retrain()

API endpoint: GET /api/ml/drift-report
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# PSI thresholds
_PSI_YELLOW = 0.10
_PSI_RED = 0.25
# KS p-value threshold
_KS_P_THRESHOLD = 0.05
# Minimum live samples needed for a meaningful drift check
_MIN_SAMPLES = 50
# Default number of bins for PSI calculation
_PSI_BINS = 10


# ── PSI computation ───────────────────────────────────────────────────────────


def _psi(
    expected: np.ndarray,
    actual: np.ndarray,
    n_bins: int = _PSI_BINS,
) -> float:
    """
    Population Stability Index between two 1-D arrays.

    PSI = Σ (actual% − expected%) × ln(actual% / expected%)

    Bins are determined from the expected (training) distribution.
    """
    if len(expected) < 2 or len(actual) < 2:
        return 0.0

    # Build bin edges from training distribution
    percentiles = np.linspace(0, 100, n_bins + 1)
    bin_edges = np.percentile(expected, percentiles)
    # Ensure strictly increasing edges (deduplicate)
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) < 2:
        return 0.0

    # Bin counts + proportions (add epsilon to avoid log(0))
    eps = 1e-9
    expected_hist, _ = np.histogram(expected, bins=bin_edges)
    actual_hist, _ = np.histogram(actual, bins=bin_edges)

    expected_pct = (expected_hist / len(expected)).clip(min=eps)
    actual_pct = (actual_hist / len(actual)).clip(min=eps)

    psi_value = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))
    return round(psi_value, 6)


def _ks_pvalue(reference: np.ndarray, live: np.ndarray) -> float:
    """
    Two-sample Kolmogorov-Smirnov test p-value.

    p-value < 0.05 → distributions are significantly different.
    Returns 1.0 when scipy is unavailable (conservative: no alarm).
    """
    try:
        from scipy.stats import ks_2samp  # type: ignore[import]

        _, p = ks_2samp(reference, live)
        return float(p)
    except Exception:
        return 1.0


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class FeatureDrift:
    """Drift statistics for a single feature."""

    feature: str
    psi: float
    ks_pvalue: float
    z_score: float
    train_mean: float
    train_std: float
    live_mean: float
    live_std: float

    @property
    def psi_level(self) -> str:
        """Return 'green', 'yellow', or 'red'."""
        if self.psi < _PSI_YELLOW:
            return "green"
        if self.psi < _PSI_RED:
            return "yellow"
        return "red"

    @property
    def ks_alarm(self) -> bool:
        """True when distributions are statistically different (p < 0.05)."""
        return self.ks_pvalue < _KS_P_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "psi": self.psi,
            "psi_level": self.psi_level,
            "ks_pvalue": round(self.ks_pvalue, 4),
            "ks_alarm": self.ks_alarm,
            "z_score": round(self.z_score, 3),
            "train_mean": round(self.train_mean, 6),
            "train_std": round(self.train_std, 6),
            "live_mean": round(self.live_mean, 6),
            "live_std": round(self.live_std, 6),
        }


@dataclass
class DriftReport:
    """Aggregate drift report across all features."""

    n_features_checked: int
    n_green: int
    n_yellow: int
    n_red: int
    n_ks_alarm: int
    max_psi: float
    max_psi_feature: str
    requires_retrain: bool
    live_samples: int
    features: list[FeatureDrift] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        if self.n_red > 0 or self.n_ks_alarm > 2:
            return "red"
        if self.n_yellow > 0 or self.n_ks_alarm > 0:
            return "yellow"
        return "green"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "requires_retrain": self.requires_retrain,
            "live_samples": self.live_samples,
            "n_features_checked": self.n_features_checked,
            "n_green": self.n_green,
            "n_yellow": self.n_yellow,
            "n_red": self.n_red,
            "n_ks_alarm": self.n_ks_alarm,
            "max_psi": round(self.max_psi, 6),
            "max_psi_feature": self.max_psi_feature,
            "features": [f.to_dict() for f in sorted(self.features, key=lambda x: -x.psi)[:20]],
        }


# ── Monitor class ─────────────────────────────────────────────────────────────


class DriftMonitor:
    """
    Statistical feature drift monitor.

    Stores training distribution statistics (mean, std, percentile bins)
    and computes PSI + KS-test against a live feature window.
    """

    def __init__(self, train_stats: dict[str, dict[str, Any]]) -> None:
        """
        Args:
            train_stats: dict mapping feature_name → {"mean": float, "std": float,
                         "percentiles": list[float]}.  Same format as
                         ml/saved_models/feature_stats.json.
        """
        self._stats: dict[str, dict[str, Any]] = train_stats

    @classmethod
    def from_reference_arrays(
        cls,
        reference_data: dict[str, np.ndarray],
        n_bins: int = _PSI_BINS,
    ) -> DriftMonitor:
        """
        Build a DriftMonitor directly from reference numpy arrays.

        Args:
            reference_data: dict mapping feature_name → 1-D numpy array of
                            training values.
            n_bins: Number of percentile bins for PSI computation.

        Returns:
            DriftMonitor instance ready to call compute().
        """
        train_stats: dict[str, dict[str, Any]] = {}
        for feat, raw_arr in reference_data.items():
            arr = np.asarray(raw_arr, dtype=float)
            if arr.size == 0:
                continue
            percentiles = np.linspace(0, 100, n_bins + 1)
            bins = np.percentile(arr, percentiles).tolist()
            train_stats[feat] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "percentiles": bins,
                "reference": arr.tolist(),
            }
        return cls(train_stats)

    # ── Construction helpers ──────────────────────────────────────────────────

    @classmethod
    def from_feature_stats(
        cls,
        stats_path: str | Path | None = None,
    ) -> DriftMonitor:
        """
        Build a DriftMonitor from the feature_stats.json artefact that the
        ML retraining pipeline produces.

        Args:
            stats_path: Path to feature_stats.json.  Defaults to
                        ml/saved_models/feature_stats.json.

        Returns:
            DriftMonitor instance.  Returns an empty monitor (no alarms
            possible) if the file is not found.
        """
        if stats_path is None:
            stats_path = Path(__file__).parent / "saved_models" / "feature_stats.json"
        stats_path = Path(stats_path)

        if not stats_path.exists():
            logger.warning("DriftMonitor: feature_stats.json not found at %s — drift checks disabled", stats_path)
            return cls({})

        try:
            with stats_path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
            logger.info("DriftMonitor: loaded stats for %d features from %s", len(raw), stats_path)
            return cls(raw)
        except Exception as exc:
            logger.error("DriftMonitor: failed to load feature_stats.json: %s", exc)
            return cls({})

    # ── Main compute ─────────────────────────────────────────────────────────

    def compute(self, live_features: Any) -> DriftReport:
        """
        Compute drift report from a live feature window.

        Args:
            live_features: pandas DataFrame (rows = recent ticks, cols = features)
                           or numpy ndarray of shape (n_samples, n_features) with
                           a `columns` attribute.

        Returns:
            DriftReport with per-feature and aggregate statistics.
        """
        try:
            import pandas as pd

            live_df = live_features if isinstance(live_features, pd.DataFrame) else pd.DataFrame(live_features)
        except ImportError:
            return _empty_report(0)

        n_samples = len(live_df)
        if n_samples < _MIN_SAMPLES:
            logger.debug("DriftMonitor: only %d samples — need %d for drift check", n_samples, _MIN_SAMPLES)
            return _empty_report(n_samples)

        if not self._stats:
            return _empty_report(n_samples)

        feature_drifts: list[FeatureDrift] = []

        for feat_name in live_df.columns:
            if feat_name not in self._stats:
                continue
            feat_stats = self._stats[feat_name]
            train_mean = float(feat_stats.get("mean", 0.0))
            train_std = float(feat_stats.get("std", 1.0))

            live_vals = live_df[feat_name].dropna().values.astype(float)
            if len(live_vals) < 2:
                continue

            live_mean = float(live_vals.mean())
            live_std = float(live_vals.std())

            # z-score on the window mean
            z = abs(live_mean - train_mean) / max(train_std, 1e-9)

            # Build reference samples from training stats (use percentiles if available)
            percentile_bins = feat_stats.get("percentiles")
            if percentile_bins and len(percentile_bins) >= 10:
                reference = np.array(percentile_bins, dtype=float)
            else:
                # Fallback: reconstruct approximate training distribution from mean/std.
                # NOTE: This assumes a Gaussian distribution — it may under/over-estimate
                # PSI for skewed or heavy-tailed features (e.g. volume, spread).
                # Run ml/train_advanced.py to generate feature_stats.json with actual
                # percentiles and eliminate this approximation.
                logger.debug(
                    "DriftMonitor: no percentiles for feature '%s' — using Gaussian fallback "
                    "(assumption may not hold for non-normal features).",
                    feat_name,
                )
                rng = np.random.default_rng(seed=42)
                reference = rng.normal(loc=train_mean, scale=max(train_std, 1e-9), size=max(n_samples, 100))

            psi_val = _psi(reference, live_vals)
            ks_p = _ks_pvalue(reference, live_vals)

            feature_drifts.append(
                FeatureDrift(
                    feature=feat_name,
                    psi=psi_val,
                    ks_pvalue=ks_p,
                    z_score=round(z, 3),
                    train_mean=train_mean,
                    train_std=train_std,
                    live_mean=live_mean,
                    live_std=live_std,
                )
            )

        n_green = sum(1 for f in feature_drifts if f.psi_level == "green")
        n_yellow = sum(1 for f in feature_drifts if f.psi_level == "yellow")
        n_red = sum(1 for f in feature_drifts if f.psi_level == "red")
        n_ks = sum(1 for f in feature_drifts if f.ks_alarm)

        requires_retrain = n_red > 0 or n_ks > len(feature_drifts) * 0.10

        max_psi_feat = max(feature_drifts, key=lambda f: f.psi, default=None)

        report = DriftReport(
            n_features_checked=len(feature_drifts),
            n_green=n_green,
            n_yellow=n_yellow,
            n_red=n_red,
            n_ks_alarm=n_ks,
            max_psi=max_psi_feat.psi if max_psi_feat else 0.0,
            max_psi_feature=max_psi_feat.feature if max_psi_feat else "",
            requires_retrain=requires_retrain,
            live_samples=n_samples,
            features=feature_drifts,
        )

        if requires_retrain:
            logger.warning(
                "DriftMonitor: RETRAIN RECOMMENDED — %d red features (PSI>%.2f), "
                "%d KS alarms.  max_psi=%.3f on feature '%s'",
                n_red,
                _PSI_RED,
                n_ks,
                report.max_psi,
                report.max_psi_feature,
            )
        elif n_yellow > 0:
            logger.info(
                "DriftMonitor: %d yellow features (PSI %.2f–%.2f).  Monitor closely.",
                n_yellow,
                _PSI_YELLOW,
                _PSI_RED,
            )

        return report


def _empty_report(n_samples: int) -> DriftReport:
    return DriftReport(
        n_features_checked=0,
        n_green=0,
        n_yellow=0,
        n_red=0,
        n_ks_alarm=0,
        max_psi=0.0,
        max_psi_feature="",
        requires_retrain=False,
        live_samples=n_samples,
        features=[],
    )


# ── Singleton accessor ────────────────────────────────────────────────────────

_monitor: DriftMonitor | None = None


def get_drift_monitor(
    stats_path: str | Path | None = None,
    force_reload: bool = False,
) -> DriftMonitor:
    """
    Return the process-level DriftMonitor singleton.

    Thread-safe (reads are safe; first-time construction done once at startup).
    Pass force_reload=True after a model retrain to reload stats.
    """
    global _monitor
    if _monitor is None or force_reload:
        _monitor = DriftMonitor.from_feature_stats(stats_path)
    return _monitor
