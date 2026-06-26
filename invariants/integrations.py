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


def verify_circuit_open_on_failure(failure_rate: float, threshold: float, circuit_open: bool,
                                   name: str = "dependency") -> list[Violation]:
    """A failing dependency must trip its circuit breaker (blast-radius containment)."""
    if _is_finite_number(failure_rate) and failure_rate > threshold and not circuit_open:
        return [_v("No Unbounded Failure", CRITICAL,
                   f"{name} failure rate {failure_rate} > {threshold} but circuit not open")]
    return []
