# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.ops_extended — incident response, overrides & strategy lifecycle.

Pure predicates for the framework's operational-governance categories that
complement ``invariants.operations``: alerts must escalate when unacknowledged,
incidents must have a root cause & postmortem, every emergency/manual override
must be logged and attributed to an accountable human, override frequency must
stay bounded, and a retired strategy must actually stop trading. The recurring
theme: humans stay accountable and in control under stress. Each returns
``list[Violation]``.
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

_RULE = "No Loss Of Human Control"


def verify_alert_escalated(unacked_seconds: float, escalate_after_seconds: float, escalated: bool) -> list[Violation]:
    """An alert unacknowledged past its window must have escalated."""
    if _is_finite_number(unacked_seconds) and unacked_seconds > escalate_after_seconds and not escalated:
        return [_v("No Silent Failure", CRITICAL,
                   f"alert unacked {unacked_seconds}s (> {escalate_after_seconds}s) but not escalated")]
    return []


def verify_incident_has_root_cause(resolved: bool, root_cause: str | None) -> list[Violation]:
    """A resolved incident must have a recorded root cause (no silent close)."""
    if resolved and not root_cause:
        return [_v("No Unexplained System Behavior", CRITICAL, "incident resolved without a recorded root cause")]
    return []


def verify_postmortem_complete(severity_rank: int, postmortem_required_rank: int,
                               postmortem_done: bool) -> list[Violation]:
    """A sufficiently severe incident must have a completed postmortem."""
    if severity_rank >= postmortem_required_rank and not postmortem_done:
        return [_v("No Unexplained System Behavior", WARNING,
                   f"severity-{severity_rank} incident missing required postmortem")]
    return []


def verify_override_logged(override_occurred: bool, logged: bool) -> list[Violation]:
    """Every emergency/manual override must be logged."""
    if override_occurred and not logged:
        return [_v(_RULE, CONSTITUTIONAL, "emergency override was NOT logged (accountability gap)")]
    return []


def verify_override_attributed(override_occurred: bool, operator: Any) -> list[Violation]:
    """Every override must be attributed to an identified accountable human."""
    if override_occurred and not operator:
        return [_v(_RULE, CONSTITUTIONAL, "override has no attributed operator (no accountability)")]
    return []


def verify_override_authorized(operator_role: Any, authorized_roles: set[Any]) -> list[Violation]:
    """An override may only be performed by an authorized role."""
    if authorized_roles and operator_role not in authorized_roles:
        return [_v(_RULE, CONSTITUTIONAL, f"override by unauthorized role {operator_role!r}")]
    return []


def verify_override_rate_bounded(overrides: int, max_overrides: int, window: str = "24h") -> list[Violation]:
    """Frequent overrides signal a broken automation that must be investigated."""
    if overrides > max_overrides:
        return [_v(_RULE, WARNING, f"{overrides} overrides in {window} exceeds {max_overrides} (automation distrust)")]
    return []


def verify_retired_strategy_stopped(retired: bool, still_trading: bool, strategy: str = "") -> list[Violation]:
    """A retired/disabled strategy must not still be placing trades."""
    if retired and still_trading:
        return [_v("No Unauthorized Trade", CONSTITUTIONAL, f"retired strategy {strategy} is still trading")]
    return []


def verify_emergency_governance(kill_switch_owner: Any, required_owner: Any) -> list[Violation]:
    """Emergency authority must rest with the designated human/role, not drift."""
    if required_owner is not None and kill_switch_owner != required_owner:
        return [_v(_RULE, CONSTITUTIONAL,
                   f"emergency authority drifted: owner {kill_switch_owner!r} != required {required_owner!r}")]
    return []


def verify_change_has_approval(in_production: bool, approved_by: Any) -> list[Violation]:
    """A production change must carry an approval (no unreviewed prod change)."""
    if in_production and not approved_by:
        return [_v("No Unapproved AI Action", CONSTITUTIONAL, "production change without recorded approval")]
    return []
