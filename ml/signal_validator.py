# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/signal_validator.py
======================
Signal distribution validation — checks that live signal distribution
matches the out-of-sample (OOS) backtest distribution.

Why this matters
----------------
A model that was profitable in OOS backtesting may degrade in live trading
if the live signal distribution drifts from the OOS distribution. This can
happen due to:
  - Feature drift (market regime change)
  - Data pipeline bugs (wrong normalisation, stale features)
  - Model staleness (weights not updated)
  - Overfitting to a specific regime

Checks performed
----------------
1. KS test (Kolmogorov-Smirnov): tests if two samples come from the same
   distribution. p < 0.05 → distributions differ significantly.

2. PSI (Population Stability Index): measures distribution shift.
   PSI < 0.10 → stable
   PSI 0.10–0.25 → minor shift (monitor)
   PSI > 0.25 → major shift (retrain)

3. Mean / std drift: checks if live mean and std are within 2 sigma of OOS.

4. Directional bias: checks if live BUY/SELL ratio matches OOS ratio.

5. Confidence score drift: checks if model confidence scores have shifted.

Usage
-----
    from ml.signal_validator import SignalDistributionValidator

    validator = SignalDistributionValidator()
    validator.set_oos_reference(oos_signals)   # call once after backtest
    result = validator.validate(live_signals)
    if not result.passed:
        print(result.summary)
        # trigger retraining or alert
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np
from scipy import stats as _stats

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
KS_P_THRESHOLD = 0.05  # KS test p-value below this → drift detected
PSI_WARN_THRESHOLD = 0.10  # PSI above this → warning
PSI_FAIL_THRESHOLD = 0.25  # PSI above this → fail (retrain required)
MEAN_DRIFT_SIGMA = 2.0  # mean drift beyond this many sigma → warning
MIN_SAMPLES = 30  # minimum samples for meaningful comparison


class ValidationStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class CheckResult:
    name: str
    status: ValidationStatus
    value: float
    threshold: float
    message: str


