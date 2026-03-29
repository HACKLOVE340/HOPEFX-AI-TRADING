# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
strategy/ — Live ML signal engine (NOT backtestable strategy classes)
=====================================================================

This package contains ONE module: engine.py (StrategyEngine).

Purpose
-------
StrategyEngine is the real-time signal producer wired into the async
event loop (core/main_loop.py). It is NOT a backtestable strategy.

Data flow
---------
  Redis hopefx:tick
      │
      ▼
  TickAggregator          aggregates N ticks → synthetic OHLCV bar
      │                   (STRATEGY_TICKS_PER_BAR, default 10)
      ▼
  AdvancedModelPredictor  ml/live_inference.py
      │                   XGBoost pipeline, 122 features, ~68% OOS accuracy
      │                   abstains when confidence < ML_MIN_TRADE_PROB (0.58)
      │                   falls back to EMA-crossover when model unavailable
      ▼
  Redis hopefx:signal     consumed by risk/gatekeeper.py → brokers/

Environment variables
---------------------
  ML_MIN_TRADE_PROB       minimum model confidence to emit a signal (default 0.58)
  STRATEGY_MIN_BARS       bars required before ML predictions start (default 100)
  STRATEGY_BUFFER_SIZE    rolling OHLCV buffer length (default 500)
  STRATEGY_TICKS_PER_BAR  ticks aggregated per synthetic bar (default 10)
  STRATEGY_EMA_FAST       EMA fast period for fallback rule (default 9)
  STRATEGY_EMA_SLOW       EMA slow period for fallback rule (default 21)

Package map
-----------
  strategy/engine.py      StrategyEngine — live signal producer (this package)
  strategies/             BaseStrategy subclasses — backtestable rule-based strategies
  strategies/manager.py   StrategyManager — loads and runs backtestable strategies
  strategies/strategy_brain.py  StrategyBrain — multi-strategy signal aggregator
  backtesting/            canonical backtest engine (engine_config.py, walk_forward.py, …)
  ml/live_inference.py    AdvancedModelPredictor — XGBoost inference
  core/event_bus.py       Redis pub/sub channels (CH_TICK, CH_SIGNAL)
  risk/gatekeeper.py      consumes hopefx:signal, applies risk rules before order

DO NOT add backtestable strategy classes here.
Backtestable strategies live in strategies/ (plural).
"""

from .engine import StrategyEngine

__all__ = ["StrategyEngine"]
