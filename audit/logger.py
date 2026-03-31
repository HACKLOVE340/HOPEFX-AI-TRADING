# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
audit/logger.py
================
Production audit logger — delegates to the hash-chained ImmutableAuditLog
in compliance/auditor.py.

This module exists for backward compatibility: code that imports
``from audit.logger import AuditLogger`` continues to work, but all
writes go through the tamper-evident compliance audit system.

The legacy AuditLogger interface (log_action, track_compliance) is
preserved and mapped to ImmutableAuditLog.append() with appropriate
AuditLevel and category values.

For new code, import directly from compliance.auditor:
    from compliance.auditor import ImmutableAuditLog, AuditLevel
"""

from __future__ import annotations

import logging
from typing import Any

from compliance.auditor import AuditLevel, ImmutableAuditLog

logger = logging.getLogger(__name__)

# Module-level singleton — shared across all importers
_audit_log = ImmutableAuditLog(log_path="data/audit/")


class AuditLogger:
    """
    Backward-compatible audit logger backed by ImmutableAuditLog.

    All writes are hash-chained and persisted to data/audit/*.jsonl.
    """

    def __init__(self, log_file: str = "audit.log") -> None:
        # log_file parameter kept for API compatibility; actual storage
        # is managed by ImmutableAuditLog (data/audit/*.jsonl)
        self._log = _audit_log

    def log_action(self, user: str, action: str, details: Any) -> None:
        """Log a user or system action to the immutable audit trail."""
        self._log.append(
            level=AuditLevel.INFO,
            category="ACTION",
            actor=str(user),
            action=str(action),
            data={"details": str(details)},
        )

    def track_compliance(self, user: str, compliance_check: str, result: str) -> None:
        """Log a compliance check result to the immutable audit trail."""
        self._log.append(
            level=AuditLevel.COMPLIANCE,
            category="COMPLIANCE_CHECK",
            actor=str(user),
            action=str(compliance_check),
            data={"result": str(result)},
        )

    def log_trade(self, trade_id: str, details: Any) -> None:
        """Log a trade event."""
        self._log.append(
            level=AuditLevel.COMPLIANCE,
            category="TRADE",
            actor="system",
            action="TRADE_EVENT",
            data={"trade_id": trade_id, "details": details},
        )

    def log_risk_event(self, event_type: str, details: Any) -> None:
        """Log a risk event (drawdown breach, circuit breaker, etc.)."""
        self._log.append(
            level=AuditLevel.CRITICAL,
            category="RISK",
            actor="system",
            action=str(event_type),
            data={"details": details},
        )

    def verify_integrity(self) -> bool:
        """Verify the hash chain integrity of the audit log."""
        return self._log.verify_integrity()


def get_audit_logger() -> AuditLogger:
    """Return the module-level AuditLogger singleton."""
    return AuditLogger()
