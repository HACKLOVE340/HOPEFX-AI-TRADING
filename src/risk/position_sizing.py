"""
ATR-based dynamic position sizing with Kelly Criterion.
"""

from decimal import Decimal
from typing import Literal

from src.core.config import settings
from src.domain.models import Account, Signal


class PositionSizer:
    """
    Institutional position sizing with volatility adjustment.
    """
    
    def __init__(
        self,
        method: Literal["atr", "kelly", "fixed"] = "atr",
        risk_per_trade_pct: float = 0.01,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
        kelly_fraction: float = 0.5
    ):
        self.method = method
        self.risk_per_trade = risk_per_trade_pct
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.kelly_fraction = kelly_fraction
    
    def calculate_size(
        self,
        account: Account,
        entry_price: Decimal,
        stop_loss: Decimal | None = None,
        atr: Decimal | None = None,
        signal_confidence: float = 0.5
    ) -> Decimal:
        """
        Calculate position size based on risk parameters.
        """
        account_balance = account.balance
        
        if self.method == "fixed":
            # Fixed fractional sizing
            risk_amount = account_balance * Decimal(str(self.risk_per_trade))
            
            if stop_loss:
                price_risk = abs(entry_price - stop_loss)
                if price_risk > 0:
                    size = risk_amount / price_risk
                else:
                    size = Decimal("0")
            else:
                size = (account_balance * Decimal("0.02")) / entry_price
            
        elif self.method == "atr" and atr:
            # ATR-based sizing
            risk_amount = account_balance * Decimal(str(self.risk_per_trade))
            stop_distance = atr * Decimal(str(self.atr_multiplier))
            
            if stop_distance > 0:
                size = risk_amount / stop_distance
            else:
                size = Decimal("0")
        
        elif self.method == "kelly":
            # Kelly Criterion with half-Kelly adjustment
            win_rate = signal_confidence
            avg_win = Decimal("2")  # 2:1 reward/risk assumed
            avg_loss = Decimal("1")
            
            kelly_pct = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            kelly_pct = max(0, kelly_pct) * self.kelly_fraction
            
            risk_amount = account_balance * Decimal(str(kelly_pct * self.risk_per_trade))
            
            if stop_loss:
                price_risk = abs(entry_price - stop_loss)
                size = risk_amount / price_risk if price_risk > 0 else Decimal("0")
            else:
                size = risk_amount / entry_price
        
        else:
            size = Decimal("0")
        
        # Apply limits
        max_size = (account_balance * Decimal(str(settings.risk.max_position_size_pct))) / entry_price
        size = min(size, max_size)
        
        # Round to standard lot sizes
        size = self._round_lot_size(size)
        
        return size
    
    def _round_lot_size(self, size: Decimal) -> Decimal:
        """Round to nearest micro-lot (0.01)."""
        return (size / Decimal("0.01")).quantize(Decimal("1")) * Decimal("0.01")
    
    def calculate_stop_loss(
        self,
        entry_price: Decimal,
        direction: str,
        atr: Decimal,
        multiplier: float = 2.0
    ) -> Decimal:
        """Calculate ATR-based stop loss."""
        stop_distance = atr * Decimal(str(multiplier))
        
        if direction == "LONG":
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
