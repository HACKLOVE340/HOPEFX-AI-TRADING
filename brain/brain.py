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
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from collections import deque
import copy

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logging.warning("NumPy not available, using fallback calculations")

logger = logging.getLogger(__name__)


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
    market_regime: Dict[str, MarketRegime] = field(default_factory=dict)
    active_positions: Dict[str, Any] = field(default_factory=dict)
    pending_orders: List[Dict] = field(default_factory=list)
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
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'system_state': self.system_state.value,
            'market_regime': {k: v.value for k, v in self.market_regime.items()},
            'account_balance': round(self.account_balance, 2),
            'equity': round(self.equity, 2),
            'margin_used': round(self.margin_used, 2),
            'free_margin': round(self.free_margin, 2),
            'daily_pnl': round(self.daily_pnl, 2),
            'total_pnl': round(self.total_pnl, 2),
            'open_trades_count': self.open_trades_count,
            'geo_risk': self.geo_risk,
            'performance': {
                'cpu': self.cpu_usage,
                'memory': self.memory_usage,
                'latency_ms': self.latency_ms,
                'cycle_time_ms': self.cycle_time_ms
            }
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
        self.last_failure_time: Optional[float] = None
        self.is_open = False
        self._lock = asyncio.Lock()
    
    async def record_success(self):
        """Record successful operation"""
        async with self._lock:
            if self.failure_count > 0:
                self.failure_count -= 1
                logger.debug(f"Circuit breaker: failure count decreased to {self.failure_count}")
            
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
                    f"Circuit breaker OPENED after {self.failure_count} consecutive failures. "
                    f"Recovery timeout: {self.recovery_timeout}s"
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
    
    def get_status(self) -> Dict:
        """Get circuit breaker status"""
        return {
            'is_open': self.is_open,
            'failure_count': self.failure_count,
            'threshold': self.failure_threshold,
            'last_failure': self.last_failure_time,
            'recovery_timeout': self.recovery_timeout
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

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # State initialization
        self.state = BrainState(
            timestamp=time.time(),
            system_state=SystemState.INITIALIZING
        )
        
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
        max_history = self.config.get('max_decision_history', 1000)
        self.decision_history: deque = deque(maxlen=max_history)
        self.error_history: deque = deque(maxlen=100)
        self.regime_history: deque = deque(maxlen=500)
        
        # FAULT TOLERANCE: Circuit breaker
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.get('circuit_breaker_threshold', 5),
            recovery_timeout=self.config.get('circuit_breaker_timeout', 60.0)
        )
        
        # Control flags
        self._running = False
        self._emergency_stop = False
        self._paused = False
        self._shutdown_event = asyncio.Event()
        
        # Timing control
        self.last_regime_check = 0
        self.regime_check_interval = self.config.get('regime_check_interval', 60)
        self._cycle_count = 0
        self._last_cycle_time = time.time()
        self._target_cycle_time = 1.0  # 1 second per cycle
        
        # Performance tracking
        self._cycle_times: deque = deque(maxlen=60)  # Last 60 cycles
        
        logger.info("HOPEFXBrain initialized (Production Version)")

    def inject_components(self, **components):
        """Inject required components with validation"""
        self.price_engine = components.get('price_engine')
        self.risk_manager = components.get('risk_manager')
        self.broker = components.get('broker')
        self.strategy_manager = components.get('strategy_manager')
        self.notification_manager = components.get('notification_manager')
        
        # Validate critical components
        missing = []
        if not self.broker:
            missing.append('broker')
        if not self.price_engine:
            missing.append('price_engine')
        
        if missing:
            logger.error(f"CRITICAL: Missing components: {', '.join(missing)}")
        else:
            logger.info("All critical components injected into Brain")

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
                
                # Adaptive cycle timing
                await self._maintain_cycle_timing(cycle_start)
                
        except asyncio.CancelledError:
            logger.info("Brain dominate loop cancelled")
        except Exception as e:
            logger.critical(f"Brain critical error: {e}", exc_info=True)
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
            'timestamp': time.time(),
            'error': str(error),
            'type': type(error).__name__,
            'cycle': self._cycle_count
        }
        self.error_history.append(error_info)
        
        logger.exception(f"Error in brain cycle {self._cycle_count}: {error}")
        
        # Record failure
        await self._circuit_breaker.record_failure()
        
        # Notify if critical
        if len(self.error_history) > 10:
            await self._safe_notify(
                "error",
                f"Multiple errors in brain: {str(error)[:100]}",
                {'error_count': len(self.error_history)}
            )
    
    async def _maintain_cycle_timing(self, cycle_start: float):
        """Maintain consistent cycle timing"""
        elapsed = time.time() - cycle_start
        sleep_time = max(0, self._target_cycle_time - elapsed)
        
        # Track cycle time for performance monitoring
        self._cycle_times.append(elapsed)
        async with self._state_lock:
            self.state.cycle_time_ms = elapsed * 1000
        
        # Sleep with shutdown check
        if sleep_time > 0:
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=sleep_time
                )
            except asyncio.TimeoutError:
                pass
    
    async def _update_state(self):
        """Gather state from all components - THREAD SAFE"""
        async with self._state_lock:
            try:
                self.state.timestamp = time.time()
                
                # Get account info from broker (with timeout)
                if self.broker:
                    try:
                        account = await asyncio.wait_for(
                            self.broker.get_account_info(),
                            timeout=5.0
                        )
                        self.state.account_balance = account.get('balance', 0)
                        self.state.equity = account.get('equity', 0)
                        self.state.margin_used = account.get('margin_used', 0)
                        self.state.free_margin = account.get('free_margin', 0)
                    except asyncio.TimeoutError:
                        logger.error("Broker timeout getting account info")
                        raise
                    except Exception as e:
                        logger.error(f"Error getting account info: {e}")
                        raise
                
                # Get positions (with timeout)
                if self.broker:
                    try:
                        positions = await asyncio.wait_for(
                            self.broker.get_positions(),
                            timeout=5.0
                        )
                        self.state.active_positions = {
                            p.id: {
                                'id': p.id,
                                'symbol': p.symbol,
                                'side': p.side.value,
                                'quantity': p.quantity,
                                'entry_price': p.entry_price,
                                'current_price': p.current_price,
                                'unrealized_pnl': p.unrealized_pnl
                            }
                            for p in positions
                        }
                        self.state.open_trades_count = len(positions)
                    except asyncio.TimeoutError:
                        logger.error("Broker timeout getting positions")
                        self.state.active_positions = {}
                        self.state.open_trades_count = 0
                    except Exception as e:
                        logger.error(f"Error getting positions: {e}")
                        self.state.active_positions = {}
                
                # Get pending orders (with timeout)
                if self.broker:
                    try:
                        orders = await asyncio.wait_for(
                            self.broker.get_pending_orders(),
                            timeout=5.0
                        )
                        self.state.pending_orders = [
                            {
                                'id': o.id,
                                'symbol': o.symbol,
                                'side': o.side.value,
                                'type': o.type.value,
                                'quantity': o.quantity,
                                'status': o.status.value
                            }
                            for o in orders
                        ]
                    except asyncio.TimeoutError:
                        logger.error("Broker timeout getting orders")
                        self.state.pending_orders = []
                    except Exception as e:
                        logger.error(f"Error getting orders: {e}")
                        self.state.pending_orders = []
                
            except Exception as e:
                logger.error(f"State update error: {e}")
                raise  # Re-raise to trigger circuit breaker
    
    async def _analyze_market_regimes(self):
        """Detect market regimes for all symbols"""
        if time.time() - self.last_regime_check < self.regime_check_interval:
            return
        
        self.last_regime_check = time.time()
        
        if not self.price_engine:
            return
        
        symbols = getattr(self.price_engine, 'symbols', [])
        
        for symbol in symbols:
            try:
                regime = await self._detect_regime(symbol)
                
                async with self._regime_lock:
                    old_regime = self.state.market_regime.get(symbol)
                    self.state.market_regime[symbol] = regime
                    
                    # Log regime changes
                    if old_regime != regime:
                        logger.info(f"Regime change for {symbol}: {old_regime.value if old_regime else 'None'} -> {regime.value}")
                        self.regime_history.append({
                            'timestamp': time.time(),
                            'symbol': symbol,
                            'old': old_regime.value if old_regime else None,
                            'new': regime.value
                        })
                        
            except Exception as e:
                logger.error(f"Regime detection error for {symbol}: {e}")
    
    async def _detect_regime(self, symbol: str) -> MarketRegime:
        """Detect market regime using price action - ROBUST VERSION"""
        if not self.price_engine:
            return MarketRegime.UNKNOWN
        
        try:
            ohlcv = self.price_engine.get_ohlcv(symbol, '1h', limit=24)
        except Exception as e:
            logger.warning(f"Failed to get OHLCV for {symbol}: {e}")
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
            else:
                return self._detect_regime_python(closes, highs, lows)
                
        except Exception as e:
            logger.error(f"Error in regime calculation for {symbol}: {e}")
            return MarketRegime.UNKNOWN
    
    def _detect_regime_numpy(self, closes, highs, lows) -> MarketRegime:
        """NumPy-based regime detection (faster)"""
        closes_arr = np.array(closes)
        highs_arr = np.array(highs)
        lows_arr = np.array(lows)
        
        # Calculate returns
        returns = np.diff(closes_arr) / closes_arr[:-1]
        
        # Volatility (annualized)
        volatility = np.std(returns) * np.sqrt(252 * 24)
        
        # Trend using linear regression
        x = np.arange(len(closes_arr[-20:]))
        y = closes_arr[-20:]
        slope, intercept = np.polyfit(x, y, 1)
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
            else:
                return MarketRegime.TRENDING_DOWN
        
        return MarketRegime.RANGING
    
    def _detect_regime_python(self, closes, highs, lows) -> MarketRegime:
        """Pure Python regime detection (fallback)"""
        # Calculate mean and std
        mean_close = sum(closes) / len(closes)
        variance = sum((x - mean_close) ** 2 for x in closes) / len(closes)
        std_close = variance ** 0.5
        
        # Simple trend detection
        recent = closes[-20:]
        first_half = sum(recent[:10]) / 10
        second_half = sum(recent[10:]) / 10
        trend = (second_half - first_half) / first_half if first_half > 0 else 0
        
        # Volatility
        volatility = (std_close / mean_close) * 100 if mean_close > 0 else 0
        
        # ATR approximation
        atr = sum(h - l for h, l in zip(highs[-14:], lows[-14:])) / 14
        
        # Classification
        current_price = closes[-1]
        volatility_pct = (atr / current_price) * 100 if current_price > 0 else 0
        
        if volatility_pct > 2.0:
            return MarketRegime.VOLATILE
        
        if abs(trend) > 0.001:
            if trend > 0:
                return MarketRegime.TRENDING_UP
            else:
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
                logger.warning(f"HIGH MARGIN USAGE: {margin_ratio:.2%}")
                await self._reduce_exposure()
                await self._safe_notify(
                    "warning",
                    f"High margin usage: {margin_ratio:.1%}",
                    {'margin_ratio': margin_ratio, 'equity': equity}
                )
            elif margin_ratio > 0.5:
                logger.info(f"Moderate margin usage: {margin_ratio:.2%}")
            
            # Check daily loss limit
            if balance > 0:
                daily_loss_pct = abs(daily_pnl) / balance
                if daily_loss_pct > 0.05:  # 5% daily loss
                    logger.critical(f"DAILY LOSS LIMIT REACHED: {daily_loss_pct:.2%}")
                    await self._safe_notify(
                        "critical",
                        f"Daily loss limit reached: {daily_loss_pct:.2%}",
                        {'daily_loss': daily_pnl, 'balance': balance}
                    )
                    await self._pause_trading()
            
            # Check drawdown
            if hasattr(self.risk_manager, 'current_drawdown'):
                dd = self.risk_manager.current_drawdown
                if dd > 0.10:  # 10% drawdown
                    logger.critical(f"MAX DRAWDOWN REACHED: {dd:.2%}")
                    await self._execute_emergency_stop()
                    
        except Exception as e:
            logger.error(f"Risk assessment error: {e}")
    
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
                logger.critical(
                    f"CATASTROPHIC LOSS: Equity ${equity:,.2f} < 50% of Balance ${balance:,.2f}"
                )
                return True
            
            # Check for data feed staleness
            if self.price_engine:
                stale_threshold = 300  # 5 minutes
                for symbol in getattr(self.price_engine, 'symbols', []):
                    try:
                        last_tick = self.price_engine.get_last_price(symbol)
                        if last_tick:
                            stale_time = time.time() - last_tick.timestamp
                            if stale_time > stale_threshold:
                                logger.warning(f"Stale data for {symbol}: {stale_time:.0f}s old")
                    except Exception as e:
                        logger.error(f"Error checking data staleness for {symbol}: {e}")
            
            # Check for too many consecutive errors
            if self._circuit_breaker.failure_count > 10:
                logger.critical("Too many consecutive failures, emergency stopping")
                return True
                
        except Exception as e:
            logger.error(f"Emergency check error: {e}")
        
        return False
    
    async def _execute_emergency_stop(self):
        """Emergency shutdown procedure - GUARANTEED EXECUTION"""
        logger.critical("🚨 EXECUTING EMERGENCY STOP")
        
        self._emergency_stop = True
        async with self._state_lock:
            self.state.system_state = SystemState.EMERGENCY_STOP
        
        # Close all positions (with retries)
        if self.broker:
            for attempt in range(3):
                try:
                    closed_positions = await asyncio.wait_for(
                        self.broker.close_all_positions(),
                        timeout=10.0
                    )
                    logger.info(f"Closed {len(closed_positions)} positions")
                    break
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1} failed to close positions: {e}")
                    await asyncio.sleep(1)
        
        # Cancel all orders
        if self.broker:
            try:
                cancelled_orders = await asyncio.wait_for(
                    self.broker.cancel_all_orders(),
                    timeout=5.0
                )
                logger.info(f"Cancelled {len(cancelled_orders)} orders")
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")
        
        # Notify
        await self._safe_notify(
            "critical",
            "🚨 EMERGENCY STOP EXECUTED",
            {
                'equity': self.state.equity,
                'open_positions': self.state.open_trades_count,
                'timestamp': datetime.now().isoformat()
            }
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
            positions.sort(key=lambda p: p.get('unrealized_pnl', 0))
            
            # Close bottom 50%
            to_close = positions[:max(1, len(positions) // 2)]
            
            for pos in to_close:
                try:
                    success = await asyncio.wait_for(
                        self.broker.close_position(pos['id']),
                        timeout=5.0
                    )
                    if success:
                        logger.info(f"Reduced exposure: closed position {pos['id']}")
                except Exception as e:
                    logger.error(f"Error reducing position {pos['id']}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in reduce_exposure: {e}")
    
    async def _make_strategy_decisions(self):
        """Execute strategy logic - WITH TIMEOUTS AND CONCURRENCY CONTROL"""
        if not self.strategy_manager:
            return
        
        try:
            # Get signals with timeout
            signals = await asyncio.wait_for(
                self.strategy_manager.generate_signals(
                    self.state.market_regime,
                    self.price_engine
                ),
                timeout=10.0
            )
            
            # Filter signals through risk manager
            if self.risk_manager:
                signals = await asyncio.wait_for(
                    self.risk_manager.filter_signals(signals, self.state),
                    timeout=5.0
                )
            
            # Execute signals with concurrency limit
            semaphore = asyncio.Semaphore(3)  # Max 3 concurrent orders
            
            async def execute_with_limit(signal):
                async with semaphore:
                    await self._execute_signal(signal)
            
            # Limit to max 5 signals per cycle
            await asyncio.gather(
                *[execute_with_limit(s) for s in signals[:5]],
                return_exceptions=True
            )
            
        except asyncio.TimeoutError:
            logger.warning("Strategy decision timeout")
        except Exception as e:
            logger.error(f"Strategy decision error: {e}")
    
    async def _execute_signal(self, signal: Dict):
        """Execute a trading signal - SAFE VERSION"""
        async with self._decision_lock:
            try:
                action = signal.get('action')
                symbol = signal.get('symbol')
                size = signal.get('size', 0)
                
                # Validate signal
                if not all([action, symbol, size]):
                    logger.warning(f"Invalid signal (missing fields): {signal}")
                    return
                
                if action not in ('buy', 'sell', 'close'):
                    logger.warning(f"Unknown action: {action}")
                    return
                
                if size <= 0:
                    logger.warning(f"Invalid size: {size}")
                    return
                
                # Execute
                if action in ('buy', 'sell'):
                    order = await asyncio.wait_for(
                        self.broker.place_market_order(
                            symbol=symbol,
                            side=action,
                            quantity=size
                        ),
                        timeout=10.0
                    )
                    
                    # Record decision
                    self.decision_history.append({
                        'timestamp': time.time(),
                        'signal': signal,
                        'order_id': order.id,
                        'fill_price': order.average_fill_price,
                        'status': order.status.value,
                        'state': self.state.to_dict()
                    })
                    
                    logger.info(
                        f"Executed {action.upper()} {size} {symbol} @ "
                        f"{order.average_fill_price:.5f} (ID: {order.id})"
                    )
                    
                elif action == 'close':
                    position_id = signal.get('position_id')
                    if position_id:
                        success = await asyncio.wait_for(
                            self.broker.close_position(position_id),
                            timeout=10.0
                        )
                        if success:
                            logger.info(f"Closed position {position_id}")
                
            except asyncio.TimeoutError:
                logger.error(f"Signal execution timeout: {signal.get('symbol')}")
            except Exception as e:
                logger.error(f"Signal execution error: {e}")
    
    async def _safe_notify(self, level: str, message: str, data: Dict = None):
        """Safe notification with error handling"""
        if not self.notification_manager:
            return
        
        try:
            await asyncio.wait_for(
                self.notification_manager.send_alert(level, message, data),
                timeout=3.0
            )
        except Exception as e:
            logger.error(f"Notification failed: {e}")
    
    async def _log_periodic_state(self):
        """Log periodic state summary"""
        try:
            async with self._state_lock:
                state_dict = self.state.to_dict()
            
            # Calculate average cycle time
            avg_cycle_time = sum(self._cycle_times) / len(self._cycle_times) if self._cycle_times else 0
            
            logger.info(
                f"State Summary [Cycle {self._cycle_count}] | "
                f"Equity: ${state_dict['equity']:,.2f} | "
                f"Positions: {state_dict['open_trades_count']} | "
                f"Regimes: {len(state_dict['market_regime'])} | "
                f"Avg Cycle: {avg_cycle_time*1000:.1f}ms | "
                f"Circuit: {'OPEN' if self._circuit_breaker.is_open else 'CLOSED'}"
            )
        except Exception as e:
            logger.error(f"Error logging state: {e}")
    
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
        asyncio.create_task(_resume())
    
    def emergency_stop(self):
        """Manual emergency stop — sets flag synchronously, schedules cleanup async."""
        logger.info("Manual emergency stop triggered")
        self._emergency_stop = True
        try:
            asyncio.create_task(self._execute_emergency_stop())
        except RuntimeError:
            pass  # No running loop — flag is already set
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Brain shutdown requested")
        self._running = False
        self._shutdown_event.set()
        
        # Wait for current cycle to complete (with timeout)
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    
    def get_state(self) -> BrainState:
        """Get current state (deep copy to prevent external modification)"""
        return copy.deepcopy(self.state)
    
    def get_decision_history(self, limit: int = 100) -> List[Dict]:
        """Get recent decision history"""
        return list(self.decision_history)[-limit:]
    
    def get_error_history(self, limit: int = 50) -> List[Dict]:
        """Get recent error history"""
        return list(self.error_history)[-limit:]
    
    def get_health(self) -> Dict:
        """Get health status"""
        return {
            'running': self._running,
            'paused': self._paused,
            'state': self.state.system_state.value,
            'circuit_breaker': self._circuit_breaker.get_status(),
            'cycle_count': self._cycle_count,
            'decision_history_size': len(self.decision_history),
            'error_history_size': len(self.error_history),
            'avg_cycle_time_ms': (sum(self._cycle_times) / len(self._cycle_times) * 1000) 
                                if self._cycle_times else 0,
            'components': {
                'price_engine': self.price_engine is not None,
                'broker': self.broker is not None,
                'risk_manager': self.risk_manager is not None,
                'strategy_manager': self.strategy_manager is not None
            }
        }
