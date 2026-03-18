async def on_tick(self, event: TickEvent) -> Decision | None:
    from src.risk.kill_switch import kill_switch
    if kill_switch.is_killed:
        return None
    # ... your existing code

"""Brain decision engine - signal generation and execution decision."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog

from src.core.events import SignalEvent, TickEvent, RiskEvent
from src.core.types import SignalType, Symbol, Side
from src.ml.predictor import OnlineEnsemble
from src.features.engineer import FeatureEngineer
from src.risk.sizing import PositionSizer
from src.risk.breakers import RiskManager

logger = structlog.get_logger()


@dataclass
class Decision:
    """Trading decision output."""
    signal: SignalType
    confidence: float
    size: Decimal
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    reasoning: dict[str, Any]


class BrainEngine:
    """AI-first decision engine."""
    
    def __init__(self) -> None:
        self.ensemble = OnlineEnsemble()
        self.feature_engineer = FeatureEngineer()
        self.position_sizer = PositionSizer()
        self.risk_manager = RiskManager()
        
        # State
        self._last_prediction: dict[str, Any] | None = None
        self._min_confidence = 0.65
        self._max_positions = 5
    
    async def initialize(self) -> None:
        """Initialize components."""
        await self.ensemble.load_or_initialize()
        logger.info("Brain engine initialized")
    
    async def on_tick(self, event: TickEvent) -> Decision | None:
        """Process tick and generate decision."""
        tick = event.tick
        
        # Compute features
        features = await self.feature_engineer.compute_from_tick(tick)
        feature_dict = features.to_dict()
        
        # ML prediction
        prediction = await self.ensemble.predict(feature_dict)
        self._last_prediction = prediction
        
        # Check risk limits first
        risk_check = await self.risk_manager.check_limits(tick, prediction)
        if not risk_check["allowed"]:
            await self._emit_risk_event(risk_check)
            return None
        
        # Generate signal
        signal = self._generate_signal(prediction)
        
        if signal == SignalType.HOLD or prediction["confidence"] < self._min_confidence:
            return None
        
        # Calculate position size
        size = await self.position_sizer.calculate(
            signal=signal,
            confidence=prediction["confidence"],
            volatility=feature_dict["volatility"],
            atr=feature_dict["atr"],
            account_equity=await self._get_equity()
        )
        
        # Calculate stops
        entry = tick.mid
        stop, take_profit = self._calculate_stops(
            signal, entry, feature_dict["atr"], prediction["confidence"]
        )
        
        decision = Decision(
            signal=signal,
            confidence=prediction["confidence"],
            size=size,
            entry_price=entry,
            stop_loss=stop,
            take_profit=take_profit,
            reasoning={
                "prediction": prediction,
                "features": feature_dict,
                "risk_check": risk_check,
            }
        )
        
        # Emit signal event
        await self._emit_signal(decision, tick.symbol)
        
        return decision
    
    def _generate_signal(self, prediction: dict[str, Any]) -> SignalType:
        """Generate trading signal from prediction."""
        direction = prediction["direction"]
        confidence = prediction["confidence"]
        
        if confidence < self._min_confidence:
            return SignalType.HOLD
        
        # Check for regime (trending vs mean-reverting)
        # This would use additional regime detection
        
        if direction == "UP":
            return SignalType.ENTRY_LONG
        else:
            return SignalType.ENTRY_SHORT
    
    def _calculate_stops(
        self, 
        signal: SignalType, 
        entry: Decimal, 
        atr: float, 
        confidence: float
    ) -> tuple[Decimal | None, Decimal | None]:
        """Calculate stop loss and take profit."""
        atr_dec = Decimal(str(atr))
        entry_dec = Decimal(entry)
        
        # Wider stops for lower confidence
        atr_multiplier = Decimal("2.0") - Decimal(str(confidence))  # 1.0 to 2.0
        
        if "LONG" in signal.value:
            stop = entry_dec - (atr_dec * atr_multiplier)
            take = entry_dec + (atr_dec * atr_multiplier * Decimal("2.0"))
        else:
            stop = entry_dec + (atr_dec * atr_multiplier)
            take = entry_dec - (atr_dec * atr_multiplier * Decimal("2.0"))
        
        return stop, take
    
    async def _get_equity(self) -> Decimal:
        """Get current account equity."""
        # Would query from broker/account manager
        return Decimal("100000.00")
    
    async def _emit_signal(self, decision: Decision, symbol: Symbol) -> None:
        """Emit signal event to bus."""
        from src.core.bus import event_bus
        
        event = SignalEvent(
            symbol=symbol,
            signal=decision.signal,
            confidence=decision.confidence,
            features=decision.reasoning["features"]
        )
        await event_bus.publish(event)
    
    async def _emit_risk_event(self, risk_check: dict[str, Any]) -> None:
        """Emit risk event."""
        from src.core.bus import event_bus
        
        event = RiskEvent(
            risk_type=risk_check["type"],
            severity=risk_check["severity"],
            message=risk_check["message"],
            metrics=risk_check.get("metrics", {})
        )
        await event_bus.publish(event)
