# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.drift — silent drift of approved baselines.

Pure predicates from the framework's drift sections: risk-appetite, capital-
allocation policy, governance rules, compliance rules, and the constitution
itself must not silently change from their approved versions. A drift is a
governance breach, not just a config change. Each returns list[Violation].
"""

from __future__ import annotations

from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


def verify_no_value_drift(
    current: float, approved: float, tol: float, name: str, rule: str = "No Unexplained System Behavior"
) -> list[Violation]:
    """A numeric policy parameter must stay at its approved value (± tolerance)."""
    if not (_is_finite_number(current) and _is_finite_number(approved)):
        return [_v(rule, CRITICAL, f"{name} drift inputs non-finite")]
    if abs(current - approved) > tol:
        return [_v(rule, CRITICAL, f"{name} drifted: current {current} vs approved {approved}")]
    return []


def verify_risk_appetite_stable(current_profile: Any, approved_profile: Any) -> list[Violation]:
    if current_profile != approved_profile:
        return [_v("No Hidden Risk", CONSTITUTIONAL, "risk appetite drifted from approved profile")]
    return []


def verify_allocation_policy_stable(current_policy: Any, approved_policy: Any) -> list[Violation]:
    if current_policy != approved_policy:
        return [
            _v("No Unauthorized Capital Movement", CONSTITUTIONAL, "capital-allocation policy drifted from approved")
        ]
    return []


def verify_governance_consistent(current_rules: Any, approved_rules: Any) -> list[Violation]:
    if current_rules != approved_rules:
        return [_v("No Compliance Breach", CONSTITUTIONAL, "governance rules drifted from approved set")]
    return []


def verify_compliance_current(rules_version: Any, required_version: Any) -> list[Violation]:
    if rules_version != required_version:
        return [
            _v(
                "No Compliance Breach",
                CONSTITUTIONAL,
                f"compliance rules out of date: {rules_version!r} != required {required_version!r}",
            )
        ]
    return []


def verify_constitution_version(current_version: Any, approved_version: Any) -> list[Violation]:
    """The constitution itself must be the approved, signed version."""
    if current_version != approved_version:
        return [
            _v(
                "No Loss Of Human Control",
                CONSTITUTIONAL,
                f"constitution version {current_version!r} != approved {approved_version!r}",
            )
        ]
    return []


def verify_incentive_alignment(actors_aligned: bool) -> list[Violation]:
    """All actors (agents, operators, strategies) must optimise the approved goal."""
    if not actors_aligned:
        return [_v("No Unapproved AI Action", WARNING, "actor incentives not aligned with platform objective")]
    return []
