# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""audit — Immutable audit logging for compliance and security events."""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)
try:
    from audit.logger import AuditLogger, get_audit_logger
except Exception as _exc:
    logger.debug("audit.logger unavailable: %s", _exc)
    AuditLogger = None  # type: ignore[assignment,misc]
    get_audit_logger = None  # type: ignore[assignment]
__all__ = ["AuditLogger", "get_audit_logger"]
