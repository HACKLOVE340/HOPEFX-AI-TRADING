# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.business_logic — domain rules & cross-service consistency.

Pure predicates for the framework's business-logic categories: workflows follow
their allowed state machine, quantities/counts are conserved across a multi-step
operation, derived totals equal the sum of their parts, discounts/limits are
bounded, uniqueness constraints hold, and a value that two services both report
must agree (cross-service consistency). These catch "every service is up but the
numbers are wrong" bugs. Each returns ``list[Violation]``.
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

_RULE = "No State Corruption"


def verify_workflow_transition(from_state: str, to_state: str, allowed: Mapping[str, Iterable[str]]) -> list[Violation]:
    """A business workflow may only follow declared state transitions."""
    valid = set(allowed.get(from_state, ()))
    if from_state != to_state and to_state not in valid:
        return [_v(_RULE, CRITICAL, f"illegal workflow transition {from_state}->{to_state}")]
    return []


def verify_quantity_conserved(before: float, after: float, expected_delta: float, tol: float = 0.0) -> list[Violation]:
    """A conserved quantity must change by exactly the expected delta."""
    if not all(_is_finite_number(x) for x in (before, after, expected_delta)):
        return [_v("No Data Corruption", CRITICAL, "quantity components non-finite")]
    if abs((before + expected_delta) - after) > tol:
        return [_v(_RULE, CONSTITUTIONAL, f"quantity not conserved: {before}+{expected_delta} != {after}")]
    return []


def verify_total_equals_sum(total: float, parts: Iterable[float], tol: float = 0.01) -> list[Violation]:
    """A derived total must equal the sum of its line items."""
    vals = list(parts)
    if not _is_finite_number(total) or not all(_is_finite_number(p) for p in vals):
        return [_v("No Data Corruption", CRITICAL, "total/parts non-finite")]
    s = sum(vals)
    if abs(total - s) > tol:
        return [_v(_RULE, CONSTITUTIONAL, f"total {total} != sum of parts {s}")]
    return []


def verify_count_matches(expected_count: int, actual_count: int, name: str = "items") -> list[Violation]:
    """A reported count must match the actual number of records."""
    if expected_count != actual_count:
        return [_v(_RULE, CRITICAL, f"{name} count mismatch: reported {expected_count} != actual {actual_count}")]
    return []


def verify_value_in_range(value: float, low: float, high: float, name: str = "value") -> list[Violation]:
    """A domain value must lie within its allowed range."""
    if _is_finite_number(value) and (value < low or value > high):
        return [_v(_RULE, CRITICAL, f"{name} {value} outside allowed range [{low}, {high}]")]
    return []


def verify_discount_bounded(discount_pct: float, max_pct: float) -> list[Violation]:
    """A discount/adjustment must not exceed its policy maximum."""
    if _is_finite_number(discount_pct) and discount_pct > max_pct:
        return [_v(_RULE, WARNING, f"discount {discount_pct}% exceeds policy max {max_pct}%")]
    return []


def verify_unique_constraint(values: Iterable[Any], name: str = "field") -> list[Violation]:
    """A business uniqueness constraint must hold (no duplicate slugs/emails/refs)."""
    seen: set[Any] = set()
    dups: set[Any] = set()
    for v in values:
        if v in seen:
            dups.add(v)
        seen.add(v)
    if dups:
        return [_v(_RULE, CRITICAL, f"uniqueness violated on {name}: {sorted(map(str, dups))[:5]}")]
    return []


def verify_cross_service_agreement(values: Mapping[str, Any], name: str = "value") -> list[Violation]:
    """A value reported by multiple services must agree across all of them."""
    distinct = {repr(v) for v in values.values()}
    if len(distinct) > 1:
        return [_v(_RULE, CONSTITUTIONAL, f"cross-service disagreement on {name}: {dict(values)}")]
    return []


def verify_no_partial_commit(steps_committed: Iterable[bool]) -> list[Violation]:
    """A multi-step transaction must be all-or-nothing (no partial commit)."""
    states = list(steps_committed)
    if states and any(states) and not all(states):
        committed = sum(states)
        return [
            _v(_RULE, CONSTITUTIONAL, f"partial commit: {committed}/{len(states)} steps committed (atomicity broken)")
        ]
    return []


def verify_invariant_count_stable(before: int, after: int, name: str = "records") -> list[Violation]:
    """A read-only operation must not change a record count (no accidental mutation)."""
    if before != after:
        return [_v(_RULE, CRITICAL, f"{name} count changed during read-only op: {before} -> {after}")]
    return []
