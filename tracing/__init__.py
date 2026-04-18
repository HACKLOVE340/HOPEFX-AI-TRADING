# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tracing — OpenTelemetry distributed tracing integration.

Public API
----------
    get_tracer(name)    Returns an OpenTelemetry tracer for the given name.
                        Falls back to a no-op tracer if OTEL is not configured.
    setup_tracing()     Initialises the OTLP exporter and global tracer provider.
                        Called once at startup from app.py.

Usage
-----
    from tracing import get_tracer
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("symbol", "XAU_USD")
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from tracing.setup import get_tracer, setup_tracing
except Exception as _exc:
    logger.debug("tracing.setup unavailable: %s", _exc)
    get_tracer = None  # type: ignore[assignment]
    setup_tracing = None  # type: ignore[assignment]

__all__ = ["get_tracer", "setup_tracing"]
