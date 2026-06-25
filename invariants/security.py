# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.security — secrets, supply chain, trust boundaries & adversarial AI.

Pure predicates from the framework's security sections: no exposed secrets,
secret rotation within policy, signed supply-chain artifacts, verified trust
boundaries, data provenance, and adversarial-AI resistance (prompt / market-data
/ memory / tool poisoning). Each returns list[Violation].
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Compliance Breach"


def verify_no_exposed_secret(value: str, placeholder_markers: tuple[str, ...] = (
        "CHANGE_ME", "your_", "_here", "changeme", "replace_me")) -> list[Violation]:
    """A live secret slot must not contain a placeholder (and must be non-empty)."""
    if not value:
        return [_v(_RULE, CRITICAL, "secret is empty/unset")]
    low = value.lower()
    if any(m.lower() in low for m in placeholder_markers):
        return [_v(_RULE, CONSTITUTIONAL, "secret still holds a placeholder value")]
    return []


def verify_secret_rotation(age_days: float, max_age_days: float) -> list[Violation]:
    if _is_finite_number(age_days) and age_days > max_age_days:
        return [_v(_RULE, CRITICAL, f"secret age {age_days}d exceeds rotation policy {max_age_days}d")]
    return []


def verify_secret_usage(accessor: Any, authorized: set[Any]) -> list[Violation]:
    """A secret may be used only by authorized systems."""
    if authorized and accessor not in authorized:
        return [_v("No Loss Of Human Control", CONSTITUTIONAL, f"secret accessed by unauthorized system {accessor!r}")]
    return []


def verify_artifact_signed(signatures: Iterable[Any]) -> list[Violation]:
    """Every deployed model/package/container must be signed (supply chain)."""
    unsigned = [i for i, sig in enumerate(signatures) if not sig]
    if unsigned:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, f"{len(unsigned)} unsigned supply-chain artifact(s)")]
    return []


def verify_data_provenance(verified: bool, source: str | None = None) -> list[Violation]:
    """Every data point used for decisions must have a trusted, verified source."""
    if not verified:
        return [_v("No Data Corruption", CRITICAL, f"data has unverified provenance (source={source!r})")]
    return []


def verify_trust_boundary(crossing: str, verified: bool) -> list[Violation]:
    """Each trust-boundary crossing (user→agent→tool→exchange→broker→ledger) must
    be authenticated/verified."""
    if not verified:
        return [_v("No Unauthorized Trade", CONSTITUTIONAL, f"unverified trust-boundary crossing: {crossing}")]
    return []


def verify_prompt_not_injected(injection_detected: bool) -> list[Violation]:
    """Agent input must be screened for prompt injection."""
    if injection_detected:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, "prompt injection detected in agent input")]
    return []


def verify_input_not_poisoned(anomaly_score: float, threshold: float, channel: str = "market_data") -> list[Violation]:
    """Market-data / memory / tool inputs must be screened for poisoning."""
    if _is_finite_number(anomaly_score) and anomaly_score > threshold:
        return [_v("No Data Corruption", CRITICAL,
                   f"possible {channel} poisoning: anomaly {anomaly_score} > {threshold}")]
    return []
