# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/feeds — Market data feed adapters.

Sub-packages
------------
    data_layer.feeds.gold    Gold price adapters (GoldAPI, Metals.dev, etc.)
                             Coordinated by GoldFeedManager.
    data_layer.feeds.macro   Macro data adapters (FRED, WGC, CFTC COT, IMF)
                             Coordinated by MacroStoreBridge.
    data_layer.feeds.news    News feed adapters (Finnhub, FMP, NewsAPI, etc.)
                             Coordinated by NewsSentimentEngine.

Architecture invariant
----------------------
All feed adapters are internal to data_layer. External code must access
data through data_layer.orchestrator, never by importing adapters directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__: list[str] = []