@dataclass
class ValidationReport:
    timestamp: datetime
    status: ValidationStatus
    oos_sample_size: int
    live_sample_size: int
    checks: list[CheckResult] = field(default_factory=list)
    psi: float | None = None
    ks_statistic: float | None = None
    ks_p_value: float | None = None
    mean_drift_sigma: float | None = None
    directional_bias_drift: float | None = None
    confidence_drift: float | None = None

    @property
    def passed(self) -> bool:
        return self.status == ValidationStatus.PASSED

    @property
    def summary(self) -> str:
        lines = [
            f"Signal Distribution Validation — {self.status.value.upper()}",
            f"  OOS samples: {self.oos_sample_size}  Live samples: {self.live_sample_size}",
            f"  PSI: {self.psi:.4f}" if self.psi is not None else "  PSI: —",
            f"  KS p-value: {self.ks_p_value:.4f}" if self.ks_p_value is not None else "  KS p-value: —",
            f"  Mean drift: {self.mean_drift_sigma:.2f}σ" if self.mean_drift_sigma is not None else "  Mean drift: —",
        ]
        for c in self.checks:
            icon = (
                "✓" if c.status == ValidationStatus.PASSED else ("⚠" if c.status == ValidationStatus.WARNING else "✗")
            )
            lines.append(f"  {icon} {c.name}: {c.message}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "oos_sample_size": self.oos_sample_size,
            "live_sample_size": self.live_sample_size,
            "psi": self.psi,
            "ks_statistic": self.ks_statistic,
            "ks_p_value": self.ks_p_value,
            "mean_drift_sigma": self.mean_drift_sigma,
            "directional_bias_drift": self.directional_bias_drift,
            "confidence_drift": self.confidence_drift,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "value": c.value,
                    "threshold": c.threshold,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


@dataclass
class SignalRecord:
    """A single signal emitted by the model."""

    direction: str  # "BUY" | "SELL" | "HOLD"
    confidence: float  # 0.0 – 1.0
    raw_score: float  # raw model output (logit or probability)
    timestamp: datetime | None = None


class SignalDistributionValidator:
    """
    Validates that live signal distribution matches OOS backtest distribution.

    Workflow:
        1. After OOS backtest, call set_oos_reference(oos_signals)
        2. As live signals accumulate, call add_live_signal(signal)
        3. Call validate() to get a ValidationReport
        4. If status is FAILED, trigger model retraining
    """

    def __init__(
        self,
        ks_p_threshold: float = KS_P_THRESHOLD,
        psi_warn: float = PSI_WARN_THRESHOLD,
        psi_fail: float = PSI_FAIL_THRESHOLD,
        mean_drift_sigma: float = MEAN_DRIFT_SIGMA,
        min_samples: int = MIN_SAMPLES,
    ) -> None:
        self.ks_p_threshold = ks_p_threshold
        self.psi_warn = psi_warn
        self.psi_fail = psi_fail
        self.mean_drift_sigma = mean_drift_sigma
        self.min_samples = min_samples

        self._oos_signals: list[SignalRecord] = []
        self._live_signals: list[SignalRecord] = []

    # ── Reference data ────────────────────────────────────────────────────────

    def set_oos_reference(self, signals: list[SignalRecord]) -> None:
        """Set the OOS backtest signal distribution as the reference."""
        self._oos_signals = list(signals)
        logger.info(
            "OOS reference set: %d signals, mean_conf=%.3f",
            len(signals),
            float(np.mean([s.confidence for s in signals])) if signals else 0.0,
        )

    def add_live_signal(self, signal: SignalRecord) -> None:
        """Append a live signal to the accumulation buffer."""
        self._live_signals.append(signal)

    def clear_live_signals(self) -> None:
        """Reset the live signal buffer (e.g. after retraining)."""
        self._live_signals.clear()

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(
        self,
        live_signals: list[SignalRecord] | None = None,
    ) -> ValidationReport:
        """
        Run all distribution checks and return a ValidationReport.

        Args:
            live_signals: Override the accumulated live signals buffer.
                          If None, uses the internal buffer.

        Returns:
            ValidationReport with status PASSED / WARNING / FAILED / INSUFFICIENT_DATA.
        """
        live = live_signals if live_signals is not None else self._live_signals
        oos = self._oos_signals

        report = ValidationReport(
            timestamp=datetime.now(UTC),
            status=ValidationStatus.INSUFFICIENT_DATA,
            oos_sample_size=len(oos),
            live_sample_size=len(live),
        )

        if len(oos) < self.min_samples or len(live) < self.min_samples:
            report.checks.append(
                CheckResult(
                    name="sample_size",
                    status=ValidationStatus.INSUFFICIENT_DATA,
                    value=min(len(oos), len(live)),
                    threshold=self.min_samples,
                    message=(f"Insufficient samples: OOS={len(oos)}, live={len(live)}, minimum={self.min_samples}"),
                )
            )
            return report

        oos_scores = np.array([s.raw_score for s in oos], dtype=float)
        live_scores = np.array([s.raw_score for s in live], dtype=float)
        oos_conf = np.array([s.confidence for s in oos], dtype=float)
        live_conf = np.array([s.confidence for s in live], dtype=float)

        checks: list[CheckResult] = []

        # 1. KS test on raw scores
        ks_stat, ks_p = _stats.ks_2samp(oos_scores, live_scores)
        report.ks_statistic = float(ks_stat)
        report.ks_p_value = float(ks_p)
        ks_status = ValidationStatus.PASSED if ks_p >= self.ks_p_threshold else ValidationStatus.WARNING
        checks.append(
            CheckResult(
                name="ks_test",
                status=ks_status,
                value=float(ks_p),
                threshold=self.ks_p_threshold,
                message=(
                    f"KS p={ks_p:.4f} (stat={ks_stat:.4f}) — "
                    + (
                        "distributions match"
                        if ks_p >= self.ks_p_threshold
                        else f"distributions differ (p < {self.ks_p_threshold})"
                    )
                ),
            )
        )

        # 2. PSI on raw scores
        psi = _compute_psi(oos_scores, live_scores)
        report.psi = float(psi)
        if psi < self.psi_warn:
            psi_status = ValidationStatus.PASSED
            psi_msg = f"PSI={psi:.4f} — stable"
        elif psi < self.psi_fail:
            psi_status = ValidationStatus.WARNING
            psi_msg = f"PSI={psi:.4f} — minor shift (monitor)"
        else:
            psi_status = ValidationStatus.FAILED
            psi_msg = f"PSI={psi:.4f} — major shift (retrain required)"
        checks.append(
            CheckResult(
                name="psi",
                status=psi_status,
                value=float(psi),
                threshold=self.psi_fail,
                message=psi_msg,
            )
        )

        # 3. Mean drift
        oos_mean = float(np.mean(oos_scores))
        oos_std = float(np.std(oos_scores, ddof=1))
        live_mean = float(np.mean(live_scores))
        drift_sigma = abs(live_mean - oos_mean) / max(oos_std, 1e-10)
        report.mean_drift_sigma = float(drift_sigma)
        mean_status = ValidationStatus.PASSED if drift_sigma <= self.mean_drift_sigma else ValidationStatus.WARNING
        checks.append(
            CheckResult(
                name="mean_drift",
                status=mean_status,
                value=float(drift_sigma),
                threshold=self.mean_drift_sigma,
                message=(f"Mean drift {drift_sigma:.2f}σ (OOS μ={oos_mean:.4f}, live μ={live_mean:.4f})"),
            )
        )

        # 4. Directional bias
        oos_buy_rate = sum(1 for s in oos if s.direction == "BUY") / len(oos)
        live_buy_rate = sum(1 for s in live if s.direction == "BUY") / len(live)
        bias_drift = abs(live_buy_rate - oos_buy_rate)
        report.directional_bias_drift = float(bias_drift)
        bias_status = (
            ValidationStatus.PASSED if bias_drift <= 0.15 else ValidationStatus.WARNING
        )
        checks.append(
            CheckResult(
                name="directional_bias",
                status=bias_status,
                value=float(bias_drift),
                threshold=0.15,
                message=(f"BUY rate: OOS={oos_buy_rate:.2%}, live={live_buy_rate:.2%}, drift={bias_drift:.2%}"),
            )
        )

        # 5. Confidence score drift
        oos_conf_mean = float(np.mean(oos_conf))
        live_conf_mean = float(np.mean(live_conf))
        conf_drift = abs(live_conf_mean - oos_conf_mean)
        report.confidence_drift = float(conf_drift)
        conf_status = (
            ValidationStatus.PASSED if conf_drift <= 0.10 else ValidationStatus.WARNING
        )
        checks.append(
            CheckResult(
                name="confidence_drift",
                status=conf_status,
                value=float(conf_drift),
                threshold=0.10,
                message=(f"Confidence: OOS μ={oos_conf_mean:.3f}, live μ={live_conf_mean:.3f}, drift={conf_drift:.3f}"),
            )
        )

        report.checks = checks

        # Overall status: worst of all checks
        statuses = [c.status for c in checks]
        if ValidationStatus.FAILED in statuses:
            report.status = ValidationStatus.FAILED
        elif ValidationStatus.WARNING in statuses:
            report.status = ValidationStatus.WARNING
        else:
            report.status = ValidationStatus.PASSED

        logger.info(
            "Signal validation: %s | PSI=%.4f KS_p=%.4f drift=%.2fσ",
            report.status.value,
            psi,
            ks_p,
            drift_sigma,
        )
        return report


# ── PSI calculation ───────────────────────────────────────────────────────────


def _compute_psi(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """
    Compute Population Stability Index between two distributions.

    PSI = Σ (actual% - expected%) × ln(actual% / expected%)

    Args:
        reference: OOS / expected distribution.
        current: Live / actual distribution.
        n_bins: Number of histogram bins.
        epsilon: Small constant to avoid log(0).

    Returns:
        PSI value (0 = identical, > 0.25 = major shift).
    """
    # Use reference distribution to define bin edges
    min_val = min(float(np.min(reference)), float(np.min(current)))
    max_val = max(float(np.max(reference)), float(np.max(current)))

    if max_val - min_val < 1e-10:
        return 0.0

    bins = np.linspace(min_val, max_val, n_bins + 1)

    ref_counts, _ = np.histogram(reference, bins=bins)
    cur_counts, _ = np.histogram(current, bins=bins)

    ref_pct = ref_counts / max(len(reference), 1) + epsilon
    cur_pct = cur_counts / max(len(current), 1) + epsilon

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(0.0, psi)


# ── API endpoint helper ───────────────────────────────────────────────────────

# Module-level singleton
_validator = SignalDistributionValidator()


def get_validator() -> SignalDistributionValidator:
    """Return the module-level SignalDistributionValidator singleton."""
    return _validator
