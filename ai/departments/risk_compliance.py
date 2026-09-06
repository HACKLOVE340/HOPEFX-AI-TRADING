# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Risk & Compliance — the read half. Spec §4 Cluster A.

Two of the department's four actions are here. The other two are declared with
their risk tiers and deliberately have no handler, which is a decision rather
than an omission:

* `block_deploy` would have to actually stop a rollout, and this repository has
  no deploy-block mechanism to call. A handler would either invent one under
  time pressure or return success for a deploy it did not block — the second
  being the exact defect this audit keeps finding. The bus refuses an
  unimplemented tool with `tool_not_implemented`, which is the honest answer.
* `propose_derisk` needs somewhere for a proposal to land that a human reviews.
  `api/safe_agent_platform.py` has that shape; wiring it is its own change with
  its own tests, not a line squeezed in here.

**Nothing in this module fabricates a risk figure.** An absent risk manager or a
check that raises returns `available: False` and the reason, and — this is the
part that matters — it does NOT carry a `passed` key at all. An agent told
"drawdown is fine" by a handler that never reached the risk manager would be
reasoning from fiction, and a missing key forces a caller to notice.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """No `passed` key, deliberately. Unavailable must not read as approved."""
    return {"available": False, "reason": reason, **extra}


def _resolve_manager(risk_manager: Any) -> Any:
    """The manager passed in, or the process-wide one, or None."""
    if risk_manager is not None:
        return risk_manager
    try:
        from risk.manager import get_risk_manager

        return get_risk_manager()
    except Exception as exc:
        logger.debug("risk_compliance: no module-level risk manager (%s)", exc)
        return None


def _report(result: Any) -> dict[str, Any]:
    """Read a RiskCheckResult without assuming more than it guarantees."""
    return {
        "available": True,
        "passed": bool(getattr(result, "passed", False)),
        "reason": str(getattr(result, "reason", "") or ""),
    }


def check_drawdown(*, risk_manager: Any = None, max_dd: float | None = None, **_: Any) -> dict[str, Any]:
    """Current drawdown against the configured limit."""
    manager = _resolve_manager(risk_manager)
    if manager is None:
        return _unavailable("risk_manager_unavailable")

    try:
        result = manager.check_drawdown(max_dd=max_dd) if max_dd is not None else manager.check_drawdown()
    except Exception as exc:
        logger.warning("risk_compliance.check_drawdown failed (%s)", exc)
        return _unavailable(f"check_failed: {exc}")
    return _report(result)


def validate_position_size(
    *, risk_manager: Any = None, trade: Any = None, max_pct: float = 0.05, **_: Any
) -> dict[str, Any]:
    """Whether a proposed trade's size passes the risk gate.

    Refuses without a trade rather than validating a default one: an approval
    for a trade nobody asked about is an approval somebody will act on.
    """
    if trade is None:
        return _unavailable("trade_required")

    manager = _resolve_manager(risk_manager)
    if manager is None:
        return _unavailable("risk_manager_unavailable")

    try:
        result = manager.check_position_size(trade, max_pct=max_pct)
    except Exception as exc:
        logger.warning("risk_compliance.validate_position_size failed (%s)", exc)
        return _unavailable(f"check_failed: {exc}")
    return _report(result)


__all__ = ["check_drawdown", "validate_position_size"]
