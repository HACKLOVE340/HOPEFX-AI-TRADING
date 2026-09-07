# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What each department persists. Spec §2's `memory/`, the third of four parts.

`ai/departments/__init__.py` gave every department a `memory` field typed
`tuple[str, ...]` — "execution/fill history", "slippage per symbol", "drawdown
curve", "past violations". Labels on a dataclass. Nothing in the tree stored,
recalled, or retained anything, so an agent could act and never learn.

**Structured recall, not semantic.** Every use the spec names is "what happened,
in this department, of this kind, most recently". That wants typed, time-ordered,
filterable recall — not vector search. `pgvector` is not a dependency here and
adding one for a capability nothing asked for is the wrong trade; the shape below
leaves room for semantic recall later, and `GatewayClient.embed_sync` already
exists for that half when it is wanted.

**Recall is a tool, not a function anyone can call.** `ai/departments` registers
`<department>.recall_memory` on the bus, so reading memory passes the permission
registry and `enforce_agent_action` like every other capability. A module-level
`recall()` reachable from anywhere would be a second door into the same room —
the shape `ai/policy/roles.py` exists to prevent.

**Three things are refused rather than stored:** an unknown department (a typo
must not open a memory nobody reads), a value that will not serialise, and
anything carrying a credential. That last one matters most: memory is durable,
so a secret written here outlives the conversation that leaked it.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from ai.guardrails.output import scan_output

logger = logging.getLogger(__name__)

#: Entries kept per (department, kind).
#:
#: Memory that only grows is a cost and, for anything touching positions, a
#: liability. 500 covers "what has this department seen lately" — the question
#: the awareness layer and the agentic loop actually ask — without becoming an
#: archive. The durable record of what happened is the audit trail, which has
#: its own retention and its own hash chain; this is working memory.
MAX_PER_KIND = 500

#: (department, kind) -> newest-last deque. The default store.
_ENTRIES: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=MAX_PER_KIND))

#: Optional durable backend, installed at startup. None keeps everything
#: process-local, which is correct for a dev box and honest about it.
_BACKEND: Any | None = None


def set_backend(backend: Any | None) -> None:
    """Install (or remove) the durable store."""
    global _BACKEND
    _BACKEND = backend


def backend_is_durable() -> bool:
    """Whether memory survives a restart. Read by the health surface."""
    return _BACKEND is not None


def current_backend() -> Any | None:
    """The installed durable backend, or None.

    Public so `ai/memory/governance.py` can ask what it supports without
    reaching into a private. Deletion has to know whether the store it is
    clearing can actually be cleared, and a governed deletion that guessed
    would be the failure that module exists to prevent.
    """
    return _BACKEND


def _known_departments() -> frozenset[str]:
    # Imported lazily: `ai.departments` imports the handlers that import this.
    from ai.departments import DEPARTMENTS

    return frozenset(DEPARTMENTS)


def remember(department: str, kind: str, value: Any) -> dict[str, Any]:
    """Persist one thing a department observed, and return the stored entry."""
    if department not in _known_departments():
        raise ValueError(f"unknown department {department!r}; a typo must not open a memory nobody reads")
    if not kind or not kind.strip():
        raise ValueError("a memory entry needs a kind")

    try:
        encoded = json.dumps(value, sort_keys=True, default=None)
    except TypeError as exc:
        raise ValueError(f"memory value is not JSON-serialisable: {exc}") from None
    if "null" in encoded and value is not None and encoded == "null":
        raise ValueError("memory value is not JSON-serialisable")

    # Durable memory is exactly where a leaked credential does the most damage:
    # it outlives the conversation, and the next recall hands it to a model
    # again. Raises GuardrailViolation, which callers already know not to retry.
    scan_output(encoded)

    entry = {
        "department": department,
        "kind": kind,
        "value": value,
        "at": datetime.now(UTC).isoformat(),
    }

    # The deque's own maxlen does the trimming: appending past it drops from the
    # left, which is the oldest. Per (department, kind), so a busy fill history
    # cannot evict a department's last heartbeat.
    _ENTRIES[(department, kind)].append(entry)

    if _BACKEND is not None:
        try:
            _BACKEND.write(entry)
        except Exception:
            # Best-effort, loudly. Memory is not on the trading path, so a
            # backend fault must not fail the caller — but a department that
            # has silently stopped remembering is a department whose awareness
            # and loop are quietly degrading.
            logger.exception(
                "ai.memory: DURABLE WRITE FAILED — %s/%s is only in this process now",
                department,
                kind,
            )
    return entry


def recall(department: str, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """What this department has seen, newest first.

    Scoped to one department by construction: Risk & Compliance must not read
    Platform Engineering's audit history just because both live in one table.
    """
    if department not in _known_departments():
        raise ValueError(f"unknown department {department!r}")

    if _BACKEND is not None:
        try:
            return list(_BACKEND.read(department, kind=kind, limit=limit))
        except Exception:
            logger.exception("ai.memory: durable read failed for %s; falling back to this process", department)

    keys = [(department, kind)] if kind else [k for k in _ENTRIES if k[0] == department]
    rows: list[dict[str, Any]] = []
    for key in keys:
        rows.extend(_ENTRIES.get(key, ()))
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[: max(0, limit)]


def stats() -> dict[str, Any]:
    """Per-department entry counts, for the AI Core read surface."""
    counts: dict[str, int] = defaultdict(int)
    for (department, _kind), entries in _ENTRIES.items():
        counts[department] += len(entries)
    return {"durable": backend_is_durable(), "entries": dict(counts), "max_per_kind": MAX_PER_KIND}


def reset_for_testing() -> None:
    _ENTRIES.clear()
    set_backend(None)


__all__ = [
    "current_backend",
    "MAX_PER_KIND",
    "backend_is_durable",
    "recall",
    "remember",
    "reset_for_testing",
    "set_backend",
    "stats",
]
