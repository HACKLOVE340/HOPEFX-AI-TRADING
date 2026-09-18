# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Durable department memory, on the table the migration creates.

Without this, everything a department observes lives in a process-local deque
and evaporates on restart — the same defect the gateway audit trail had, in the
layer the agentic loop is about to be built on. A department that forgets every
deploy cannot notice that a violation has happened before.

**Trimmed on write, per (department, kind).** The application enforces the cap
rather than a database job, so the bound holds on SQLite and PostgreSQL alike
without a scheduled task nobody remembers to run. Per pair, so a busy fill
history cannot evict a department's last heartbeat.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ai.memory.store import MAX_PER_KIND

logger = logging.getLogger(__name__)

#: Trim runs every N writes rather than on every one. A DELETE on each insert
#: doubles the write cost to enforce a bound that only matters in aggregate;
#: the deque in `store.py` keeps the in-process view exact meanwhile.
_TRIM_EVERY = 50


class SqlMemoryBackend:
    """`remember`/`recall` against `ai_department_memory`."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._writes_since_trim = 0

    def write(self, entry: dict[str, Any]) -> None:
        from database.models import DepartmentMemoryEntry

        with self._session_factory() as session:
            session.add(
                DepartmentMemoryEntry(
                    department=entry["department"],
                    kind=entry["kind"],
                    value_json=json.dumps(entry["value"], sort_keys=True, default=str),
                )
            )
            session.commit()

        self._writes_since_trim += 1
        if self._writes_since_trim >= _TRIM_EVERY:
            self._writes_since_trim = 0
            self._trim(entry["department"], entry["kind"])

    def read(self, department: str, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        from database.models import DepartmentMemoryEntry

        with self._session_factory() as session:
            query = session.query(DepartmentMemoryEntry).filter(
                DepartmentMemoryEntry.department == department,
            )
            if kind:
                query = query.filter(DepartmentMemoryEntry.kind == kind)
            rows = query.order_by(DepartmentMemoryEntry.id.desc()).limit(max(0, limit)).all()

        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row.value_json)
            except (TypeError, ValueError):
                # A row that will not parse is skipped and reported rather than
                # returned as a null reading an agent might act on.
                logger.error("ai.memory: unparseable row id=%s for %s/%s", row.id, row.department, row.kind)
                continue
            out.append(
                {
                    "department": row.department,
                    "kind": row.kind,
                    "value": value,
                    "at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return out

    def _trim(self, department: str, kind: str) -> None:
        """Drop everything past `MAX_PER_KIND` for one (department, kind)."""
        from database.models import DepartmentMemoryEntry

        try:
            with self._session_factory() as session:
                keep = (
                    session.query(DepartmentMemoryEntry.id)
                    .filter(
                        DepartmentMemoryEntry.department == department,
                        DepartmentMemoryEntry.kind == kind,
                    )
                    .order_by(DepartmentMemoryEntry.id.desc())
                    .limit(MAX_PER_KIND)
                    .all()
                )
                if len(keep) < MAX_PER_KIND:
                    return
                cutoff = min(row_id for (row_id,) in keep)
                session.query(DepartmentMemoryEntry).filter(
                    DepartmentMemoryEntry.department == department,
                    DepartmentMemoryEntry.kind == kind,
                    DepartmentMemoryEntry.id < cutoff,
                ).delete(synchronize_session=False)
                session.commit()
        except Exception:
            # Retention is housekeeping. Failing it must not fail the write that
            # triggered it, but it must not be silent either — unbounded growth
            # in a table nobody watches is how a disk fills.
            logger.exception("ai.memory: trim failed for %s/%s", department, kind)


__all__ = ["SqlMemoryBackend"]
