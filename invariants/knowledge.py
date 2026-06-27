# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.knowledge — RAG, knowledge-graph & long-term-memory invariants.

Pure predicates from the framework's knowledge/memory sections: retrieved
documents exist & come from trusted sources & are fresh; knowledge graph has no
orphan/contradictory entities or invalid relations; long-term memory respects
aging and has no contradictions. Each returns list[Violation].
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)


def verify_retrieval(
    doc_ids: Iterable[Any], known_ids: set[Any], trusted_sources: set[str], sources: Iterable[str]
) -> list[Violation]:
    """RAG: every retrieved doc must exist and come from a trusted source."""
    out: list[Violation] = []
    missing = [d for d in doc_ids if d not in known_ids]
    if missing:
        out.append(_v("No Data Corruption", CRITICAL, f"retrieved {len(missing)} non-existent document(s)"))
    untrusted = [s for s in sources if s not in trusted_sources]
    if untrusted:
        out.append(_v("No Compliance Breach", CRITICAL, f"retrieval from untrusted sources: {untrusted[:5]}"))
    return out


def verify_context_freshness(age_s: float, max_age_s: float) -> list[Violation]:
    if _is_finite_number(age_s) and age_s > max_age_s:
        return [_v("No Hidden Risk", WARNING, f"retrieval context stale: {age_s}s > {max_age_s}s")]
    return []


def verify_no_orphan_entities(entity_ids: set[Any], referenced_ids: set[Any]) -> list[Violation]:
    """Knowledge-graph: every referenced entity must exist."""
    orphans = referenced_ids - entity_ids
    if orphans:
        return [_v("No Data Corruption", CRITICAL, f"knowledge graph has {len(orphans)} dangling reference(s)")]
    return []


def verify_no_contradictory_facts(contradictions: int) -> list[Violation]:
    if contradictions > 0:
        return [_v("No Data Corruption", CRITICAL, f"knowledge graph has {contradictions} contradictory fact(s)")]
    return []


def verify_memory_age(age_s: float, policy_limit_s: float) -> list[Violation]:
    """Old memory must expire per policy (no unbounded stale memory)."""
    if _is_finite_number(age_s) and age_s > policy_limit_s:
        return [_v("No Hidden Risk", WARNING, f"memory age {age_s}s exceeds policy limit {policy_limit_s}s")]
    return []


def verify_no_memory_conflict(has_contradiction: bool) -> list[Violation]:
    """Agent memory must not hold contradictory beliefs."""
    if has_contradiction:
        return [_v("No Unexplained System Behavior", CRITICAL, "contradictory entries in agent memory")]
    return []
