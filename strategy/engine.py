# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
strategy/engine.py — backward-compatibility shim.

The canonical implementation has moved to core/strategy_engine.py.
This module re-exports everything so existing import sites continue to work
while code is gradually migrated.

.. deprecated::
    Import from ``core.strategy_engine`` instead.
"""

from __future__ import annotations

# Re-export everything from the canonical module so both old and new import
# paths resolve to the same objects.
from core.strategy_engine import (
    EMA_FAST,
    EMA_SLOW,
    BUFFER_SIZE,
    HEARTBEAT_INTERVAL,
    MIN_BARS,
    ML_MIN_PROB,
    TICKS_PER_BAR,
    StrategyEngine,
    _MLPredictor,
    _OHLCVBuffer,
)

__all__ = [
    "StrategyEngine",
    "_OHLCVBuffer",
    "_MLPredictor",
    "ML_MIN_PROB",
    "MIN_BARS",
    "BUFFER_SIZE",
    "EMA_FAST",
    "EMA_SLOW",
    "HEARTBEAT_INTERVAL",
    "TICKS_PER_BAR",
]
