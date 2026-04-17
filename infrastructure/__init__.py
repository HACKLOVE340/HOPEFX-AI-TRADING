# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
infrastructure — Observability and operational infrastructure.

Public API
----------
    MetricsRegistry     Prometheus-compatible metrics collection with custom
                        collectors. Exposes Counter, Gauge, Histogram, Summary.
    HealthChecker       Comprehensive health monitoring with dependency checks.
                        Supports async health check functions and HTTP endpoint.
    StructuredLogger    JSON-structured logging with rotation and remote shipping.

Usage
-----
    from infrastructure import get_metrics_registry, Counter
    from infrastructure.health import HealthChecker
    from infrastructure.logging import get_logger
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from infrastructure.metrics import (  # noqa: F401
        Counter,
        Gauge,
        Histogram,
        MetricsRegistry,
        Summary,
        get_metrics_registry,
    )
except Exception as _exc:
    logger.debug("infrastructure.metrics unavailable: %s", _exc)
    MetricsRegistry = None  # type: ignore[assignment,misc]
    get_metrics_registry = None  # type: ignore[assignment]

try:
    from infrastructure.health import HealthChecker  # noqa: F401
except Exception as _exc:
    logger.debug("infrastructure.health unavailable: %s", _exc)
    HealthChecker = None  # type: ignore[assignment,misc]

try:
    from infrastructure.logging import StructuredLogger, get_logger  # noqa: F401
except Exception as _exc:
    logger.debug("infrastructure.logging unavailable: %s", _exc)
    StructuredLogger = None  # type: ignore[assignment,misc]
    get_logger = None  # type: ignore[assignment]

__all__ = [
    "Counter",
    "Gauge",
    "HealthChecker",
    "Histogram",
    "MetricsRegistry",
    "StructuredLogger",
    "Summary",
    "get_logger",
    "get_metrics_registry",
]
