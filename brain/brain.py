
# 2. THE BRAIN - Central intelligence and decision engine

brain_code = '''"""
HOPEFX Brain - Central Intelligence System
Coordinates all components, makes trading decisions, manages state
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json

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
    """Complete system state snapshot"""
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
    geo_risk: str = "low"  # Geopolitical risk assessment
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'system_state': self.system_state.value,
            'market_regime': {k: v.value for k, v in self.market_regime.items()},
            'account_balance': self.account_balance,
            'equity': self.equity,
            'margin_used': self.margin_used,
            'free_margin': self.free_margin,
            'daily_pnl': self.daily_pnl,
            'total_pnl': self.total_pnl,
            'open_trades_count': self.open_trades_count,
            'geo_risk': self.geo_risk
        }

class HOPEFXBrain:
    """
    Central Intelligence System
    
    Responsibilities:
    - Market regime detection
    - Risk assessment
    - Strategy selection
    - Position sizing
    - Emergency protocols
    - Coordination between data, strategies, and execution
    """
    
    def __init__(self):
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
        
        # Decision tracking
        self.decision_history: List[Dict] = []
        self.last_regime_check = 0
        self.regime_check_interval = 60  # seconds
        
        # Control flags
        self._running = False
        self._emergency_stop = False
        
        logger.info("HOPEFXBrain initialized")
    
    def inject_components(self, **components):
        """Inject required components"""
        self.price_engine = components.get('price_engine')
        self.risk_manager = components.get('risk_manager')
        self.broker = components.get('broker')
        self.strategy_manager = components.get('strategy_manager')
        self.notification_manager = components.get('notification_manager')
        logger.info("Components injected into Brain")
    
    async def dominate(self):
        """Main control loop - the brain takes over"""
        self._running = True
        self.state.system_state = SystemState.RUNNING
        
        logger.info("🧠 BRAIN DOMINATE SEQUENCE INITIATED")
        
        try:
            while self._running:
                cycle_start = time.time()
                
                # 1. Update state from all components
                await self._update_state()
                
                # 2. Check market regimes
                await self._analyze_market_regimes()
                
                # 3. Risk assessment
                await self._assess_risk()
                
                # 4. Check emergency conditions
                if await self._check_emergency_conditions():
                    await self._execute_emergency_stop()
                    break
                
                # 5. Strategy decisions
                await self._make_strategy_decisions()
                
                # 6. Log state
                if int(cycle_start) % 60 == 0:  # Every minute
                    logger.info(f"Brain State: {self.state.to_dict()}")
                
                # Maintain 1-second cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, 1.0 - elapsed)
                await asyncio.sleep(sleep_time)
                
        except asyncio.CancelledError:
            logger.info("Brain dominate loop cancelled")
        except Exception as e:
            logger.critical(f"Brain critical error: {e}", exc_info=True)
            await self._execute_emergency_stop()
    
    async def _update_state(self):
        """Gather state from all components"""
        try:
            # Update timestamp
            self.state.timestamp = time.time()
            
            # Get account info from broker
            if self.broker:
                account = await self.broker.get_account_info()
                self.state.account_balance = account.get('balance', 0)
                self.state.equity = account.get('equity', 0)
                self.state.margin_used = account.get('margin_used', 0)
                self.state.free_margin = account.get('free_margin', 0)
            
            # Get positions
            if self.broker:
                positions = await self.broker.get_positions()
                self.state.active_positions = {p['id']: p for p in positions}
                self.state.open_trades_count = len(positions)
            
            # Get pending orders
            if self.broker:
                self.state.pending_orders = await self.broker.get_pending_orders()
                
        except Exception as e:
            logger.error(f"State update error: {e}")
    
    async def _analyze_market_regimes(self):
        """Detect market regimes for all symbols"""
        if time.time() - self.last_regime_check < self.regime_check_interval:
            return
        
        self.last_regime_check = time.time()
        
        if not self.price_engine:
            return
        
        for symbol in getattr(self.price_engine, 'symbols', []):
            try:
                regime = await self._detect_regime(symbol)
                self.state.market_regime[symbol] = regime
            except Exception as e:
                logger.error(f"Regime detection error for {symbol}: {e}")
    
    async def _detect_regime(self, symbol: str) -> MarketRegime:
        """Detect market regime using price action"""
        # Get 1h OHLCV data
        ohlcv = self.price_engine.get_ohlcv(symbol, '1h', limit=24)
        
        if len(ohlcv) < 20:
            return MarketRegime.UNKNOWN
        
        closes = [c.close for c in ohlcv]
        
        # Calculate metrics
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        
        volatility = sum(r**2 for r in returns) / len(returns)
        trend = sum(returns) / len(returns)
        
        # ADX-like trend strength (simplified)
        directional_movement = sum(abs(r) for r in returns) / len(returns)
        
        # Classify regime
        if volatility > 0.0001:  # High volatility threshold
            return MarketRegime.VOLATILE
        elif abs(trend) > 0.00005 and directional_movement > abs(trend) * 0.5:
            if trend > 0:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN
        else:
            return MarketRegime.RANGING
    
    async def _assess_risk(self):
        """Assess overall system risk"""
        try:
            # Check margin usage
            if self.state.equity > 0:
                margin_ratio = self.state.margin_used / self.state.equity
                
                if margin_ratio > 0.8:
                    logger.warning(f"HIGH MARGIN USAGE: {margin_ratio:.2%}")
                    await self._reduce_exposure()
                elif margin_ratio > 0.5:
                    logger.info(f"Moderate margin usage: {margin_ratio:.2%}")
            
            # Check daily loss limit
            if self.state.daily_pnl < -self.state.account_balance * 0.05:  # 5% daily loss
                logger.critical("DAILY LOSS LIMIT REACHED")
                await self._execute_emergency_stop()
            
            # Geopolitical risk (placeholder for news integration)
            self.state.geo_risk = "low"  # Would integrate with news module
            
        except Exception as e:
            logger.error(f"Risk assessment error: {e}")
    
    async def _check_emergency_conditions(self) -> bool:
        """Check if emergency stop is needed"""
        if self._emergency_stop:
            return True
        
        # Check for catastrophic conditions
        if self.state.equity < self.state.account_balance * 0.5:  # 50% equity loss
            logger.critical("CATASTROPHIC LOSS DETECTED")
            return True
        
        # Check for data feed staleness
        if self.price_engine:
            for symbol in self.price_engine.symbols:
                last_tick = self.price_engine.get_last_price(symbol)
                if last_tick and time.time() - last_tick.timestamp > 300:  # 5 min stale
                    logger.warning(f"Stale data for {symbol}")
        
        return False
    
    async def _execute_emergency_stop(self):
        """Emergency shutdown procedure"""
        logger.critical("🚨 EXECUTING EMERGENCY STOP")
        
        self._emergency_stop = True
        self.state.system_state = SystemState.EMERGENCY_STOP
        
        # Close all positions
        if self.broker:
            try:
                await self.broker.close_all_positions()
                logger.info("All positions closed")
            except Exception as e:
                logger.error(f"Error closing positions: {e}")
        
        # Cancel all orders
        if self.broker:
            try:
                await self.broker.cancel_all_orders()
                logger.info("All orders cancelled")
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")
        
        # Notify
        if self.notification_manager:
            await self.notification_manager.send_alert(
                level="CRITICAL",
                message="EMERGENCY STOP EXECUTED",
                data=self.state.to_dict()
            )
        
        self._running = False
    
    async def _reduce_exposure(self):
        """Reduce position sizes when risk is high"""
        if not self.broker:
            return
        
        # Close worst performing positions
        positions = list(self.state.active_positions.values())
        positions.sort(key=lambda p: p.get('unrealized_pnl', 0))
        
        # Close bottom 50% of positions
        to_close = positions[:len(positions)//2]
        for pos in to_close:
            try:
                await self.broker.close_position(pos['id'])
                logger.info(f"Reduced exposure: closed position {pos['id']}")
            except Exception as e:
                logger.error(f"Error reducing position: {e}")
    
    async def _make_strategy_decisions(self):
        """Execute strategy logic"""
        if not self.strategy_manager:
            return
        
        try:
            # Get signals from strategies
            signals = await self.strategy_manager.generate_signals(
                self.state.market_regime,
                self.price_engine
            )
            
            # Filter signals through risk manager
            if self.risk_manager:
                signals = await self.risk_manager.filter_signals(signals, self.state)
            
            # Execute signals
            for signal in signals:
                await self._execute_signal(signal)
                
        except Exception as e:
            logger.error(f"Strategy decision error: {e}")
    
    async def _execute_signal(self, signal: Dict):
        """Execute a trading signal"""
        try:
            action = signal.get('action')  # 'buy', 'sell', 'close'
            symbol = signal.get('symbol')
            
            if action == 'buy':
                await self.broker.place_market_order(
                    symbol=symbol,
                    side='buy',
                    quantity=signal.get('size', 0)
                )
            elif action == 'sell':
                await self.broker.place_market_order(
                    symbol=symbol,
                    side='sell',
                    quantity=signal.get('size', 0)
                )
            elif action == 'close':
                position_id = signal.get('position_id')
                if position_id:
                    await self.broker.close_position(position_id)
            
            # Record decision
            self.decision_history.append({
                'timestamp': time.time(),
                'signal': signal,
                'state': self.state.to_dict()
            })
            
        except Exception as e:
            logger.error(f"Signal execution error: {e}")
    
    def pause(self):
        """Pause trading (keep monitoring)"""
        self.state.system_state = SystemState.PAUSED
        logger.info("Brain paused")
    
    def resume(self):
        """Resume trading"""
        self.state.system_state = SystemState.RUNNING
        logger.info("Brain resumed")
    
    def emergency_stop(self):
        """Manual emergency stop"""
        asyncio.create_task(self._execute_emergency_stop())
    
    def get_state(self) -> BrainState:
        return self.state
    
    def get_decision_history(self, limit: int = 100) -> List[Dict]:
        return self.decision_history[-limit:]
'''

with open(project_root / "brain" / "brain.py", "w") as f:
    f.write(brain_code)

print("✓ Created brain/brain.py")
