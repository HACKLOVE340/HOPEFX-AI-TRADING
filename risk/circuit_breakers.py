# risk/circuit_breaker.py
"""
Production-grade circuit breaker system with kill switches, 
drawdown monitoring, and automated trading halts.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from collections import deque
import threading
import json
import redis

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Trading halted
    HALF_OPEN = "half_open"  # Testing if safe to resume

@dataclass
class RiskLimits:
    """Configurable risk limits with automatic enforcement"""
    # Drawdown limits
    max_daily_drawdown_pct: float = 0.03  # 3% daily max
    max_total_drawdown_pct: float = 0.10  # 10% total max
    max_session_drawdown_pct: float = 0.05  # 5% per session
    
    # Position limits
    max_position_size_pct: float = 0.02  # 2% per position
    max_correlated_positions: int = 3  # Max positions in correlated assets
    max_total_exposure_pct: float = 0.20  # 20% total exposure
    
    # Rate limits
    max_orders_per_minute: int = 10
    max_orders_per_hour: int = 100
    max_order_size: float = 100000.0  # Notional value
    
    # Loss limits
    max_consecutive_losses: int = 5
    max_loss_streak_pct: float = 0.05  # 5% loss over streak
    
    # Volatility limits
    max_volatility_threshold: float = 0.50  # VIX-like threshold
    halt_on_volatility_spike: bool = True
    
    # Cooldown periods
    circuit_breaker_cooldown_minutes: int = 15
    daily_loss_cooldown_hours: int = 2


class CircuitBreaker:
    """
    Multi-layer circuit breaker with automatic trading halts.
    
    Features:
    - Real-time P&L monitoring
    - Automatic position flattening on breach
    - Tiered cooldown periods
    - Manual override with audit trail
    - Redis-backed state persistence
    """
    
    def __init__(self, broker, redis_client: Optional[redis.Redis] = None):
        self.broker = broker
        self.redis = redis_client
        self.limits = RiskLimits()
        
        # State management
        self.state = CircuitState.CLOSED
        self.state_lock = threading.RLock()
        self._manual_override = False
        self._override_reason: Optional[str] = None
        
        # P&L tracking
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.peak_balance = 0.0
        self.current_drawdown = 0.0
        self.session_start_balance = 0.0
        
        # Order tracking
        self.orders_last_minute: deque = deque(maxlen=100)
        self.orders_last_hour: deque = deque(maxlen=1000)
        self.consecutive_losses = 0
        self.loss_streak_amount = 0.0
        
        # History
        self.breach_history: List[Dict] = []
        self.state_changes: List[Dict] = []
        
        # Callbacks
        self.on_breach: Optional[Callable] = None
        self.on_state_change: Optional[Callable] = None
        
        # Async task
        self._monitoring_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        # Initialize
        self._load_state()
        self._initialize_monitoring()
    
    def _initialize_monitoring(self):
        """Start background monitoring"""
        self.peak_balance = self.broker.get_balance()
        self.session_start_balance = self.peak_balance
        
        if asyncio.get_event_loop().is_running():
            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
    
    async def _monitoring_loop(self):
        """Continuous risk monitoring"""
        while not self._shutdown:
            try:
                await self._check_risk_limits()
                await asyncio.sleep(1)  # Check every second
            except Exception as e:
                logger.error(f"Risk monitoring error: {e}")
                await asyncio.sleep(5)
    
    async def _check_risk_limits(self):
        """Check all risk limits and trigger circuit breakers if breached"""
        current_balance = self.broker.get_balance()
        
        # Update P&L tracking
        self.total_pnl = current_balance - self.session_start_balance
        self.daily_pnl = self._calculate_daily_pnl()
        
        # Update drawdown
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
        self.current_drawdown = (self.peak_balance - current_balance) / self.peak_balance
        
        # Check drawdown limits
        if self.current_drawdown >= self.limits.max_daily_drawdown_pct:
            await self._trigger_circuit_breaker(
                "DAILY_DRAWDOWN",
                f"Daily drawdown limit breached: {self.current_drawdown:.2%}"
            )
            return
        
        if self.current_drawdown >= self.limits.max_total_drawdown_pct:
            await self._trigger_circuit_breaker(
                "TOTAL_DRAWDOWN",
                f"Total drawdown limit breached: {self.current_drawdown:.2%}",
                severity="CRITICAL"
            )
            return
        
        # Check order rate limits
        now = datetime.utcnow()
        cutoff_minute = now - timedelta(minutes=1)
        cutoff_hour = now - timedelta(hours=1)
        
        recent_minute = sum(1 for t in self.orders_last_minute if t > cutoff_minute)
        recent_hour = sum(1 for t in self.orders_last_hour if t > cutoff_hour)
        
        if recent_minute >= self.limits.max_orders_per_minute:
            await self._trigger_circuit_breaker(
                "ORDER_RATE",
                f"Order rate limit: {recent_minute} orders/minute"
            )
            return
        
        # Check consecutive losses
        if self.consecutive_losses >= self.limits.max_consecutive_losses:
            if self.loss_streak_amount >= self.limits.max_loss_streak_pct * self.session_start_balance:
                await self._trigger_circuit_breaker(
                    "LOSS_STREAK",
                    f"Loss streak: {self.consecutive_losses} trades, ${self.loss_streak_amount:.2f}"
                )
                return
    
    async def _trigger_circuit_breaker(self, reason: str, message: str, severity: str = "HIGH"):
        """Trigger circuit breaker and halt trading"""
        with self.state_lock:
            if self.state == CircuitState.OPEN:
                return  # Already open
            
            old_state = self.state
            self.state = CircuitState.OPEN
            
            # Record breach
            breach = {
                "timestamp": datetime.utcnow().isoformat(),
                "reason": reason,
                "message": message,
                "severity": severity,
                "balance": self.broker.get_balance(),
                "drawdown": self.current_drawdown,
                "daily_pnl": self.daily_pnl
            }
            self.breach_history.append(breach)
            self._persist_state()
            
            logger.critical(f"🚨 CIRCUIT BREAKER TRIGGERED: {reason} - {message}")
            
            # Execute kill switch
            await self._execute_kill_switch(reason)
            
            # Notify
            if self.on_breach:
                try:
                    self.on_breach(breach)
                except Exception as e:
                    logger.error(f"Breach callback error: {e}")
            
            # Schedule recovery attempt
            asyncio.create_task(self._schedule_recovery())
    
    async def _execute_kill_switch(self, reason: str):
        """
        Emergency position flattening with retry logic.
        This is the kill switch - closes all positions immediately.
        """
        logger.critical("🔴 EXECUTING KILL SWITCH - CLOSING ALL POSITIONS")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                positions = self.broker.get_positions()
                if not positions:
                    logger.info("No open positions to close")
                    break
                
                # Cancel all pending orders first
                self.broker.cancel_all_orders()
                await asyncio.sleep(0.5)  # Brief pause
                
                # Close all positions at market
                for position in positions:
                    try:
                        self.broker.close_position(position, order_type="MARKET")
                        logger.info(f"Closed position: {position}")
                    except Exception as e:
                        logger.error(f"Failed to close position {position}: {e}")
                
                # Verify closure
                await asyncio.sleep(1)
                remaining = self.broker.get_positions()
                if not remaining:
                    logger.info("✅ All positions closed successfully")
                    break
                else:
                    logger.warning(f"⚠️ {len(remaining)} positions still open, retrying...")
                    
            except Exception as e:
                logger.error(f"Kill switch attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1)
        
        # Final verification
        final_positions = self.broker.get_positions()
        if final_positions:
            logger.critical(f"🚨 FAILED TO CLOSE {len(final_positions)} POSITIONS - MANUAL INTERVENTION REQUIRED")
            # Send emergency notification
            self._send_emergency_alert(f"Kill switch partial failure: {len(final_positions)} positions remain")
    
    async def _schedule_recovery(self):
        """Schedule automatic recovery attempt after cooldown"""
        cooldown = self.limits.circuit_breaker_cooldown_minutes * 60
        
        logger.info(f"⏱️ Circuit breaker active. Recovery attempt in {self.limits.circuit_breaker_cooldown_minutes} minutes")
        
        await asyncio.sleep(cooldown)
        
        with self.state_lock:
            if self._manual_override:
                logger.info("Manual override active, skipping auto-recovery")
                return
            
            self.state = CircuitState.HALF_OPEN
            logger.info("🟡 Circuit breaker entering HALF_OPEN state - testing with reduced size")
            
            # Reduce position sizes for testing
            self.limits.max_position_size_pct *= 0.5
            
            # Schedule full recovery check
            asyncio.create_task(self._check_recovery())
    
    async def _check_recovery(self):
        """Check if conditions allow full recovery"""
        await asyncio.sleep(300)  # 5 minutes in half-open state
        
        with self.state_lock:
            if self.state != CircuitState.HALF_OPEN:
                return
            
            # Check if drawdown has recovered
            if self.current_drawdown < self.limits.max_daily_drawdown_pct * 0.5:
                self.state = CircuitState.CLOSED
                self.limits.max_position_size_pct /= 0.5  # Restore limits
                logger.info("🟢 Circuit breaker CLOSED - normal trading resumed")
                self._persist_state()
            else:
                # Re-open circuit
                self.state = CircuitState.OPEN
                logger.warning("🔴 Recovery failed - circuit breaker re-opened")
                asyncio.create_task(self._schedule_recovery())
    
    def pre_trade_check(self, order: Dict) -> tuple[bool, Optional[str]]:
        """
        Pre-trade risk check. Call this before every order.
        Returns: (allowed: bool, reason: Optional[str])
        """
        with self.state_lock:
            if self.state == CircuitState.OPEN:
                return False, f"Circuit breaker OPEN: {self._get_last_breach_reason()}"
            
            # Check order size
            notional = order.get('size', 0) * order.get('price', 0)
            if notional > self.limits.max_order_size:
                return False, f"Order size ${notional:,.2f} exceeds limit ${self.limits.max_order_size:,.2f}"
            
            # Check exposure
            current_exposure = self._calculate_total_exposure()
            new_exposure = current_exposure + notional
            max_exposure = self.broker.get_balance() * self.limits.max_total_exposure_pct
            
            if new_exposure > max_exposure:
                return False, f"Exposure limit would be breached: {new_exposure/max_exposure:.1%}"
            
            # Check correlation
            symbol = order.get('symbol')
            if self._would_breach_correlation_limit(symbol):
                return False, f"Correlation limit would be breached for {symbol}"
            
            # Record order for rate limiting
            now = datetime.utcnow()
            self.orders_last_minute.append(now)
            self.orders_last_hour.append(now)
            
            # In half-open state, reduce size
            if self.state == CircuitState.HALF_OPEN:
                order['size'] = order.get('size', 0) * 0.5
                logger.info(f"Half-open state: reduced order size by 50%")
            
            return True, None
    
    def update_trade_result(self, pnl: float):
        """Update risk state after trade completion"""
        if pnl < 0:
            self.consecutive_losses += 1
            self.loss_streak_amount += abs(pnl)
        else:
            self.consecutive_losses = 0
            self.loss_streak_amount = 0.0
        
        self._persist_state()
    
    def manual_override(self, enable: bool, reason: str, authorized_by: str):
        """Manual override with full audit trail"""
        with self.state_lock:
            self._manual_override = enable
            self._override_reason = reason if enable else None
            
            action = "ENABLED" if enable else "DISABLED"
            logger.critical(f"🔧 MANUAL OVERRIDE {action} by {authorized_by}: {reason}")
            
            audit_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "action": f"MANUAL_OVERRIDE_{action}",
                "authorized_by": authorized_by,
                "reason": reason,
                "state_before": self.state.value,
                "balance": self.broker.get_balance()
            }
            self.state_changes.append(audit_record)
            self._persist_state()
            
            if not enable:
                # Re-evaluate state
                asyncio.create_task(self._check_risk_limits())
    
    def _persist_state(self):
        """Persist state to Redis for recovery"""
        if self.redis:
            state_data = {
                "state": self.state.value,
                "daily_pnl": self.daily_pnl,
                "peak_balance": self.peak_balance,
                "consecutive_losses": self.consecutive_losses,
                "breach_history": json.dumps(self.breach_history[-10:]),  # Last 10
                "timestamp": datetime.utcnow().isoformat()
            }
            try:
                self.redis.hset("circuit_breaker:state", mapping=state_data)
                self.redis.expire("circuit_breaker:state", 86400)  # 24h TTL
            except Exception as e:
                logger.error(f"Failed to persist state: {e}")
    
    def _load_state(self):
        """Load previous state from Redis"""
        if not self.redis:
            return
        
        try:
            data = self.redis.hgetall("circuit_breaker:state")
            if data:
                self.daily_pnl = float(data.get(b'daily_pnl', 0))
                self.peak_balance = float(data.get(b'peak_balance', 0))
                self.consecutive_losses = int(data.get(b'consecutive_losses', 0))
                logger.info("Loaded previous risk state from Redis")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
    
    def _calculate_daily_pnl(self) -> float:
        """Calculate today's P&L"""
        # Implementation depends on broker API
        return self.broker.get_daily_pnl() if hasattr(self.broker, 'get_daily_pnl') else 0.0
    
    def _calculate_total_exposure(self) -> float:
        """Calculate current total exposure"""
        positions = self.broker.get_positions()
        return sum(p.get('notional', 0) for p in positions)
    
    def _would_breach_correlation_limit(self, symbol: str) -> bool:
        """Check if adding this symbol would breach correlation limits"""
        # Simplified - implement actual correlation matrix check
        positions = self.broker.get_positions()
        correlated_count = sum(1 for p in positions if self._is_correlated(p['symbol'], symbol))
        return correlated_count >= self.limits.max_correlated_positions
    
    def _is_correlated(self, sym1: str, sym2: str) -> bool:
        """Check if two symbols are correlated"""
        # Implement actual correlation logic (e.g., EUR/USD and GBP/USD)
        correlated_groups = [
            {'EUR/USD', 'GBP/USD', 'AUD/USD', 'NZD/USD'},  # USD pairs
            {'XAU/USD', 'XAG/USD'},  # Metals
            {'US30', 'US500', 'USTEC'},  # Indices
        ]
        for group in correlated_groups:
            if sym1 in group and sym2 in group:
                return True
        return False
    
    def _get_last_breach_reason(self) -> str:
        """Get reason for last breach"""
        if self.breach_history:
            return self.breach_history[-1].get('reason', 'Unknown')
        return 'Unknown'
    
    def _send_emergency_alert(self, message: str):
        """Send emergency notification through all channels"""
        logger.critical(f"EMERGENCY ALERT: {message}")
        # Implement actual notification (SMS, phone call, etc.)
    
    def get_status(self) -> Dict:
        """Get current circuit breaker status"""
        with self.state_lock:
            return {
                "state": self.state.value,
                "current_drawdown": self.current_drawdown,
                "daily_pnl": self.daily_pnl,
                "consecutive_losses": self.consecutive_losses,
                "open_positions": len(self.broker.get_positions()),
                "manual_override": self._manual_override,
                "last_breach": self.breach_history[-1] if self.breach_history else None,
                "limits": {
                    "max_daily_dd": self.limits.max_daily_drawdown_pct,
                    "max_total_dd": self.limits.max_total_drawdown_pct,
                    "max_position": self.limits.max_position_size_pct
                }
            }
    
    def shutdown(self):
        """Graceful shutdown"""
        self._shutdown = True
        if self._monitoring_task:
            self._monitoring_task.cancel()
        self._persist_state()
