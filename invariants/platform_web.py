# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.platform_web — generic-platform health: availability, frontend, API & infra.

Pure predicates for the framework's Section-1 generic-platform categories that a
*correct* trading platform shares with any serious web system: the service must
be up, error rates bounded, the frontend must actually render, the API must meet
its schema/latency contract, and host resources must not be exhausted. Every
threshold is a parameter (no magic values) and each function returns
``list[Violation]`` — empty means the invariant holds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_AVAIL = "No Silent Failure"


# ── availability ────────────────────────────────────────────────────────────────
def verify_service_up(healthy: bool, name: str = "service") -> list[Violation]:
    """The service must report healthy."""
    if not healthy:
        return [_v(_AVAIL, CRITICAL, f"{name} is not healthy/up")]
    return []


def verify_uptime(uptime_pct: float, min_pct: float) -> list[Violation]:
    """Availability must stay above the SLA floor."""
    if _is_finite_number(uptime_pct) and uptime_pct < min_pct:
        return [_v(_AVAIL, CRITICAL, f"uptime {uptime_pct}% below SLA {min_pct}%")]
    return []


def verify_error_rate(error_rate: float, max_rate: float) -> list[Violation]:
    """The 5xx/error rate must stay bounded."""
    if _is_finite_number(error_rate) and error_rate > max_rate:
        return [_v(_AVAIL, CRITICAL, f"error rate {error_rate} exceeds max {max_rate}")]
    return []


def verify_restart_count(restarts: int, max_restarts: int, window: str = "1h") -> list[Violation]:
    """A crash-looping process (excess restarts in a window) is a silent failure."""
    if restarts > max_restarts:
        return [_v(_AVAIL, CRITICAL, f"{restarts} restarts in {window} exceeds {max_restarts} (crash loop?)")]
    return []


# ── frontend ────────────────────────────────────────────────────────────────────
def verify_no_console_errors(error_count: int) -> list[Violation]:
    """The UI must load without runtime console errors."""
    if error_count > 0:
        return [_v(_AVAIL, WARNING, f"frontend produced {error_count} console error(s)")]
    return []


def verify_page_renders(rendered: bool, route: str = "/") -> list[Violation]:
    """A route must actually render content (not a blank/white screen)."""
    if not rendered:
        return [_v(_AVAIL, CRITICAL, f"route {route} did not render (blank screen)")]
    return []


def verify_page_load_time(load_ms: float, budget_ms: float, route: str = "/") -> list[Violation]:
    """Page load must meet its performance budget."""
    if _is_finite_number(load_ms) and load_ms > budget_ms:
        return [_v(_AVAIL, WARNING, f"{route} load {load_ms}ms exceeds budget {budget_ms}ms")]
    return []


def verify_web_vital(name: str, value: float, budget: float) -> list[Violation]:
    """A Core Web Vital (LCP/FCP/TTI/CLS) must stay within budget."""
    if _is_finite_number(value) and value > budget:
        return [_v(_AVAIL, WARNING, f"web vital {name} {value} exceeds budget {budget}")]
    return []


def verify_bundle_size(size_kb: float, max_kb: float) -> list[Violation]:
    """The shipped JS bundle must not balloon past its size budget."""
    if _is_finite_number(size_kb) and size_kb > max_kb:
        return [_v(_AVAIL, WARNING, f"bundle {size_kb}KB exceeds budget {max_kb}KB")]
    return []


# ── API ─────────────────────────────────────────────────────────────────────────
def verify_api_status(status_code: int, expected: Iterable[int] = (200, 201, 204)) -> list[Violation]:
    """An API endpoint must return an expected status code."""
    if status_code not in set(expected):
        return [_v(_AVAIL, CRITICAL, f"API returned {status_code}, expected one of {sorted(set(expected))}")]
    return []


def verify_api_schema(payload: Mapping[str, Any], required_keys: set[str]) -> list[Violation]:
    """An API response must contain its contract's required keys."""
    missing = required_keys - set(payload.keys())
    if missing:
        return [_v(_AVAIL, CRITICAL, f"API response missing required keys: {sorted(missing)}")]
    return []


def verify_api_latency(latency_ms: float, budget_ms: float, endpoint: str = "") -> list[Violation]:
    """An API call must meet its latency budget."""
    if _is_finite_number(latency_ms) and latency_ms > budget_ms:
        return [_v(_AVAIL, WARNING, f"API {endpoint} latency {latency_ms}ms exceeds budget {budget_ms}ms")]
    return []


def verify_api_version_supported(version: Any, supported: set[Any]) -> list[Violation]:
    """A client must speak a still-supported API version (no silent break)."""
    if supported and version not in supported:
        return [_v(_AVAIL, WARNING, f"API version {version!r} not in supported set {sorted(map(str, supported))}")]
    return []


# ── infrastructure / host resources ──────────────────────────────────────────────
def verify_resource_headroom(used_pct: float, max_pct: float, resource: str = "cpu") -> list[Violation]:
    """A host resource (cpu/mem/disk/network) must keep headroom below saturation."""
    if _is_finite_number(used_pct) and used_pct > max_pct:
        sev = CRITICAL if used_pct >= 100 else WARNING  # noqa: PLR2004 - 100% = saturation
        return [_v(_AVAIL, sev, f"{resource} usage {used_pct}% exceeds limit {max_pct}%")]
    return []


def verify_disk_not_full(free_pct: float, min_free_pct: float) -> list[Violation]:
    """Disk must retain a minimum free fraction (a full disk corrupts/halts writes)."""
    if _is_finite_number(free_pct) and free_pct < min_free_pct:
        return [_v(_AVAIL, CRITICAL, f"disk free {free_pct}% below minimum {min_free_pct}%")]
    return []


def verify_connection_pool(active: int, capacity: int) -> list[Violation]:
    """A connection/thread pool must not be exhausted (exhaustion = stalled requests)."""
    if capacity > 0 and active >= capacity:
        return [_v(_AVAIL, CRITICAL, f"connection pool exhausted: {active}/{capacity} in use")]
    return []


def verify_certificate_valid(days_to_expiry: float, min_days: float) -> list[Violation]:
    """TLS certificates must be renewed before they expire."""
    if _is_finite_number(days_to_expiry):
        if days_to_expiry <= 0:
            return [_v(_AVAIL, CONSTITUTIONAL, "TLS certificate is EXPIRED")]
        if days_to_expiry < min_days:
            return [_v(_AVAIL, WARNING, f"TLS certificate expires in {days_to_expiry}d (< {min_days}d)")]
    return []
