# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.derivatives — options / futures / swaps invariants.

Pure predicates from the framework's derivatives section: net Greek-exposure
bounds (delta/gamma/vega/theta), collateral sufficiency, and expiration handling.
Only relevant if/when the platform trades derivatives; safe no-ops otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Hidden Exposure"


def verify_greek_limits(greeks: Mapping[str, float], limits: Mapping[str, float]) -> list[Violation]:
    """Net delta/gamma/vega/theta must each stay within their approved limits."""
    out: list[Violation] = []
    for g, val in greeks.items():
        if not _is_finite_number(val):
            out.append(_v(_RULE, CONSTITUTIONAL, f"greek '{g}' is non-finite"))
            continue
        lim = limits.get(g)
        if lim is not None and abs(val) > lim:
            out.append(_v(_RULE, CRITICAL, f"net {g} {val} exceeds |limit| {lim}"))
    return out


def verify_collateral_sufficient(required_collateral: float, posted_collateral: float) -> list[Violation]:
    if not (_is_finite_number(required_collateral) and _is_finite_number(posted_collateral)):
        return [_v("No Hidden Risk", CONSTITUTIONAL, "collateral values non-finite")]
    if posted_collateral < required_collateral:
        return [_v("No Hidden Risk", CRITICAL,
                   f"under-collateralised: posted {posted_collateral} < required {required_collateral}")]
    return []


def verify_expiry_handled(days_to_expiry: float, has_action_plan: bool) -> list[Violation]:
    """A near-expiry position must have an exercise/roll/close plan."""
    if _is_finite_number(days_to_expiry) and days_to_expiry <= 1 and not has_action_plan:
        return [_v("No Hidden Risk", WARNING,
                   f"position expires in {days_to_expiry}d with no exercise/roll/close plan")]
    return []
