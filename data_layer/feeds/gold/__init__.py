# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/feeds/gold — Gold price feed adapters.

Public API
----------
    GoldFeedManager     Coordinates all five gold price adapters with
                        priority-ordered failover, cross-source consensus,
                        and Redis pub/sub publishing.
    GoldFeedBase        Abstract base class for all gold feed adapters.
                        Implements retry, rate limiting, and circuit breaker.

Individual adapters (internal — use GoldFeedManager, not these directly)
-------------------------------------------------------------------------
    GoldAPIFeed, MetalsDevFeed, MetalsAPIFeed,
    MetalpriceAPIFeed, CommodityAPIFeed
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.feeds.gold.manager import GoldFeedManager
except Exception as _exc:
    logger.debug("data_layer.feeds.gold: GoldFeedManager unavailable: %s", _exc)
    GoldFeedManager = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.gold.base import GoldFeedBase
except Exception as _exc:
    logger.debug("data_layer.feeds.gold: GoldFeedBase unavailable: %s", _exc)
    GoldFeedBase = None  # type: ignore[assignment,misc]

__all__ = ["GoldFeedBase", "GoldFeedManager"]
