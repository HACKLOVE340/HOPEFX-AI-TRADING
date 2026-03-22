"""
Advanced strategy-level risk rules with dynamic adjustment.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Literal

import numpy as np
import pandas as pd

from src.core.events import Event, RiskEvent, get_event_bus
from src.core.logging_config import get_logger
from src.domain.enums import RiskLevel, SignalStrength, TradeDirection
from src.domain.models import Signal

logger = get_logger(__name__)


@dataclass
class RiskRule:
    """Individual risk rule definition."""
    name: str
    condition: Callable[[Signal, dict], bool]
    action: Literal["block", "reduce_size", "reduce_confidence", "warn"]
    severity: RiskLevel
    message: str
    cooldown_minutes: int = 60
    last_triggered: datetime | None = None


class StrategyRiskManager:
    """
    Dynamic strategy risk management with ML-based rule optimization.
    """
    
    def __init__(self, strategy_id: str):
        self.strategy_id = strategy_id
        self.rules: list[RiskRule] = []
        self._performance_history: list[dict] = []
        self._rule_effectiveness: dict[str, float] = {}
        self._adaptive_mode = True
        
        self._setup_default_rules()
    
    def _setup_default_rules(self) -> None:
        """Initialize default risk rules."""
        self.rules = [
            RiskRule(
                name="consecutive_losses",
                condition=self._check_consecutive_losses,
                action="block",
                severity=RiskLevel.HIGH,
                message="Too many consecutive losses - strategy paused",
                cooldown_minutes=30
            ),
            RiskRule(
                name="drawdown_limit",
                condition=self._check_drawdown,
                action="block",
                severity=RiskLevel.CRITICAL,
                message="Maximum drawdown exceeded",
                cooldown_minutes=120
            ),
            RiskRule(
                name="volatility_regime",
                condition=self._check_volatility_regime,
                action="reduce_size",
                severity=RiskLevel.MEDIUM,
                message="High volatility - reducing position size",
                cooldown_minutes=15
            ),
            RiskRule(
                name="correlation_spike",
                condition=self._check_correlation_spike,
                action="reduce_confidence",
                severity=RiskLevel.MEDIUM,
                message="Correlation breakdown detected",
                cooldown_minutes=60
            ),
            RiskRule(
                name="weekend_exposure",
                condition=self._check_weekend_exposure,
                action="block",
                severity=RiskLevel.HIGH,
                message="Weekend gap risk - no new positions",
                cooldown_minutes=1440
            ),
            RiskRule(
                name="news_blackout",
                condition=self._check_news_blackout,
                action="block",
                severity=RiskLevel.HIGH,
                message="High-impact news period",
                cooldown_minutes=30
            ),
            RiskRule(
                name="liquidity_dryup",
                condition=self._check_liquidity,
                action="reduce_size",
                severity=RiskLevel.MEDIUM,
                message="Low liquidity - reducing exposure",
                cooldown_minutes=30
            ),
        ]
    
    def evaluate_signal(
        self,
        signal: Signal,
        context: dict
    ) -> tuple[bool, Signal | None, list[str]]:
        """
        Evaluate signal against all risk rules.
        
        Returns:
            (allowed, modified_signal, warnings)
        """
        warnings = []
        modified_signal = signal
        allowed = True
        
        for rule in self.rules:
            # Check cooldown
            if rule.last_triggered:
                elapsed = datetime.now(timezone.utc) - rule.last_triggered
                if elapsed < timedelta(minutes=rule.cooldown_minutes):
                    continue
            
            # Evaluate condition
            if rule.condition(signal, context):
                rule.last_triggered = datetime.now(timezone.utc)
                
                # Track effectiveness
                self._track_rule_trigger(rule.name, signal)
                
                if rule.action == "block":
                    allowed = False
                    warnings.append(f"[BLOCKED] {rule.message}")
                    self._emit_risk_event(rule, signal)
                    break
                
                elif rule.action == "reduce_size":
                    modified_signal = self._reduce_signal_size(modified_signal, 0.5)
                    warnings.append(f"[WARNING] {rule.message} - Size reduced 50%")
                
                elif rule.action == "reduce_confidence":
                    modified_signal = self._reduce_signal_confidence(modified_signal, 0.7)
                    warnings.append(f"[WARNING] {rule.message} - Confidence adjusted")
                
                elif rule.action == "warn":
                    warnings.append(f"[WARNING] {rule.message}")
        
        # Adaptive adjustment
        if self._adaptive_mode:
            modified_signal = self._apply_adaptive_adjustments(modified_signal, context)
        
        return allowed, modified_signal, warnings
    
    def update_performance(self, trade_result: dict) -> None:
        """Update with trade outcome for adaptive learning."""
        self._performance_history.append({
            "timestamp": datetime.now(timezone.utc),
            "pnl": trade_result.get("pnl", 0),
            "signal_strength": trade_result.get("signal_strength", 0),
            "risk_rules_active": trade_result.get("rules_active", [])
        })
        
        # Keep last 100 trades
        if len(self._performance_history) > 100:
            self._performance_history = self._performance_history[-100:]
        
        # Update rule effectiveness
        self._update_rule_effectiveness()
    
    def _update_rule_effectiveness(self) -> None:
        """Calculate how well each rule predicts bad outcomes."""
        for rule in self.rules:
            trades_with_rule = [
                t for t in self._performance_history
                if rule.name in t.get("risk_rules_active", [])
            ]
            
            if len(trades_with_rule) >= 10:
                win_rate = sum(1 for t in trades_with_rule if t["pnl"] > 0) / len(trades_with_rule)
                avg_pnl = np.mean([t["pnl"] for t in trades_with_rule])
                
                # Rule is effective if it prevents losses
                self._rule_effectiveness[rule.name] = -avg_pnl if avg_pnl < 0 else 0.1
    
    def _apply_adaptive_adjustments(self, signal: Signal, context: dict) -> Signal:
        """Apply ML-based adjustments to signal."""
        # Recent performance trend
        if len(self._performance_history) >= 20:
            recent_pnl = [t["pnl"] for t in self._performance_history[-20:]]
            trend = np.polyfit(range(len(recent_pnl)), recent_pnl, 1)[0]
            
            # If negative trend, reduce confidence
            if trend < 0:
                signal = self._reduce_signal_confidence(signal, 0.9)
                signal.metadata["adaptive_adjustment"] = "negative_trend"
        
        # Time-of-day adjustment
        hour = datetime.now(timezone.utc).hour
        if hour in [0, 1, 2, 3]:  # Low liquidity hours
            signal = self._reduce_signal_size(signal, 0.7)
            signal.metadata["adaptive_adjustment"] = "low_liquidity_hours"
        
        return signal
    
    # Rule condition implementations
    
    def _check_consecutive_losses(self, signal: Signal, context: dict) -> bool:
        """Check for consecutive losing trades."""
        recent = self._performance_history[-5:]
        if len(recent) < 5:
            return False
        
        losses = sum(1 for t in recent if t["pnl"] < 0)
        return losses >= 4  # 4 out of 5 losses
    
    def _check_drawdown(self, signal: Signal, context: dict) -> bool:
        """Check current drawdown."""
        current_dd = context.get("current_drawdown", 0)
        return current_dd > 0.05  # 5% drawdown
    
    def _check_volatility_regime(self, signal: Signal, context: dict) -> bool:
        """Check if in high volatility regime."""
        current_vol = context.get("current_volatility", 0)
        normal_vol = context.get("normal_volatility", 0.01)
        return current_vol > normal_vol * 2
    
    def _check_correlation_spike(self, signal: Signal, context: dict) -> bool:
        """Check for correlation breakdown."""
        # Would check if normally uncorrelated assets suddenly correlate
        return context.get("correlation_spike", False)
    
    def _check_weekend_exposure(self, signal: Signal, context: dict) -> bool:
        """Check if near weekend."""
        now = datetime.now(timezone.utc)
        friday_afternoon = now.weekday() == 4 and now.hour >= 20
        sunday_night = now.weekday() == 6 and now.hour >= 20
        return friday_afternoon or sunday_night
    
    def _check_news_blackout(self, signal: Signal, context: dict) -> bool:
        """Check if in news blackout period."""
        return context.get("news_event_imminent", False)
    
    def _check_liquidity(self, signal: Signal, context: dict) -> bool:
        """Check market liquidity."""
        spread_bps = context.get("spread_bps", 1.0)
        return spread_bps > 3.0  # Wide spreads indicate low liquidity
    
    # Signal modification methods
    
    def _reduce_signal_size(self, signal: Signal, factor: float) -> Signal:
        """Reduce signal size by factor."""
        from dataclasses import replace
        return replace(
            signal,
            strength=signal.strength * factor,
            metadata={**signal.metadata, "size_reduced": True, "reduction_factor": factor}
        )
    
    def _reduce_signal_confidence(self, signal: Signal, factor: float) -> Signal:
        """Reduce signal confidence by factor."""
        from dataclasses import replace
        return replace(
            signal,
            confidence=signal.confidence * factor,
            metadata={**signal.metadata, "confidence_adjusted": True}
        )
    
    def _emit_risk_event(self, rule: RiskRule, signal: Signal) -> None:
        """Emit risk event to event bus."""
        asyncio.create_task(get_event_bus().emit(
            Event.create(
                RiskEvent(
                    level=rule.severity.name,
                    metric=f"strategy_{rule.name}",
                    value=1.0,
                    threshold=1.0
                ),
                source=f"strategy_{self.strategy_id}",
                priority=rule.severity.value
            )
        ))
    
    def get_rule_stats(self) -> dict:
        """Get statistics on rule triggers."""
        return {
            rule.name: {
                "triggered_count": sum(
                    1 for t in self._performance_history
                    if rule.name in t.get("rules_active", [])
                ),
                "effectiveness": self._rule_effectiveness.get(rule.name, 0),
                "last_triggered": rule.last_triggered
            }
            for rule in self.rules
        }
