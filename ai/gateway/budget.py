# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Spend ceilings for model calls, per operator and globally.

Checked BEFORE the call, not after. A ceiling enforced after the request has
been paid for is a report, not a limit.

Limits are data: they come from platform config so a superadmin can change them
without a redeploy, and default conservatively rather than to "unlimited" -- an
absent configuration must not mean an absent ceiling.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

#: Conservative defaults. An unset budget must not read as an infinite one.
DEFAULT_PER_OPERATOR_USD = 25.0
DEFAULT_GLOBAL_USD = 250.0

_per_operator_usd: float | None = None
_global_usd: float | None = None
_spend: dict[str, float] = defaultdict(float)
_period: str = ""


def _current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def set_limits(*, per_operator_usd: float, global_usd: float) -> None:
    """Override the ceilings (settings, or a test)."""
    global _per_operator_usd, _global_usd
    _per_operator_usd, _global_usd = per_operator_usd, global_usd


def limits() -> tuple[float, float]:
    """The ceilings in force: (per operator, global), monthly USD."""
    if _per_operator_usd is not None and _global_usd is not None:
        return _per_operator_usd, _global_usd
    try:
        from api.superadmin.platform import _load_platform_config

        config = _load_platform_config() or {}
        return (
            float(config.get("ai_budget_per_operator_usd", DEFAULT_PER_OPERATOR_USD)),
            float(config.get("ai_budget_global_usd", DEFAULT_GLOBAL_USD)),
        )
    except Exception as exc:  # a config read must not remove the ceiling
        logger.warning("ai.gateway.budget: config unreadable (%s); using defaults", exc)
        return DEFAULT_PER_OPERATOR_USD, DEFAULT_GLOBAL_USD


def _roll_period() -> None:
    global _period
    now = _current_period()
    if now != _period:
        _spend.clear()
        _period = now


def spent(operator: str) -> float:
    _roll_period()
    return _spend[operator]


def total_spent() -> float:
    _roll_period()
    return sum(_spend.values())


def check(operator: str, estimated_usd: float = 0.0) -> tuple[bool, str]:
    """(allowed, reason). Called before the request is issued."""
    _roll_period()
    per_operator, global_ceiling = limits()
    # Headroom, not "would this call exceed it". `spend + estimate > ceiling`
    # let a ceiling of 0.00 through whenever the estimate was 0.00 -- and the
    # estimate IS 0.00 by default, because a call's cost is not known until the
    # provider answers. A ceiling of zero has to mean no spend permitted, so the
    # test is whether any headroom remains at all.
    operator_headroom = per_operator - _spend[operator]
    if operator_headroom <= 0 or estimated_usd > operator_headroom:
        return False, (f"operator budget exhausted: {_spend[operator]:.2f} of {per_operator:.2f} USD this month")
    global_headroom = global_ceiling - total_spent()
    if global_headroom <= 0 or estimated_usd > global_headroom:
        return False, (f"global budget exhausted: {total_spent():.2f} of {global_ceiling:.2f} USD this month")
    return True, "within budget"


def charge(operator: str, cost_usd: float) -> None:
    _roll_period()
    _spend[operator] += max(0.0, cost_usd)


def reset_for_testing() -> None:
    global _per_operator_usd, _global_usd, _period
    _per_operator_usd = _global_usd = None
    _spend.clear()
    _period = ""


__all__ = [
    "DEFAULT_GLOBAL_USD",
    "DEFAULT_PER_OPERATOR_USD",
    "charge",
    "check",
    "limits",
    "reset_for_testing",
    "set_limits",
    "spent",
    "total_spent",
]
