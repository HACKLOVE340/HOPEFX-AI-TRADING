# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Spec §4 Cluster A — the Trading Core departments.

The tool bus, the sandbox and the eval runner were each built, tested,
documented and invoked by **nothing**. Departments are what gives them callers:
an agent that can do something has to reach a tool, and reaching a tool is what
makes `ToolBus.invoke` and `enforce_agent_action` run outside a test.

**One table drives three things** — the department directory, the permission
registry and the bus registration. Three hand-maintained lists of the same
tools is how a tool becomes permitted and uncallable, or callable and
unpermitted; `ai/gateway/vendors.py` exists for the same reason.

**Build order is deliberate.** Research & Intelligence has handlers because all
four of its actions are read-only. Markets & Execution is declared and
unimplemented because `place_order` and `cancel_order` are the only actions in
Cluster A that can lose money, and they should be last — after the permission
tiers, the scope gate and the audit trail have been exercised by departments
that cannot.

**A declared action with no handler is not a dead control.** `ToolBus.invoke`
refuses it with `tool_not_implemented` rather than returning a successful no-op,
and `tests/unit/test_departments_cluster_a.py` asserts exactly which are
implemented, so the set cannot grow or shrink quietly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from core.ai_tool_permissions import ToolPermission, ToolPermissionRegistry, ToolRisk

from ai import execution_shadow

from . import (
    data_ops,
    markets_execution,
    news_intelligence,
    notification_ops,
    platform_engineering,
    research,
    risk_compliance,
    voice_interface,
)

#: Bumped whenever the action set or a risk tier changes. An unversioned
#: permission set cannot be audited after the fact.
#: Bumped when the per-department `recall_memory` actions landed — spec §2's
#: `memory/`, which had been a tuple of strings.
PERMISSIONS_VERSION: Final = "departments-cluster-b-agent-network-2026-09-07"
ACTION_VERSION: Final = "1.0.0"


@dataclass(frozen=True)
class DepartmentAction:
    """One thing a department can do, and what it takes to be allowed to."""

    name: str
    risk: ToolRisk
    summary: str
    handler: Callable[..., Any] | None = None
    requires_approval: bool = False


@dataclass(frozen=True)
class Department:
    key: str
    title: str
    status: str
    agents: tuple[str, ...]
    actions: tuple[DepartmentAction, ...]
    memory: tuple[str, ...]
    awareness: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "agents": list(self.agents),
            "memory": list(self.memory),
            "awareness": list(self.awareness),
            "actions": [
                {
                    "name": a.name,
                    "risk": str(a.risk),
                    "summary": a.summary,
                    "requires_approval": a.requires_approval,
                    # The honest bit: an action nobody implemented says so here
                    # rather than looking identical to one that works.
                    "implemented": a.handler is not None,
                }
                for a in self.actions
            ],
        }


def _action(dept: str, name: str, risk: ToolRisk, summary: str, handler=None, approval=False) -> DepartmentAction:
    return DepartmentAction(
        name=f"{dept}.{name}",
        risk=risk,
        summary=summary,
        handler=handler,
        requires_approval=approval,
    )


