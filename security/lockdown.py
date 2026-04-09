# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
security/lockdown.py
====================
Platform lockdown manager.

Provides a high-level interface to trigger and query system-wide lockdowns.
Delegates to HOPEFXBrain when available; maintains independent state otherwise.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc


class LockdownManager:
    """Manages platform-wide security lockdowns.

    When a lockdown is active all new trading orders are rejected and
    suspicious IPs are blocked.  The lockdown can be manually lifted by a
    superadmin via :meth:`lift`.
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._reason: str = ""
        self._triggered_at: datetime | None = None
        self._triggered_by: str = "system"

    @property
    def is_active(self) -> bool:
        """``True`` when a lockdown is currently in effect."""
        return self._active

    async def trigger(self, reason: str = "manual", triggered_by: str = "superadmin") -> dict[str, Any]:
        """Activate the platform lockdown.

        Args:
            reason:       Human-readable reason for the lockdown.
            triggered_by: Identifier of the actor who triggered it.

        Returns:
            Status dict with ``active``, ``reason``, and ``triggered_at``.
        """
        self._active = True
        self._reason = reason
        self._triggered_at = datetime.now(UTC)
        self._triggered_by = triggered_by
        logger.warning("PLATFORM LOCKDOWN ACTIVATED — reason=%s by=%s", reason, triggered_by)

        # Notify via HOPEFXBrain when available
        try:
            from security.global_fortress import _brain_instance  # type: ignore[attr-defined]

            if _brain_instance is not None:
                asyncio.ensure_future(_brain_instance.trigger_full_lockdown(f"manual:{reason}"))
        except Exception as exc:
            logger.debug("HOPEFXBrain lockdown delegation error: %s", exc)

        return self.status()

    async def lift(self, lifted_by: str = "superadmin") -> dict[str, Any]:
        """Deactivate the platform lockdown.

        Args:
            lifted_by: Identifier of the actor lifting the lockdown.

        Returns:
            Status dict with ``active`` set to ``False``.
        """
        self._active = False
        logger.warning("PLATFORM LOCKDOWN LIFTED by=%s", lifted_by)
        return self.status()

    def status(self) -> dict[str, Any]:
        """Return current lockdown state.

        Returns:
            Dict with ``active``, ``reason``, ``triggered_at``, and ``triggered_by``.
        """
        return {
            "active": self._active,
            "reason": self._reason,
            "triggered_at": self._triggered_at.isoformat() if self._triggered_at else None,
            "triggered_by": self._triggered_by,
        }


# Singleton
_lockdown_instance: LockdownManager | None = None


def get_lockdown_manager() -> LockdownManager:
    """Return the singleton :class:`LockdownManager` instance.

    Returns:
        Shared LockdownManager (created on first call).
    """
    global _lockdown_instance  # pylint: disable=global-statement
    if _lockdown_instance is None:
        _lockdown_instance = LockdownManager()
    return _lockdown_instance
