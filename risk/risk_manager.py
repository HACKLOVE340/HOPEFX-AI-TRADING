# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/risk_manager.py
====================
Backwards-compatibility shim.

Callers that use ``from risk.risk_manager import RiskManager`` are
redirected to the canonical implementation in ``risk.manager``.

The shim also exposes ``activate_kill_switch(reason)`` as a public
method so that settings endpoints can trigger a halt without needing
to know the internal ``_halt_trading`` API.
"""

from __future__ import annotations

import logging

from risk.manager import RiskManager as _BaseRiskManager

logger = logging.getLogger(__name__)


class RiskManager(_BaseRiskManager):
    """
    Drop-in replacement for ``risk.manager.RiskManager`` with an additional
    public ``activate_kill_switch`` method used by the settings API.
    """

    def activate_kill_switch(self, reason: str = "manual") -> None:
        """
        Immediately halt all trading.

        Delegates to the internal ``_halt_trading`` method and also
        attempts to propagate the halt to the running FastAPI application
        via the ``kill_switch`` attribute if available.
        """
        logger.warning("Kill switch activated via RiskManager: %s", reason)
        self._halt_trading(reason)

        # Best-effort propagation to the app-level kill switch
        try:
            import sys

            app = sys.modules.get("app") or sys.modules.get("run")
            ks = getattr(app, "kill_switch", None)
            if ks is not None and callable(getattr(ks, "activate", None)):
                ks.activate(reason=reason)
        except Exception as exc:  # pragma: no cover
            logger.debug("Could not propagate kill switch to app: %s", exc)

    def deactivate_kill_switch(self, reason: str = "manual reset") -> None:
        """Re-enable trading after a kill switch halt."""
        logger.info("Kill switch deactivated via RiskManager: %s", reason)
        self._halt = False
        self._trading_halted = False
        self._halt_reason = ""
        self._clear_halt_state()


__all__ = ["RiskManager"]