DEPARTMENTS: Final[dict[str, Department]] = {
    "markets_execution": Department(
        key="markets_execution",
        title="Markets & Execution",
        status="watch: OANDA disconnected",
        agents=("Execution Agent", "Broker Liaison"),
        actions=(
            # The two actions in Cluster A that can lose money. LIVE_TRADING
            # means the registry refuses them without an explicit human
            # approval AND without live mode — two separate refusals, so
            # neither one alone is what stands between an agent and an order.
            _action(
                "markets_execution",
                "place_order",
                ToolRisk.LIVE_TRADING,
                "Place an order with the broker.",
                approval=True,
            ),
            _action(
                "markets_execution", "cancel_order", ToolRisk.LIVE_TRADING, "Cancel a working order.", approval=True
            ),
            _action(
                "markets_execution",
                "sync_positions",
                ToolRisk.READ_ONLY,
                "Report how local positions differ from the broker's. Reports only; corrects nothing.",
                markets_execution.sync_positions,
            ),
            _action(
                "markets_execution",
                "query_broker_status",
                ToolRisk.READ_ONLY,
                "Broker connection and heartbeat state.",
                markets_execution.query_broker_status,
            ),
            # Shadow mode. READ_ONLY because it genuinely is: `ai/execution_shadow`
            # imports no broker and no OMS, so there is nothing for it to touch.
            #
            # Separate actions rather than a `dry_run` flag on the two above. A
            # flag is one changed default or one forgotten argument away from a
            # live order; two different tools with two different handlers cannot
            # be confused for each other by a config edit.
            _action(
                "markets_execution",
                "shadow_place_order",
                ToolRisk.READ_ONLY,
                "What placing this order WOULD do, with the risk gate's verdict. Sends nothing.",
                execution_shadow.shadow_place_order,
            ),
            _action(
                "markets_execution",
                "shadow_cancel_order",
                ToolRisk.READ_ONLY,
                "What cancelling this order WOULD do. Sends nothing.",
                execution_shadow.shadow_cancel_order,
            ),
        ),
        memory=("execution/fill history", "slippage per symbol", "last broker heartbeat"),
        awareness=("broker disconnect detection", "orphaned-order flagging"),
    ),
    "risk_compliance": Department(
        key="risk_compliance",
        title="Risk & Compliance",
        status="active",
        agents=("Compliance Guard", "Risk Monitor"),
        actions=(
            _action(
                "risk_compliance",
                "check_drawdown",
                ToolRisk.READ_ONLY,
                "Current drawdown against the configured limits.",
                risk_compliance.check_drawdown,
            ),
            _action(
                "risk_compliance",
                "validate_position_size",
                ToolRisk.READ_ONLY,
                "Whether a proposed size passes the risk gate.",
                risk_compliance.validate_position_size,
            ),
            # Proposing is not acting. block_deploy stops a rollout rather than
            # touching a position, and propose_derisk writes a proposal a human
            # approves — the approval is the money step, not this.
            _action(
                "risk_compliance",
                "block_deploy",
                ToolRisk.IRREVERSIBLE,
                "Block a deployment that would breach a rule.",
                approval=True,
            ),
            _action(
                "risk_compliance",
                "propose_derisk",
                ToolRisk.PAPER_TRADING,
                "Propose a de-risking action for human approval.",
            ),
        ),
        memory=("rule-set per prop firm", "drawdown curve", "past violations"),
        awareness=("live exposure vs rules", "volatility-regime shift"),
    ),
    "research_intelligence": Department(
        key="research_intelligence",
        title="Research & Intelligence",
        status="active",
        agents=("Model Analyst", "Research Scout"),
        actions=(
            _action(
                "research_intelligence",
                "run_backtest",
                ToolRisk.READ_ONLY,
                "Backtest a strategy over historical data.",
                research.run_backtest,
            ),
            _action(
                "research_intelligence",
                "fetch_market_news",
                ToolRisk.READ_ONLY,
                "Upcoming economic events.",
                research.fetch_market_news,
            ),
            _action(
                "research_intelligence",
                "score_regime",
                ToolRisk.READ_ONLY,
                "The current market regime for a symbol.",
                research.score_regime,
            ),
            _action(
                "research_intelligence",
                "walk_forward_validate",
                ToolRisk.READ_ONLY,
                "Out-of-sample walk-forward validation.",
                research.walk_forward_validate,
            ),
        ),
        memory=("model version history", "OOS accuracy log", "regime history"),
        awareness=("strategy drift vs trained regime", "confidence calibration"),
    ),
    "platform_engineering": Department(
        key="platform_engineering",
        title="Platform Engineering",
        status="reviewing: credential rotation pending",
        agents=("Code Auditor", "Deploy Sentinel"),
        actions=(
            _action(
                "platform_engineering",
                "scan_secrets",
                ToolRisk.READ_ONLY,
                "Scan the tree for committed credentials.",
                platform_engineering.scan_secrets,
            ),
            _action(
                "platform_engineering",
                "run_tests",
                ToolRisk.READ_ONLY,
                "Run a bounded selection of the test suite.",
                platform_engineering.run_tests,
            ),
            _action(
                "platform_engineering", "propose_fix", ToolRisk.PAPER_TRADING, "Propose a code change for human review."
            ),
            _action(
                "platform_engineering",
                "check_broken_imports",
                ToolRisk.READ_ONLY,
                "Find imports that do not resolve.",
                platform_engineering.check_broken_imports,
            ),
        ),
        memory=("audit history", "bug registry", "dead execution paths"),
        awareness=("commits touching security-sensitive files", "CI failure patterns"),
    ),
    # ── Cluster B — §11's remaining agents ───────────────────────────────────
    #
    # Every action here is READ_ONLY, and that is a design decision rather than
    # a starting point. A voice agent that could synthesise on its own
    # initiative can talk to somebody who did not ask it to; a notification
    # agent that could notify is a spam generator with a review process. Both
    # belong to a different risk tier and a different review than "can be asked
    # a question", which is all these four do.
    "news_intelligence": Department(
        key="news_intelligence",
        title="News Intelligence",
        status="reading: headlines and geopolitical severity",
        agents=("Headline Reader", "Geopolitical Analyst"),
        actions=(
            _action(
                "news_intelligence",
                "fetch_headlines",
                ToolRisk.READ_ONLY,
                "Recent headlines from the feed manager.",
                news_intelligence.fetch_headlines,
            ),
            _action(
                "news_intelligence",
                "score_geopolitical_risk",
                ToolRisk.READ_ONLY,
                "Geopolitical severity of one piece of text, from the existing scorer.",
                news_intelligence.score_geopolitical_risk,
            ),
        ),
        memory=("headline", "severity_score"),
        awareness=("news_feed_silent",),
    ),
    "voice_interface": Department(
        key="voice_interface",
        title="Voice",
        status="reporting: provider configuration and turn rules",
        agents=("Turn Manager",),
        actions=(
            _action(
                "voice_interface",
                "voice_status",
                ToolRisk.READ_ONLY,
                "Which synthesis and recognition providers are configured. Booleans, never keys.",
                voice_interface.voice_status,
            ),
            _action(
                "voice_interface",
                "turn_policy",
                ToolRisk.READ_ONLY,
                "The turn-taking rules this deployment actually enforces.",
                voice_interface.turn_policy,
            ),
        ),
        memory=("voice_availability",),
        awareness=("no_voice_provider",),
    ),
    "notification_ops": Department(
        key="notification_ops",
        title="Notification",
        status="watching: severity, escalation, interruption",
        agents=("Interruption Warden",),
        actions=(
            _action(
                "notification_ops",
                "evaluate_notification",
                ToolRisk.READ_ONLY,
                "What the policy WOULD do with a notification. A dry run that delivers nothing.",
                notification_ops.evaluate_notification,
            ),
            _action(
                "notification_ops",
                "pending_notifications",
                ToolRisk.READ_ONLY,
                "One operator's inbox, held notifications and unacknowledged keys.",
                notification_ops.pending_notifications,
            ),
            _action(
                "notification_ops",
                "describe_policy",
                ToolRisk.READ_ONLY,
                "One operator's notification settings, and the floor no setting turns off.",
                notification_ops.describe_policy,
            ),
        ),
        memory=("interruption",),
        awareness=("escalation_unacknowledged",),
    ),
    "data_ops": Department(
        key="data_ops",
        title="Data",
        status="validating: acquisition, freshness, cross-source agreement",
        agents=("Feed Warden", "Quality Auditor"),
        actions=(
            _action(
                "data_ops",
                "feed_health",
                ToolRisk.READ_ONLY,
                "Per-source health as the quality engine computes it.",
                data_ops.feed_health,
            ),
            _action(
                "data_ops",
                "stale_sources",
                ToolRisk.READ_ONLY,
                "Which sources the engine currently considers stale, and which it checked.",
                data_ops.stale_sources,
            ),
        ),
        memory=("feed_health",),
        awareness=("feed_stale",),
    ),
}


