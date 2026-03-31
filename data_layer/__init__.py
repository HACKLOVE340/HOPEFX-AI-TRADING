# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer
==========
Production market data layer for HOPEFX AI Trading.

Public API — the ONLY interface the rest of the codebase uses:

    from data_layer import orchestrator

    # Lifecycle
    await orchestrator.start()
    await orchestrator.stop()

    # Data access
    tick     = orchestrator.get_latest_tick()          # Optional[GoldTick]
    price    = orchestrator.get_current_gold_price()   # Optional[float]
    features = orchestrator.get_ml_features(as_of)     # Dict[str, float]
    impact   = orchestrator.get_macro_impact_score()   # float [0,1]
    safe     = orchestrator.is_safe_to_trade()         # bool
    blackout = orchestrator.is_blackout_window()       # bool
    report   = orchestrator.get_quality_report()       # Optional[QualityReport]
    health   = orchestrator.health()                   # Dict[str, Any]

Architecture invariant
----------------------
No module outside data_layer/ may import directly from individual feed
adapters, quality engines, or sentiment feeds. All data flows through
the MarketDataOrchestrator singleton.

    OK:  from data_layer import orchestrator
    OK:  from data_layer.orchestrator import orchestrator
    OK:  from data_layer.types import GoldTick, OHLCVBar, ...
    BAD: from data_layer.feeds.gold.goldapi import GoldAPIFeed
    BAD: from data_layer.quality.engine import dqe
"""

from __future__ import annotations

from data_layer.orchestrator import MarketDataOrchestrator, orchestrator  # noqa: F401
from data_layer.types import (  # noqa: F401
    Direction,
    FeedHealth,
    FeedSource,
    GoldTick,
    MacroEvent,
    MacroImpact,
    MicrostructureSnapshot,
    NewsArticle,
    NewsSource,
    OHLCVBar,
    QualityReport,
    TickQuality,
)

__all__ = [
    "MarketDataOrchestrator",
    "orchestrator",
    "Direction",
    "FeedHealth",
    "FeedSource",
    "GoldTick",
    "MacroEvent",
    "MacroImpact",
    "MicrostructureSnapshot",
    "NewsArticle",
    "NewsSource",
    "OHLCVBar",
    "QualityReport",
    "TickQuality",
]
