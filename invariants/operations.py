# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.operations — alerting, monitoring, incident & human-operations.

Pure predicates from the framework's observability/operations/meta sections:
critical-alert delivery & acknowledgement & escalation, monitoring blind-spot
coverage, incident-timeline & root-cause completeness, human-operator readiness
& fatigue & approval, emergency reversibility, alert-fatigue protection, and the
meta-invariant "monitor the monitors".
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


def verify_critical_alert_delivered(delivered: bool) -> list[Violation]:
    if not delivered:
        return [_v("No Silent Failure", CRITICAL, "a critical alert was NOT delivered")]
    return []


def verify_critical_alert_acknowledged(age_s: float, max_ack_s: float) -> list[Violation]:
    if _is_finite_number(age_s) and age_s > max_ack_s:
        return [
            _v(
                "No Silent Failure",
                CRITICAL,
                f"critical alert unacknowledged for {age_s}s (> {max_ack_s}s) — must escalate",
            )
        ]
    return []


def verify_monitoring_coverage(monitored: int, critical_total: int) -> list[Violation]:
    """No critical workflow may be unmonitored (blind-spot detection)."""
    if critical_total > 0 and monitored < critical_total:
        return [
            _v(
                "No Silent Failure",
                CRITICAL,
                f"monitoring blind spot: {monitored}/{critical_total} critical workflows monitored",
            )
        ]
    return []


def verify_incident_timeline_complete(has_detect: bool, has_cause: bool, has_resolve: bool) -> list[Violation]:
    """Every incident must be reconstructable (detected→root-caused→resolved)."""
    missing = [
        n for n, ok in (("detection", has_detect), ("root_cause", has_cause), ("resolution", has_resolve)) if not ok
    ]
    if missing:
        return [_v("No Unexplained System Behavior", CRITICAL, f"incident timeline incomplete: missing {missing}")]
    return []


def verify_operator_available(qualified_operators_on_call: int) -> list[Violation]:
    """A qualified human must always be reachable to take control."""
    if qualified_operators_on_call < 1:
        return [_v("No Loss Of Human Control", CRITICAL, "no qualified operator on call")]
    return []


def verify_operator_fatigue(hours_on_shift: float, max_hours: float) -> list[Violation]:
    if _is_finite_number(hours_on_shift) and hours_on_shift > max_hours:
        return [
            _v(
                "No Loss Of Human Control",
                WARNING,
                f"operator fatigue: {hours_on_shift}h on shift exceeds {max_hours}h",
            )
        ]
    return []


def verify_emergency_reversible(action: str, has_rollback: bool) -> list[Violation]:
    """Every emergency action must have a tested rollback path."""
    if not has_rollback:
        return [_v("No Unrecoverable Failure", CRITICAL, f"emergency action '{action}' has no rollback path")]
    return []


def verify_alert_fatigue(false_alert_rate: float, threshold: float) -> list[Violation]:
    """Too many false alerts degrade response — protect signal quality."""
    if _is_finite_number(false_alert_rate) and false_alert_rate > threshold:
        return [
            _v("No Silent Failure", WARNING, f"alert fatigue risk: false-alert rate {false_alert_rate} > {threshold}")
        ]
    return []


def verify_monitors_healthy(monitor_status: Mapping[str, bool]) -> list[Violation]:
    """Monitor the monitors — a dead safety system is worse than none."""
    dead = [m for m, ok in monitor_status.items() if not ok]
    if dead:
        return [_v("No Silent Failure", CONSTITUTIONAL, f"safety/monitoring systems down: {dead}")]
    return []