def _recall_handler(department: str) -> Callable[..., Any]:
    """A bound reader for one department's memory.

    Bound rather than parameterised: a single `recall_memory(department=...)`
    tool would let an agent granted Research's scope read Risk's violations by
    passing a different argument. One action per department means the
    permission registry and `enforce_agent_action` are deciding about the
    department, not trusting a parameter.
    """

    def handler(*, kind: str | None = None, limit: int = 50) -> dict[str, Any]:
        from ai.memory.store import recall

        entries = recall(department, kind=kind, limit=min(int(limit), 200))
        return {"available": True, "department": department, "count": len(entries), "entries": entries}

    handler.__name__ = f"recall_{department}_memory"
    return handler


#: Spec §2's `memory/`, reachable the way every other capability is.
#:
#: Registered here rather than exposed as a plain function so recall passes the
#: same two gates as anything else an agent can do. A module-level reader
#: callable from anywhere would be a second door into the same room.
_MEMORY_ACTIONS: Final[dict[str, DepartmentAction]] = {
    key: _action(
        key,
        "recall_memory",
        ToolRisk.READ_ONLY,
        f"What {dept.title} has observed, newest first. Reads only; records nothing.",
        _recall_handler(key),
    )
    for key, dept in DEPARTMENTS.items()
}


