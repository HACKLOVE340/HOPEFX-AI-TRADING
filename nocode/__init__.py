# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nocode — No-Code Strategy Builder

Provides a visual, drag-and-drop interface for building trading strategies
without writing code. Supports plain-English parsing, built-in templates,
and Python code export.

Submodules:
    models  — Data classes and enums (Indicator, Condition, StrategyRule, …)
    builder — NoCodeStrategyBuilder: create, parse, validate, export strategies
    router  — FastAPI router exposing the builder via REST API
"""

from nocode.builder import NoCodeStrategyBuilder
from nocode.models import (
    ActionType,
    Condition,
    ConditionGroup,
    ConditionOperator,
    Indicator,
    IndicatorType,
    LogicOperator,
    NoCodeStrategy,
    StrategyRule,
    TradingAction,
)
from nocode.router import create_nocode_router

__all__ = [
    "ActionType",
    "Condition",
    "ConditionGroup",
    "ConditionOperator",
    "Indicator",
    "IndicatorType",
    "LogicOperator",
    "NoCodeStrategy",
    "NoCodeStrategyBuilder",
    "StrategyRule",
    "TradingAction",
    "create_nocode_router",
]
