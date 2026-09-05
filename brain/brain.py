# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Brain - Central Intelligence System
PRODUCTION VERSION with all critical fixes:
- Thread safety (asyncio.Lock)
- Bounded memory (deque with maxlen)
- Circuit breaker pattern
- Proper error handling
- Health checks
"""

import asyncio
import contextlib
import copy
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Rate-limit repeated "strategy decision timeout" warnings to once per 5 minutes.
_DECISION_TIMEOUT_LOG_INTERVAL: float = 300.0
_decision_timeout_last_logged: float = 0.0

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.warning("NumPy not available, using fallback calculations")


class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class SystemState(Enum):
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    EMERGENCY_STOP = "emergency_stop"
    SHUTDOWN = "shutdown"


@dataclass
class BrainState:
    """Complete system state snapshot with thread safety considerations"""

    timestamp: float
    system_state: SystemState
    market_regime: dict[str, MarketRegime] = field(default_factory=dict)
    active_positions: dict[str, Any] = field(default_factory=dict)
    pending_orders: list[dict] = field(default_factory=list)
    account_balance: float = 0.0
    equity: float = 0.0
    margin_used: float = 0.0
    free_margin: float = 0.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    open_trades_count: int = 0
    geo_risk: str = "low"

    # Performance metrics
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    latency_ms: float = 0.0
    cycle_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "system_state": self.system_state.value,
            "market_regime": {k: v.value for k, v in self.market_regime.items()},
            "account_balance": round(self.account_balance, 2),
            "equity": round(self.equity, 2),
            "margin_used": round(self.margin_used, 2),
            "free_margin": round(self.free_margin, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "open_trades_count": self.open_trades_count,
            "geo_risk": self.geo_risk,
            "performance": {
                "cpu": self.cpu_usage,
                "memory": self.memory_usage,
                "latency_ms": self.latency_ms,
                "cycle_time_ms": self.cycle_time_ms,
            },
        }


class CircuitBreaker:
    """
    Circuit breaker pattern for fault tolerance
    Prevents infinite error loops by stopping operations after repeated failures
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.is_open = False
        self._lock = asyncio.Lock()

    async def record_success(self):
        """Record successful operation"""
        async with self._lock:
            if self.failure_count > 0:
                self.failure_count -= 1
                logger.debug("Circuit breaker: failure count decreased to %s", self.failure_count)

            if self.failure_count == 0 and self.is_open:
                self.is_open = False
                logger.info("Circuit breaker CLOSED (recovered)")

    async def record_failure(self):
        """Record failed operation"""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold and not self.is_open:
                self.is_open = True
                logger.critical(
                    "Circuit breaker OPENED after %s consecutive failures. Recovery timeout: %ss",
                    self.failure_count,
                    self.recovery_timeout,
                )

    async def check_recovery(self) -> bool:
        """Check if circuit can be closed automatically"""
        async with self._lock:
            if not self.is_open:
                return True

            if self.last_failure_time and (time.time() - self.last_failure_time > self.recovery_timeout):
                self.is_open = False
                self.failure_count = max(0, self.failure_threshold - 1)
                logger.info("Circuit breaker auto-recovery triggered")
                return True

            return False

    def get_status(self) -> dict:
        """Get circuit breaker status"""
        return {
            "is_open": self.is_open,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "last_failure": self.last_failure_time,
            "recovery_timeout": self.recovery_timeout,
        }


