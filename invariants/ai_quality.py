# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.ai_quality — model & signal quality beyond drift/staleness.

Pure predicates for the framework's AI-quality categories that complement
``invariants.ai``: feature-count explosion, feature sparsity, regime
misclassification, signal/position concentration, trade clustering, explanation
consistency (same input → same explanation), and the integrity of the risk &
stress models that gate capital. A quietly-degraded model that still returns
confident numbers is the dangerous case. Each returns ``list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Unverified AI Decision"


def verify_feature_count_stable(count: int, expected: int) -> list[Violation]:
    """The live feature count must equal what the model was trained on."""
    if count != expected:
        return [_v(_RULE, CRITICAL, f"feature count {count} != trained {expected} (feature explosion/loss)")]
    return []


def verify_feature_sparsity(zero_fraction: float, max_fraction: float) -> list[Violation]:
    """Excessive zero/NaN features mean the model is flying blind."""
    if _is_finite_number(zero_fraction) and zero_fraction > max_fraction:
        return [_v(_RULE, WARNING, f"feature sparsity {zero_fraction} exceeds {max_fraction}")]
    return []


def verify_regime_classified(confidence: float, min_confidence: float, regime: str = "") -> list[Violation]:
    """Market-regime classification must be confident enough to act on."""
    if _is_finite_number(confidence) and confidence < min_confidence:
        return [_v(_RULE, WARNING, f"regime {regime} classified at {confidence} < min {min_confidence}")]
    return []


def verify_signal_concentration(weights: Iterable[float], max_weight: float) -> list[Violation]:
    """No single signal/feature may dominate the decision past a cap."""
    vals = [w for w in weights if _is_finite_number(w)]
    if vals and max(abs(w) for w in vals) > max_weight:
        return [_v(_RULE, WARNING, f"signal concentration {max(abs(w) for w in vals)} exceeds cap {max_weight}")]
    return []


def verify_trade_not_clustered(trades_in_window: int, max_in_window: int, window: str = "1m") -> list[Violation]:
    """A burst of trades in a tiny window suggests a loop/runaway model."""
    if trades_in_window > max_in_window:
        return [_v(_RULE, CRITICAL,
                   f"{trades_in_window} trades in {window} exceeds {max_in_window} (clustering/runaway)")]
    return []


def verify_explanation_consistent(explanation_a: Any, explanation_b: Any) -> list[Violation]:
    """The same input must yield the same explanation (explainability stability)."""
    if explanation_a != explanation_b:
        return [_v(_RULE, WARNING, "explanation differs for identical input (unstable explainability)")]
    return []


def verify_prediction_matches_explanation(direction: str, explained_direction: str) -> list[Violation]:
    """The action taken must agree with its stated rationale (no post-hoc fiction)."""
    if direction != explained_direction:
        return [_v(_RULE, CONSTITUTIONAL,
                   f"action {direction!r} contradicts its explanation {explained_direction!r}")]
    return []


def verify_risk_model_fresh(age_seconds: float, max_age_seconds: float) -> list[Violation]:
    """The risk model that gates sizing must not be stale."""
    if _is_finite_number(age_seconds) and age_seconds > max_age_seconds:
        return [_v("No Hidden Risk", CRITICAL, f"risk model age {age_seconds}s exceeds {max_age_seconds}s")]
    return []


def verify_stress_model_complete(scenarios_run: Iterable[Any], required_scenarios: Iterable[Any]) -> list[Violation]:
    """Required stress scenarios must all have been evaluated."""
    missing = sorted({str(s) for s in required_scenarios} - {str(s) for s in scenarios_run})
    if missing:
        return [_v("No Hidden Risk", CRITICAL, f"stress scenarios not run: {missing[:5]}")]
    return []


def verify_model_output_bounded(value: float, low: float, high: float, name: str = "output") -> list[Violation]:
    """A model output (e.g. probability, position fraction) must be within bounds."""
    if not _is_finite_number(value):
        return [_v("No Data Corruption", CRITICAL, f"model {name} non-finite: {value!r}")]
    if value < low or value > high:
        return [_v(_RULE, CRITICAL, f"model {name} {value} outside valid range [{low}, {high}]")]
    return []


def verify_calibration_error(observed_freq: Mapping[Any, float], predicted_prob: Mapping[Any, float],
                             max_error: float) -> list[Violation]:
    """Predicted probabilities must roughly match observed frequencies (calibration)."""
    out: list[Violation] = []
    for bucket, pred in predicted_prob.items():
        obs = observed_freq.get(bucket)
        if obs is None or not (_is_finite_number(obs) and _is_finite_number(pred)):
            continue
        if abs(obs - pred) > max_error:
            out.append(_v(_RULE, WARNING,
                          f"miscalibrated bucket {bucket!r}: predicted {pred} vs observed {obs}"))
    return out
