# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_feed/sources — individual REST tick-source adapters.

Each adapter implements the TickSourceAdapter protocol:
  - name: str
  - async fetch(symbol: str, cfg: dict) -> float | None
  - async close() -> None

Adapters are stateless with respect to symbol state; all circuit-breaker
and retry logic lives in MultiSourceTickFeed.
"""

from .alpha_vantage import AlphaVantageSource
from .twelve_data import TwelveDataSource
from .yfinance_source import YFinanceSource

__all__ = ["YFinanceSource", "AlphaVantageSource", "TwelveDataSource"]
