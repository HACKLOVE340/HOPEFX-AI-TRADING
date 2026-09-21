# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§12's agent-to-agent communication: a typed bus, a lifecycle, a task graph.

**This package cannot act.** It does not import `ai.tools.bus`, and a test
asserts that it never will. Publishing an event moves a message; everything
that *does* something still passes the permission registry and the sixteen
constitutional invariants at the tool layer. A bus that can invoke a tool is a
second execution path with none of the first one's gates.

`ai/awareness` already holds this shape for the same reason — a watcher raises
a proposal and never acts, because the thing that acts is not importable from
where it lives.
"""

from ai.bus.agent_bus import AgentBus, Delivery, Subscription, get_agent_bus
from ai.bus.graph import CycleRefused, TaskGraph
from ai.bus.lifecycle import TaskLifecycle

__all__ = [
    "AgentBus",
    "CycleRefused",
    "Delivery",
    "Subscription",
    "TaskGraph",
    "TaskLifecycle",
    "get_agent_bus",
]
