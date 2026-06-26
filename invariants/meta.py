# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.meta — observation integrity, platform identity & existential control.

The supreme layer. Pure predicates from the framework's meta/existential
sections: observed state must equal actual state (the most dangerous failure is
an all-green platform whose beliefs are wrong), the platform must remain the
approved system, anomalies (unknown-unknowns) must be detectable, and humans
must always retain ultimate control. Plus a constitutional aggregate.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _v,
    summarize,
)


def verify_observed_matches_actual(observed: Any, actual: Any, kind: str = "state") -> list[Violation]:
    """Monitoring/beliefs must reflect reality — the supreme invariant. A green
    dashboard that disagrees with reality is the most dangerous failure mode."""
    if observed != actual:
        return [
            _v(
                "No Unexplained System Behavior",
                CONSTITUTIONAL,
                f"observation integrity broken: observed {kind} {observed!r} != actual {actual!r}",
            )
        ]
    return []


def verify_platform_identity(capabilities: Iterable[str], approved_capabilities: set[str]) -> list[Violation]:
    """The platform must remain the approved system — no undeclared capabilities."""
    extra = set(capabilities) - approved_capabilities
    if extra:
        return [
            _v("No Loss Of Human Control", CONSTITUTIONAL, f"platform gained undeclared capabilities: {sorted(extra)}")
        ]
    return []


def verify_anomaly_detection_operational(operational: bool) -> list[Violation]:
    """The unknown-unknown detector itself must be alive (you can't catch novel
    failures with a dead anomaly detector)."""
    if not operational:
        return [_v("No Silent Failure", CRITICAL, "anomaly/unknown-unknown detection is not operational")]
    return []


def verify_human_can_stop(controls: dict[str, bool]) -> list[Violation]:
    """Humans must always be able to stop trading/agents/capital/models/strategies
    /deployments — existential control supremacy."""
    broken = [c for c, works in controls.items() if not works]
    if broken:
        return [_v("No Loss Of Human Control", CONSTITUTIONAL, f"human stop controls NOT operable: {broken}")]
    return []


def verify_invariant_engine_healthy(healthy: bool) -> list[Violation]:
    """Monitor the monitors: a broken invariant engine is worse than none."""
    if not healthy:
        return [_v("No Silent Failure", CONSTITUTIONAL, "the invariant engine itself is unhealthy")]
    return []


def verify_constitution(all_violations: list[Violation]) -> list[Violation]:
    """Master aggregate: the constitution is satisfied iff there are zero
    CONSTITUTIONAL and zero CRITICAL violations across the whole platform.
    Returns a single summarizing violation when breached (else empty)."""
    s = summarize(all_violations)
    if not s["ok"]:
        c = s["counts"]
        return [
            _v(
                "Constitutional Integrity",
                CONSTITUTIONAL,
                f"constitution breached: {c.get('CONSTITUTIONAL', 0)} constitutional, "
                f"{c.get('CRITICAL', 0)} critical violation(s)",
                counts=c,
            )
        ]
    return []


# ════════════════════════════════════════════════════════════════════════════════
# META-INVARIANTS — coverage guarantees ("is every critical thing protected?")
# At platform scale, the failure mode is not a missing single check — it is a
# critical component that NOBODY checks, monitors, alerts on, or can recover. These
# assert completeness of the protection itself.
# ════════════════════════════════════════════════════════════════════════════════
def _coverage(
    covered: int, total: int, rule: str, what: str, min_fraction: float = 1.0, severity: str = CRITICAL
) -> list[Violation]:
    if total <= 0:
        return []
    fraction = covered / total
    if fraction < min_fraction:
        return [
            _v(
                rule,
                severity,
                f"{what} coverage {covered}/{total} ({fraction:.0%}) below required {min_fraction:.0%}",
                covered=covered,
                total=total,
            )
        ]
    return []


def verify_invariant_coverage(
    protected_components: int, total_components: int, min_fraction: float = 1.0
) -> list[Violation]:
    """Every critical component must have invariants guarding it."""
    return _coverage(protected_components, total_components, "No Silent Failure", "invariant", min_fraction)


def verify_alert_coverage(
    failures_with_alerts: int, total_critical_failures: int, min_fraction: float = 1.0
) -> list[Violation]:
    """Every critical failure mode must generate an alert."""
    return _coverage(failures_with_alerts, total_critical_failures, "No Silent Failure", "alert", min_fraction)


def verify_recovery_coverage(
    services_with_recovery: int, total_critical_services: int, min_fraction: float = 1.0
) -> list[Violation]:
    """Every critical service must have a recovery procedure."""
    return _coverage(
        services_with_recovery, total_critical_services, "No Unrecoverable Failure", "recovery", min_fraction
    )


def verify_ai_explainability_coverage(
    explained_decisions: int, total_decisions: int, min_fraction: float = 1.0
) -> list[Violation]:
    """Every AI decision must carry an explanation."""
    return _coverage(
        explained_decisions, total_decisions, "No Unverified AI Decision", "AI-explainability", min_fraction
    )


def verify_decision_trace(
    trace: dict[str, Any],
    links: tuple[str, ...] = (
        "decision_id",
        "model_version",
        "prompt_hash",
        "features_hash",
        "data_snapshot",
        "trade_id",
    ),
) -> list[Violation]:
    """A decision must be fully reconstructable end-to-end:
    decision → model → prompt → features → data → trade. Any missing link breaks
    traceability (No Hidden AI Action / No Hidden Decision)."""
    missing = [link for link in links if not trace.get(link)]
    if missing:
        return [
            _v(
                "No Hidden AI Action",
                CONSTITUTIONAL,
                f"decision trace not reconstructable — missing link(s): {missing}",
                missing=missing,
            )
        ]
    return []


def verify_five_master_guarantees(
    *,
    nothing_unnoticed: bool,
    nothing_unbounded: bool,
    nothing_unrecoverable: bool,
    nothing_unaccounted: bool,
    human_in_control: bool,
) -> list[Violation]:
    """The framework's definition of success (§10): the five master guarantees."""
    checks = {
        "nothing important happens unnoticed": nothing_unnoticed,
        "nothing dangerous happens unbounded": nothing_unbounded,
        "nothing critical fails unrecoverably": nothing_unrecoverable,
        "nothing financial becomes unaccounted": nothing_unaccounted,
        "nothing autonomous outranks human control": human_in_control,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return [_v("Constitutional Integrity", CONSTITUTIONAL, f"master guarantee(s) not met: {failed}")]
    return []
