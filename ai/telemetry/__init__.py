# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§22 telemetry. Every number here is a real reading or a stated absence.

The rule the section exists for: **an unmeasured metric is absent, never
zero.** `ai/telemetry/reading.py` carries the argument and the evidence; the
short version is that a CPU gauge reading 0% because its probe never ran tells
an operator the machine is idle, and no gauge at all would have told them the
truth.

`snapshot()` reports what it measured and, separately, what it could not —
because a caller that has to infer the second from the first will infer wrong.
"""

from typing import Any

from ai.telemetry.reading import Reading, absent, measured


def snapshot(*, runner: Any = None, tool_bus: Any = None, watcher_runs: int | None = None) -> dict[str, Any]:
    """Host, agents, security and the model layer, in one read.

    Sources are injected rather than reached for, so "nobody gave me the
    runner" stays distinguishable from "the runner is idle".
    """
    from ai.telemetry import agents, host, neural, security

    host_snap = host.snapshot()
    agent_snap = agents.agent_health(runner=runner, watcher_runs=watcher_runs)
    security_snap = security.security_events(tool_bus=tool_bus)
    engine = neural.neural_engine()

    unmeasured: dict[str, str] = dict(host_snap["unmeasured"])
    if not host_snap["gpu"]["detectable"]:
        unmeasured["gpu"] = host_snap["gpu"]["reason"]
    for block, key in ((agent_snap["jobs"], "jobs"), (agent_snap["awareness"], "awareness")):
        if not block.get("measured", True):
            unmeasured[key] = block.get("reason", "")
    for name, block in security_snap.items():
        if not block.get("measured", True):
            unmeasured[name] = block.get("reason", "")

    return {
        "host": host_snap,
        "agents": agent_snap,
        "security": security_snap,
        "neural_engine": engine,
        "unmeasured": unmeasured,
    }


__all__ = ["Reading", "absent", "measured", "snapshot"]
