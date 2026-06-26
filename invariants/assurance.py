# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.assurance — simulation fidelity, sovereignty & insider-threat control.

Pure predicates for the framework's assurance/trust categories: paper/simulation
results must track live behaviour (no sim-to-real gap that hides real risk), data
must stay within its required jurisdiction/region (sovereignty), no single human
can unilaterally move capital (separation of powers under insider threat), access
is least-privilege, and privileged actions require dual control. These protect
against the failure mode where the platform *looks* trustworthy. Each returns
``list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


def verify_sim_fidelity(sim_metric: float, live_metric: float, max_divergence: float,
                        name: str = "pnl") -> list[Violation]:
    """Simulation/paper results must track live behaviour within tolerance."""
    if not (_is_finite_number(sim_metric) and _is_finite_number(live_metric)):
        return [_v("No Data Corruption", CRITICAL, "sim/live metric non-finite")]
    if abs(sim_metric - live_metric) > max_divergence:
        return [_v("No Hidden Risk", WARNING,
                   f"sim/live {name} gap {abs(sim_metric - live_metric)} exceeds {max_divergence}")]
    return []


def verify_paper_not_mistaken_for_live(mode: str, broker_is_live: bool) -> list[Violation]:
    """Paper mode must never route to a live broker (and vice versa)."""
    if mode == "paper" and broker_is_live:
        return [_v("No Unauthorized Trade", CONSTITUTIONAL, "paper mode routed to a LIVE broker")]
    if mode == "live" and not broker_is_live:
        return [_v("No Silent Failure", CRITICAL, "live mode routed to a paper/sim broker (orders not real)")]
    return []


def verify_data_in_jurisdiction(data_region: str, allowed_regions: set[str]) -> list[Violation]:
    """Data must reside within an allowed jurisdiction (sovereignty/GDPR)."""
    if allowed_regions and data_region not in allowed_regions:
        return [_v("No Compliance Breach", CONSTITUTIONAL,
                   f"data in disallowed region {data_region!r} (allowed: {sorted(allowed_regions)})")]
    return []


def verify_no_cross_region_leak(request_region: str, data_region: str) -> list[Violation]:
    """A request must not pull data across a region/jurisdiction boundary."""
    if request_region != data_region:
        return [_v("No Cross-Tenant Leakage", CONSTITUTIONAL,
                   f"cross-region data access: request {request_region!r} -> data {data_region!r}")]
    return []


def verify_no_unilateral_capital_move(amount: float, approvers: Iterable[Any], min_approvers: int) -> list[Violation]:
    """A large capital movement must require more than one approver (insider-threat)."""
    n = len({a for a in approvers if a})
    if amount > 0 and n < min_approvers:
        return [_v("No Unauthorized Capital Movement", CONSTITUTIONAL,
                   f"capital move of {amount} had {n} approver(s) < required {min_approvers}")]
    return []


def verify_least_privilege(granted_scopes: Iterable[str], needed_scopes: Iterable[str]) -> list[Violation]:
    """A principal must not hold scopes beyond what its role needs."""
    excess = sorted(set(granted_scopes) - set(needed_scopes))
    if excess:
        return [_v("No Loss Of Human Control", WARNING, f"excess privileges granted: {excess}")]
    return []


def verify_dual_control(action_sensitive: bool, distinct_approvers: int) -> list[Violation]:
    """A privileged action must have two distinct approvers (four-eyes)."""
    min_eyes = 2
    if action_sensitive and distinct_approvers < min_eyes:
        return [_v("No Loss Of Human Control", CONSTITUTIONAL,
                   f"sensitive action with {distinct_approvers} approver(s) < dual-control {min_eyes}")]
    return []


def verify_access_reviewed(days_since_review: float, max_days: float) -> list[Violation]:
    """Access grants must be periodically reviewed (stale access = insider risk)."""
    if _is_finite_number(days_since_review) and days_since_review > max_days:
        return [_v("No Compliance Breach", WARNING, f"access not reviewed for {days_since_review}d (> {max_days}d)")]
    return []


def verify_anomalous_access_blocked(anomaly_score: float, threshold: float, blocked: bool) -> list[Violation]:
    """Anomalous privileged access above threshold must be blocked/challenged."""
    if _is_finite_number(anomaly_score) and anomaly_score > threshold and not blocked:
        return [_v("No Loss Of Human Control", CRITICAL,
                   f"anomalous access (score {anomaly_score} > {threshold}) was not blocked")]
    return []
