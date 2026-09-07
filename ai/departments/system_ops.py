# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""System — §11's system agent: infrastructure, services, resources, failures.

The measurements already existed. `ai/telemetry/` was built for §22 and is
served by `GET /api/ai-core/telemetry`; what was missing was an agent that can
be *asked* rather than an endpoint a dashboard polls. Those are different
things: an operator saying "why is everything slow" wants a sentence, and
`ai/agent/loop.py` can only produce one from a tool it is allowed to call.

## It passes the readings through, it does not summarise them into numbers

Every function here returns §22's `Reading` shape intact — value, unit,
`measured`, reason. The temptation is to flatten it: `{"cpu": 7.0}` reads
better and is the exact defect §22 exists about. `infrastructure/metrics.py`
returns early when psutil is unavailable, leaving `system_cpu_percent` unset,
and an unset `Gauge` reads back 0.0 — so the same registry's two readers
disagree about whether the machine is idle or unknown. An agent that flattened
these would tell an operator the machine is idle because nobody looked.

`unmeasured` is returned as its own key for the same reason the endpoint does
it: a caller should not have to infer absence by scanning for nulls.

## Everything here is READ_ONLY, structurally

There is no restart, no scale, no clear-cache, no kill. Not because those are
hard, but because "the machine is struggling" is precisely the moment an agent
acting on its own initiative does the most damage — and this one is reachable
from a model's tool loop. Diagnosing is what it does.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def host_resources(*, operator: str, **_: Any) -> dict[str, Any]:
    """CPU, memory, disk and GPU, with §22's absences intact.

    `operator` is accepted and unused: every department action takes it so the
    permission gate has one signature to check, and an action that quietly
    ignored it would be the one nobody notices is unscoped. Host resources are
    genuinely not per-operator — there is one machine.
    """
    try:
        from ai.telemetry import host
    except Exception as exc:  # pragma: no cover - import-time environment problem
        return _unavailable(f"the telemetry package could not be imported: {type(exc).__name__}")

    try:
        snapshot = host.snapshot()
    except Exception as exc:
        logger.warning("system_ops: host snapshot failed: %s", exc)
        return _unavailable(f"the host probes failed: {type(exc).__name__}")

    return {
        "available": True,
        # Passed through, not flattened. See the module docstring.
        "readings": snapshot.get("readings", {}),
        "unmeasured": snapshot.get("unmeasured", {}),
        "gpu": snapshot.get("gpu", {}),
    }


def service_health(*, operator: str, **_: Any) -> dict[str, Any]:
    """Which model vendors this deployment can reach, and which breakers are open.

    Booleans and states, never keys. `neural_engine` is already bound to real
    vendor state rather than to a decorative pulse, which is what makes it worth
    exposing here at all.
    """
    try:
        from ai.telemetry import neural
    except Exception as exc:  # pragma: no cover
        return _unavailable(f"the telemetry package could not be imported: {type(exc).__name__}")

    try:
        engine = neural.neural_engine()
    except Exception as exc:
        logger.warning("system_ops: neural engine snapshot failed: %s", exc)
        return _unavailable(f"vendor state could not be read: {type(exc).__name__}")

    return {"available": True, "neural_engine": engine}


def recent_failures(*, operator: str, **_: Any) -> dict[str, Any]:
    """What has been failing, and — separately — what nobody counted.

    "No failures" and "nobody counted" are different facts. `ai/telemetry/`
    already keeps them apart, and this reports both halves rather than folding
    an unmeasured counter into a reassuring zero. That fold is the whole of
    F176: `scripts/invariant_coverage.py` printed full coverage by counting
    hand-typed `True` literals while three of the components it certified were
    provably unprotected.
    """
    measured: dict[str, Any] = {}
    unmeasured: dict[str, str] = {}

    try:
        from ai.telemetry import agents as agent_telemetry

        health = agent_telemetry.agent_health()
        measured["agents"] = health
    except Exception as exc:
        unmeasured["agents"] = f"agent health could not be read: {type(exc).__name__}"

    try:
        from ai.telemetry import security

        # No tool bus is passed. `build_tool_bus()` constructs a fresh bus per
        # caller, so there is no process-wide audit to count — and reporting a
        # brand-new bus's empty audit as "0 denials" would be a reassuring
        # number produced by never having looked. The endpoint makes the same
        # choice, for the same reason.
        measured["security"] = security.security_events()
    except Exception as exc:
        unmeasured["security"] = f"security events could not be read: {type(exc).__name__}"

    return {"available": True, "measured": measured, "unmeasured": unmeasured}


__all__ = ["host_resources", "recent_failures", "service_health"]
