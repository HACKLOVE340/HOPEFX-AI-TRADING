# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer — Elite institutional-grade market data infrastructure.

Single import surface:
    from data_layer import orchestrator
    tick = await orchestrator.get_latest_tick("XAU_USD")
"""
from data_layer.orchestrator import MarketDataOrchestrator, orchestrator

__all__ = ["MarketDataOrchestrator", "orchestrator"]
