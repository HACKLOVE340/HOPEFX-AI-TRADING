# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/calendar — Macro economic calendar with gold impact scoring.

Public API
----------
    MacroCalendarEngine   Fetches events from Finnhub (primary) or hard-coded
                          schedule (fallback). Scores gold impact per event.
                          Exposes is_blackout_window() and get_ml_features().

Usage
-----
    from data_layer.calendar import MacroCalendarEngine
    engine = MacroCalendarEngine()
    await engine.start()
    score = engine.get_current_impact_score()   # float [0, 1]
    blackout = engine.is_blackout_window()      # bool
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.calendar.engine import MacroCalendarEngine
except Exception as _exc:
    logger.debug("data_layer.calendar: MacroCalendarEngine unavailable: %s", _exc)
    MacroCalendarEngine = None  # type: ignore[assignment,misc]

__all__ = ["MacroCalendarEngine"]
