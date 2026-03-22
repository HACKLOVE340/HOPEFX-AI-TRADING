"""
Prop firm compliance rules engine.
"""

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from src.domain.enums import PropFirm


@dataclass
class PropFirmRules:
    """Prop firm trading constraints."""
    firm: PropFirm
    max_daily_loss_pct: Decimal
    max_total_drawdown_pct: Decimal
    profit_target_pct: Decimal
    min_trading_days: int
    max_position_size: Decimal
    news_trading_allowed: bool
    weekend_holding_allowed: bool
    consistency_rule: bool  # Best day < 30% of total profits
    
    # Time restrictions
    trading_start: time = time(0, 0)
    trading_end: time = time(23, 59)


class PropFirmCompliance:
    """
    Prop firm rule enforcement for FTMO, MFF, The5ers, TopStep.
    """
    
    RULES = {
        PropFirm.FTMO: PropFirmRules(
            firm=PropFirm.FTMO,
            max_daily_loss_pct=Decimal("0.05"),
            max_total_drawdown_pct=Decimal("0.10"),
            profit_target_pct=Decimal("0.10"),
            min_trading_days=4,
            max_position_size=Decimal("100"),  # Lots
            news_trading_allowed=True,
            weekend_holding_allowed=True,
            consistency_rule=True
        ),
        PropFirm.MY_FOREX_FUNDS: PropFirmRules(
            firm=PropFirm.MY_FOREX_FUNDS,
            max_daily_loss_pct=Decimal("0.05"),
            max_total_drawdown_pct=Decimal("0.12"),
            profit_target_pct=Decimal("0.08"),
            min_trading_days=5,
            max_position_size=Decimal("50"),
            news_trading_allowed=False,
            weekend_holding_allowed=False,
            consistency_rule=False
        ),
        PropFirm.THE5ERS: PropFirmRules(
            firm=PropFirm.THE5ERS,
            max_daily_loss_pct=Decimal("0.04"),
            max_total_drawdown_pct=Decimal("0.05"),
            profit_target_pct=Decimal("0.06"),
            min_trading_days=3,
            max_position_size=Decimal("200"),
            news_trading_allowed=True,
            weekend_holding_allowed=True,
            consistency_rule=False
        ),
        PropFirm.TOPSTEP: PropFirmRules(
            firm=PropFirm.TOPSTEP,
            max_daily_loss_pct=Decimal("0.02"),
            max_total_drawdown_pct=Decimal("0.03"),
            profit_target_pct=Decimal("0.06"),
            min_trading_days=5,
            max_position_size=Decimal("30"),  # Micros
            news_trading_allowed=False,
            weekend_holding_allowed=False,
            consistency_rule=True
        ),
    }
    
    def __init__(self, firm: PropFirm = PropFirm.NONE):
        self.firm = firm
        self.rules = self.RULES.get(firm)
        self._daily_pnl: dict[datetime, Decimal] = {}
        self._trading_days: set[datetime] = set()
    
    def check_trade_allowed(
        self,
        current_balance: Decimal,
        daily_pnl: Decimal,
        total_pnl: Decimal,
        position_size: Decimal,
        is_news_time: bool = False,
        is_weekend: bool = False
    ) -> tuple[bool, str | None]:
        """
        Check if trade complies with prop firm rules.
        """
        if self.firm == PropFirm.NONE or not self.rules:
            return True, None
        
        # Daily loss limit
        daily_loss_pct = abs(daily_pnl) / current_balance
        if daily_loss_pct >= self.rules.max_daily_loss_pct:
            return False, f"Daily loss limit: {daily_loss_pct:.2%}"
        
        # Total drawdown
        total_return_pct = total_pnl / current_balance
        if total_return_pct <= -self.rules.max_total_drawdown_pct:
            return False, f"Max drawdown reached: {total_return_pct:.2%}"
        
        # Position size
        if position_size > self.rules.max_position_size:
            return False, f"Position size limit: {position_size} > {self.rules.max_position_size}"
        
        # News trading
        if is_news_time and not self.rules.news_trading_allowed:
            return False, "News trading not allowed"
        
        # Weekend holding
        if is_weekend and not self.rules.weekend_holding_allowed:
            return False, "Weekend holding not allowed"
        
        return True, None
    
    def check_consistency(self, daily_pnls: list[Decimal]) -> tuple[bool, float]:
        """
        Check FTMO consistency rule: best day < 30% of total profit.
        """
        if not self.rules or not self.rules.consistency_rule:
            return True, 0.0
        
        if len(daily_pnls) < 2:
            return True, 0.0
        
        total_profit = sum(max(0, pnl) for pnl in daily_pnls)
        if total_profit <= 0:
            return True, 0.0
        
        best_day = max(daily_pnls)
        consistency_ratio = best_day / total_profit
        
        return consistency_ratio < Decimal("0.30"), float(consistency_ratio)
    
    def get_status(self) -> dict:
        """Get current compliance status."""
        if not self.rules:
            return {"firm": "NONE", "active": False}
        
        return {
            "firm": self.firm.value,
            "active": True,
            "rules": {
                "max_daily_loss": f"{self.rules.max_daily_loss_pct:.2%}",
                "max_drawdown": f"{self.rules.max_total_drawdown_pct:.2%}",
                "profit_target": f"{self.rules.profit_target_pct:.2%}",
                "min_trading_days": self.rules.min_trading_days,
                "news_trading": "allowed" if self.rules.news_trading_allowed else "forbidden",
                "weekend_holding": "allowed" if self.rules.weekend_holding_allowed else "forbidden",
            }
        }
