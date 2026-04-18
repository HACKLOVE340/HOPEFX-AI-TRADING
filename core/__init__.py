# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core — HOPEFX trading engine core package.

Sub-packages
------------
    core.acceleration   GPU inference engine (QuantizedTransformer, GPUInferenceEngine)
    core.analytics      Real-time heatmap and correlation analytics
    core.arbitrage      Cross-exchange arbitrage detection and execution
    core.decision       Central five-phase tick-to-order decision engine
    core.mcc            Master Control Core — strategy lifecycle orchestration
    core.risk           Monte Carlo / GARCH / CVaR risk engine

Key singletons (import directly from their modules)
---------------------------------------------------
    from core.app_state import app_state
    from core.event_bus import bus
    from core.config_store import config_store
    from core.secrets_manager import secrets, get_secret
    from core.live_trading_gate import get_gate
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Re-export the most commonly used singletons so callers can do:
#   from core import app_state, bus
try:
    from core.app_state import app_state
except Exception as _exc:
    logger.debug("core: app_state unavailable: %s", _exc)

try:
    from core.event_bus import bus
except Exception as _exc:
    logger.debug("core: event_bus unavailable: %s", _exc)

try:
    from core.exceptions import (
        AuthenticationError,
        CircuitBreakerError,
        DataValidationError,
        EventBusError,
        ExecutionError,
        HopeFXError,
        ModelError,
        RiskLimitError,
        VaultError,
    )
except Exception as _exc:
    logger.debug("core: exceptions unavailable: %s", _exc)

__all__ = [
    "app_state",
    "bus",
    # exceptions
    "HopeFXError",
    "VaultError",
    "AuthenticationError",
    "EventBusError",
    "DataValidationError",
    "CircuitBreakerError",
    "RiskLimitError",
    "ExecutionError",
    "ModelError",
]
