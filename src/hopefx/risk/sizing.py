from dataclasses import dataclass
from decimal import Decimal


@dataclass
class RiskConfig:
    max_risk_per_trade_pct: float = 0.01  # 1%
    max_position_size_lots: float = 10.0
    atr_multiplier: float = 2.0


class PositionSizer:
    """ATR-based position sizing with Kelly Criterion adjustment."""
    
    def __init__(self, account_balance: Decimal, config: RiskConfig | None = None) -> None:
        self.balance = account_balance
        self.config = config or RiskConfig()
    
    def calculate(self, symbol: str, confidence: float, atr: float) -> float:
        """Calculate position size in lots."""
        if atr <= 0 or confidence < 0.5:
            return 0.0
        
        # Risk amount
        risk_amount = float(self.balance) * self.config.max_risk_per_trade_pct
        
        # ATR stop distance
        stop_distance = atr * self.config.atr_multiplier
        
        # Base size
        base_size =
