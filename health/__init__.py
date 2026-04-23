# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
health — Health check service for external monitoring integrations.

The primary health endpoints are in api/health.py (FastAPI router).
This package provides a standalone health check service for use by
Kubernetes liveness/readiness probes and external monitoring tools.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from health.health_check_service import HealthCheckService
except Exception as _exc:
    logger.debug("health.health_check_service unavailable: %s", _exc)
    HealthCheckService = None  # type: ignore[assignment,misc]

__all__ = ["HealthCheckService"]
