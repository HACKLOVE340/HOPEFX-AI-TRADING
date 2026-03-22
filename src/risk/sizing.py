"""ATR-based position sizing with Kelly criterion."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from src.core.types import SignalType

logger = structlog.get_logger()


class PositionSizer:
    """Dynamic position sizing."""
    
    def __init__(self) -> None:
        self.max_risk_per_trade = Decimal("0.02")  # 2%
        self.max_position_pct = Decimal("0.05")    # 5%
        self.kelly_fraction = Decimal("0.25")     # Quarter Kelly
    
    async def calculate(
        self,
        signal: SignalType,
        confidence: float,
        volatility: float,
        atr: float,
        account_equity: Decimal
    ) -> Decimal:
        """Calculate position size."""
        # Base risk amount
        risk_amount = account_equity * self.max_risk_per_trade
        
        # ATR-based stop distance
        stop_distance = Decimal(str(atr * 2))  # 2 ATR stop
        
        if stop_distance == 0:
            logger.warning("Zero stop distance, using default")
            stop_distance = Decimal("0.01")
        
        # Position size based on risk
        position_size = risk_amount / stop_distance
        
        # Adjust for confidence (scale 0.5 to 1.0)
        confidence_factor = Decimal(str(0.5 + confidence / 2))
        position_size *= confidence_factor
        
        # Cap at max position %
        max_size = account_equity * self.max_position_pct
        position_size = min(position_size, max_size)
        
        # Volatility scaling (reduce size in high vol)
        vol_factor = Decimal("1.0") / (Decimal("1.0") + Decimal(str(volatility)))
        position_size *= vol_factor
        
        return position_size.quantize(Decimal("0.01"))
