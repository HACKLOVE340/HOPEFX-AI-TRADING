"""Pure signal generation from features."""
from __future__ import annotations

from dataclasses import dataclass

from src.core.types import SignalType
from src.ml.regime import MarketRegime


@dataclass
class Signal:
    type: SignalType
    strength: float  # 0-1
    confidence: float  # Model confidence
    regime_alignment: float  # How well signal aligns with regime


class SignalGenerator:
    """Generate raw signals from ML predictions."""
    
    def generate(
        self,
        prediction: dict,
        regime: MarketRegime,
        features: dict
    ) -> Signal:
        """Generate signal with regime alignment check."""
        direction = prediction["direction"]
        confidence = prediction["confidence"]
        
        # Regime alignment
        alignment = self._calculate_regime_alignment(direction, regime, features)
        
        # Filter by alignment
        if alignment < 0.3:
            return Signal(SignalType.HOLD, 0.0, confidence, alignment)
        
        signal_type = (
            SignalType.ENTRY_LONG if direction == "UP" 
            else SignalType.ENTRY_SHORT
        )
        
        # Strength combines confidence and alignment
        strength = confidence * alignment
        
        return Signal(signal_type, strength, confidence, alignment)
    
    def _calculate_regime_alignment(
        self, 
        direction: str, 
        regime: MarketRegime,
        features: dict
    ) -> float:
        """Calculate how well signal aligns with detected regime."""
        if regime == MarketRegime.TRENDING_UP:
            return 1.0 if direction == "UP" else 0.0
        elif regime == MarketRegime.TRENDING_DOWN:
            return 1.0 if direction == "DOWN" else 0.0
        elif regime == MarketRegime.MEAN_REVERTING:
            # Counter-trend is preferred
            return 0.7 if direction == "DOWN" else 0.7  # Simplified
        return 0.5
