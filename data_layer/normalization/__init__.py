# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/normalization — Real-time tick and OHLCV cleaning pipeline.

Public API
----------
    NormalizationPipeline   Applies 9-step tick normalisation and 9-step
                            OHLCV cleaning. Enforces UTC timestamps, price
                            rounding, spread floors, and OHLCV integrity.
                            All operations are causal (no look-ahead).

Usage
-----
    from data_layer.normalization import NormalizationPipeline
    pipeline = NormalizationPipeline()
    clean_tick = pipeline.normalize_tick(raw_tick)
    clean_df   = pipeline.normalize_ohlcv(raw_df)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.normalization.pipeline import NormalizationPipeline
except Exception as _exc:
    logger.debug("data_layer.normalization: NormalizationPipeline unavailable: %s", _exc)
    NormalizationPipeline = None  # type: ignore[assignment,misc]

__all__ = ["NormalizationPipeline"]
