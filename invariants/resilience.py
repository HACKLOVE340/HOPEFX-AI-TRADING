# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.resilience — disaster recovery, failover & chaos invariants.

Pure predicates from the framework's DR / sovereign-failure / chaos sections:
backup recency & integrity, restore-tested, region/multi-region failover, chaos
survival, recovery-path & rollback existence, and recovery-SLA. list[Violation].
"""

from __future__ import annotations

from collections.abc import Mapping

from invariants.constitution import (
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Unrecoverable Failure"


def verify_backup_recent(age_hours: float, max_age_hours: float = 24.0) -> list[Violation]:
    if not _is_finite_number(age_hours):
        return [_v(_RULE, CRITICAL, "backup age non-finite")]
    if age_hours > max_age_hours:
        return [_v(_RULE, CRITICAL, f"last backup {age_hours}h old > max {max_age_hours}h")]
    return []


def verify_backup_integrity(integrity_verified: bool) -> list[Violation]:
    if not integrity_verified:
        return [_v(_RULE, CRITICAL, "backup integrity not verified — backup may be unusable")]
    return []


def verify_restore_tested(restore_test_passed: bool, days_since_test: float, max_days: float = 30.0) -> list[Violation]:
    """A backup you have never restored is not a backup."""
    out: list[Violation] = []
    if not restore_test_passed:
        out.append(_v(_RULE, CRITICAL, "restore test has never passed"))
    if _is_finite_number(days_since_test) and days_since_test > max_days:
        out.append(_v(_RULE, WARNING, f"restore last tested {days_since_test}d ago (> {max_days}d)"))
    return out


def verify_failover_ready(replicas_healthy: int, min_replicas: int = 1) -> list[Violation]:
    if replicas_healthy < min_replicas:
        return [_v("No Critical Single Point Of Failure", CRITICAL,
                   f"failover not ready: {replicas_healthy} healthy replica(s) < {min_replicas}")]
    return []


def verify_multi_region(regions_replicated: int, min_regions: int = 2) -> list[Violation]:
    if regions_replicated < min_regions:
        return [_v("No Critical Single Point Of Failure", WARNING,
                   f"only {regions_replicated} region(s) replicated (< {min_regions}) — region SPOF")]
    return []


def verify_recovery_path_exists(component: str, has_runbook: bool, has_rollback: bool) -> list[Violation]:
    """Every component needs a documented recovery + rollback path."""
    out: list[Violation] = []
    if not has_runbook:
        out.append(_v(_RULE, CRITICAL, f"{component} has no recovery runbook"))
    if not has_rollback:
        out.append(_v(_RULE, CRITICAL, f"{component} has no rollback path"))
    return out


def verify_chaos_survival(scenarios: Mapping[str, bool]) -> list[Violation]:
    """Each chaos scenario (broker/exchange/db/cache/model/queue offline) must be
    survived (system detects, contains, recovers)."""
    failed = [s for s, survived in scenarios.items() if not survived]
    if failed:
        return [_v("No Unbounded Failure", CRITICAL, f"chaos scenarios NOT survived: {failed}")]
    return []


def verify_recovery_sla(recovery_seconds: float, sla_seconds: float) -> list[Violation]:
    if _is_finite_number(recovery_seconds) and recovery_seconds > sla_seconds:
        return [_v(_RULE, CRITICAL, f"recovery {recovery_seconds}s breached SLA {sla_seconds}s")]
    return []
