# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/regime_router.py
=====================
Shim that re-exports :class:`~strategies.regime_router.RegimeRouter` from the
``strategies`` package so that callers using ``from core.regime_router import …``
continue to work.

The canonical implementation lives in ``strategies/regime_router.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from strategies.regime_router import RegimeRouter

logger = logging.getLogger(__name__)

__all__ = ["RegimeRouter", "get_current_regime"]

# Module-level RegimeRouter singleton — created lazily on first call.
_router: RegimeRouter | None = None


def _get_router() -> RegimeRouter | None:
    """Return the module-level RegimeRouter singleton."""
    global _router
    if _router is None:
        try:
            _router = RegimeRouter()
        except Exception as exc:
            logger.debug("RegimeRouter init failed: %s", exc)
    return _router


def get_current_regime(symbol: str = "XAUUSD") -> dict[str, Any] | None:
    """Return the current market regime for *symbol* as a dict.

    Returns
    -------
    dict with keys:
        regime      : str  — regime name (e.g. "TRENDING_UP", "HIGH_VOL")
        confidence  : float — detector confidence 0–1
        duration    : int   — bars in current regime
    Returns None when the router is unavailable or not yet fitted.
    """
    router = _get_router()
    if router is None:
        return None
    try:
        status = router.status()
        regime = status.get("current_regime", "UNKNOWN")
        # status() returns "confidence" (not "regime_confidence")
        confidence = float(status.get("confidence", status.get("regime_confidence", 0.0)))
        duration = int(status.get("regime_duration_bars", status.get("duration", 0)))
        return {
            "regime": regime,
            "confidence": confidence,
            "duration": duration,
            "symbol": symbol,
        }
    except Exception as exc:
        logger.debug("get_current_regime failed for %s: %s", symbol, exc)
        return None
