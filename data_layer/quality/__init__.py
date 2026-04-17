# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/quality — Real-time data quality validation engine.

Public API
----------
    DataQualityEngine   Validates every tick: price jump detection, stale
                        tick rejection, inverted/excessive spread detection,
                        cross-source consensus, Mahalanobis anomaly scoring,
                        and per-source confidence tracking.

Usage
-----
    from data_layer.quality import DataQualityEngine
    dqe = DataQualityEngine()
    result = dqe.validate_tick(tick)   # TickQuality enum
    report = dqe.get_quality_report()  # QualityReport dataclass
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.quality.engine import DataQualityEngine  # noqa: F401
except Exception as _exc:
    logger.debug("data_layer.quality: DataQualityEngine unavailable: %s", _exc)
    DataQualityEngine = None  # type: ignore[assignment,misc]

__all__ = ["DataQualityEngine"]
