# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tracing/setup.py — OpenTelemetry + Jaeger tracing setup.

Requires: opentelemetry-sdk, opentelemetry-exporter-jaeger
Set JAEGER_HOST / JAEGER_PORT env vars to point at your Jaeger agent.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    try:
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    except ImportError:
        from opentelemetry.exporter.jaeger import JaegerExporter  # type: ignore[no-redef]

    resource = Resource.create({"service.name": os.getenv("SERVICE_NAME", "hopefx")})
    trace.set_tracer_provider(TracerProvider(resource=resource))

    jaeger_exporter = JaegerExporter(
        agent_host_name=os.getenv("JAEGER_HOST", "localhost"),
        agent_port=int(os.getenv("JAEGER_PORT", "6831")),
    )
    trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jaeger_exporter))
    logger.info("Jaeger tracing configured → %s:%s", os.getenv("JAEGER_HOST", "localhost"), os.getenv("JAEGER_PORT", "6831"))

except Exception as _exc:
    logger.debug("Jaeger tracing not available: %s", _exc)

# Usage:
# tracer = trace.get_tracer(__name__)
# with tracer.start_span("my_span"):
#     # do some work
