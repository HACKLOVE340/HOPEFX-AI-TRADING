# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One append-only record per model call.

Before the gateway there was no record at all: `api/brain.py` called a provider
inline and, on failure, raised 502. Nothing could answer "which model answered,
what did it cost, and which legs were tried first" -- and a failed call, the one
you most need a record of, left no trace whatsoever.

**The record never contains the prompt.** Prompts on this platform carry
position data, stop levels and, as the audit found in `changes` payloads,
occasionally credentials. The record holds a SHA-256 of the prompt so two calls
can be recognised as identical without the text being retained anywhere.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Calls retained in memory for the fast read surface (`/ai-core/calls`). This
#: is a CACHE, not the record of account.
#:
#: This comment used to read "the durable sink is the config store via the
#: control plane". No code wrote there. So the trail was 500 rows in RAM that a
#: restart erased, while spec §6 promised an immutable audit trail and
#: exportable regulatory-grade logs -- a control documented accurately,
#: believed, and never wired. `_SINK` below is the sink that sentence claimed.
_LIMIT = 500

_RECORDS: list[dict[str, Any]] = []

#: Where a record goes to survive the process. Set by
#: `core.startup_factories.init_ai_audit_sink`; None means nothing durable is
#: installed, which `durable_sink_installed()` reports honestly rather than
#: letting the trail quietly become a ring buffer again.
_SINK: Callable[[dict[str, Any]], Any] | None = None


def set_durable_sink(sink: Callable[[dict[str, Any]], Any] | None) -> None:
    """Install the durable writer. One writer, so one hash chain."""
    global _SINK
    _SINK = sink


def durable_sink_installed() -> bool:
    """Whether records are actually leaving the process.

    The health surface asks this. A deployment answering False is one whose
    audit trail does not survive a restart, and that is worth being able to see
    rather than infer.
    """
    return _SINK is not None


def prompt_fingerprint(prompt: str) -> str:
    """A stable hash of the prompt. Never store or log the prompt itself."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def record_call(
    *,
    operator: str,
    role: str,
    prompt: str,
    attempts: list[dict[str, Any]],
    served_by: str | None,
    model: str | None,
    latency_ms: float,
    cost_usd: float,
    tokens_in: int,
    tokens_out: int,
) -> dict[str, Any]:
    """Append one record and return it.

    `attempts` names every leg tried and why each failed, so a chain that
    silently degrades to its third vendor is visible rather than merely slower.
    """
    entry: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "operator": operator,
        "role": role,
        "prompt_sha256": prompt_fingerprint(prompt),
        "attempts": attempts,
        "served_by": served_by,
        "model": model,
        "latency_ms": round(latency_ms, 2),
        "cost_usd": round(cost_usd, 6),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
    _RECORDS.append(entry)
    del _RECORDS[:-_LIMIT]
    _write_durable(entry)
    if served_by is None:
        logger.warning(
            "ai.gateway: no leg served role=%s operator=%s attempts=%s",
            role,
            operator,
            [a.get("reason") for a in attempts],
        )
    return entry


def _write_durable(entry: dict[str, Any]) -> None:
    """Persist `entry`, or say loudly that it could not be persisted.

    Two rules, and they pull in opposite directions:

    **An audit failure must not fail the trade.** A database outage must not
    take down the model call that was about to answer a risk question. So the
    write is best-effort and the exception is caught.

    **A swallowed failure is worse than no audit at all**, because the
    documentation still promises a regulatory-grade trail and nobody knows it
    stopped. So it is caught at ERROR with the record's identity, never at
    DEBUG, and never bare. `hopefx-dead-controls` exists for exactly the
    variant of this that logs at DEBUG and moves on.
    """
    sink = _SINK
    if sink is None:
        return
    try:
        sink(entry)
    except Exception:
        # A copy of what was lost, minus nothing that was ever secret: the
        # entry holds a fingerprint, not a prompt.
        logger.exception(
            "ai.gateway.audit: DURABLE WRITE FAILED -- this call is not in the "
            "permanent record. operator=%s role=%s model=%s cost_usd=%s at=%s",
            entry.get("operator"),
            entry.get("role"),
            entry.get("model"),
            entry.get("cost_usd"),
            entry.get("at"),
        )


def records() -> list[dict[str, Any]]:
    """The retained records, newest last."""
    return list(_RECORDS)


def reset_for_testing() -> None:
    """Clear the ring AND the sink.

    Clearing only the ring left one test's fake sink installed for the next,
    which is how a test suite starts asserting against another test's writes.
    """
    _RECORDS.clear()
    set_durable_sink(None)


__all__ = [
    "durable_sink_installed",
    "prompt_fingerprint",
    "record_call",
    "records",
    "reset_for_testing",
    "set_durable_sink",
]
