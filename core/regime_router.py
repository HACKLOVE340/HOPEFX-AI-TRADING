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
import os
import time
from typing import Any

from strategies.regime_router import RegimeRouter

logger = logging.getLogger(__name__)

__all__ = ["RegimeRouter", "get_current_regime"]

# Module-level RegimeRouter singleton — created lazily on first call.
_router: RegimeRouter | None = None

#: Monotonic timestamp of the last successful detection. Detection sits on the
#: per-signal path, so it is cached rather than re-run for every order.
_last_detect_at: float = 0.0

#: Seconds a detection stays current. Cached, not frozen: a cache that never
#: expires is F94 again with a shorter duration.
_DETECT_TTL_S: float = float(os.getenv("REGIME_DETECT_TTL_S", "60"))

#: Below this, detect_regime is measuring noise rather than a regime.
_MIN_BARS_FOR_DETECTION: int = int(os.getenv("REGIME_MIN_BARS", "50"))

#: How many bars to ask the data layer for.
_DETECT_BARS: int = int(os.getenv("REGIME_DETECT_BARS", "200"))
_DETECT_TIMEFRAME: str = os.getenv("REGIME_DETECT_TIMEFRAME", "H1")


def _detect_now(router: RegimeRouter, symbol: str) -> bool:
    """Run the detector against fresh bars. Returns True if it ran.

    ``RegimeRouter.route()`` is the only writer of ``_last_regime`` and
    ``_last_confidence``, and **nothing in the repo called it** — so
    ``status()`` returned the constructor's "unknown" for the life of the
    process and ``_REGIME_SIZE_MAP["UNKNOWN"] == 0.5`` scaled every position on
    the platform (F94).

    Stays conservative on every failure path. No bars, too few bars, or a
    detector that raises all leave the regime UNKNOWN, which keeps the 0.5
    scalar. Inventing a regime to avoid the halving would be worse than the
    halving.
    """
    try:
        from data_layer.orchestrator import orchestrator

        df = orchestrator.get_ohlcv_window(
            symbol=symbol, bars=_DETECT_BARS, timeframe=_DETECT_TIMEFRAME
        )
    except Exception as exc:
        logger.debug("Regime detection: no bar source for %s: %s", symbol, exc)
        return False

    if df is None or len(df) < _MIN_BARS_FOR_DETECTION:
        logger.debug(
            "Regime detection skipped for %s: %s bars, need >= %d",
            symbol,
            0 if df is None else len(df),
            _MIN_BARS_FOR_DETECTION,
        )
        return False

    try:
        router.route(df)
        return True
    except Exception as exc:
        logger.warning("Regime detection failed for %s — regime stays UNKNOWN: %s", symbol, exc)
        return False


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
    global _last_detect_at

    router = _get_router()
    if router is None:
        return None

    # Run the detector when the cached result has expired. Without this the
    # router's state never leaves its constructor and every position is scaled
    # by the UNKNOWN fallback (F94).
    now = time.monotonic()
    if now - _last_detect_at >= _DETECT_TTL_S and _detect_now(router, symbol):
        _last_detect_at = now

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
