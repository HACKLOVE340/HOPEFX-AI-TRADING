# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/arbitrage — Cross-exchange arbitrage detection and execution.

Public API
----------
    CrossExchangeEngine   Main engine: add_exchange(), run(), get_stats()
    ArbitrageOpportunity  Dataclass describing a detected opportunity
    ExchangeConnector     Abstract base class for exchange adapters
    ArbitrageDetector     Price-scan and opportunity detection
    ArbitrageExecutor     Dual-leg order execution with emergency hedge
"""

from core.arbitrage.cross_exchange import (
    ArbitrageDetector,
    ArbitrageExecutor,
    ArbitrageOpportunity,
    CrossExchangeEngine,
    ExchangeConnector,
)

__all__ = [
    "ArbitrageDetector",
    "ArbitrageExecutor",
    "ArbitrageOpportunity",
    "CrossExchangeEngine",
    "ExchangeConnector",
]
