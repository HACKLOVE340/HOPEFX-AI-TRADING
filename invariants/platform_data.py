# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.platform_data — database & data-store integrity.

Pure predicates for the framework's data-layer categories: primary keys unique,
foreign keys valid, no orphans, referential integrity, migrations applied,
indexes healthy, and every derived store (cache, search index, read replica,
billing rollup) agreeing with the system of record. A trading platform that
shows stale or contradictory data has a *correctness* failure even if every
service is "up". Each function returns ``list[Violation]``.
"""

from __future__ import annotations

import re
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

_RULE = "No Data Corruption"


def verify_primary_keys_unique(keys: Iterable[Any]) -> list[Violation]:
    """A primary-key column must hold no duplicates."""
    seen: set[Any] = set()
    dups: set[Any] = set()
    for k in keys:
        if k in seen:
            dups.add(k)
        seen.add(k)
    if dups:
        return [_v(_RULE, CONSTITUTIONAL, f"duplicate primary key(s): {sorted(map(str, dups))[:5]}")]
    return []


def verify_foreign_keys_valid(child_refs: Iterable[Any], parent_keys: set[Any]) -> list[Violation]:
    """Every foreign-key reference must point at an existing parent row."""
    dangling = sorted({str(r) for r in child_refs if r not in parent_keys})
    if dangling:
        return [_v(_RULE, CRITICAL, f"dangling foreign-key reference(s): {dangling[:5]}")]
    return []


def verify_no_orphans(orphan_count: int, entity: str = "row") -> list[Violation]:
    """No orphaned records (children whose parent was deleted)."""
    if orphan_count > 0:
        return [_v(_RULE, CRITICAL, f"{orphan_count} orphaned {entity}(s) detected")]
    return []


def verify_referential_integrity(violations_count: int) -> list[Violation]:
    """Database referential-integrity constraint checks must report zero failures."""
    if violations_count > 0:
        return [_v(_RULE, CONSTITUTIONAL, f"{violations_count} referential-integrity violation(s)")]
    return []


def verify_migrations_applied(applied: Iterable[Any], expected: Iterable[Any]) -> list[Violation]:
    """All expected schema migrations must be applied (no drift between code & DB)."""
    missing = sorted({str(m) for m in expected} - {str(m) for m in applied})
    if missing:
        return [_v(_RULE, CRITICAL, f"unapplied migration(s): {missing[:5]}")]
    return []


def verify_index_healthy(bloat_pct: float, max_bloat_pct: float, index: str = "") -> list[Violation]:
    """Index bloat/corruption must stay bounded (degraded indexes slow & mis-serve)."""
    if _is_finite_number(bloat_pct) and bloat_pct > max_bloat_pct:
        return [_v(_RULE, WARNING, f"index {index} bloat {bloat_pct}% exceeds {max_bloat_pct}%")]
    return []


def verify_cache_matches_db(cache_value: Any, db_value: Any, key: str = "") -> list[Violation]:
    """A cache entry must match the system of record (stale cache = wrong answer)."""
    if cache_value != db_value:
        return [_v(_RULE, CRITICAL, f"cache/DB divergence for {key!r}: cache {cache_value!r} != db {db_value!r}")]
    return []


def verify_search_matches_db(indexed_ids: set[Any], db_ids: set[Any]) -> list[Violation]:
    """The search index must reflect the database (no missing/phantom documents)."""
    missing = db_ids - indexed_ids
    phantom = indexed_ids - db_ids
    out: list[Violation] = []
    if missing:
        out.append(_v(_RULE, WARNING, f"search index missing {len(missing)} doc(s) present in DB"))
    if phantom:
        out.append(_v(_RULE, WARNING, f"search index has {len(phantom)} phantom doc(s) absent from DB"))
    return out


def verify_replica_lag(lag_seconds: float, max_lag_seconds: float) -> list[Violation]:
    """A read replica must not lag the primary past tolerance (stale reads)."""
    if _is_finite_number(lag_seconds) and lag_seconds > max_lag_seconds:
        return [_v(_RULE, WARNING, f"replica lag {lag_seconds}s exceeds {max_lag_seconds}s")]
    return []


def verify_rollup_matches_source(
    rollup_total: float, source_total: float, tol: float = 0.01, name: str = "rollup"
) -> list[Violation]:
    """A derived aggregate (billing/analytics rollup) must reconcile with its source."""
    if not (_is_finite_number(rollup_total) and _is_finite_number(source_total)):
        return [_v(_RULE, CRITICAL, f"{name} reconciliation values non-finite")]
    if abs(rollup_total - source_total) > tol:
        return [_v(_RULE, CONSTITUTIONAL, f"{name} {rollup_total} disagrees with source {source_total}")]
    return []


def verify_no_null_in_required(row: Mapping[str, Any], required_columns: Iterable[str]) -> list[Violation]:
    """NOT-NULL columns must never hold null (data-quality corruption)."""
    nulls = [c for c in required_columns if row.get(c) is None]
    if nulls:
        return [_v(_RULE, CRITICAL, f"null in required column(s): {sorted(nulls)}")]
    return []


def verify_timestamp_monotonic(timestamps: Iterable[float]) -> list[Violation]:
    """An append-only/time-series store must have non-decreasing timestamps."""
    prev: float | None = None
    for i, ts in enumerate(timestamps):
        if prev is not None and _is_finite_number(ts) and ts < prev:
            return [_v(_RULE, CRITICAL, f"non-monotonic timestamp at index {i}: {ts} < {prev}")]
        prev = ts
    return []


def verify_money_precision(column: str, sql_type: str) -> list[Violation]:
    """Monetary columns must be exact NUMERIC/DECIMAL, never FLOAT/REAL/DOUBLE —
    binary floats silently lose cents (master-registry #66)."""
    t = str(sql_type or "").upper()
    if any(bad in t for bad in ("FLOAT", "REAL", "DOUBLE")):
        return [
            _v(
                _RULE,
                CONSTITUTIONAL,
                f"monetary column {column!r} is {sql_type!r} — use NUMERIC/DECIMAL, not binary float",
            )
        ]
    return []


def verify_enum_value(column: str, value: Any, allowed: set[Any]) -> list[Violation]:
    """A status/type column may only hold a value from its declared enum
    (check-constraint equivalent, master-registry #68)."""
    if allowed and value not in allowed:
        return [_v(_RULE, CRITICAL, f"{column}={value!r} not in allowed enum {sorted(map(str, allowed))[:8]}")]
    return []


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def verify_email_format(email: str) -> list[Violation]:
    """A stored user email must be syntactically valid (master-registry #70)."""
    if not email or not _EMAIL_RE.match(str(email)):
        return [_v(_RULE, WARNING, f"invalid email format: {email!r}")]
    return []
