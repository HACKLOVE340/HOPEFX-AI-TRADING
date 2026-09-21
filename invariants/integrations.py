# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.integrations — external dependencies & ancillary services.

Pure predicates for the framework's integration categories: third-party/vendor
dependencies must be healthy and within rate limits, webhooks must be verified
and not replayed, notifications must actually be delivered, object storage must
be durable and consistent, search & analytics pipelines must stay fresh and not
drop events. These are the "edges" of the platform where silent failures hide.
Each returns ``list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_RULE = "No Silent Failure"


def verify_dependency_healthy(healthy: bool, name: str = "dependency") -> list[Violation]:
    """A critical external dependency must be healthy."""
    if not healthy:
        return [_v(_RULE, CRITICAL, f"external dependency {name} is unhealthy")]
    return []


def verify_dependency_rate_limit(used: int, limit: int, name: str = "vendor") -> list[Violation]:
    """Vendor API usage must stay under quota (exhaustion = silent outage)."""
    if limit > 0 and used >= limit:
        return [_v(_RULE, CRITICAL, f"{name} API quota exhausted: {used}/{limit}")]
    return []


def verify_vendor_sla(response_ms: float, sla_ms: float, name: str = "vendor") -> list[Violation]:
    """A vendor call must meet its SLA latency."""
    if _is_finite_number(response_ms) and response_ms > sla_ms:
        return [_v(_RULE, WARNING, f"{name} response {response_ms}ms exceeds SLA {sla_ms}ms")]
    return []


def verify_webhook_signature(valid: bool, source: str = "webhook") -> list[Violation]:
    """An inbound webhook must carry a valid signature (forgery guard)."""
    if not valid:
        return [_v("No Data Corruption", CONSTITUTIONAL, f"{source} signature invalid (possible forgery)")]
    return []


def verify_webhook_not_replayed(event_id: Any, seen_ids: Iterable[Any]) -> list[Violation]:
    """A webhook event must not be processed twice (replay → double-effect)."""
    if event_id in set(seen_ids):
        return [_v("No Data Corruption", CRITICAL, f"webhook event {event_id!r} replayed")]
    return []


def verify_notification_delivered(sent: int, delivered: int, max_failures: int) -> list[Violation]:
    """Notification delivery failures must stay bounded (missed alerts are dangerous)."""
    failures = max(0, sent - delivered)
    if failures > max_failures:
        return [_v(_RULE, CRITICAL, f"{failures} notification delivery failure(s) exceed {max_failures}")]
    return []


def _bad_count(value: Any) -> bool:
    """True when *value* cannot be a count.

    Written out rather than inlined because the failure it guards is silent: a
    NaN compared with ``>`` is False on every side, so a broken counter sails
    through every threshold below and the ladder reports health.
    """
    return not _is_finite_number(value) or value < 0


