# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.systems — distributed-systems, streaming, cache & lifecycle invariants.

Pure predicates from the framework's distributed/event-sourcing/cache/stream and
"zombie"/"circular" detection sections: single-leader/no-split-brain, quorum,
exactly-once streams, stream lag, cache age/version, acyclic dependency graphs,
circular approval/authority/capital/delegation loops, and zombie process/agent/
capital/position detection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    Violation,
    _is_finite_number,
    _v,
)


# ── distributed consensus ───────────────────────────────────────────────────────
def verify_single_leader(leader_count: int) -> list[Violation]:
    """A cluster must have exactly one leader (no split-brain, no leaderless)."""
    if leader_count != 1:
        sev = CONSTITUTIONAL if leader_count > 1 else CRITICAL
        kind = "split-brain" if leader_count > 1 else "leaderless"
        return [_v("No State Corruption", sev, f"{kind}: {leader_count} leaders")]
    return []


def verify_quorum(healthy_nodes: int, total_nodes: int) -> list[Violation]:
    """Cluster must retain quorum (> half)."""
    if total_nodes > 0 and healthy_nodes <= total_nodes // 2:
        return [
            _v("No Critical Single Point Of Failure", CRITICAL, f"quorum lost: {healthy_nodes}/{total_nodes} healthy")
        ]
    return []


# ── event-sourcing / streaming ──────────────────────────────────────────────────
def verify_exactly_once(processed_count: int, unique_count: int) -> list[Violation]:
    """Events must be processed exactly once — duplicates corrupt state/PnL."""
    if processed_count != unique_count:
        return [
            _v(
                "No Data Corruption",
                CONSTITUTIONAL,
                f"events not exactly-once: processed {processed_count} vs unique {unique_count}",
            )
        ]
    return []


def verify_stream_lag(lag: float, limit: float, name: str = "stream") -> list[Violation]:
    if not _is_finite_number(lag):
        return [_v("No Data Corruption", CRITICAL, f"{name} lag is non-finite")]
    if lag > limit:
        return [_v("No Hidden Risk", CRITICAL, f"{name} lag {lag} exceeds limit {limit}")]
    return []


def verify_dead_letter_empty(dlq_size: int) -> list[Violation]:
    if dlq_size > 0:
        return [_v("No Silent Failure", CRITICAL, f"dead-letter queue not empty ({dlq_size} messages)")]
    return []


# ── cache correctness ───────────────────────────────────────────────────────────
def verify_cache_fresh(cache_age_ms: float, max_age_ms: float) -> list[Violation]:
    if not _is_finite_number(cache_age_ms):
        return [_v("No Data Corruption", CRITICAL, "cache age non-finite")]
    if cache_age_ms > max_age_ms:
        return [_v("No Hidden Risk", CRITICAL, f"stale cache: age {cache_age_ms}ms > {max_age_ms}ms")]
    return []


def verify_cache_version(cache_version: Any, source_version: Any) -> list[Violation]:
    if cache_version != source_version:
        return [_v("No Data Corruption", CRITICAL, f"cache version {cache_version!r} != source {source_version!r}")]
    return []


# ── dependency graph / circular detection ───────────────────────────────────────
def _has_cycle(graph: Mapping[Any, Iterable[Any]]) -> bool:
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[Any, int] = dict.fromkeys(graph, WHITE)

    def visit(n: Any) -> bool:
        color[n] = GREY
        for m in graph.get(n, ()):
            c = color.get(m, WHITE)
            if c == GREY or (c == WHITE and visit(m)):
                return True
        color[n] = BLACK
        return False

    return any(color[n] == WHITE and visit(n) for n in graph)


def verify_acyclic(
    graph: Mapping[Any, Iterable[Any]], rule: str = "No Unbounded Failure", what: str = "dependency"
) -> list[Violation]:
    """No cycles in dependency / approval / authority / capital / delegation graphs."""
    if _has_cycle(graph):
        return [_v(rule, CRITICAL, f"circular {what} chain detected (cycle in graph)")]
    return []


# ── zombie detection ────────────────────────────────────────────────────────────
def verify_no_zombies(count: int, what: str) -> list[Violation]:
    """Zombie processes/agents/capital/positions (allocated to nothing) must be 0."""
    if count > 0:
        sev = CONSTITUTIONAL if what in ("capital", "position") else CRITICAL
        return [
            _v(
                "No Hidden Exposure" if what in ("capital", "position") else "No Silent Failure",
                sev,
                f"{count} zombie {what}(s) detected",
            )
        ]
    return []


def verify_blast_radius_contained(
    failed_components: int, total_components: int, max_fraction: float = 0.5
) -> list[Violation]:
    """One failure must not be able to take down most of the platform."""
    if total_components > 0 and failed_components / total_components > max_fraction:
        return [
            _v(
                "No Unbounded Failure",
                CRITICAL,
                f"blast radius too large: {failed_components}/{total_components} components down",
            )
        ]
    return []


def verify_no_single_point_of_failure(dependencies: Mapping[str, Mapping[str, Any]]) -> list[Violation]:
    """No critical dependency may be a single point of failure.

    ``dependencies`` maps name -> {"critical": bool, "redundancy": int,
    "failover": bool}. A *critical* dependency with redundancy < 2 and no
    failover is a SPOF: its loss takes the platform down with no fallback.
    Non-critical or redundant/failover-capable dependencies pass.
    """
    out: list[Violation] = []
    min_redundancy = 2
    for name, spec in dependencies.items():
        if not spec.get("critical"):
            continue
        redundancy = int(spec.get("redundancy", 1))
        failover = bool(spec.get("failover", False))
        if redundancy < min_redundancy and not failover:
            out.append(
                _v(
                    "No Critical Single Point Of Failure",
                    CRITICAL,
                    f"critical dependency '{name}' is a SPOF (redundancy={redundancy}, no failover)",
                    dependency=name,
                )
            )
    return out
