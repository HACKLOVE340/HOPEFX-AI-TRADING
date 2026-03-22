"""
HOPEFX Strategy Orchestra
Coordinates multiple strategies to prevent conflicts and maximize returns
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

from core.event_bus import EventBus, DomainEvent
from strategies.base import BaseStrategy, Signal, SignalType


@dataclass
class StrategyPerformance:
    strategy_id: str
    total_signals: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    current_drawdown: float = 0.0
    correlation_to_portfolio: float = 0.0
    regime_suitability: Dict[str, float] = field(default_factory=dict)


class StrategyOrchestra:
    """Conducts multiple strategies like an orchestra"""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.strategies: Dict[str, BaseStrategy] = {}
        self.performance: Dict[str, StrategyPerformance] = {}
        self.allocations: Dict[str, float] = {}
        self.active_strategies: List[str] = []
        self.current_regime: str = "unknown"
        self.signal_buffer: Dict[str, List[Signal]] = defaultdict(list)
        
        self.event_bus.subscribe('POSITION_CLOSED', self._on_position_closed)
        self.event_bus.subscribe('REGIME_CHANGE', self._on_regime_change)
    
    def register_strategy(self, strategy: BaseStrategy, max_allocation: float = 0.20):
        sid = strategy.config.name
        self.strategies[sid] = strategy
        self.allocations[sid] = max_allocation
        self.performance[sid] = StrategyPerformance(
            strategy_id=sid,
            regime_suitability=self._detect_regime_suitability(strategy)
        )
        print(f"🎼 Strategy registered: {sid} (max alloc: {max_allocation:.0%})")
    
    def _detect_regime_suitability(self, strategy: BaseStrategy) -> Dict[str, float]:
        name = strategy.config.name.lower()
        if 'trend' in name or 'momentum' in name:
            return {'trending_up': 0.9, 'trending_down': 0.8, 'ranging': 0.3, 'volatile': 0.5}
        elif 'mean' in name or 'reversion' in name:
            return {'trending_up': 0.3, 'trending_down': 0.3, 'ranging': 0.9, 'volatile': 0.4}
        elif 'breakout' in name or 'volatility' in name:
            return {'trending_up': 0.5, 'trending_down': 0.5, 'ranging': 0.4, 'volatile': 0.9}
        return {'trending_up': 0.5, 'trending_down': 0.5, 'ranging': 0.5, 'volatile': 0.5}
    
    def activate_strategy(self, strategy_id: str):
        if strategy_id in self.strategies:
            self.strategies[strategy_id].start()
            if strategy_id not in self.active_strategies:
                self.active_strategies.append(strategy_id)
            print(f"▶️  Activated: {strategy_id}")
    
    def deactivate_strategy(self, strategy_id: str, reason: str = ""):
        if strategy_id in self.strategies:
            self.strategies[strategy_id].stop()
            if strategy_id in self.active_strategies:
                self.active_strategies.remove(strategy_id)
            print(f"⏸️  Deactivated: {strategy_id} {f'({reason})' if reason else ''}")
    
    def distribute_price(self, price: float):
        """Distribute price to all active strategies"""
        for sid in self.active_strategies:
            try:
                bar = {'close': price, 'timestamp': datetime.utcnow()}
                signal = self.strategies[sid].on_bar(bar)
                if signal:
                    self.signal_buffer[sid].append(signal)
                    if len(self.signal_buffer[sid]) > 100:
                        self.signal_buffer[sid].pop(0)
                    self.event_bus.publish(DomainEvent.create(
                        'SIGNAL_GENERATED', sid,
                        {'signal_type': signal.signal_type.value, 'confidence': signal.confidence}
                    ))
            except Exception as e:
                print(f"Error in {sid}: {e}")
        
        # Calculate and emit composite signal
        composite = self._calculate_composite_signal()
        if composite:
            self.event_bus.publish(DomainEvent.create(
                'COMPOSITE_SIGNAL', 'orchestra',
                {'action': composite.signal_type.value, 'strength': composite.confidence},
                priority=2
            ))
    
    def _calculate_composite_signal(self) -> Optional[Signal]:
        if not self.active_strategies:
            return None
        
        votes = defaultdict(float)
        total_weight = 0
        
        for sid in self.active_strategies:
            perf = self.performance[sid]
            weight = perf.sharpe_ratio * self.allocations[sid]
            if self.current_regime in perf.regime_suitability:
                weight *= perf.regime_suitability[self.current_regime]
            
            if self.signal_buffer[sid]:
                latest = self.signal_buffer[sid][-1]
                votes[latest.signal_type] += weight * latest.confidence
                total_weight += weight
        
        if not votes or total_weight == 0:
            return None
        
        best_signal = max(votes.items(), key=lambda x: x[1])
        if best_signal[1] > 0.3 * total_weight:
            return Signal(
                signal_type=best_signal[0],
                symbol="XAUUSD",
                price=0,
                timestamp=datetime.utcnow(),
                confidence=min(best_signal[1] / total_weight, 1.0)
            )
        return None
    
    def _on_position_closed(self, event: DomainEvent):
        data = event.decode()
        sid = data.get('strategy_id')
        pnl = data.get('pnl', 0)
        if sid in self.performance:
            perf = self.performance[sid]
            perf.total_signals += 1
            # Update metrics (simplified)
    
    def _on_regime_change(self, event: DomainEvent):
        data = event.decode()
        new_regime = data.get('regime')
        self.current_regime = new_regime
        print(f"🌊 Regime change: {new_regime}")
        
        for sid, perf in self.performance.items():
            suit = perf.regime_suitability.get(new_regime, 0.5)
            if suit > 0.7 and sid not in self.active_strategies:
                self.activate_strategy(sid)
            elif suit < 0.3 and sid in self.active_strategies:
                self.deactivate_strategy(sid, f"unsuitable for {new_regime}")
    
    def get_heatmap_data(self) -> Dict:
        return {
            'strategies': {
                sid: {
                    'allocation': self.allocations.get(sid, 0),
                    'active': sid in self.active_strategies,
                    'win_rate': perf.win_rate,
                    'sharpe': perf.sharpe_ratio,
                    'drawdown': perf.current_drawdown,
                    'regime_fit': perf.regime_suitability.get(self.current_regime, 0)
                }
                for sid, perf in self.performance.items()
            },
            'current_regime': self.current_regime,
            'active_count': len(self.active_strategies)
        }
