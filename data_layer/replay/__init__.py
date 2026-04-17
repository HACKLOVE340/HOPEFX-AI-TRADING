# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
data_layer/replay — Deterministic historical market replay engine.

Public API
----------
    MarketReplayEngine   Fetches Dukascopy bi5 tick data and replays it
                         through the full pipeline (DQE → Microstructure →
                         Normalization). Enforces strict causal ordering.
                         Exposes build_ohlcv_dataframe() for backtesting.

    DukascopyFetcher     Low-level Dukascopy bi5 binary format fetcher.

Usage
-----
    from data_layer.replay import MarketReplayEngine
    engine = MarketReplayEngine()
    df = await engine.build_ohlcv_dataframe(start, end, symbol="XAU_USD")
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from data_layer.replay.engine import MarketReplayEngine  # noqa: F401
except Exception as _exc:
    logger.debug("data_layer.replay: MarketReplayEngine unavailable: %s", _exc)
    MarketReplayEngine = None  # type: ignore[assignment,misc]

try:
    from data_layer.replay.dukascopy import DukascopyFetcher  # noqa: F401
except Exception as _exc:
    logger.debug("data_layer.replay: DukascopyFetcher unavailable: %s", _exc)
    DukascopyFetcher = None  # type: ignore[assignment,misc]

__all__ = ["DukascopyFetcher", "MarketReplayEngine"]
