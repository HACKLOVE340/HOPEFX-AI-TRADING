# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The typed surface an agent acts through.

This module exists to give two controls something to gate.

`invariants.enforcement.enforce_agent_action` holds sixteen CONSTITUTIONAL
predicates -- scoped actions, scoped tools, no self-escalation, hard capital
limits, no uncontrolled agent spawning, no strategy reaching production without
a human. Until this bus it had **no production caller at all**, only its own
tests (audit F260). Its docstring names the sentence it exists to satisfy: "per
agent permission scoping enforced at the tool layer, not just prompted". A tool
layer is where that stops being a sentence, and there was no tool layer.

`core.ai_tool_permissions.ToolPermissionRegistry` had one importer and no bus.

**Every invocation passes both, in order, before the callable is reached.**
The registry answers "may this tool be used at all, at this risk tier, with
this approval"; the invariant layer answers "is this agent acting inside the
scope it was granted". Neither subsumes the other: the registry knows nothing
about an agent's capital limit, and the invariants know nothing about whether a
tool is enabled. A call that satisfied only one of them would be exactly the
kind of half-enforced action this audit keeps finding.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.ai_tool_permissions import ToolPermissionRegistry

logger = logging.getLogger(__name__)

_AUDIT_LIMIT = 500


class ToolDenied(PermissionError):
    """A gate refused the invocation. The tool was NOT run."""

    def __init__(self, reason_codes: tuple[str, ...], detail: str = "") -> None:
        super().__init__(detail or ", ".join(reason_codes))
        self.reason_codes = reason_codes


@dataclass(frozen=True)
class ToolResult:
    tool: str
    allowed: bool
    value: Any = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def as_prompt_data(self) -> str:
        """This result, rendered for inclusion in a prompt as UNTRUSTED DATA.

        A tool result is not the agent's own reasoning. `fetch_market_news`
        returns text somebody else published; `scan_secrets` returns file
        contents; a camera frame can show a screen saying anything at all. Fed
        back raw, any of them can carry an instruction the agent then follows.

        `ai.guardrails.input.fence` already handles this correctly, including
        neutralising a closing tag hidden inside the payload -- without which a
        crafted result ends the quarantine early and everything after it reads
        as prompt. This delegates to it rather than keeping a second copy that
        would drift.

        Provided as a method so the safe form is the easy one: a caller building
        a prompt reaches for this instead of `str(result.value)`, and cannot
        forget the step.
        """
        from ai.guardrails.input import fence

        if not self.allowed:
            # A refusal must never render as an empty successful reading -- the
            # same reason `invoke` raises `tool_not_implemented` rather than
            # returning a no-op.
            codes = ", ".join(self.reason_codes) or "no reason given"
            body = f"The tool {self.tool} was REFUSED and produced no result. Reason: {codes}"
        else:
            body = f"Result of {self.tool}:\n{self.value!r}"

        return fence(body, kind="tool_result")


@dataclass
class _Registered:
    handler: Callable[..., Any]
    allowed_actions: frozenset[str]


class ToolBus:
    """Dispatches tool calls through the permission registry and the invariants."""

    def __init__(self, registry: ToolPermissionRegistry, *, live_mode: bool = False) -> None:
        self._registry = registry
        self._live_mode = live_mode
        self._tools: dict[str, _Registered] = {}
        self._audit: list[dict[str, Any]] = []

    def register(self, name: str, handler: Callable[..., Any], *, allowed_actions: set[str] | None = None) -> None:
        self._tools[name] = _Registered(handler, frozenset(allowed_actions or {name}))

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)

    def invoke(
        self,
        tool: str,
        *,
        operator: str,
        allowed_actions: set[str] | None = None,
        approved: bool = False,
        **context: Any,
    ) -> ToolResult:
        """Run `tool`, or raise ToolDenied. Both gates are consulted first."""
        reason_codes: list[str] = []

        # Gate 1 -- may this tool be used at all, at this risk tier?
        review = self._registry.review(tool, approved=approved, live_mode=self._live_mode)
        if not review.allowed:
            reason_codes.extend(review.reason_codes)
            self._record(tool, operator, False, tuple(reason_codes))
            raise ToolDenied(tuple(reason_codes), f"{tool}: {', '.join(review.reason_codes)}")

        registered = self._tools.get(tool)
        if registered is None:
            # The registry permits it but nothing implements it. Refusing is the
            # only safe answer: a permitted-but-absent tool must not read as a
            # successful no-op.
            self._record(tool, operator, False, ("tool_not_implemented",))
            raise ToolDenied(("tool_not_implemented",), f"{tool} has no handler")

        # Gate 2 -- is this agent acting inside the scope it was granted?
        from invariants.enforcement import enforce_agent_action

        request = {
            "action": tool,
            "allowed_actions": set(allowed_actions or ()),
            "tool": tool,
            "allowed_tools": set(registered.allowed_actions),
            "approved_by": operator if approved else None,
            **context,
        }
        result = enforce_agent_action(request)
        # `result.allowed` is False only in ENFORCE mode, and the global default
        # is MONITOR -- so honouring `allowed` would make this gate advisory on a
        # default deployment, which is the exact defect this bus exists to close.
        #
        # `result.blocking` is mode-independent: any CONSTITUTIONAL or CRITICAL
        # violation. The staged-rollout rationale for monitor mode is to avoid
        # breaking EXISTING trading paths while checks are proven; this bus is
        # new and has no existing behaviour to protect, so a constitutional
        # violation here refuses outright. The spec's sentence is "enforced at
        # the tool layer, not just prompted" -- enforced.
        if result.blocking or not result.allowed:
            codes = tuple(getattr(v, "rule", str(v)) for v in getattr(result, "violations", ()))
            reason_codes.extend(codes or ("agent_action_refused",))
            self._record(tool, operator, False, tuple(reason_codes))
            raise ToolDenied(tuple(reason_codes), f"{tool}: {getattr(result, 'reason', 'refused')}")

        value = registered.handler(**context)
        self._record(tool, operator, True, ("permission_granted",))
        return ToolResult(tool=tool, allowed=True, value=value, reason_codes=("permission_granted",))

    def _record(self, tool: str, operator: str, allowed: bool, reason_codes: tuple[str, ...]) -> None:
        """Every invocation is recorded, refusals included.

        A refusal that leaves no trace cannot be told apart from an attempt that
        never happened, which is the repudiation gap the plan's STRIDE notes
        call out.
        """
        self._audit.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "tool": tool,
                "operator": operator,
                "allowed": allowed,
                "reason_codes": list(reason_codes),
                "permission_version": self._registry.version,
            }
        )
        del self._audit[:-_AUDIT_LIMIT]
        if not allowed:
            logger.warning("ai.tools: refused %s for %s (%s)", tool, operator, ", ".join(reason_codes))


__all__ = ["ToolBus", "ToolDenied", "ToolResult"]
