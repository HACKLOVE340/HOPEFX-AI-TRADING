# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§16: the operator's control over what the AI remembers.

Review, correction, deletion, and the approval a fact needs before it becomes
long-term.

## Deletion reports what it could not reach

This is the one thing in the module that can be wrong in a way nobody notices.
A `forget()` that clears the in-process tiers and leaves the durable rows
returns success, prints a reassuring count, and has deleted nothing that
survives a restart — the operator was told their data was gone.

`SqlMemoryBackend` had `write` and `read` and no `delete`, so that was not a
hypothetical: it was the only outcome available. It has a `delete` now, and
this module still does not assume one exists. A backend without it makes
`complete` false and names what was left behind, because **an incomplete
deletion reported as complete is worse than a deletion that failed loudly.**

## Correction is not overwriting

`correct()` keeps `corrected_from` and `corrected_by`. Silently replacing a
value loses the fact that the AI once believed something else, which is exactly
what somebody auditing a wrong decision needs to find.

## Long-term needs an approval

The staged note on this capability read "durable storage exists; approval
governance does not" — which means "long-term" was a synonym for "everything,
for ever". A proposal sits in `pending_long_term` until somebody approves it,
and the approver's name is stored with it.
"""

from __future__ import annotations

import itertools
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ai.memory import graph, store, tiers

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_IDS = itertools.count(1)

#: operator -> proposal id -> proposal, awaiting approval.
_PENDING: dict[str, dict[str, dict[str, Any]]] = {}


@dataclass(frozen=True)
class ForgetResult:
    """What a deletion actually managed to remove."""

    operator: str
    #: Entries dropped from the tiered stores.
    removed: int = 0
    #: Edges dropped from the knowledge graph.
    edges: int = 0
    #: Rows the durable backend reported deleting. Zero with no backend.
    durable_rows: int = 0
    #: Stores that could not be cleared, and why. Empty means everything was.
    unreachable: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        """True only when nothing was left behind.

        A property rather than a stored flag so it cannot be set to True beside
        a non-empty `unreachable` — the two would then disagree, and a caller
        reading only the flag would report a clean deletion.
        """
        return not self.unreachable

    def as_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "removed": self.removed,
            "edges": self.edges,
            "durable_rows": self.durable_rows,
            "complete": self.complete,
            "unreachable": list(self.unreachable),
        }


def forget(*, operator: str) -> ForgetResult:
    """Delete everything remembered about one operator, and say what remains."""
    removed = tiers.forget_operator(operator)
    edges = graph.forget_operator(operator)

    with _LOCK:
        _PENDING.pop(operator, None)

    durable_rows = 0
    unreachable: list[str] = []
    backend = store.current_backend()
    if backend is not None:
        deleter = getattr(backend, "delete", None)
        if not callable(deleter):
            # `SqlMemoryBackend` is deliberately in this branch. Its table is
            # keyed by DEPARTMENT and has no operator column, so an
            # operator-scoped delete is not expressible against it without a
            # migration — and a `delete(operator=...)` that quietly matched
            # nothing and returned 0 would be worse than none: it would make
            # this result complete while deleting nothing. Saying so is the
            # honest answer, and it is the whole reason this field exists.
            unreachable.append(
                "The durable department-memory store cannot be deleted by operator: it is keyed "
                "by department and has no operator column, so anything it recorded about this "
                "operator is still on disk and will return after a restart."
            )
        else:
            try:
                durable_rows = int(deleter(operator=operator) or 0)
            except Exception as exc:
                logger.exception("ai.memory: durable delete failed for %s", operator)
                unreachable.append(f"The durable memory backend refused the delete: {exc}")

    return ForgetResult(
        operator=operator,
        removed=removed,
        edges=edges,
        durable_rows=durable_rows,
        unreachable=tuple(unreachable),
    )


def review(*, operator: str) -> dict[str, Any]:
    """Everything remembered about one operator, by tier.

    Scoped to the operator asked about and nothing wider. "Review" that showed a
    subset would not be review, and one that showed somebody else's would be the
    leak this platform has already shipped once.
    """
    by_tier = tiers.recall_all(operator=operator)
    return {
        "operator": operator,
        "tiers": {tier: rows for tier, rows in by_tier.items()},
        "total": sum(len(rows) for rows in by_tier.values()),
        "graph_edges": graph.edge_count(operator),
        "pending_long_term": len(pending_long_term(operator=operator)),
    }


def correct(entry_id: str, *, operator: str, value: Any, by: str) -> dict[str, Any] | None:
    """Replace a remembered value, keeping that it was replaced.

    Returns None when the entry is not this operator's — the same answer as
    "no such entry", deliberately, so an id cannot be used to discover which
    entries exist for somebody else.
    """
    entry = tiers.find(entry_id, operator=operator)
    if entry is None:
        return None

    previous = entry.get("value")
    entry["corrected_from"] = previous
    entry["corrected_by"] = by
    entry["corrected_at"] = datetime.now(UTC).isoformat()
    entry["value"] = value
    return entry


def propose_long_term(*, operator: str, kind: str, value: Any, source: str) -> dict[str, Any]:
    """Ask for a fact to be kept permanently. It is not kept until approved."""
    proposal = {
        "id": f"p{next(_IDS)}",
        "operator": operator,
        "kind": kind,
        "value": value,
        "source": source,
        "proposed_at": datetime.now(UTC).isoformat(),
    }
    with _LOCK:
        _PENDING.setdefault(operator, {})[proposal["id"]] = proposal
    return proposal


def approve_long_term(proposal_id: str, *, by: str) -> bool:
    """Approve a proposal. False when there was nothing pending to approve.

    Approving twice returns False rather than storing the fact twice: the
    second call is usually a retry, not a second decision.
    """
    owner: str | None = None
    proposal: dict[str, Any] | None = None
    with _LOCK:
        for candidate, proposals in _PENDING.items():
            found = proposals.pop(proposal_id, None)
            if found is not None:
                owner, proposal = candidate, found
                break
    if proposal is None or owner is None:
        return False

    tiers.remember(
        "long_term",
        operator=owner,
        kind=proposal["kind"],
        value=proposal["value"],
        source=proposal["source"],
        approved_by=by,
        approved_at=datetime.now(UTC).isoformat(),
    )
    return True


def reject_long_term(proposal_id: str, *, by: str) -> bool:
    """Decline a proposal. Recorded as a decision rather than a silent drop."""
    with _LOCK:
        for proposals in _PENDING.values():
            proposal = proposals.pop(proposal_id, None)
            if proposal is not None:
                logger.info("ai.memory: long-term proposal %s rejected by %s", proposal_id, by)
                return True
    return False


def pending_long_term(*, operator: str) -> list[dict[str, Any]]:
    with _LOCK:
        return list(_PENDING.get(operator, {}).values())


def reset_for_testing() -> None:
    with _LOCK:
        _PENDING.clear()


__all__ = [
    "ForgetResult",
    "approve_long_term",
    "correct",
    "forget",
    "pending_long_term",
    "propose_long_term",
    "reject_long_term",
    "reset_for_testing",
    "review",
]
