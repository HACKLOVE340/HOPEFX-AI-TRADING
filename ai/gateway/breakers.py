# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One circuit breaker per vendor, so a dead leg stops being dialled.

`resolve_chain` returns an ordered list and `should_fall_through` decides whether
to advance. Neither remembers anything between calls, so a vendor that is
comprehensively down was contacted, timed out, and fell through on EVERY
subsequent request. With the 60-second default timeout and a dead primary, every
call paid that timeout before reaching a leg that works — and the operator saw
latency rather than an outage.

Nothing new is invented here. `resilience/service_circuit_breakers.py` is
already the platform's breaker and already guards redis, broker, ml_model and
database; these join the same registry, so gateway legs appear on the same
health surface as everything else.

**Only a transport failure trips a breaker.** A guardrail rejection, a refusal,
a `bad_request` — those mean the vendor answered, correctly, and the problem is
at this end. Counting them as outages would take a healthy vendor offline
because somebody sent a malformed prompt. `chain.should_fall_through` already
draws exactly this line for a different decision; `trips_breaker` reuses its
answer rather than keeping a second list that could drift from it.
"""

from __future__ import annotations

import logging
from typing import Any

from resilience.service_circuit_breakers import (
    BreakerConfig,
    ServiceCircuitBreaker,
    register_breaker,
)

logger = logging.getLogger(__name__)

#: Consecutive transport failures before a vendor is taken out of rotation.
#:
#: Higher than it looks like it should be, on purpose: the chain already has
#: fall-through, so a single failure costs one extra leg rather than a failed
#: request. The breaker exists to stop paying a 60-second timeout repeatedly,
#: not to react to one bad minute — and opening too eagerly on a vendor that is
#: merely slow removes a leg the chain still needs.
FAILURE_THRESHOLD = 4

#: Consecutive successes in half-open before the vendor is trusted again.
SUCCESS_THRESHOLD = 2

#: How long before a probe is allowed through. Short, because a vendor coming
#: back and not being noticed for ten minutes is its own kind of outage.
RECOVERY_TIMEOUT_S = 45.0

_BREAKERS: dict[str, ServiceCircuitBreaker] = {}


def leg_breaker(provider: str) -> ServiceCircuitBreaker:
    """The breaker for `provider`, created and registered on first use."""
    existing = _BREAKERS.get(provider)
    if existing is not None:
        return existing

    breaker = ServiceCircuitBreaker(
        BreakerConfig(
            name=f"ai_gateway_{provider}",
            failure_threshold=FAILURE_THRESHOLD,
            success_threshold=SUCCESS_THRESHOLD,
            timeout_seconds=RECOVERY_TIMEOUT_S,
        )
    )
    _BREAKERS[provider] = breaker
    try:
        register_breaker(breaker)
    except Exception as exc:  # a registry problem must not disable routing
        logger.warning("ai.gateway.breakers: could not register %s (%s)", provider, exc)
    return breaker


def trips_breaker(reason: str) -> bool:
    """Whether `reason` is an outage rather than an answer.

    Delegates to `should_fall_through`, which already separates the two:
    anything that means "this leg could not answer" is a transport problem and
    counts; anything that IS an answer does not. Keeping a second list here
    would be a list that drifts.
    """
    from ai.gateway.chain import should_fall_through

    return should_fall_through(reason)


def is_open(provider: str) -> bool:
    """True when `provider` is currently out of rotation."""
    return leg_breaker(provider).is_open


def record_outcome(provider: str, *, reason: str | None) -> None:
    """Tell the breaker how a leg behaved. `reason=None` means it served."""
    breaker = leg_breaker(provider)
    if reason is None:
        breaker.record_success()
    elif trips_breaker(reason):
        breaker.record_failure(RuntimeError(reason))


def status() -> dict[str, Any]:
    """Per-vendor breaker state, for the AI Core read surface."""
    return {name: breaker.get_status() for name, breaker in _BREAKERS.items()}


def reset_for_testing() -> None:
    _BREAKERS.clear()


__all__ = [
    "FAILURE_THRESHOLD",
    "RECOVERY_TIMEOUT_S",
    "SUCCESS_THRESHOLD",
    "is_open",
    "leg_breaker",
    "record_outcome",
    "reset_for_testing",
    "status",
    "trips_breaker",
]
