# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
strategy/ — Live ML signal engine (NOT backtestable strategy classes)
=====================================================================
This package contains ONE module: engine.py (StrategyEngine).

StrategyEngine is the real-time signal producer wired into the async
event loop (core/main_loop.py). It:
  - Subscribes to hopefx:tick on the Redis event bus
  - Aggregates ticks into OHLCV bars
  - Runs AdvancedModelPredictor (advanced_oos.pkl, 176 features)
  - Publishes signals to hopefx:signal for the Gatekeeper to consume

DO NOT add backtestable strategy classes here.
Backtestable strategies live in strategies/ (plural).

Package map
-----------
  strategy/engine.py   — StrategyEngine (live signal producer)
  strategies/          — BaseStrategy subclasses (backtesting / paper)
  backtesting/         — canonical backtest engine
"""

from .engine import StrategyEngine

__all__ = ["StrategyEngine"]
