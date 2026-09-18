# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The chain fell through on failure and remembered nothing.

`resolve_chain` returns an ordered list and `should_fall_through` decides
whether to advance. Neither carries any memory between calls, so a vendor that
is comprehensively down was contacted, timed out, and fell through on EVERY
subsequent request. With a 60-second default timeout and a dead primary, each
call paid that timeout before reaching a leg that works.

`resilience/service_circuit_breakers.py` already solves this and is already used
for redis, broker, ml_model and database. This extends it to gateway legs rather
than writing a second mechanism.

**The rule that matters: only a transport failure trips the breaker.** A
guardrail rejection, a refusal, or a 400 is the vendor working correctly and
answering. Counting those as outages would take a perfectly healthy vendor
offline because somebody sent it a badly formed prompt — the same distinction
`should_fall_through` already draws, applied to a second decision.

These tests fail on the pre-fix tree — `leg_breaker` does not exist there.
"""

from __future__ import annotations

import pytest

from ai.gateway import breakers
from ai.gateway.client import GatewayClient, ModelRequest, ProviderError

pytestmark = pytest.mark.unit


class _Result:
    text, cost_usd, tokens_in, tokens_out = "ok", 0.0, 1, 1


class _Dead:
    """A vendor that is comprehensively down."""

    def __init__(self, reason="connection_error"):
        self.reason, self.calls = reason, 0

    def complete(self, *, model, prompt, timeout_s):
        self.calls += 1
        raise ProviderError(self.reason, provider="anthropic", model=model)


class _Alive:
    def __init__(self):
        self.calls = 0

    def complete(self, *, model, prompt, timeout_s):
        self.calls += 1
        return _Result()


@pytest.fixture(autouse=True)
def _clean():
    from ai.gateway import audit, budget

    budget.reset_for_testing()
    audit.reset_for_testing()
    breakers.reset_for_testing()
    budget.set_limits(per_operator_usd=1000.0, global_usd=10000.0)
    yield
    budget.reset_for_testing()
    audit.reset_for_testing()
    breakers.reset_for_testing()


def _call(client, role="reasoning"):
    return client.call_sync(ModelRequest(role=role, prompt="hello"), operator="owner")


def test_a_dead_vendor_stops_being_contacted_after_the_threshold():
    """The defect: a dead primary was dialled on every single call."""
    dead, alive = _Dead(), _Alive()
    client = GatewayClient({"anthropic": dead, "openai": alive}, cache=None)

    for _ in range(12):
        _call(client)

    threshold = breakers.FAILURE_THRESHOLD
    assert dead.calls <= threshold, (
        f"the dead vendor was contacted {dead.calls} times across 12 calls; "
        f"the breaker should have stopped it after {threshold}"
    )
    assert alive.calls == 12, "every call should still have been served"


def test_the_breaker_opens_for_that_vendor_only():
    """One vendor being down must not disable the others."""
    dead, alive = _Dead(), _Alive()
    client = GatewayClient({"anthropic": dead, "openai": alive}, cache=None)

    for _ in range(12):
        _call(client)

    assert breakers.leg_breaker("anthropic").is_open is True
    assert breakers.leg_breaker("openai").is_open is False


def test_a_guardrail_rejection_does_not_trip_the_breaker():
    """The rule that keeps a healthy vendor online.

    `bad_request` means the vendor answered. Counting it as an outage would
    take a working vendor offline because somebody sent a malformed prompt.
    """
    refuser = _Dead(reason="bad_request")
    client = GatewayClient({"anthropic": refuser}, cache=None)

    for _ in range(12):
        with pytest.raises(Exception):  # noqa: B017 — any refusal; the point is the breaker
            _call(client)

    assert breakers.leg_breaker("anthropic").is_open is False, "a vendor that answered correctly was marked as down"


def test_a_success_resets_the_failure_run():
    """Intermittent failures must not accumulate into an open breaker."""
    breaker = breakers.leg_breaker("anthropic")
    for _ in range(breakers.FAILURE_THRESHOLD - 1):
        breaker.record_failure(RuntimeError("timeout"))
    breaker.record_success()
    for _ in range(breakers.FAILURE_THRESHOLD - 1):
        breaker.record_failure(RuntimeError("timeout"))

    assert breaker.is_open is False


def test_an_open_leg_is_recorded_as_skipped_in_the_audit_trail():
    """An operator needs to see WHY the chain used its second choice."""
    from ai.gateway import audit

    dead, alive = _Dead(), _Alive()
    client = GatewayClient({"anthropic": dead, "openai": alive}, cache=None)

    for _ in range(12):
        _call(client)

    reasons = [a.get("reason") for record in audit.records() for a in record["attempts"]]
    assert "circuit_open" in reasons, "a skipped leg left no trace in the audit trail"


def test_every_leg_still_being_open_surfaces_as_no_provider_available():
    """A total outage must not read as a success."""
    from ai.gateway.client import NoProviderAvailable

    dead = _Dead()
    client = GatewayClient({"anthropic": dead}, cache=None)

    for _ in range(breakers.FAILURE_THRESHOLD + 2):
        with pytest.raises(NoProviderAvailable):
            _call(client)


def test_breakers_are_registered_so_the_health_surface_can_see_them():
    """They join the same registry redis/broker/ml_model already use."""
    from resilience.service_circuit_breakers import get_all_breaker_status

    breakers.leg_breaker("anthropic")
    names = get_all_breaker_status()["breakers"]
    assert any("anthropic" in name for name in names), (
        f"the gateway breaker is not in the shared registry; saw {sorted(names)}"
    )
