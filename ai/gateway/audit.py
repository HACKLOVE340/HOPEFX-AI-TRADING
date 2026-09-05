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
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Calls retained in memory. The durable sink is the config store via the
#: control plane; this bound stops an unbounded list in a long-lived process.
_LIMIT = 500

_RECORDS: list[dict[str, Any]] = []


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
    if served_by is None:
        logger.warning(
            "ai.gateway: no leg served role=%s operator=%s attempts=%s",
            role,
            operator,
            [a.get("reason") for a in attempts],
        )
    return entry


def records() -> list[dict[str, Any]]:
    """The retained records, newest last."""
    return list(_RECORDS)


def reset_for_testing() -> None:
    _RECORDS.clear()


__all__ = ["prompt_fingerprint", "record_call", "records", "reset_for_testing"]
