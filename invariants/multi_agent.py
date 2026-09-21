# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.multi_agent — multi-agent society & emergent-behavior invariants.

Pure predicates from the framework's multi-agent-society section: no collusion,
no deadlock, no circular delegation/approval, bounded conflict, fair resource
allocation, and detection of unexpected emergent behavior. list[Violation].
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


def verify_no_deadlock(waiting_on: Mapping[Any, Any]) -> list[Violation]:
    """Agent wait-for graph must be acyclic (no deadlock)."""
    # Follow each chain; a revisit means a wait cycle.
    for start in waiting_on:
        seen: set[Any] = set()
        node = start
        while node in waiting_on:
            if node in seen:
                return [_v("No Unbounded Failure", CRITICAL, "agent deadlock: cycle in wait-for graph")]
            seen.add(node)
            node = waiting_on[node]
    return []


def verify_no_collusion(off_book_messages: int) -> list[Violation]:
    """Agents must coordinate only through audited channels — off-book coordination
    that could manipulate markets is collusion."""
    if off_book_messages > 0:
        return [
            _v(
                "No Compliance Breach",
                CONSTITUTIONAL,
                f"{off_book_messages} off-book inter-agent message(s) — possible collusion",
            )
        ]
    return []


def verify_conflict_rate(conflict_rate: float, threshold: float) -> list[Violation]:
    if _is_finite_number(conflict_rate) and conflict_rate > threshold:
        return [
            _v("No Unexplained System Behavior", WARNING, f"inter-agent conflict rate {conflict_rate} > {threshold}")
        ]
    return []


def verify_resource_fairness(allocations: Iterable[float], max_share: float = 0.7) -> list[Violation]:
    """No single agent may starve others by hogging shared resources."""
    vals = [a for a in allocations if _is_finite_number(a) and a >= 0]
    total = sum(vals)
    if total > 0 and max(vals) / total > max_share:
        return [
            _v(
                "No Unbounded Failure",
                WARNING,
                f"resource unfairness: one agent holds {max(vals) / total:.0%} (> {max_share:.0%})",
            )
        ]
    return []


def verify_no_circular_delegation(delegations: Mapping[Any, Any]) -> list[Violation]:
    """Authority delegation must not form loops (A→B→A)."""
    for start in delegations:
        seen: set[Any] = set()
        node = start
        while node in delegations:
            if node in seen:
                return [_v("No Loss Of Human Control", CONSTITUTIONAL, "circular authority delegation detected")]
            seen.add(node)
            node = delegations[node]
    return []


def verify_emergent_behavior(anomaly_score: float, threshold: float) -> list[Violation]:
    """Unexpected collective behavior (unplanned coordination, capital flows) must
    be flagged for human review."""
    if _is_finite_number(anomaly_score) and anomaly_score > threshold:
        return [
            _v(
                "No Unexplained System Behavior",
                CRITICAL,
                f"emergent-behavior anomaly score {anomaly_score} > {threshold} — needs review",
            )
        ]
    return []


def verify_agent_count_bounded(active_agents: int, max_agents: int) -> list[Violation]:
    """Guard against uncontrolled agent proliferation."""
    if active_agents > max_agents:
        return [
            _v("No Loss Of Human Control", CRITICAL, f"agent proliferation: {active_agents} active > max {max_agents}")
        ]
    return []
