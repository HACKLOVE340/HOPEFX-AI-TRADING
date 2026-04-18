# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/cache — Redis caching layer for the data pipeline.

Public API
----------
    DataLayerRedisStore   High-performance Redis store for ticks, OHLCV,
                          microstructure, sentiment, and quality reports.
                          Key schema: hopefx:dl:{type}:{symbol}

Usage
-----
    from data_layer.cache import DataLayerRedisStore
    store = DataLayerRedisStore()
    await store.set_latest_tick("XAU_USD", tick)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.cache.redis_store import DataLayerRedisStore
except Exception as _exc:
    logger.debug("data_layer.cache: DataLayerRedisStore unavailable: %s", _exc)
    DataLayerRedisStore = None  # type: ignore[assignment,misc]

__all__ = ["DataLayerRedisStore"]
