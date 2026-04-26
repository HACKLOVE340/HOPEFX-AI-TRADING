# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed — real-time price ingestion layer.

Architecture
------------
Market data and order execution are strictly separated:

  NuclearStreamer       — WebSocket streaming layer (Finnhub / Twelve Data /
                          Polygon).  This is the ONLY source of live price
                          ticks for the entire system.  No broker connector
                          is ever used for streaming.

  ProductionDataEngine  — REST polling engine (GoldAPI / MetalPriceAPI / MT5
                          demo) used as a fallback when WebSocket sources are
                          unavailable or during backtesting warm-up.

  MT5Backup             — Last-resort MT5 demo price source used exclusively
                          by ProductionDataEngine.

Broker connectors (brokers/) handle ORDER EXECUTION ONLY and must never be
used to obtain price data.

Public API
----------
NuclearStreamer       : primary WebSocket streaming engine
ProductionDataEngine  : REST polling fallback engine
MT5Backup             : MT5 price source (ProductionDataEngine internal use)
"""

from .engine import ProductionDataEngine
from .mt5_backup import MT5Backup
from .multi_source_feed import MultiSourceTickFeed, get_multi_source_feed
from .nuclear_streamer import NuclearStreamer

__all__ = [
    "NuclearStreamer",
    "MT5Backup",
    "ProductionDataEngine",
    "MultiSourceTickFeed",
    "get_multi_source_feed",
]
