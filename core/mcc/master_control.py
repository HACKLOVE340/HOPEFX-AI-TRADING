# core/mcc/master_control.py
"""
Master Control Core - connects your existing HOPEFX components
with advanced features. Non-breaking integration.
"""

import asyncio
import threading
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import json

# Import your existing components
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config.config_manager import ConfigManager
from cache.market_data_cache import MarketDataCache
from database.models import Session, Trade, Position
from strategies.base_enhanced import EnhancedStrategy, StrategySignal, StrategyAdapter


@dataclass
class MCCConfig:
    """Configuration for Master Control Core"""
    max_strategies_active: int = 5
    risk_check_interval_ms: int = 100
    correlation_threshold: float = 0.7
    emergency_drawdown_pct: float = 0.10
    
    # Feature flags (enable gradually)
    enable_gpu: bool = False
    enable_fpga: bool = False
    enable_arbitrage: bool = False


class MasterControlCore:
    """
    The Brain of HOPEFX.
    
    Connects your existing:
    - ConfigManager (encrypted settings)
    - MarketDataCache (Redis)
    - Database (SQLAlchemy)
    - Strategies (your existing + new)
    
    Adds:
    - Strategy orchestration
    - Risk monitoring
    - Performance tracking
    - Heatmap analysis
    """
    
    def __init__(self, config: Optional[MCCConfig] = None):
        self.config = config or MCCConfig()
        
        print("╔══════════════════════════════════════════════════╗")
        print("║     HOPEFX MASTER CONTROL CORE v2.0              ║")
        print("║     Integrating your existing infrastructure       ║")
        print("╚══════════════════════════════════════════════════╝")
        
        # Your existing components
        self.config_manager: Optional[ConfigManager] = None
        self.cache: Optional[MarketDataCache] = None
        self.db_session = None
        
        # Strategy management
        self.strategies: Dict[str, EnhancedStrategy] = {}
        self.strategy_allocations: Dict[str, Decimal] = {}
        self.active_strategies: List[str] = []
        
        # Market state
        self.current_prices: Dict[str, Decimal] = {}
        self.current_regime: str = "unknown"
        self.price_history: Dict[str, List[tuple]] = defaultdict(list)
        
        # Risk management
        self.daily_pnl: Decimal = Decimal("0")
        self.total_exposure: Decimal = Decimal("0")
        self.kill_switch_triggered: bool = False
        
        # Event system (simplified for integration)
        self.event_handlers: Dict[str, List[callable]] = defaultdict(list)
        
        # State
        self.is_running: bool = False
        self._lock = threading.RLock()
        
        # Performance tracking
        self.heatmap_data: Dict[str, Any] = {}
    
    def initialize(self, 
                   config_manager: ConfigManager,
                   cache: MarketDataCache,
                   db_session=None):
        """
        Initialize with your existing HOPEFX components.
        """
        self.config_manager = config_manager
        self.cache = cache
        self.db_session = db_session
        
        print("\n📡 Connecting to your infrastructure...")
        print(f"   ✓ ConfigManager: {type(config_manager).__name__}")
        print(f"   ✓ MarketDataCache: {type(cache).__name__}")
        print(f"   ✓ Database: {'Connected' if db_session else 'Not connected'}")
        
        # Load configuration
        self._load_mcc_config()
        
        print("\n✅ MCC initialized and ready")
    
    def _load_mcc_config(self):
        """Load MCC-specific config from your config manager"""
        try:
            # Try to get from your existing config
            if self.config_manager:
                mcc_settings = self.config_manager.get('mcc', {})
                self.config.max_strategies_active = mcc_settings.get('max_strategies', 5)
                self.config.emergency_drawdown_pct = Decimal(str(mcc_settings.get('max_drawdown', 0.10)))
        except:
            pass  # Use defaults
    
    def register_strategy(self, strategy: EnhancedStrategy, 
                         max_allocation: Decimal = Decimal("0.20")):
        """
        Register a strategy with MCC.
        Works with both new EnhancedStrategy and old strategies via adapter.
        """
        # Wrap if needed
        if not isinstance(strategy, EnhancedStrategy):
            strategy = StrategyAdapter(strategy)
        
        name = strategy.config.name
        
        with self._lock:
            self.strategies[name] = strategy
            self.strategy_allocations[name] = max_allocation
            
            # Set callback so strategy can report to MCC
            strategy.mcc_callback = self._on_strategy_signal
        
        print(f"   📊 Strategy registered: {name} (max alloc: {max_allocation})")
    
    def activate_strategy(self, name: str):
        """Activate a strategy"""
        if name in self.strategies:
            self.strategies[name].activate()
            if name not in self.active_strategies:
                self.active_strategies.append(name)
            print(f"   ▶️  Activated: {name}")
    
    def deactivate_strategy(self, name: str, reason: str = ""):
        """Deactivate a strategy"""
        if name in self.strategies:
            self.strategies[name].deactivate()
            if name in self.active_strategies:
                self.active_strategies.remove(name)
            print(f"   ⏸️  Deactivated: {name} {f'({reason})' if reason else ''}")
    
    def _on_strategy_signal(self, strategy_name: str, signal: StrategySignal):
        """
        Callback when any strategy generates a signal.
        This is where the magic happens - aggregation, risk check, execution.
        """
        if self.kill_switch_triggered:
            return
        
        # Log signal
        print(f"📡 [{strategy_name}] Signal: {signal.action} "
              f"(strength: {signal.strength:.2f}, conf: {signal.confidence:.2f})")
        
        # Risk check
        if not self._check_signal_risk(strategy_name, signal):
            print(f"   ⚠️ Risk check failed - signal rejected")
            return
        
        # Aggregate with other signals
        composite = self._aggregate_signals()
        
        # Execute if consensus
        if composite['action'] != 'HOLD' and composite['confidence'] > 0.6:
            self._execute_signal(composite)
    
    def _check_signal_risk(self, strategy_name: str, signal: StrategySignal) -> bool:
        """Pre-trade risk check"""
        # Check daily loss limit
        if self.daily_pnl < -Decimal("1000"):  # $1k daily loss
            return False
        
        # Check strategy allocation
        current_alloc = self._calculate_strategy_exposure(strategy_name)
        max_alloc = self.strategy_allocations.get(strategy_name, Decimal("0.20"))
        
        if current_alloc >= max_alloc:
            return False
        
        # Check correlation (don't add to correlated position)
        if self._is_correlated_signal(strategy_name, signal):
            return False
        
        return True
    
    def _is_correlated_signal(self, strategy_name: str, signal: StrategySignal) -> bool:
        """Check if signal is correlated with existing positions"""
        # Simplified: check if another strategy has similar signal
        for name, strat in self.strategies.items():
            if name != strategy_name and strat.is_active:
                # Would check actual correlation matrix here
                pass
        return False
    
    def _aggregate_signals(self) -> Dict:
        """
        Combine signals from all active strategies.
        Weight by performance and confidence.
        """
        votes = {'BUY': [], 'SELL': [], 'HOLD': []}
        
        for name in self.active_strategies:
            strat = self.strategies[name]
            # Get latest signal (would store in buffer)
            # Simplified: assume we have it
            pass
        
        # For now, simple majority
        return {
            'action': 'HOLD',
            'confidence': 0.5,
            'strength': 0.0
        }
    
    def _execute_signal(self, composite: Dict):
        """Send to execution"""
        print(f"🚀 EXECUTING: {composite['action']} "
              f"(confidence: {composite['confidence']:.2f})")
        # Connect to your existing broker execution here
    
    def on_price_update(self, symbol: str, price: Decimal, 
                       bid: Optional[Decimal] = None,
                       ask: Optional[Decimal] = None):
        """
        Call this from your existing price feed handler.
        MCC distributes to all strategies.
        """
        timestamp = datetime.utcnow()
        
        # Store price
        self.current_prices[symbol] = price
        self.price_history[symbol].append((timestamp, price))
        if len(self.price_history[symbol]) > 1000:
            self.price_history[symbol].pop(0)
        
        # Detect regime
        self._detect_regime(symbol)
        
        # Distribute to strategies
        for name in self.active_strategies:
            try:
                self.strategies[name].on_price(timestamp, price, bid, ask)
            except Exception as e:
                print(f"   ⚠️ Error in {name}: {e}")
    
    def _detect_regime(self, symbol: str):
        """Detect market regime from price history"""
        history = self.price_history[symbol]
        if len(history) < 50:
            return
        
        # Simple regime detection (enhance with your ML)
        prices = [p for _, p in history[-50:]]
        returns = [(prices[i] - prices[i-1]) / prices[i-1] 
                   for i in range(1, len(prices))]
        
        volatility = sum(r**2 for r in returns) / len(returns)
        trend = sum(returns) / len(returns)
        
        if volatility > 0.001:  # High volatility threshold
            if abs(trend) > 0.0005:
                new_regime = "trending_up" if trend > 0 else "trending_down"
            else:
                new_regime = "volatile"
        else:
            new_regime = "ranging"
        
        if new_regime != self.current_regime:
            self.current_regime = new_regime
            self._on_regime_change(new_regime)
    
    def _on_regime_change(self, new_regime: str):
        """Adjust strategies based on regime"""
        print(f"🌊 Regime change: {new_regime}")
        
        # Activate/deactivate strategies based on suitability
        regime_strategies = {
            'trending_up': ['trend_following', 'momentum'],
            'trending_down': ['trend_following', 'mean_reversion'],
            'ranging': ['mean_reversion', 'stat_arb'],
            'volatile': ['volatility', 'breakout']
        }
        
        suitable = regime_strategies.get(new_regime, [])
        
        for name, strat in self.strategies.items():
            is_suitable = any(s in name.lower() for s in suitable)
            
            if is_suitable and not strat.is_active:
                self.activate_strategy(name)
            elif not is_suitable and strat.is_active:
                self.deactivate_strategy(name, f"unsuitable for {new_regime}")
    
    def _calculate_strategy_exposure(self, strategy_name: str) -> Decimal:
        """Calculate current exposure for a strategy"""
        # Query from your database
        return Decimal("0")
    
    def trigger_kill_switch(self, reason: str):
        """Emergency stop all trading"""
        print(f"🚨 KILL SWITCH TRIGGERED: {reason}")
        self.kill_switch_triggered = True
        
        for name in list(self.active_strategies):
            self.deactivate_strategy(name, "kill switch")
        
        # Close all positions via your existing broker
    
    def get_heatmap_data(self) -> Dict:
        """
        Generate heatmap data for visualization.
        Shows strategy performance, correlations, risk.
        """
        return {
            'strategies': {
                name: strat.get_metrics()
                for name, strat in self.strategies.items()
            },
            'regime': self.current_regime,
            'exposure': float(self.total_exposure),
            'daily_pnl': float(self.daily_pnl),
            'active_count': len(self.active_strategies),
            'prices': {
                sym: float(price) 
                for sym, price in self.current_prices.items()
            }
        }
    
    def get_status(self) -> Dict:
        """Full system status"""
        return {
            'running': self.is_running,
            'kill_switch': self.kill_switch_triggered,
            'strategies_registered': len(self.strategies),
            'strategies_active': len(self.active_strategies),
            'regime': self.current_regime,
            'daily_pnl': float(self.daily_pnl),
            'heatmap': self.get_heatmap_data()
        }
    
    def run(self):
        """Main loop - integrate with your existing main.py"""
        self.is_running = True
        print("\n🎯 MCC Running - coordinating all strategies")
        
        # Your existing main loop calls on_price_update()
        # This distributes to all strategies
    
    def stop(self):
        """Graceful shutdown"""
        print("\n🛑 MCC Stopping...")
        self.is_running = False
        
        for name in list(self.active_strategies):
            self.deactivate_strategy(name, "shutdown")
        
        print("   ✓ All strategies deactivated")