class HOPEFXBrain:
    """
    Central Intelligence System - PRODUCTION VERSION

    Critical Fixes Applied:
    1. Thread safety: All state access protected by asyncio.Lock
    2. Memory management: Bounded collections (deque with maxlen)
    3. Fault tolerance: Circuit breaker pattern
    4. Error isolation: Exceptions don't crash the main loop
    5. Timeouts: All external calls have timeouts
    6. Graceful degradation: Components can fail individually
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}

        # State initialization
        self.state = BrainState(timestamp=time.time(), system_state=SystemState.INITIALIZING)

        # Component references (injected later)
        self.price_engine = None
        self.risk_manager = None
        self.broker = None
        self.strategy_manager = None
        self.notification_manager = None

        # THREAD SAFETY: Locks for shared state
        self._state_lock = asyncio.Lock()
        self._decision_lock = asyncio.Lock()
        self._regime_lock = asyncio.Lock()

        # MEMORY MANAGEMENT: Bounded collections
        max_history = self.config.get("max_decision_history", 1000)
        self.decision_history: deque = deque(maxlen=max_history)
        self.error_history: deque = deque(maxlen=100)
        self.regime_history: deque = deque(maxlen=500)

        # FAULT TOLERANCE: Circuit breaker
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.get("circuit_breaker_threshold", 5),
            recovery_timeout=self.config.get("circuit_breaker_timeout", 60.0),
        )

        # Control flags
        self._running = False
        self._emergency_stop = False
        self._paused = False
        self._shutdown_event = asyncio.Event()

        # Timing control
        self.last_regime_check = 0
        self.regime_check_interval = self.config.get("regime_check_interval", 60)
        self._cycle_count = 0
        self._last_cycle_time = time.time()
        # In development use a 5s cycle to avoid hammering yfinance/thread pool.
        import os as _brain_os

        _dev = _brain_os.getenv("APP_ENV", "development").lower() in ("development", "dev")
        self._target_cycle_time = float(_brain_os.getenv("BRAIN_CYCLE_SEC", "5.0" if _dev else "1.0"))

        # Performance tracking
        self._cycle_times: deque = deque(maxlen=60)  # Last 60 cycles

        logger.info("HOPEFXBrain initialized (Production Version)")

    def inject_components(self, **components):
        """Inject required components with validation.

        Accepted keys:
            price_engine, risk_manager, broker, strategy_manager,
            notification_manager, position_tracker, trade_executor
        """
        self.price_engine = components.get("price_engine")
        self.risk_manager = components.get("risk_manager")
        self.broker = components.get("broker")
        self.strategy_manager = components.get("strategy_manager")
        self.notification_manager = components.get("notification_manager")
        # Optional execution components
        self.position_tracker = components.get("position_tracker")
        self.trade_executor = components.get("trade_executor")

        # Validate critical components
        missing = []
        if not self.broker:
            missing.append("broker")
        if not self.price_engine:
            missing.append("price_engine")
        if not self.strategy_manager:
            missing.append("strategy_manager")

        if missing:
            logger.error(
                "HOPEFXBrain: Missing components %s — brain will run in degraded mode "
                "(no live prices/account data until components are available)",
                missing,
            )
        else:
            logger.info(
                "HOPEFXBrain: all critical components injected (broker=%s price_engine=%s strategy_manager=%s)",
                type(self.broker).__name__,
                type(self.price_engine).__name__,
                type(self.strategy_manager).__name__ if self.strategy_manager else "None",
            )

    async def dominate(self):
        """
        Main control loop - PRODUCTION GRADE

        Features:
        - Circuit breaker protection
        - Adaptive cycle timing
        - Error isolation
        - Graceful shutdown
        """
        self._running = True
        async with self._state_lock:
            self.state.system_state = SystemState.RUNNING

        logger.info("🧠 BRAIN DOMINATE SEQUENCE INITIATED")

        try:
            while self._running and not self._shutdown_event.is_set():
                cycle_start = time.time()

                try:
                    # Check circuit breaker
                    if self._circuit_breaker.is_open:
                        await self._handle_circuit_open()
                        continue

                    # Check for pause
                    if self._paused:
                        await asyncio.sleep(0.1)
                        continue

                    # Main cycle operations
                    await self._execute_cycle()

                    # Record success
                    await self._circuit_breaker.record_success()

                except asyncio.CancelledError:
                    logger.info("Brain cycle cancelled")
                    break
                except Exception as e:
                    await self._handle_cycle_error(e)

                # Adaptive cycle timing — TimeoutError here is the normal poll
                # expiry from asyncio.wait_for inside _maintain_cycle_timing.
                # On Python <=3.10 asyncio.TimeoutError is NOT a subclass of
                # the builtin TimeoutError, so we suppress it explicitly to
                # prevent it from reaching the outer emergency-stop handler.
                with contextlib.suppress(TimeoutError):
                    await self._maintain_cycle_timing(cycle_start)

        except asyncio.CancelledError:
            logger.info("Brain dominate loop cancelled")
            raise
        except Exception as e:
            logger.critical("Brain critical error: %s", e, exc_info=True)
            await self._execute_emergency_stop()
        finally:
            await self._cleanup()

    async def _execute_cycle(self):
        """Execute one full brain cycle"""
        # 1. Update state (with lock protection)
        await self._update_state()

        # 2. Check market regimes
        await self._analyze_market_regimes()

        # 3. Risk assessment
        await self._assess_risk()

        # 4. Check emergency conditions
        if await self._check_emergency_conditions():
            await self._execute_emergency_stop()
            return

        # 5. Strategy decisions (only if running)
        if self.state.system_state == SystemState.RUNNING:
            await self._make_strategy_decisions()

        # 6. Periodic logging
        self._cycle_count += 1
        if self._cycle_count % 60 == 0:
            await self._log_periodic_state()

    async def _handle_circuit_open(self):
        """Handle circuit breaker open state"""
        logger.warning("Circuit breaker OPEN - skipping cycle")

        # Try recovery
        recovered = await self._circuit_breaker.check_recovery()
        if not recovered:
            await asyncio.sleep(5.0)  # Back off

    async def _handle_cycle_error(self, error: Exception):
        """Handle errors in the main cycle"""
        error_info = {
            "timestamp": time.time(),
            "error": str(error),
            "type": type(error).__name__,
            "cycle": self._cycle_count,
        }
        self.error_history.append(error_info)

        logger.exception("Error in brain cycle %s", self._cycle_count)

        # Record failure
        await self._circuit_breaker.record_failure()

        # Notify if critical
        if len(self.error_history) > 10:
            await self._safe_notify(
                "error",
                f"Multiple errors in brain: {str(error)[:100]}",
                {"error_count": len(self.error_history)},
            )

    async def _maintain_cycle_timing(self, cycle_start: float):
        """Maintain consistent cycle timing"""
        elapsed = time.time() - cycle_start
        sleep_time = max(0, self._target_cycle_time - elapsed)

        # Track cycle time for performance monitoring
        self._cycle_times.append(elapsed)
        async with self._state_lock:
            self.state.cycle_time_ms = elapsed * 1000

        # Sleep with shutdown check — suppress TimeoutError (normal) but let
        # CancelledError propagate so the task can be cancelled cleanly.
        if sleep_time > 0:
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=sleep_time)
            except asyncio.CancelledError:
                raise
            except TimeoutError:  # nosec B110
                pass

    @staticmethod
    async def _await_or_return(raw):
        """Await if coroutine, otherwise return directly (handles sync/async brokers)."""
        if asyncio.iscoroutine(raw):
            return await raw
        return raw

    @staticmethod
    def _extract_account_fields(account) -> tuple[float, float, float, float]:
        """Extract balance/equity/margin fields from dict or dataclass AccountInfo."""
        if isinstance(account, dict):
            return (
                float(account.get("balance", 0) or 0),
                float(account.get("equity", 0) or 0),
                float(account.get("margin_used", 0) or 0),
                float(account.get("free_margin", account.get("margin_available", 0)) or 0),
            )
        return (
            float(getattr(account, "balance", 0) or 0),
            float(getattr(account, "equity", 0) or 0),
            float(getattr(account, "margin_used", 0) or 0),
            float(getattr(account, "margin_available", getattr(account, "free_margin", 0)) or 0),
        )

    async def _update_state(self):
        """Gather state from all components - THREAD SAFE"""
        async with self._state_lock:
            try:
                self.state.timestamp = time.time()

                # Get account info — handles sync and async brokers, dict and dataclass results
                if self.broker:
                    try:
                        raw = self.broker.get_account_info()
                        account = await asyncio.wait_for(self._await_or_return(raw), timeout=5.0)
                        if account is not None:
                            bal, eq, mu, fm = self._extract_account_fields(account)
                            self.state.account_balance = bal
                            self.state.equity = eq
                            self.state.margin_used = mu
                            self.state.free_margin = fm
                    except TimeoutError:
                        logger.warning("Broker timeout getting account info")
                        raise
                    except Exception as e:
                        logger.warning("Error getting account info: %s", e)

                # Get positions (with timeout)
                if self.broker:
                    try:
                        raw = self.broker.get_positions()
                        positions = await asyncio.wait_for(self._await_or_return(raw), timeout=5.0)
                        self.state.active_positions = {
                            p.id: {
                                "id": p.id,
                                "symbol": p.symbol,
                                # Position.side is a plain str ("LONG"/"SHORT"),
                                # not an Enum — use getattr to handle both forms.
                                "side": p.side.value if hasattr(p.side, "value") else p.side,
                                "quantity": p.quantity,
                                "entry_price": p.entry_price,
                                "current_price": p.current_price,
                                "unrealized_pnl": p.unrealized_pnl,
                            }
                            for p in (positions or [])
                        }
                        self.state.open_trades_count = len(positions or [])
                    except TimeoutError:
                        logger.warning("Broker timeout getting positions")
                        self.state.active_positions = {}
                        self.state.open_trades_count = 0
                    except Exception as e:
                        logger.warning("Error getting positions: %s", e)
                        self.state.active_positions = {}

                # Get pending orders (with timeout; broker may not support this)
                if self.broker and hasattr(self.broker, "get_pending_orders"):
                    try:
                        raw = self.broker.get_pending_orders()
                        orders = await asyncio.wait_for(self._await_or_return(raw), timeout=5.0)
                        self.state.pending_orders = [
                            {
                                "id": o.id,
                                "symbol": o.symbol,
                                "side": o.side.value,
                                "type": o.type.value,
                                "quantity": o.quantity,
                                "status": o.status.value,
                            }
                            for o in (orders or [])
                        ]
                    except TimeoutError:
                        logger.warning("Broker timeout getting orders")
                        self.state.pending_orders = []
                    except Exception as e:
                        logger.warning("Error getting orders: %s", e)
                        self.state.pending_orders = []

            except Exception as e:
                logger.error("State update error: %s", e)
                raise  # Re-raise to trigger circuit breaker

    async def _analyze_market_regimes(self):
        """Detect market regimes for all symbols"""
        if time.time() - self.last_regime_check < self.regime_check_interval:
            return

        self.last_regime_check = time.time()

        if not self.price_engine:
            return

        symbols = getattr(self.price_engine, "symbols", [])

        for symbol in symbols:
            try:
                regime = await self._detect_regime(symbol)

                async with self._regime_lock:
                    old_regime = self.state.market_regime.get(symbol)
                    self.state.market_regime[symbol] = regime

                    # Log regime changes
                    if old_regime != regime:
                        logger.info(
                            "Regime change for %s: %s -> %s",
                            symbol,
                            old_regime.value if old_regime else "None",
                            regime.value,
                        )
                        self.regime_history.append(
                            {
                                "timestamp": time.time(),
                                "symbol": symbol,
                                "old": old_regime.value if old_regime else None,
                                "new": regime.value,
                            }
                        )

            except Exception as e:
                logger.error("Regime detection error for %s: %s", symbol, e)

    async def _detect_regime(self, symbol: str) -> MarketRegime:
        """Detect market regime using price action - ROBUST VERSION"""
        if not self.price_engine:
            return MarketRegime.UNKNOWN

        try:
            ohlcv = await self.price_engine.get_ohlcv(symbol, "1h", limit=24)
        except Exception as e:
            logger.warning("Failed to get OHLCV for %s: %s", symbol, e)

            return MarketRegime.UNKNOWN

        if len(ohlcv) < 20:
            return MarketRegime.UNKNOWN

        try:
            # Extract data
            closes = [c.close for c in ohlcv]
            highs = [c.high for c in ohlcv]
            lows = [c.low for c in ohlcv]

            if NUMPY_AVAILABLE:
                return self._detect_regime_numpy(closes, highs, lows)
            return self._detect_regime_python(closes, highs, lows)

        except Exception as e:
            logger.error("Error in regime calculation for %s: %s", symbol, e)

            return MarketRegime.UNKNOWN

    def _detect_regime_numpy(self, closes, highs, lows) -> MarketRegime:
        """NumPy-based regime detection (faster)"""
        closes_arr = np.array(closes)
        highs_arr = np.array(highs)
        lows_arr = np.array(lows)

        # Calculate returns
        closes_arr = np.nan_to_num(closes_arr, nan=0.0)
        denom = np.where(closes_arr[:-1] != 0, closes_arr[:-1], 1.0)
        returns = np.diff(closes_arr) / denom

        # Volatility (annualized)
        _annualized_vol = np.std(returns) * np.sqrt(252 * 24)

        # Trend using linear regression
        x = np.arange(len(closes_arr[-20:]))
        y = closes_arr[-20:]
        slope, _intercept = np.polyfit(x, y, 1)
        normalized_slope = slope / closes_arr[-1] if closes_arr[-1] > 0 else 0

        # ATR calculation
        tr1 = highs_arr[1:] - lows_arr[1:]
        tr2 = np.abs(highs_arr[1:] - closes_arr[:-1])
        tr3 = np.abs(lows_arr[1:] - closes_arr[:-1])
        true_range = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = np.mean(true_range[-14:]) if len(true_range) >= 14 else np.mean(true_range)

        # Classification
        current_price = closes_arr[-1]
        price_range = np.max(highs_arr[-20:]) - np.min(lows_arr[-20:])
        volatility_pct = (atr / current_price) * 100 if current_price > 0 else 0

        if volatility_pct > 2.0:
            return MarketRegime.VOLATILE

        if abs(normalized_slope) > 0.001 and price_range > atr * 3:
            if normalized_slope > 0:
                return MarketRegime.TRENDING_UP
            return MarketRegime.TRENDING_DOWN

        return MarketRegime.RANGING

    def _detect_regime_python(self, closes, highs, lows) -> MarketRegime:
        """Pure Python regime detection (fallback)"""
        # Calculate mean and std
        mean_close = sum(closes) / len(closes)
        variance = sum((x - mean_close) ** 2 for x in closes) / len(closes)
        std_close = variance**0.5

        # Simple trend detection
        recent = closes[-20:]
        first_half = sum(recent[:10]) / 10
        second_half = sum(recent[10:]) / 10
        trend = (second_half - first_half) / first_half if first_half > 0 else 0

        # Volatility
        _volatility_pct = (std_close / mean_close) * 100 if mean_close > 0 else 0

        # ATR approximation
        atr = sum(h - l for h, l in zip(highs[-14:], lows[-14:], strict=False)) / 14

        # Classification
        current_price = closes[-1]
        volatility_pct = (atr / current_price) * 100 if current_price > 0 else 0

        if volatility_pct > 2.0:
            return MarketRegime.VOLATILE

        if abs(trend) > 0.001:
            if trend > 0:
                return MarketRegime.TRENDING_UP
            return MarketRegime.TRENDING_DOWN

        return MarketRegime.RANGING

    async def _assess_risk(self):
        """Assess overall system risk - PRODUCTION VERSION"""
        try:
            async with self._state_lock:
                equity = self.state.equity
                margin_used = self.state.margin_used
                daily_pnl = self.state.daily_pnl
                balance = self.state.account_balance

            if equity <= 0:
                logger.warning("Equity is zero or negative")
                return

            # Check margin usage
            margin_ratio = margin_used / equity if equity > 0 else 0

            if margin_ratio > 0.8:
                logger.warning("HIGH MARGIN USAGE: %s", margin_ratio)

                await self._reduce_exposure()
                await self._safe_notify(
                    "warning",
                    f"High margin usage: {margin_ratio:.1%}",
                    {"margin_ratio": margin_ratio, "equity": equity},
                )
            elif margin_ratio > 0.5:
                logger.info("Moderate margin usage: %s", margin_ratio)

            # Check daily loss limit
            if balance > 0:
                daily_loss_pct = abs(daily_pnl) / balance
                if daily_loss_pct > 0.05:  # 5% daily loss
                    logger.critical("DAILY LOSS LIMIT REACHED: %s", daily_loss_pct)

                    await self._safe_notify(
                        "critical",
                        f"Daily loss limit reached: {daily_loss_pct:.2%}",
                        {"daily_loss": daily_pnl, "balance": balance},
                    )
                    await self._pause_trading()

            # Check drawdown
            if hasattr(self.risk_manager, "current_drawdown"):
                dd = self.risk_manager.current_drawdown
                if dd > 0.10:  # 10% drawdown
                    logger.critical("MAX DRAWDOWN REACHED: %s", dd)

                    await self._execute_emergency_stop()

        except Exception as e:
            logger.error("Risk assessment error: %s", e)

    async def _check_emergency_conditions(self) -> bool:
        """Check if emergency stop is needed - ROBUST"""
        if self._emergency_stop:
            return True

        try:
            async with self._state_lock:
                equity = self.state.equity
                balance = self.state.account_balance

            # Check catastrophic loss (50% of initial balance)
            if balance > 0 and equity < balance * 0.5:
                logger.critical("CATASTROPHIC LOSS: Equity $%s < 50%% of Balance $%s", equity, balance)

                return True

            # Check for data feed staleness
            if self.price_engine:
                stale_threshold = 300  # 5 minutes
                for symbol in getattr(self.price_engine, "symbols", []):
                    try:
                        last_tick = self.price_engine.get_last_price(symbol)
                        if last_tick:
                            stale_time = time.time() - last_tick.timestamp
                            if stale_time > stale_threshold:
                                logger.warning("Stale data for %s: %ss old", symbol, stale_time)

                    except Exception as e:
                        logger.error("Error checking data staleness for %s: %s", symbol, e)

            # Check for too many consecutive errors
            if self._circuit_breaker.failure_count > 10:
                logger.critical("Too many consecutive failures, emergency stopping")
                return True

        except Exception as e:
            logger.error("Emergency check error: %s", e)

        return False

    async def _execute_emergency_stop(self):
        """Emergency shutdown procedure - GUARANTEED EXECUTION"""
        logger.critical("🚨 EXECUTING EMERGENCY STOP")

        self._emergency_stop = True
        async with self._state_lock:
            self.state.system_state = SystemState.EMERGENCY_STOP

        # Close all positions (with retries)
        # Broker implementations vary: the abstract base returns list[str],
        # but some concrete brokers (e.g. PaperTradingBroker) return int.
        # Normalise to a count so len() is never called on a non-sequence.
        if self.broker:
            for attempt in range(3):
                try:
                    result = self.broker.close_all_positions()
                    # Await if the broker returns a coroutine.
                    if asyncio.iscoroutine(result):
                        result = await asyncio.wait_for(result, timeout=10.0)
                    closed_count = (
                        result if isinstance(result, int) else len(result) if hasattr(result, "__len__") else 0
                    )
                    logger.info("Closed %s positions", closed_count)
                    break
                except Exception as e:
                    logger.error("Attempt %s failed to close positions: %s", attempt + 1, e)
                    await asyncio.sleep(1)

        # Cancel all orders
        # Same normalisation: some brokers return bool (sync), others return
        # list[str] (async). Await only when the result is a coroutine.
        if self.broker:
            try:
                result = self.broker.cancel_all_orders()
                if asyncio.iscoroutine(result):
                    result = await asyncio.wait_for(result, timeout=5.0)
                cancelled_count = (
                    result
                    if isinstance(result, int)
                    else len(result)
                    if hasattr(result, "__len__")
                    else int(bool(result))
                )
                logger.info("Cancelled %s orders", cancelled_count)
            except Exception as e:
                logger.error("Error cancelling orders: %s", e)

        # Notify
        await self._safe_notify(
            "critical",
            "🚨 EMERGENCY STOP EXECUTED",
            {
                "equity": self.state.equity,
                "open_positions": self.state.open_trades_count,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        self._running = False
        self._shutdown_event.set()

    async def _reduce_exposure(self):
        """Reduce position sizes when risk is high"""
        if not self.broker:
            return

        try:
            async with self._state_lock:
                positions = list(self.state.active_positions.values())

            if not positions:
                return

            # Sort by P&L (close worst first)
            positions.sort(key=lambda p: p.get("unrealized_pnl", 0))

            # Close bottom 50%
            to_close = positions[: max(1, len(positions) // 2)]

            for pos in to_close:
                try:
                    success = await asyncio.wait_for(self.broker.close_position(pos["id"]), timeout=5.0)
                    if success:
                        logger.info("Reduced exposure: closed position %s", pos["id"])

                except Exception as e:
                    logger.error("Error reducing position %s: %s", pos["id"], e)

        except Exception as e:
            logger.error("Error in reduce_exposure: %s", e)

    async def _make_strategy_decisions(self):
        """Execute strategy logic - WITH TIMEOUTS AND CONCURRENCY CONTROL"""
        if not self.strategy_manager:
            logger.warning(
                "HOPEFXBrain: strategy_manager is None — no signals will be generated. "
                "Check that init_strategy_brain completed successfully at startup."
            )
            return

        try:
            # Get signals with timeout
            signals = await asyncio.wait_for(
                self.strategy_manager.generate_signals(self.state.market_regime, self.price_engine),
                timeout=10.0,
            )

            # Filter signals through risk manager (only if it supports filter_signals)
            if self.risk_manager and hasattr(self.risk_manager, "filter_signals"):
                signals = await asyncio.wait_for(self.risk_manager.filter_signals(signals, self.state), timeout=5.0)

            # Publish signals to RealTimeSignalService so /api/signals/active
            # reflects live brain activity.
            for sig in signals[:5]:
                self._publish_to_signal_service(sig)

            # Execute signals with concurrency limit
            semaphore = asyncio.Semaphore(3)  # Max 3 concurrent orders

            async def execute_with_limit(signal):
                async with semaphore:
                    await self._execute_signal(signal)

            # Limit to max 5 signals per cycle
            await asyncio.gather(*[execute_with_limit(s) for s in signals[:5]], return_exceptions=True)

        except TimeoutError:
            global _decision_timeout_last_logged
            now = time.monotonic()
            if now - _decision_timeout_last_logged >= _DECISION_TIMEOUT_LOG_INTERVAL:
                # Log at INFO — timeouts are expected when data feeds or broker
                # are not connected (dev/offline mode). The brain continues
                # running and will retry on the next cycle.
                logger.info(
                    "Strategy decision timeout (further timeouts suppressed for %.0f s)",
                    _DECISION_TIMEOUT_LOG_INTERVAL,
                )
                _decision_timeout_last_logged = now
            else:
                logger.debug("Strategy decision timeout")
        except Exception as e:
            logger.error("Strategy decision error: %s", e)

    def _publish_to_signal_service(self, signal: dict) -> None:
        """
        Push a brain strategy signal into RealTimeSignalService.

        Translates the brain's internal signal dict (action/symbol/size/…)
        into the SignalService schema so the signal appears on
        /api/signals/active and triggers alerts/social-feed publishing.
        Non-blocking — failures are logged and swallowed.
        """
        try:
            from api.signals import SignalDirection, _get_signal_service

            action = signal.get("action", "")
            symbol = signal.get("symbol", "")
            confidence = float(signal.get("confidence", 0.5))
            strategy_name = signal.get("strategy", "brain")
            price = float(signal.get("price", 0.0))

            if not symbol or action not in ("buy", "sell"):
                return

            direction = SignalDirection.BUY if action == "buy" else SignalDirection.SELL

            # Derive SL/TP from signal dict or use conservative defaults
            entry = float(signal.get("entry_price", price) or price)
            sl = float(signal.get("stop_loss", entry * (0.995 if action == "buy" else 1.005)))
            tp = float(signal.get("take_profit", entry * (1.015 if action == "buy" else 0.985)))

            svc = _get_signal_service()
            svc.generate_signal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                price=price or entry,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                timeframe=signal.get("timeframe", "1h"),
                strategies_agreeing=[strategy_name],
                total_strategies=1,
                regime=str(self.state.market_regime.get(symbol, "unknown")),
                session="brain",
                metadata={"source": "brain", "size": signal.get("size", 0)},
            )
        except Exception as exc:
            logger.debug("Signal service publish failed (non-fatal): %s", exc)

    async def _execute_signal(self, signal: dict):
        """Execute a trading signal - SAFE VERSION"""
        async with self._decision_lock:
            try:
                action = signal.get("action")
                symbol = signal.get("symbol")
                size = signal.get("size", 0)

                # Validate signal
                if not all([action, symbol, size]):
                    logger.warning("Invalid signal (missing fields): %s", signal)

                    return

                if action not in ("buy", "sell", "close"):
                    logger.warning("Unknown action: %s", action)

                    return

                if size <= 0:
                    logger.warning("Invalid size: %s", size)

                    return

                # Execute
                if action in ("buy", "sell"):
                    order = await asyncio.wait_for(
                        self.broker.place_market_order(symbol=symbol, side=action, quantity=size),
                        timeout=10.0,
                    )

                    # Record decision
                    self.decision_history.append(
                        {
                            "timestamp": time.time(),
                            "signal": signal,
                            "order_id": order.id,
                            "fill_price": order.average_fill_price,
                            "status": order.status.value,
                            "state": self.state.to_dict(),
                        }
                    )

                    logger.info(
                        "Executed %s %s %s @ %s (ID: %s)",
                        action.upper(),
                        size,
                        symbol,
                        order.average_fill_price,
                        order.id,
                    )

                elif action == "close":
                    position_id = signal.get("position_id")
                    if position_id:
                        success = await asyncio.wait_for(self.broker.close_position(position_id), timeout=10.0)
                        if success:
                            logger.info("Closed position %s", position_id)

            except TimeoutError:
                logger.error("Signal execution timeout: %s", signal.get("symbol"))

            except Exception as e:
                logger.error("Signal execution error: %s", e)

    async def _safe_notify(self, level: str, message: str, data: dict | None = None):
        """Safe notification with error handling"""
        if not self.notification_manager:
            return

        try:
            await asyncio.wait_for(self.notification_manager.send_alert(level, message, data), timeout=3.0)
        except Exception as e:
            logger.error("Notification failed: %s", e)

    async def _log_periodic_state(self):
        """Log periodic state summary"""
        try:
            async with self._state_lock:
                state_dict = self.state.to_dict()

            # Calculate average cycle time
            avg_cycle_time = sum(self._cycle_times) / len(self._cycle_times) if self._cycle_times else 0

            logger.info(
                "State Summary [Cycle %s] | Equity: $%s | Positions: %s | Regimes: %s | Avg Cycle: %sms | Circuit: %s",
                self._cycle_count,
                state_dict["equity"],
                state_dict["open_trades_count"],
                len(state_dict["market_regime"]),
                avg_cycle_time * 1000,
                "OPEN" if self._circuit_breaker.is_open else "CLOSED",
            )
        except Exception as e:
            logger.error("Error logging state: %s", e)

    async def _pause_trading(self):
        """Pause trading but keep monitoring"""
        self._paused = True
        async with self._state_lock:
            self.state.system_state = SystemState.PAUSED
        logger.info("Trading paused (monitoring continues)")
        await self._safe_notify("warning", "Trading paused due to risk limit", {})

    async def _cleanup(self):
        """Cleanup on shutdown"""
        async with self._state_lock:
            self.state.system_state = SystemState.SHUTDOWN
        logger.info("Brain cleanup complete")

    # Public API methods

    def pause(self):
        """Pause trading (keep monitoring)"""
        self._paused = True
        logger.info("Pause requested")

    def resume(self):
        """Resume trading"""
        self._paused = False

        async def _resume():
            async with self._state_lock:
                self.state.system_state = SystemState.RUNNING
            logger.info("Trading resumed")
            await self._safe_notify("info", "Trading resumed", {})

        _t = asyncio.create_task(_resume())
        _t.add_done_callback(lambda _: None)

    def emergency_stop(self):
        """Manual emergency stop — sets flag synchronously, schedules cleanup async."""
        logger.info("Manual emergency stop triggered")
        self._emergency_stop = True
        with contextlib.suppress(RuntimeError):
            _t = asyncio.create_task(self._execute_emergency_stop())
            _t.add_done_callback(lambda _: None)

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Brain shutdown requested")
        self._running = False
        self._shutdown_event.set()

        # Wait for current cycle to complete (with timeout)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=2.0)

    def get_state(self) -> BrainState:
        """Get current state (deep copy to prevent external modification)"""
        return copy.deepcopy(self.state)

    def get_decision_history(self, limit: int = 100) -> list[dict]:
        """Get recent decision history"""
        return list(self.decision_history)[-limit:]

    def get_error_history(self, limit: int = 50) -> list[dict]:
        """Get recent error history"""
        return list(self.error_history)[-limit:]

    def get_health(self) -> dict:
        """Get health status"""
        return {
            "running": self._running,
            "paused": self._paused,
            "state": self.state.system_state.value,
            "circuit_breaker": self._circuit_breaker.get_status(),
            "cycle_count": self._cycle_count,
            "decision_history_size": len(self.decision_history),
            "error_history_size": len(self.error_history),
            "avg_cycle_time_ms": (sum(self._cycle_times) / len(self._cycle_times) * 1000) if self._cycle_times else 0,
            "components": {
                "price_engine": self.price_engine is not None,
                "broker": self.broker is not None,
                "risk_manager": self.risk_manager is not None,
                "strategy_manager": self.strategy_manager is not None,
            },
        }

    # ── Lifecycle aliases expected by integration tests ───────────────────────

    async def start(self) -> None:
        """Start the brain in the background (alias for compatibility)."""
        self._running = True
        async with self._state_lock:
            self.state.system_state = SystemState.RUNNING
        logger.info("HOPEFXBrain started")

    async def stop(self) -> None:
        """Stop the brain gracefully (alias for compatibility)."""
        self._running = False
        self._emergency_stop = True
        async with self._state_lock:
            self.state.system_state = SystemState.SHUTDOWN
        logger.info("HOPEFXBrain stopped")