def all_actions() -> tuple[DepartmentAction, ...]:
    declared = tuple(a for d in DEPARTMENTS.values() for a in d.actions)
    return declared + tuple(_MEMORY_ACTIONS[k] for k in DEPARTMENTS)


def action_by_name(name: str) -> DepartmentAction:
    """The declared action, or KeyError. Never a default."""
    for action in all_actions():
        if action.name == name:
            return action
    raise KeyError(name)


def implemented_actions() -> tuple[DepartmentAction, ...]:
    return tuple(a for a in all_actions() if a.handler is not None)


def permission_registry() -> ToolPermissionRegistry:
    """Built from the same table the bus registers from, so they cannot drift."""
    return ToolPermissionRegistry(
        (
            ToolPermission(
                tool_name=action.name,
                version=ACTION_VERSION,
                risk=action.risk,
                enabled=True,
                requires_approval=action.requires_approval,
            )
            for action in all_actions()
        ),
        version=PERMISSIONS_VERSION,
    )


def build_tool_bus(*, live_mode: bool = False):
    """The bus, with every implemented action registered on it.

    `live_mode` stays False unless a deployment deliberately turns it on: a
    LIVE_TRADING tool is refused without it, and defaulting it True would remove
    one of the two refusals standing in front of `place_order`.
    """
    from ai.tools.bus import ToolBus

    bus = ToolBus(permission_registry(), live_mode=live_mode)
    for action in implemented_actions():
        bus.register(action.name, action.handler, allowed_actions={action.name})
    return bus


def directory() -> list[dict[str, Any]]:
    """The department directory, for the read-only AI Core surface."""
    return [d.as_dict() for d in DEPARTMENTS.values()]


__all__ = [
    "ACTION_VERSION",
    "DEPARTMENTS",
    "PERMISSIONS_VERSION",
    "Department",
    "DepartmentAction",
    "action_by_name",
    "all_actions",
    "build_tool_bus",
    "directory",
    "implemented_actions",
    "permission_registry",
]
