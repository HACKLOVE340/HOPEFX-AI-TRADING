# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Data — §11's data agent: acquisition, validation, freshness. Read-only.

`data_layer.quality.engine.DataQualityEngine` already validates ticks, tracks
per-source latency and decides what counts as stale. This is the agent that can
be asked about it.

## The rule that matters most here

**An unavailable reading is not a healthy one.** Of all four agents added in
this pass, this is the one where inventing an answer does concrete harm: a
freshness figure nobody measured reports a dead feed as live, and everything
downstream — the staleness gate, the presence, the risk manager's own view of
whether prices can be trusted — is built on the assumption that when this says
fresh, something checked.

So every handler returns `available: False` with a reason and **no reading at
all** when the engine cannot be reached. A caller that skipped the check finds
nothing that looks like a measurement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(reason: str) -> dict[str, Any]:
    """Carries no `sources`, no `stale`, no `latency_ms`, no `confidence`."""
    return {"available": False, "reason": reason}


def _default_engine() -> Any:
    from core.app_state import app_state

    engine = getattr(app_state, "data_quality_engine", None)
    if engine is None:
        raise RuntimeError("no data quality engine is constructed in this process")
    return engine


def feed_health(*, engine: Callable[[], Any] | None = None, **_: Any) -> dict[str, Any]:
    """Per-source health, as the quality engine already computes it."""
    try:
        instance = (engine or _default_engine)()
        health = instance.get_source_health()
    except Exception as exc:
        logger.info("ai.departments.data: feed health unavailable: %s", exc)
        return _unavailable(str(exc))
    return {"available": True, "sources": health}


def stale_sources(*, engine: Callable[[], Any] | None = None, **_: Any) -> dict[str, Any]:
    """Which sources the engine currently considers stale.

    An empty list means "the engine checked and found none". It is not the same
    fact as `available: False`, which means nobody checked — and those two
    render identically if a caller only looks at the list.
    """
    try:
        instance = (engine or _default_engine)()
        health = instance.get_source_health()
    except Exception as exc:
        logger.info("ai.departments.data: staleness unavailable: %s", exc)
        return _unavailable(str(exc))

    stale = [name for name, state in health.items() if bool(state.get("stale"))]
    return {
        "available": True,
        "stale": stale,
        "checked": sorted(health),
        "note": (
            "An empty `stale` list means every source named in `checked` was measured and none "
            "was stale. It does not mean nothing was checked — that is `available: false`."
        ),
    }


__all__ = ["feed_health", "stale_sources"]
