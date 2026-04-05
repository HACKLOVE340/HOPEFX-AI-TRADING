# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
nuclear/ — HOPEFX Nuclear Strategy Agent

All data sourced exclusively from internal Redis pub/sub streams
(NuclearStreamer → Redis). No broker APIs, no OANDA data feeds.
Brokers are used only for order execution after signal approval.

Modules
-------
itos_cone_engine    Ito's Lemma drift/diffusion probabilistic price cones
redis_stream_reader Real-time Redis pub/sub consumer for all OHLCV channels
feature_builder     Multi-timeframe ATR/BB/RSI/EMA + macro feature extraction
regime_classifier   Market regime detection (high-vol/low-vol/crisis/range/trend)
strategy_engine     ICT/SMC + breakout + mean-reversion, ITOS-cone-aware
shadow_backtest     30-tick + 5-bar shadow simulation with real P&L metrics
signal_composer     Entry/exit rules, risk params, confidence scoring
nuclear_agent       Top-level NuclearStrategyAgent orchestrator
"""

__all__: list[str] = []

# Full exports available after all modules are built:
#   from nuclear.nuclear_agent import NuclearStrategyAgent, get_nuclear_agent
