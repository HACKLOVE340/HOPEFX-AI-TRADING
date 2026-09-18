# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§16: five memory tiers, distinguished by how long they last.

`ai/memory/store.py` holds what a *department* has seen. This holds what the AI
knows about working with one *operator*, and the two are different questions:
"what has Risk & Compliance observed" versus "what were we in the middle of".

## The tiers differ by retention, and the retention is enforced

Working memory that survives the turn is not working memory, it is a leak with
a label. Each boundary below actually clears its tier, and a test asserts it —
because a tier list in a docstring with one dict behind it is five names for one
thing.

    working    the current turn      cleared by end_turn
    session    the current session   cleared by end_session (which ends the turn)
    episodic   significant events    survives a session, bounded
    project    long-running work     survives a session, bounded
    long_term  approved facts        written only through ai/memory/governance.py

`long_term` has no public `remember` path of its own by design: reaching it
requires an approval, and a second door into the same room is the shape
`ai/policy/roles.py` exists to prevent.

## Everything carries provenance and is scanned

`source` is required. An unattributable memory is one nobody can check, and it
will be handed back to a model later as though somebody had. And every value
goes through `scan_output` before it is stored, at every tier: memory is
durable, so a secret written here outlives the conversation that leaked it.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from ai.guardrails.output import scan_output

logger = logging.getLogger(__name__)

#: Ordered shortest-lived to longest.
TIERS: tuple[str, ...] = ("working", "session", "episodic", "project", "long_term")

#: Entries kept per (operator, tier).
#:
#: Working and session are small because they are a scratchpad, not a record.
#: Episodic is larger because a significant event is worth keeping and there are
#: not many. The durable record of what happened is the audit trail, which has
#: its own retention and its own hash chain; none of this is that.
LIMITS: dict[str, int] = {
    "working": 50,
    "session": 200,
    "episodic": 500,
    "project": 500,
    "long_term": 500,
}

#: Cleared when a turn ends. Anything not here survives it.
_TURN_SCOPED = ("working",)

#: Cleared when a session ends — including the turn inside it, because a turn
#: cannot outlive the session it happened in.
_SESSION_SCOPED = ("working", "session")

_LOCK = threading.Lock()
_IDS = itertools.count(1)
#: A plain dict, not a defaultdict: `_bucket` creates each deque with the
#: tier's own maxlen, and a default factory would silently create an
#: unbounded one for anything that reached this dict another way.
_ENTRIES: dict[tuple[str, str], deque[dict[str, Any]]] = {}


def _bucket(operator: str, tier: str) -> deque[dict[str, Any]]:
    key = (operator, tier)
    if key not in _ENTRIES:
        _ENTRIES[key] = deque(maxlen=LIMITS[tier])
    return _ENTRIES[key]


def remember(
    tier: str,
    *,
    operator: str,
    kind: str,
    value: Any,
    source: str,
    **extra: Any,
) -> dict[str, Any]:
    """Store one thing at one tier, and return the stored entry."""
    if tier not in LIMITS:
        raise ValueError(f"unknown tier {tier!r}; a typo must not open a memory nobody reads")
    if not operator.strip():
        raise ValueError("a memory entry belongs to one operator")
    if not kind.strip():
        raise ValueError("a memory entry needs a kind")
    if not source.strip():
        # An unattributable memory is one nobody can check, and it will be
        # handed back to a model later as though somebody had.
        raise ValueError("a memory entry needs a source; provenance is not optional")

    try:
        encoded = json.dumps(value, sort_keys=True, default=str)
    except TypeError as exc:
        raise ValueError(f"memory value is not JSON-serialisable: {exc}") from None

    # Before storage, at every tier. Durable memory is exactly where a leaked
    # credential does the most damage.
    scan_output(encoded)

    entry = {
        "id": f"m{next(_IDS)}",
        "tier": tier,
        "operator": operator,
        "kind": kind,
        "value": value,
        "source": source,
        "at": datetime.now(UTC).isoformat(),
        **extra,
    }
    with _LOCK:
        _bucket(operator, tier).append(entry)
    return entry


def recall(tier: str, *, operator: str, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """What this operator has at this tier, newest first."""
    if tier not in LIMITS:
        raise ValueError(f"unknown tier {tier!r}")
    with _LOCK:
        rows = list(_bucket(operator, tier))
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return list(reversed(rows))[: max(0, limit)]


def recall_all(*, operator: str) -> dict[str, list[dict[str, Any]]]:
    """Every tier at once, for review and for deletion."""
    return {tier: recall(tier, operator=operator, limit=LIMITS[tier]) for tier in TIERS}


def end_turn(operator: str) -> int:
    """A turn ended. Returns how many entries that discarded."""
    return _clear(operator, _TURN_SCOPED)


def end_session(operator: str) -> int:
    """A session ended. Ends the turn inside it too."""
    return _clear(operator, _SESSION_SCOPED)


def _clear(operator: str, scoped: tuple[str, ...]) -> int:
    removed = 0
    with _LOCK:
        for tier in scoped:
            bucket = _ENTRIES.get((operator, tier))
            if bucket:
                removed += len(bucket)
                bucket.clear()
    return removed


def forget_operator(operator: str) -> int:
    """Drop everything at every tier for one operator.

    Used by `ai/memory/governance.py`. Deliberately not exported as a casual
    convenience: deletion has a governed path with a report, and a second
    unreported one would make the report a partial truth.
    """
    removed = 0
    with _LOCK:
        for tier in TIERS:
            bucket = _ENTRIES.pop((operator, tier), None)
            if bucket:
                removed += len(bucket)
    return removed


def find(entry_id: str, *, operator: str) -> dict[str, Any] | None:
    """One entry, if it belongs to this operator.

    Scoped on purpose: an id is a guessable handle, and a lookup that ignored
    the owner would be a read of somebody else's memory by trying numbers.
    """
    with _LOCK:
        for tier in TIERS:
            for entry in _ENTRIES.get((operator, tier), ()):
                if entry["id"] == entry_id:
                    return entry
    return None


def stats(*, operator: str) -> dict[str, int]:
    return {tier: len(_ENTRIES.get((operator, tier), ())) for tier in TIERS}


def reset_for_testing() -> None:
    with _LOCK:
        _ENTRIES.clear()


__all__ = [
    "LIMITS",
    "TIERS",
    "end_session",
    "end_turn",
    "find",
    "forget_operator",
    "recall",
    "recall_all",
    "remember",
    "reset_for_testing",
    "stats",
]
