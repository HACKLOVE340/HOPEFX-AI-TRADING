# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§19 notification policy: when the AI may interrupt you, and when it may not.

The floor, restated here because it is the reason the package exists: **a
critical notification is never suppressed and never deferred**, by quiet hours,
sleep mode, deduplication, rate limiting, or any combination of them.
"""

from ai.notify.policy import (
    CRITICAL_FLOOR_REASON,
    DEDUP_WINDOW_S,
    Alarm,
    Decision,
    Notification,
    Policy,
    QuietHours,
    Severity,
    Watch,
    decide,
)
from ai.notify.router import Router

__all__ = [
    "CRITICAL_FLOOR_REASON",
    "DEDUP_WINDOW_S",
    "Alarm",
    "Decision",
    "Notification",
    "Policy",
    "QuietHours",
    "Router",
    "Severity",
    "Watch",
    "decide",
]
