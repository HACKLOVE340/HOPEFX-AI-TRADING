# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A monthly ceiling is not a brake. This adds the brake.

`ai/gateway/budget.py` enforced a per-operator and a global ceiling, both
monthly, and nothing else. A runaway agent loop — the ordinary failure mode of
an agent that can call itself — spends the entire monthly global in minutes and
the ceiling is the only thing that ever stops it. By then the month's budget is
gone and the AI is off until the period rolls.

Two limits over one rolling window, and the second is the one that matters most
here:

**Spend velocity.** Expressed as a fraction of the configured monthly ceiling
rather than as a second set of dollar figures, so it tracks whatever a
superadmin sets and there is no second number to keep in step. A deployment
whose monthly global is $250 will not spend more than 20% of it in an hour
without something being wrong.

**Call rate.** Local inference costs nothing — `FREE_PROVIDERS` is `{ollama}`
and `OllamaAdapter` returns `cost_usd=0.0`, so `charge(operator, 0.0)` is what a
local call records. **A spend-based limit is therefore structurally blind to a
local runaway loop**: it can spin at full speed forever and never move a
dollar figure. The call-rate limit is the only thing that sees it. That is why
it is not optional.

Both live inside `budget.check()` and `budget.charge()`, which the gateway
already calls on every model request and every served response. No new
registration, no new call site to wire — `KillSwitch.register_callback` in this
same repository has existed for a long time with zero production registrants,
and a gate nobody remembers to subscribe to is not a gate.
"""

from __future__ import annotations

import pytest

from ai.gateway import budget

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_budget():
    budget.reset_for_testing()
    yield
    budget.reset_for_testing()


# ── the limits exist and are configurable ────────────────────────────────────


def test_velocity_limits_have_conservative_defaults():
    """An unset velocity limit must not read as an infinite one."""
    assert 0.0 < budget.DEFAULT_VELOCITY_FRACTION < 1.0
    assert budget.DEFAULT_MAX_CALLS_PER_WINDOW > 0
    assert budget.VELOCITY_WINDOW_S > 0


def test_the_spend_velocity_ceiling_tracks_the_monthly_ceiling():
    """One number to configure, not two that can drift apart."""
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    per_operator, global_ceiling = budget.velocity_limits()
    assert per_operator == pytest.approx(100.0 * budget.DEFAULT_VELOCITY_FRACTION)
    assert global_ceiling == pytest.approx(1000.0 * budget.DEFAULT_VELOCITY_FRACTION)


# ── spend velocity ───────────────────────────────────────────────────────────


def test_a_normal_call_is_allowed():
    """The control case. A limit that refuses everything proves nothing."""
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    allowed, _reason = budget.check("alice", 0.10)
    assert allowed is True


def test_spending_fast_is_refused_before_the_monthly_ceiling_is_reached():
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    # Derived from the constant, never from the number it happens to hold: the
    # first version of this test hardcoded 20% and broke the moment the default
    # was tuned, which is a test measuring the wrong thing.
    over_the_hourly_cap = int(100.0 * budget.DEFAULT_VELOCITY_FRACTION) + 1
    for _ in range(over_the_hourly_cap):
        budget.charge("alice", 1.0)

    allowed, reason = budget.check("alice", 0.10)
    assert allowed is False
    assert "velocity" in reason or "too fast" in reason
    assert budget.spent("alice") < 100.0, "the MONTHLY ceiling was never reached — velocity is what refused"


def test_the_global_velocity_ceiling_catches_many_operators_at_once():
    """A loop spread across operators must not slip past a per-operator limit."""
    budget.set_limits(per_operator_usd=100.0, global_usd=200.0)
    over_the_global_cap = int(200.0 * budget.DEFAULT_VELOCITY_FRACTION) + 1
    for i in range(over_the_global_cap):
        budget.charge(f"agent-{i}", 1.0)  # one operator each, so only the global cap binds

    allowed, reason = budget.check("agent-new", 0.10)
    assert allowed is False
    assert "velocity" in reason


# ── call rate: the one that sees a free local loop ───────────────────────────


def test_a_runaway_loop_of_free_calls_is_still_stopped():
    """The reason a spend-only limit is not enough.

    Local inference records cost 0.0, so no spend-based ceiling ever moves. Only
    the call count sees this.
    """
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    for _ in range(budget.DEFAULT_MAX_CALLS_PER_WINDOW + 1):
        budget.charge("local-agent", 0.0)

    assert budget.spent("local-agent") == 0.0, "free calls moved no money, by construction"
    allowed, reason = budget.check("local-agent", 0.0)
    assert allowed is False
    assert "call rate" in reason or "calls" in reason


def test_calls_below_the_rate_limit_are_allowed():
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    for _ in range(5):
        budget.charge("local-agent", 0.0)
    assert budget.check("local-agent", 0.0)[0] is True


# ── the window rolls ─────────────────────────────────────────────────────────


def test_the_window_rolls_so_a_refusal_is_not_permanent(monkeypatch):
    """A velocity limit that never releases is an outage, not a brake."""
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)

    clock = {"now": 1000.0}
    monkeypatch.setattr(budget, "_monotonic", lambda: clock["now"])

    for _ in range(int(100.0 * budget.DEFAULT_VELOCITY_FRACTION) + 1):
        budget.charge("alice", 1.0)
    assert budget.check("alice", 0.10)[0] is False

    clock["now"] += budget.VELOCITY_WINDOW_S + 1
    assert budget.check("alice", 0.10)[0] is True, "the window should have released"


def test_velocity_state_is_cleared_between_tests():
    """reset_for_testing must clear the new state too, or suites cross-talk."""
    budget.charge("alice", 5.0)
    budget.reset_for_testing()
    assert budget.recent_calls("alice") == 0
    assert budget.recent_spend("alice") == 0.0


# ── the monthly ceiling still works ──────────────────────────────────────────


def test_the_monthly_ceiling_is_unchanged():
    """The velocity gate is additive; it must not have replaced the ceiling."""
    budget.set_limits(per_operator_usd=1.0, global_usd=1000.0)
    budget.charge("alice", 1.0)
    allowed, reason = budget.check("alice", 0.0)
    assert allowed is False
    assert "budget exhausted" in reason
