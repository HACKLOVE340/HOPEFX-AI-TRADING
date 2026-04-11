# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""execution package

Exports all execution-layer classes from a single surface.
Legacy paper-trading classes are re-exported for backward compatibility.
"""

import logging as _logging

_log = _logging.getLogger(__name__)

# ── Legacy compatibility ───────────────────────────────────────────────────────
from execution.legacy import (  # noqa: F401
    ExecutionResult,
    Order,
    OrderStatus,
    PaperExecutor,
    SmartOrderRouter,
)

# ── Core execution engine ──────────────────────────────────────────────────────
try:
    from execution.engine import ExecutionEngine  # noqa: F401
except Exception as _e:
    _log.debug("ExecutionEngine unavailable: %s", _e)

# ── Order management ──────────────────────────────────────────────────────────
try:
    from execution.oms import (  # noqa: F401
        ComplexOrderManager,
        OrderLifecycleManager,
    )
except Exception as _e:
    _log.debug("OMS unavailable: %s", _e)

# ── Trade executor ────────────────────────────────────────────────────────────
try:
    from execution.trade_executor import TradeExecutor  # noqa: F401
except Exception as _e:
    _log.debug("TradeExecutor unavailable: %s", _e)

# ── Smart router ──────────────────────────────────────────────────────────────
try:
    from execution.smart_router import SmartRouter  # noqa: F401
except Exception as _e:
    _log.debug("SmartRouter unavailable: %s", _e)

# ── Position management ───────────────────────────────────────────────────────
try:
    from execution.position_manager import PositionManager  # noqa: F401
except Exception as _e:
    _log.debug("PositionManager unavailable: %s", _e)

try:
    from execution.position_tracker import PositionTracker  # noqa: F401
except Exception as _e:
    _log.debug("PositionTracker unavailable: %s", _e)

# ── Order gateway ─────────────────────────────────────────────────────────────
try:
    from execution.order_gateway import OrderGateway  # noqa: F401
except Exception as _e:
    _log.debug("OrderGateway unavailable: %s", _e)

# ── TCA ───────────────────────────────────────────────────────────────────────
try:
    from execution.tca import TCAEngine  # noqa: F401
except Exception as _e:
    _log.debug("TCAEngine unavailable: %s", _e)

try:
    from execution.tca_recorder import TCARecorder  # noqa: F401
except Exception as _e:
    _log.debug("TCARecorder unavailable: %s", _e)

# ── Async engine ──────────────────────────────────────────────────────────────
try:
    from execution.async_engine import AsyncExecutionEngine  # noqa: F401
except Exception as _e:
    _log.debug("AsyncExecutionEngine unavailable: %s", _e)

# ── Circuit breaker ───────────────────────────────────────────────────────────
try:
    from execution.broker_circuit_breaker import BrokerCircuitBreaker  # noqa: F401
except Exception as _e:
    _log.debug("BrokerCircuitBreaker unavailable: %s", _e)

# ── Market impact ─────────────────────────────────────────────────────────────
try:
    from execution.market_impact import AlmgrenChrissModel, FillSimulator  # noqa: F401
except Exception as _e:
    _log.debug("MarketImpact unavailable: %s", _e)

# ── SL/TP monitor ─────────────────────────────────────────────────────────────
try:
    from execution.sl_tp_monitor import SLTPMonitor  # noqa: F401
except Exception as _e:
    _log.debug("SLTPMonitor unavailable: %s", _e)

# ── Throttler ─────────────────────────────────────────────────────────────────
try:
    from execution.throttler import MessageThrottler  # noqa: F401
except Exception as _e:
    _log.debug("MessageThrottler unavailable: %s", _e)

# ── FIX router ────────────────────────────────────────────────────────────────
try:
    from execution.fix_router import FIXRouter  # noqa: F401
except Exception as _e:
    _log.debug("FIXRouter unavailable: %s", _e)

# ── Algo orders ───────────────────────────────────────────────────────────────
try:
    from execution.algo_orders import AlgoOrderManager  # noqa: F401
except Exception as _e:
    _log.debug("AlgoOrderManager unavailable: %s", _e)

try:
    from execution.order_algorithms import (  # noqa: F401
        TWAPExecutor,
        TWAPOrder,
        VWAPExecutor,
        VWAPOrder,
    )
except Exception as _e:
    _log.debug("OrderAlgorithms unavailable: %s", _e)

# ── Spread monitor ────────────────────────────────────────────────────────────
try:
    from execution.spread_monitor import SpreadMonitor  # noqa: F401
except Exception as _e:
    _log.debug("SpreadMonitor unavailable: %s", _e)

# ── Redis state ───────────────────────────────────────────────────────────────
try:
    from execution.redis_state import AsyncRedisStateStore, RedisStateStore  # noqa: F401
except Exception as _e:
    _log.debug("RedisState unavailable: %s", _e)

# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from execution._prom_metrics import get_metrics  # noqa: F401
except Exception as _e:
    _log.debug("PromMetrics unavailable: %s", _e)

__version__ = "1.0.0"
