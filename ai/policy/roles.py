# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Single source of truth for who may do what in the AI control plane.

Every endpoint in `api/safe_agent_platform.py` and
`api/professional_control_plane.py` depended on `require_role("admin")`.
`_ROLE_RANK` in `api/auth.py` is a **minimum-rank** check
(starter 0, user 1, trader 2, admin 3, superadmin 4), so rank 3 cleared every
gate in those modules: an admin could approve a proposal, execute it, roll it
back, change the model route, and authorize, revoke or rotate an integration's
credentials.

One separation-of-duties control was already correct and is kept: an approver
cannot decide twice on the same proposal, and repairs and upgrades require two
distinct approvers. What was missing is that both of those approvers could be
admins, so two admins could together approve and execute an AI-proposed change
with no superadmin involved — the "admin overtakes superadmin" case.

Two rules close it, and they are the reason this module exists rather than each
endpoint declaring its own role inline (which is how such a matrix drifts):

  Quorum rule     a repair or upgrade needs two distinct approvers AND at least
                  one of them must be a superadmin.
  Execution rule  approval and execution are different privileges. An admin may
                  contribute an approval; only a superadmin may execute, roll
                  back, or touch credentials, models, budgets or tool risk
                  tiers — and those additionally require a 2FA-verified token,
                  because a stolen token should not reach them.

See docs/audit/plans/2026-09-05-ai-core.md Part 1B for the full matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

VIEW: Final = "view"
PROPOSE: Final = "propose"
APPROVE: Final = "approve"
EXECUTE: Final = "execute"


@dataclass(frozen=True)
class Capability:
    """What a single AI control-plane action requires.

    `min_role` is the role floor. `requires_2fa` additionally demands a
    TOTP-verified token via `api.superadmin._shared.require_superadmin_2fa`.
    `quorum_needs_superadmin` applies only to approval capabilities.
    """

    tier: str
    min_role: str
    requires_2fa: bool = False
    quorum_needs_superadmin: bool = False


_VIEW = Capability(VIEW, "admin")
_PROPOSE = Capability(PROPOSE, "admin")
_SUPERADMIN = Capability(EXECUTE, "superadmin", requires_2fa=True)

# Keyed by the endpoint function's name in api/safe_agent_platform.py, so the
# mapping can be asserted against the module rather than trusted.
CAPABILITIES: Final[dict[str, Capability]] = {
    # ── read-only ─────────────────────────────────────────────────────────────
    "overview": _VIEW,
    "model_routes": _VIEW,
    "model_health": _VIEW,
    "list_supervisor_tasks": _VIEW,
    "diagnostics_graph": _VIEW,
    "diagnostics_run": _VIEW,
    "proposals": _VIEW,
    "integrations": _VIEW,
    "chat_capabilities": _VIEW,
    # api/ai_core.py -- the AI Core page's read surface. Read-only by
    # construction: every consequential action lives in safe_agent_platform
    # behind the rows below, and a reporting surface that could also act would
    # be a second, weaker door to the same room. `ai_core_budget` and
    # `ai_core_calls` widen their scope for a superadmin inside the handler
    # (per-operator spend, every operator's calls); the row is the floor, not
    # the ceiling.
    "ai_core_summary": _VIEW,
    "ai_core_capabilities": _VIEW,
    "ai_core_chain": _VIEW,
    "ai_core_budget": _VIEW,
    "ai_core_calls": _VIEW,
    "ai_core_cache": _VIEW,
    "ai_core_evals": _VIEW,
    # Which models each vendor currently serves. Reporting, not acting: choosing
    # a model is `route_model`, which is superadmin + 2FA below. Admin may see
    # WHICH vendors are configured -- a boolean, never a credential.
    "ai_core_models": _VIEW,
    # ── propose / plan: an admin may ask, and may not act ─────────────────────
    "create_supervisor_task": _PROPOSE,
    "cancel_supervisor_task": _PROPOSE,
    "plan_supervisor_task": _PROPOSE,
    "delegate_supervisor_task": _PROPOSE,
    "request_external_research": _PROPOSE,
    "run_diagnostics": _PROPOSE,
    "create_proposal": _PROPOSE,
    "propose_upgrade": _PROPOSE,
    "create_proposal_checkpoint": _PROPOSE,
    "validate_proposal": _PROPOSE,
    # ── approval: an admin may contribute one; a repair needs a superadmin ────
    "approve_supervisor_task": Capability(APPROVE, "admin"),
    "decide_approval": Capability(APPROVE, "admin", quorum_needs_superadmin=True),
    # ── consequential: superadmin, with 2FA ──────────────────────────────────
    "execute_supervisor_task": _SUPERADMIN,
    "execute_proposal": _SUPERADMIN,
    "rollback_proposal": _SUPERADMIN,
    "route_model": _SUPERADMIN,
    "integration_action": _SUPERADMIN,
}

#: Kinds whose approval quorum must include at least one superadmin.
QUORUM_NEEDS_SUPERADMIN_KINDS: Final[frozenset[str]] = frozenset({"repair", "upgrade"})

#: The exact role set each tier admits. Asserted in tests against the resolved
#: FastAPI dependencies, so a future role ranked above admin cannot silently
#: inherit the AI control plane the way `require_role` alone would allow.
ROLES_ADMITTED: Final[dict[str, frozenset[str]]] = {
    VIEW: frozenset({"admin", "superadmin"}),
    PROPOSE: frozenset({"admin", "superadmin"}),
    APPROVE: frozenset({"admin", "superadmin"}),
    EXECUTE: frozenset({"superadmin"}),
}


def capability_for(endpoint_name: str) -> Capability | None:
    """The capability for an endpoint, or None when it is not classified.

    Callers must treat None as a refusal, not as permission: an endpoint added
    without a row here has no declared authorization, and defaulting it open is
    how the original defect arrived.
    """
    return CAPABILITIES.get(endpoint_name)


__all__ = [
    "APPROVE",
    "CAPABILITIES",
    "EXECUTE",
    "PROPOSE",
    "QUORUM_NEEDS_SUPERADMIN_KINDS",
    "ROLES_ADMITTED",
    "VIEW",
    "Capability",
    "capability_for",
]
