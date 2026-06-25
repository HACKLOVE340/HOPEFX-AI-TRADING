# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.replay — replay fidelity, time-travel & data-resurrection.

Pure predicates from the framework's replay/forensics section: market / strategy
/ decision / agent replay must reproduce the original; historical state must be
recoverable; and deleted data must stay deleted. Each returns list[Violation].
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


def verify_replay_matches(original: Any, replayed: Any, kind: str = "decision") -> list[Violation]:
    """A replay must reproduce the original exactly (audit/forensics)."""
    if original != replayed:
        return [_v("No Audit Gap", CRITICAL, f"{kind} replay diverged from original")]
    return []


def verify_replay_within_tolerance(original: float, replayed: float, tol: float, kind: str = "market") -> list[Violation]:
    """Numeric replay (PnL/price reconstruction) must match within tolerance."""
    if not (_is_finite_number(original) and _is_finite_number(replayed)):
        return [_v("No Audit Gap", CRITICAL, f"{kind} replay value non-finite")]
    if abs(original - replayed) > tol:
        return [_v("No Audit Gap", CRITICAL,
                   f"{kind} replay drift {abs(original - replayed)} > tol {tol}")]
    return []


def verify_historical_recoverable(recoverable: bool, as_of: Any = None) -> list[Violation]:
    """Historical state at a point in time must be reconstructable."""
    if not recoverable:
        return [_v("No Audit Gap", CRITICAL, f"historical state not recoverable (as_of={as_of!r})")]
    return []


def verify_deleted_stays_deleted(deleted_ids: Iterable[Any], present_ids: Iterable[Any]) -> list[Violation]:
    """Deleted records must not reappear (data resurrection)."""
    resurrected = set(deleted_ids) & set(present_ids)
    if resurrected:
        return [_v("No State Corruption", CONSTITUTIONAL,
                   f"data resurrection: {len(resurrected)} deleted record(s) reappeared",
                   ids=sorted(resurrected)[:5])]
    return []


def verify_event_replay_idempotent(state_first: Any, state_second: Any) -> list[Violation]:
    """Replaying the same event stream twice must yield the same state."""
    if state_first != state_second:
        return [_v("No State Corruption", CRITICAL, "event replay is not idempotent (states differ)")]
    return []


def verify_snapshot_consistent(snapshot_total: float, rebuilt_total: float, tol: float = 0.01) -> list[Violation]:
    """A state snapshot must match the value rebuilt from the event log."""
    if not (_is_finite_number(snapshot_total) and _is_finite_number(rebuilt_total)):
        return [_v("No State Corruption", CRITICAL, "snapshot/rebuilt total non-finite")]
    if abs(snapshot_total - rebuilt_total) > tol:
        return [_v("No State Corruption", CONSTITUTIONAL,
                   f"snapshot {snapshot_total} != event-log rebuild {rebuilt_total}")]
    return []