def verify_alert_evidence_ladder(
    fired: int,
    delivered: int,
    accepted: int | None = None,
    *,
    expected_fired: int | None = None,
    name: str = "alert",
) -> list[Violation]:
    """AOS-EVID-046 — firing, delivery and acceptance are three separate rungs.

    An alert that FIRED reached the log. One that was DELIVERED was handed to a
    channel. One that was ACCEPTED was acknowledged by something outside this
    process. Collapsing those into one boolean is how an alerting pipeline
    reports health while notifying nobody, which has happened here twice: F159
    (the delivery guard and the delivery were the same branch, so every alert
    stopped at the log line) and F248 (three call sites passed arguments the
    target rejects, so a tripped circuit breaker, a model rollback and a
    position-drift halt each notified no one).

    ``accepted=None`` means NOT OBSERVED and is reported as such. It is
    deliberately NOT defaulted to ``delivered``: a rung nobody measured is not a
    rung that passed, and assuming otherwise is the precise conflation this
    invariant exists to forbid.

    ``expected_fired`` closes the hole that ``verify_notification_delivered``
    cannot: (0 fired, 0 delivered) is arithmetically perfect and is also exactly
    what a completely dead pipeline looks like. When the caller knows alerts were
    due, silence is the failure. Left unset, a quiet period stays clean — a
    predicate that cries wolf is one operators learn to ignore.
    """
    out: list[Violation] = []

    for label, value in (("fired", fired), ("delivered", delivered)):
        if _bad_count(value):
            return [_v(_RULE, CRITICAL, f"{name} {label} count is not a usable number ({value!r})")]
    if accepted is not None and _bad_count(accepted):
        return [_v(_RULE, CRITICAL, f"{name} accepted count is not a usable number ({accepted!r})")]

    # Rung 0 — was there anything to measure at all?
    if expected_fired is not None:
        if _bad_count(expected_fired):
            return [_v(_RULE, CRITICAL, f"{name} expected_fired is not a usable number ({expected_fired!r})")]
        if fired < expected_fired:
            out.append(
                _v(
                    _RULE,
                    CRITICAL,
                    f"{name}s expected {expected_fired} but only {fired} fired — silence is being read as health",
                )
            )

    # Rung 1 — fired -> delivered.
    if delivered > fired:
        out.append(_v(_RULE, CRITICAL, f"{name} counting is broken: {delivered} delivered exceeds {fired} fired"))
    elif fired > 0 and delivered == 0:
        out.append(_v(_RULE, CRITICAL, f"{name}s reached the log only: {fired} fired, {delivered} delivered"))
    elif delivered < fired:
        out.append(
            _v(_RULE, CRITICAL, f"{name} delivery lost {fired - delivered}: {fired} fired, {delivered} delivered")
        )

    # Rung 2 — delivered -> accepted.
    if accepted is None:
        if delivered > 0:
            out.append(
                _v(
                    _RULE,
                    WARNING,
                    f"{name} acceptance was never observed for {delivered} delivered — "
                    "not observed is not the same as accepted",
                )
            )
    elif accepted > delivered:
        out.append(_v(_RULE, CRITICAL, f"{name} counting is broken: {accepted} accepted exceeds {delivered} delivered"))
    elif accepted < delivered:
        out.append(
            _v(_RULE, CRITICAL, f"{name} delivery was not acknowledged for {delivered - accepted} of {delivered}")
        )

    return out


def verify_storage_durable(replicas: int, min_replicas: int, name: str = "object") -> list[Violation]:
    """Stored objects must meet the minimum replication for durability."""
    if replicas < min_replicas:
        return [_v(_RULE, CRITICAL, f"{name} stored with {replicas} replica(s) < required {min_replicas}")]
    return []


def verify_storage_checksum(expected: str, actual: str, key: str = "") -> list[Violation]:
    """A stored object must read back with a matching checksum (no bit-rot)."""
    if expected != actual:
        return [_v("No Data Corruption", CONSTITUTIONAL, f"storage checksum mismatch for {key!r} (corruption)")]
    return []


def verify_pipeline_fresh(lag_seconds: float, max_lag_seconds: float, name: str = "pipeline") -> list[Violation]:
    """A search/analytics pipeline must stay within its freshness budget."""
    if _is_finite_number(lag_seconds) and lag_seconds > max_lag_seconds:
        return [_v(_RULE, WARNING, f"{name} lag {lag_seconds}s exceeds {max_lag_seconds}s")]
    return []


def verify_no_event_loss(emitted: int, ingested: int, tolerance: int = 0) -> list[Violation]:
    """An analytics/event pipeline must not silently drop events."""
    lost = emitted - ingested
    if lost > tolerance:
        return [_v(_RULE, CRITICAL, f"{lost} event(s) lost in pipeline (emitted {emitted}, ingested {ingested})")]
    return []


def verify_circuit_open_on_failure(
    failure_rate: float, threshold: float, circuit_open: bool, name: str = "dependency"
) -> list[Violation]:
    """A failing dependency must trip its circuit breaker (blast-radius containment)."""
    if _is_finite_number(failure_rate) and failure_rate > threshold and not circuit_open:
        return [
            _v(
                "No Unbounded Failure",
                CRITICAL,
                f"{name} failure rate {failure_rate} > {threshold} but circuit not open",
            )
        ]
    return []
