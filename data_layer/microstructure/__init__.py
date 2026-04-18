# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/microstructure — Tick-by-tick market microstructure analytics.

Public API
----------
    MicrostructureEngine   Computes spread dynamics, order flow imbalance (OFI),
                           Kyle's lambda, absorption ratio, and delta divergence
                           from raw tick data. Zero look-ahead guaranteed.

Usage
-----
    from data_layer.microstructure import MicrostructureEngine
    engine = MicrostructureEngine()
    snapshot = engine.on_tick(tick)   # MicrostructureSnapshot
    features = engine.get_ml_features()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.microstructure.engine import MicrostructureEngine
except Exception as _exc:
    logger.debug("data_layer.microstructure: MicrostructureEngine unavailable: %s", _exc)
    MicrostructureEngine = None  # type: ignore[assignment,misc]

__all__ = ["MicrostructureEngine"]
