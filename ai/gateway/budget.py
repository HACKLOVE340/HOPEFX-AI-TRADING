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
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

#: Conservative defaults. An unset budget must not read as an infinite one.
#:
#: Derived from this repository's own PRICING table rather than picked, so they
#: can be re-derived when prices change. The `reasoning` chain's primary is
#: claude-opus-5 at $15/M in and $75/M out, and DEFAULT_MAX_TOKENS caps output
#: at 2048, so one reasoning call costs roughly:
#:
#:     2,000 in  -> 2000/1e6 * 15  = $0.030
#:     1,000 out -> 1000/1e6 * 75  = $0.075
#:                                  ~$0.105, worst case ~$0.27
#:
#: The `fast` chain (claude-sonnet-5, $3/$15) is about a tenth of that at
#: ~$0.02 — route routine work there rather than at `reasoning`.
#:
#: $10 per operator is therefore ~100 reasoning calls or ~475 fast ones a
#: month, which is generous for interactive use; $60 global covers several
#: operators with headroom. Raise both when the department agents land, since
#: they will call far more often than a person does.
DEFAULT_PER_OPERATOR_USD = 10.0
DEFAULT_GLOBAL_USD = 60.0

#: The velocity window, and the two limits over it.
#:
#: A monthly ceiling is not a brake. A runaway agent loop -- the ordinary
#: failure mode of an agent that can call itself -- spends the whole monthly
#: global in minutes, and the ceiling is the only thing that ever stops it. By
#: then the month is gone and the AI is off until the period rolls.
VELOCITY_WINDOW_S = 3600.0

#: Spend velocity as a FRACTION of the configured monthly ceiling, rather than
#: as a second set of dollar figures. It then tracks whatever a superadmin sets,
#: and there is no second number to keep in step with the first.
DEFAULT_VELOCITY_FRACTION = 0.25

#: Calls per window, and this one is not optional.
#:
#: Local inference costs nothing: FREE_PROVIDERS is {"ollama"} and OllamaAdapter
#: returns cost_usd=0.0, so a local call records charge(operator, 0.0). A
#: spend-based limit is therefore STRUCTURALLY BLIND to a local runaway loop --
#: it can spin at full speed forever without moving a dollar figure. The call
#: count is the only thing that sees it.
#:
#: 120/hour is a sustained rate, not a burst allowance. The separation it draws
#: is the point: a person working hard peaks around one call a minute, while a
#: loop does thousands an hour. 120 sits above the first and far below the
#: second, so it catches a runaway within a minute or two without ever being
#: reached by real use.
#:
#: The two limits do different jobs and it is worth being explicit about which:
#: the spend ceilings are COST control, and this is the RUNAWAY catch — and the
#: only one of the two that can see a local loop at all, since local calls
#: move no money.
DEFAULT_MAX_CALLS_PER_WINDOW = 120

_per_operator_usd: float | None = None
_global_usd: float | None = None
_spend: dict[str, float] = defaultdict(float)
_period: str = ""

#: (timestamp, operator, cost) for the rolling window. Monotonic, so a clock
#: correction cannot empty the window or freeze it full.
_recent: deque[tuple[float, str, float]] = deque()


def _monotonic() -> float:
    """Indirected so a test can advance the window without sleeping an hour."""
    return time.monotonic()


def _expire_window() -> None:
    cutoff = _monotonic() - VELOCITY_WINDOW_S
    while _recent and _recent[0][0] < cutoff:
        _recent.popleft()


def velocity_limits() -> tuple[float, float]:
    """(per operator, global) USD permitted within one window."""
    per_operator, global_ceiling = limits()
    fraction = DEFAULT_VELOCITY_FRACTION
    try:
        from api.superadmin.platform import _load_platform_config

        config = _load_platform_config() or {}
        fraction = float(config.get("ai_budget_velocity_fraction", DEFAULT_VELOCITY_FRACTION))
    except Exception as exc:  # a config read must not remove the brake
        logger.warning("ai.gateway.budget: velocity config unreadable (%s); using defaults", exc)
    fraction = min(max(fraction, 0.0), 1.0)
    return per_operator * fraction, global_ceiling * fraction


def max_calls_per_window() -> int:
    try:
        from api.superadmin.platform import _load_platform_config

        config = _load_platform_config() or {}
        return max(1, int(config.get("ai_budget_max_calls_per_window", DEFAULT_MAX_CALLS_PER_WINDOW)))
    except Exception:
        return DEFAULT_MAX_CALLS_PER_WINDOW


def recent_spend(operator: str | None = None) -> float:
    """USD spent within the window, for one operator or everyone."""
    _expire_window()
    return sum(cost for _ts, who, cost in _recent if operator is None or who == operator)


def recent_calls(operator: str | None = None) -> int:
    """Calls made within the window, for one operator or everyone."""
    _expire_window()
    return sum(1 for _ts, who, _cost in _recent if operator is None or who == operator)


def _velocity_refusal(operator: str, estimated_usd: float) -> str | None:
    """A reason to refuse on rate, or None."""
    calls_ceiling = max_calls_per_window()
    if recent_calls(operator) >= calls_ceiling:
        return (
            f"call rate exceeded: {recent_calls(operator)} calls in the last "
            f"{VELOCITY_WINDOW_S / 60:.0f} minutes (limit {calls_ceiling})"
        )

    per_operator_cap, global_cap = velocity_limits()
    operator_recent = recent_spend(operator)
    if operator_recent + estimated_usd > per_operator_cap:
        return (
            f"spend velocity exceeded: {operator_recent:.2f} USD in the last "
            f"{VELOCITY_WINDOW_S / 60:.0f} minutes (limit {per_operator_cap:.2f})"
        )

    total_recent = recent_spend(None)
    if total_recent + estimated_usd > global_cap:
        return (
            f"global spend velocity exceeded: {total_recent:.2f} USD in the last "
            f"{VELOCITY_WINDOW_S / 60:.0f} minutes (limit {global_cap:.2f})"
        )
    return None


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

    # The brake, checked last so an exhausted monthly ceiling still reports
    # itself as exhausted rather than as "too fast" — they are different
    # problems and an operator needs to know which one they have.
    velocity_reason = _velocity_refusal(operator, estimated_usd)
    if velocity_reason:
        logger.error("ai.gateway.budget: refusing %s — %s", operator, velocity_reason)
        return False, velocity_reason

    return True, "within budget"


def charge(operator: str, cost_usd: float) -> None:
    _roll_period()
    cost = max(0.0, cost_usd)
    _spend[operator] += cost
    # Recorded even when the cost is zero: a free local call still consumes the
    # call-rate allowance, and that is the only limit a local runaway loop can
    # ever trip.
    _expire_window()
    _recent.append((_monotonic(), operator, cost))


def reset_for_testing() -> None:
    global _per_operator_usd, _global_usd, _period
    _per_operator_usd = _global_usd = None
    _spend.clear()
    _recent.clear()
    _period = ""


__all__ = [
    "DEFAULT_GLOBAL_USD",
    "DEFAULT_MAX_CALLS_PER_WINDOW",
    "DEFAULT_PER_OPERATOR_USD",
    "DEFAULT_VELOCITY_FRACTION",
    "VELOCITY_WINDOW_S",
    "charge",
    "check",
    "limits",
    "max_calls_per_window",
    "recent_calls",
    "recent_spend",
    "reset_for_testing",
    "set_limits",
    "spent",
    "total_spent",
    "velocity_limits",
]
