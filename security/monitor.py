# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
security/monitor.py
===================
Security event monitor — tracks attack events and exposes recent activity.

Backed by the HOPEFXBrain (global_fortress) when available; falls back to an
in-memory ring buffer so the API never hard-fails.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc

# In-memory ring buffer (used when HOPEFXBrain is not running)
_MAX_EVENTS = 1000
_event_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_total_count: int = 0


def record_attack(event: dict[str, Any]) -> None:
    """Append *event* to the in-memory attack log.

    Args:
        event: Arbitrary dict describing the security event.  A ``timestamp``
               key (ISO-8601) will be added if not present.
    """
    global _total_count  # pylint: disable=global-statement
    if "timestamp" not in event:
        event = {**event, "timestamp": datetime.now(UTC).isoformat()}
    _event_buffer.append(event)
    _total_count += 1


class SecurityMonitor:
    """Provides access to recent security events and aggregate counts.

    Wraps the in-memory ring buffer when HOPEFXBrain is not available.
    """

    def recent_attacks(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the *limit* most recent attack events (newest first).

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of event dicts.
        """
        events = list(_event_buffer)
        return list(reversed(events[-limit:]))

    def attack_count(self) -> int:
        """Return the total number of attacks recorded since startup."""
        return _total_count

    def summary(self) -> dict[str, Any]:
        """Return a brief summary dict for dashboards."""
        recent = self.recent_attacks(10)
        return {
            "total_attacks": self._total_count(),
            "recent_10": recent,
        }

    def _total_count(self) -> int:
        return _total_count


# Singleton
_monitor_instance: SecurityMonitor | None = None


def get_security_monitor() -> SecurityMonitor:
    """Return the singleton :class:`SecurityMonitor` instance.

    Returns:
        Shared SecurityMonitor (created on first call).
    """
    global _monitor_instance  # pylint: disable=global-statement
    if _monitor_instance is None:
        _monitor_instance = SecurityMonitor()
    return _monitor_instance
