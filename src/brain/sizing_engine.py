"""Position sizing with Kelly and risk overlay."""
from __future__ import annotations

from decimal import Decimal
from dataclasses import dataclass

from src.brain.signal_generator import Signal


@dataclass
class SizeRecommendation:
    quantity: Decimal
    leverage: float
    reasoning: str


class SizingEngine:
    """Dynamic position sizing."""
    
    def calculate(
        self,
        signal: Signal,
        portfolio_value: Decimal,
        volatility: float,
        win_rate: float = 0.55,
        avg_win_loss_ratio: float = 1.5
    ) -> SizeRecommendation:
        """Kelly criterion with fractional adjustment."""
        # Kelly fraction: (p*b - q) / b
        # p = win rate, q = loss rate, b = win/loss ratio
        p = win_rate
        q = 1 - p
        b = avg_win_loss_ratio
        
        kelly = (p * b - q) / b if b > 0 else 0
        
        # Quarter Kelly for safety
        fractional_kelly = kelly * 0.25
        
        # Volatility adjustment
        vol_factor = 1.0 / (1.0 + volatility * 10)
        
        # Signal strength adjustment
        final_size = fractional_kelly * vol_factor * signal.strength
        
        # Cap at 5% of portfolio
        max_size = portfolio_value * Decimal("0.05")
        actual_size = min(
            Decimal(str(final_size)) * portfolio_value,
            max_size
        )
        
        return SizeRecommendation(
            quantity=actual_size.quantize(Decimal("0.01")),
            leverage=1.0,
            reasoning=f"Kelly={kelly:.3f}, frac={fractional_kelly:.3f}, vol_adj={vol_factor:.3f}"
        )
