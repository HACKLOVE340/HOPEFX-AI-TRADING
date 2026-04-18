# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/feeds/macro — Macro data feed adapters.

Public API
----------
    MacroStoreBridge    Keeps ml/macro_store.py populated from FRED.
                        Fetches all series on startup, refreshes daily at
                        18:00 UTC, and exposes get_ml_features() for
                        real-time macro feature injection.

Individual adapters (internal — use MacroStoreBridge, not these directly)
-------------------------------------------------------------------------
    FREDFeed            FRED economic data (DXY, yields, CPI, etc.)
    WGCFeed             World Gold Council gold demand/supply data
    CFTCCOTFeed         CFTC Commitment of Traders positioning data
    IMFGoldFeed         IMF official gold reserve statistics
    YahooMacroFeed      Yahoo Finance macro proxy series
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.feeds.macro.store_bridge import MacroStoreBridge
except Exception as _exc:
    logger.debug("data_layer.feeds.macro: MacroStoreBridge unavailable: %s", _exc)
    MacroStoreBridge = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.macro.fred import FREDFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.macro: FREDFeed unavailable: %s", _exc)
    FREDFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.macro.wgc import WGCFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.macro: WGCFeed unavailable: %s", _exc)
    WGCFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.macro.cftc_cot import CFTCCOTFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.macro: CFTCCOTFeed unavailable: %s", _exc)
    CFTCCOTFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.macro.imf_gold import IMFGoldFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.macro: IMFGoldFeed unavailable: %s", _exc)
    IMFGoldFeed = None  # type: ignore[assignment,misc]

try:
    from data_layer.feeds.macro.yahoo_macro import YahooMacroFeed
except Exception as _exc:
    logger.debug("data_layer.feeds.macro: YahooMacroFeed unavailable: %s", _exc)
    YahooMacroFeed = None  # type: ignore[assignment,misc]

__all__ = [
    "CFTCCOTFeed",
    "FREDFeed",
    "IMFGoldFeed",
    "MacroStoreBridge",
    "WGCFeed",
    "YahooMacroFeed",
]
