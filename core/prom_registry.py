# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/prom_registry.py
=====================
Idempotent Prometheus metric factory helpers.

Prometheus raises ``ValueError`` when the same metric name is registered
twice — this happens in tests when a module is re-imported after another
test has already imported it, and in multi-worker processes that share a
registry.  These helpers look up an existing metric by name before
creating a new one, preventing duplicate-registration errors.

Usage::

    from core.prom_registry import prom_counter, prom_gauge, prom_histogram

    MY_COUNTER = prom_counter("hopefx_my_events_total", "Description", ["label"])
    MY_GAUGE   = prom_gauge("hopefx_my_value", "Description")
"""

from __future__ import annotations

from typing import List, Optional, Sequence

try:
    from prometheus_client import Counter, Gauge, Histogram, Summary, REGISTRY

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


def _lookup(name: str):
    """Return an already-registered collector for *name*, or ``None``.

    prometheus_client stores metrics under their base name (without the
    ``_total`` suffix that Counter appends automatically).
    """
    if not _AVAILABLE:
        return None
    for candidate in (name, name.removesuffix("_total")):
        if candidate in REGISTRY._names_to_collectors:
            return REGISTRY._names_to_collectors[candidate]
    return None


def prom_counter(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
) -> "Optional[Counter]":
    """Return (or create) a Counter without raising on duplicate registration."""
    if not _AVAILABLE:
        return None
    existing = _lookup(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, list(labelnames))


def prom_gauge(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
) -> "Optional[Gauge]":
    """Return (or create) a Gauge without raising on duplicate registration."""
    if not _AVAILABLE:
        return None
    existing = _lookup(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Gauge(name, documentation, list(labelnames))


def prom_histogram(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
    buckets: "Sequence[float]" = Histogram.DEFAULT_BUCKETS if _AVAILABLE else (),  # type: ignore[attr-defined]
) -> "Optional[Histogram]":
    """Return (or create) a Histogram without raising on duplicate registration."""
    if not _AVAILABLE:
        return None
    existing = _lookup(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Histogram(name, documentation, list(labelnames), buckets=list(buckets))


def prom_summary(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
) -> "Optional[Summary]":
    """Return (or create) a Summary without raising on duplicate registration."""
    if not _AVAILABLE:
        return None
    existing = _lookup(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Summary(name, documentation, list(labelnames))
