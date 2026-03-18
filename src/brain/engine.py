"""Institution-grade decision engine with regime-aware ensemble."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

import numpy as np
import structlog
from anyio import create_task_group

from src.core.events import SignalEvent, TickEvent, RiskEvent, DriftEvent
from src.core.types import SignalType, Symbol, Side, Tick
from src.features.engineer import FeatureEngineer, FeatureVector
from src.ml.ensemble import AdaptiveEnsemble
from src.ml.regime import RegimeDetector, MarketRegime
from src.risk.kill_switch import kill_switch, KillSource, KillScope
from src.risk.sizing import DynamicPositionSizer
from src.risk.breakers import RiskManager

logger = structlog.get_logger()


@dataclass
class Decision:
    signal: SignalType
    confidence: float
    size: Decimal
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    regime: MarketRegime
    model_contributions: dict[str, float]
    reasoning: dict[str, Any]


class BrainEngine:
    """Multi-model, regime-aware decision engine."""
    
    def __init__(self) -> None:
        # Core components
        self.feature_engineer = FeatureEngineer(parallel=True)
        self.ensemble = AdaptiveEnsemble()
        self.regime_detector = RegimeDetector()
        self.position_sizer = DynamicPositionSizer()
        self.risk_manager = RiskManager()
        
        # State
        self._decision_history: list[Decision] = []
        self._max_history = 10000
        self._performance_by_regime: dict[MarketRegime, dict[str, float]] = {}
        self._min_confidence = 0.70
        self._min_regime_confidence = 0.85
        
        # Circuit breakers
        self._consecutive_errors = 0
        self._max_errors = 5
        self._last_decision_ns = 0
        self._min_decision_interval_ns = 1_000_000  # 1ms minimum
        
        # Metrics
        self._total_decisions = 0
        self._filtered_by_risk = 0
        self._filtered_by_kill = 0
        
        # Async
        self._lock = asyncio.Lock()
        self._precomputed_features: dict[Symbol, FeatureVector] = {}
    
    async def initialize(self) -> None:
        """Initialize all components."""
        await asyncio.gather(
            self.ensemble.load(),
            self.regime_detector.load(),
        )
        
        # Register kill callback
        kill_switch.register_callback(self._on_kill)
        
        logger.info("Brain engine initialized")
    
    async def _on_kill(self, cmd) -> None:
        """Emergency shutdown callback."""
        logger.critical("Brain received kill command - halting decisions")
        # Cancel any pending work
        self._precomputed_features.clear()
    
    async def on_tick(self, event: TickEvent) -> Decision | None:
        """Process tick with full risk stack."""
        tick = event.tick
        
        # 1. Kill switch check (fast path)
        if kill_switch.is_killed(tick.symbol):
            self._filtered_by_kill += 1
            return None
        
        # 2. Rate limiting (prevent spam)
        now_ns = time.time_ns()
        if now_ns - self._last_decision_ns < self._min_decision_interval_ns:
            return None
        
        # 3. Feature engineering (parallel GPU if available)
        try:
            features = await self.feature_engineer.compute_async(tick)
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_errors:
                await kill_switch.kill(
                    f"Feature engineering failed {self._consecutive_errors} times",
                    source=KillSource.CIRCUIT_BREAKER
                )
            return None
        
        # 4. Regime detection
        regime, regime_conf = await self.regime_detector.detect(features)
        
        # 5. Model inference (ensemble with regime weighting)
        try:
            predictions = await self.ensemble.predict(
                features,
                regime=regime,
                regime_confidence=regime_conf
            )
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            await self._handle_model_failure(e)
            return None
        
        self._consecutive_errors = 0  # Reset on success
        
        # 6. Confidence filtering
        if predictions["confidence"] < self._min_confidence:
            return None
        
        if regime_conf < self._min_regime_confidence and regime != MarketRegime.UNKNOWN:
            logger.warning(f"Low regime confidence: {regime_conf:.2f}")
            return None
        
        # 7. Signal generation (regime-aware)
        signal = self._generate_signal(predictions, regime)
        if signal == SignalType.HOLD:
            return None
        
        # 8. Dynamic position sizing (Kelly + volatility)
        size = await self.position_sizer.calculate(
            signal=signal,
            confidence=predictions["confidence"],
            uncertainty=predictions["uncertainty"],
            regime=regime,
            features=features,
            portfolio_state=await self._get_portfolio()
        )
        
        if size <= 0:
            return None
        
        # 9. Risk gate (comprehensive checks)
        risk_check = await self.risk_manager.evaluate(
            symbol=tick.symbol,
            side=Side.BUY if "LONG" in signal.value else Side.SELL,
            size=size,
            price=tick.mid,
            regime=regime,
            predictions=predictions
        )
        
        if not risk_check["approved"]:
            self._filtered_by_risk += 1
            await self._emit_risk_event(risk_check)
            return None
        
        # 10. Calculate stops (ATR-based with regime adjustment)
        entry = tick.mid
        stop, take = self._calculate_stops(
            signal, entry, features.atr, 
            predictions["confidence"], regime
        )
        
        # Build decision
        decision = Decision(
            signal=signal,
            confidence=predictions["confidence"],
            size=size,
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            regime=regime,
            model_contributions=predictions["contributions"],
            reasoning={
                "features": features.to_dict(),
                "predictions": predictions,
                "regime": {"type": regime.name, "confidence": regime_conf},
                "risk_check": risk_check,
                "latency_us": (time.time_ns() - now_ns) / 1000
            }
        )
        
        # Track and emit
        async with self._lock:
            self._decision_history.append(decision)
            if len(self._decision_history) > self._max_history:
                self._decision_history.pop(0)
            self._total_decisions += 1
            self._last_decision_ns = time.time_ns()
        
        await self._emit_signal(decision, tick.symbol)
        
        # Async feedback for online learning
        asyncio.create_task(self._feedback_loop(decision, tick))
        
        return decision
    
    def _generate_signal(
        self, 
        predictions: dict[str, Any], 
        regime: MarketRegime
    ) -> SignalType:
        """Regime-aware signal generation."""
        direction = predictions["direction"]
        confidence = predictions["confidence"]
        
        # Regime-specific thresholds
        thresholds = {
            MarketRegime.TRENDING_UP: 0.60,
            MarketRegime.TRENDING_DOWN: 0.60,
            MarketRegime.MEAN_REVERTING: 0.75,  # Higher bar for counter-trend
            MarketRegime.RANGE_BOUND: 0.70,
            MarketRegime.HIGH_VOL: 0.80,  # Very high bar
            MarketRegime.UNKNOWN: 0.85,
        }
        
        threshold = thresholds.get(regime, 0.70)
        
        if confidence < threshold:
            return SignalType.HOLD
        
        # Regime-direction alignment check
        if regime == MarketRegime.TRENDING_UP and direction == "DOWN":
            return SignalType.HOLD  # Don't fight trend
        if regime == MarketRegime.TRENDING_DOWN and direction == "UP":
            return SignalType.HOLD
        
        if direction == "UP":
            return SignalType.ENTRY_LONG
        return SignalType.ENTRY_SHORT
    
    def _calculate_stops(
        self,
        signal: SignalType,
        entry: Decimal,
        atr: float,
        confidence: float,
        regime: MarketRegime
    ) -> tuple[Decimal, Decimal]:
        """Dynamic stop calculation."""
        atr_d = Decimal(str(atr))
        
        # Regime-based ATR multiplier
        multipliers = {
            MarketRegime.TRENDING_UP: Decimal("1.5"),
            MarketRegime.TRENDING_DOWN: Decimal("1.5"),
            MarketRegime.MEAN_REVERTING: Decimal("2.5"),  # Wider for noise
            MarketRegime.RANGE_BOUND: Decimal("2.0"),
            MarketRegime.HIGH_VOL: Decimal("3.0"),
        }
        
        multiplier = multipliers.get(regime, Decimal("2.0"))
        
        # Confidence adjustment (higher confidence = tighter stop)
        conf_adj = Decimal(str(1.0 + (1.0 - confidence)))
        
        stop_distance = atr_d * multiplier * conf_adj
        
        if "LONG" in signal.value:
            stop = entry - stop_distance
            take = entry + (stop_distance * Decimal("2.0"))  # 2:1 R/R
        else:
            stop = entry + stop_distance
            take = entry - (stop_distance * Decimal("2.0"))
        
        return stop.quantize(Decimal("0.01")), take.quantize(Decimal("0.01"))
    
    async def _feedback_loop(self, decision: Decision, tick: Tick) -> None:
        """Async feedback for online learning."""
        # Wait for outcome (simplified)
        await asyncio.sleep(60)  # 1 minute later
        
        # Get realized return
        # Update ensemble with outcome
        # await self.ensemble.update(decision, outcome)
        pass
    
    async def _handle_model_failure(self, error: Exception) -> None:
        """Handle model failure with escalation."""
        self._consecutive_errors += 1
        
        if self._consecutive_errors >= 3:
            logger.error(f"Model degradation: {error}")
            await self.ensemble.fallback_to_simpler_model()
        
        if self._consecutive_errors >= self._max_errors:
            await kill_switch.kill(
                f"Model failure cascade: {error}",
                source=KillSource.DRIFT
            )
    
    async def _emit_signal(self, decision: Decision, symbol: Symbol) -> None:
        """Emit signal event."""
        from src.core.bus import event_bus
        event = SignalEvent(
            symbol=symbol,
            signal=decision.signal,
            confidence=decision.confidence,
            features=decision.reasoning["features"]
        )
        await event_bus.publish(event)
    
    async def _emit_risk_event(self, risk_check: dict) -> None:
        """Emit risk event."""
        from src.core.bus import event_bus
        event = RiskEvent(
            risk_type=risk_check["type"],
            severity=risk_check["severity"],
            message=risk_check["message"],
            metrics=risk_check.get("metrics", {})
        )
        await event_bus.publish(event)
    
    async def _get_portfolio(self) -> dict[str, Any]:
        """Get current portfolio state."""
        # Query from OMS/position manager
        return {"equity": Decimal("100000"), "open_positions": 0}
    
    def get_stats(self) -> dict[str, Any]:
        """Engine statistics."""
        return {
            "total_decisions": self._total_decisions,
            "filtered_by_risk": self._filtered_by_risk,
            "filtered_by_kill": self._filtered_by_kill,
            "consecutive_errors": self._consecutive_errors,
            "performance_by_regime": self._performance_by_regime,
        }
