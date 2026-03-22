"""
Prop Firm Challenge Compliance Engine
FTMO, MyForexFunds, The5ers, TopStep integration
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Callable
import json

from hopefx.core.events import EventType, DomainEvent, event_bus

# ============================================================================
# PROP FIRM CONFIGURATIONS
# ============================================================================

class PropFirm(Enum):
    FTMO = "ftmo"
    MY_FOREX_FUNDS = "my_forex_funds"
    THE5ERS = "the5ers"
    TOPSTEP = "topstep"
    TRUE_FOREX_FUNDS = "true_forex_funds"

@dataclass
class ChallengeRules:
    """Rules for specific prop firm challenge."""
    firm: PropFirm
    account_size: Decimal
    max_daily_loss_pct: Decimal
    max_total_loss_pct: Decimal
    profit_target_pct: Decimal
    min_trading_days: int
    max_trading_days: int
    max_lot_per_10k: Decimal  # Max lots per $10k
    weekend_holding_allowed: bool = True
    news_trading_allowed: bool = True
    consistency_rule: bool = False  # FTMO consistency

CHALLENGE_RULES = {
    PropFirm.FTMO: {
        10000: ChallengeRules(
            firm=PropFirm.FTMO,
            account_size=Decimal("10000"),
            max_daily_loss_pct=Decimal("0.05"),
            max_total_loss_pct=Decimal("0.10"),
            profit_target_pct=Decimal("0.10"),
            min_trading_days=4,
            max_trading_days=30,
            max_lot_per_10k=Decimal("1.0"),
            consistency_rule=True
        ),
        100000: ChallengeRules(
            firm=PropFirm.FTMO,
            account_size=Decimal("100000"),
            max_daily_loss_pct=Decimal("0.05"),
            max_total_loss_pct=Decimal("0.10"),
            profit_target_pct=Decimal("0.10"),
            min_trading_days=4,
            max_trading_days=30,
            max_lot_per_10k=Decimal("1.0"),
            consistency_rule=True
        )
    },
    PropFirm.MY_FOREX_FUNDS: {
        10000: ChallengeRules(
            firm=PropFirm.MY_FOREX_FUNDS,
            account_size=Decimal("10000"),
            max_daily_loss_pct=Decimal("0.05"),
            max_total_loss_pct=Decimal("0.12"),
            profit_target_pct=Decimal("0.08"),
            min_trading_days=3,
            max_trading_days=30,
            max_lot_per_10k=Decimal("2.0")
        )
    }
}

# ============================================================================
# COMPLIANCE ENGINE
# ============================================================================

class PropFirmCompliance:
    """
    Real-time compliance monitoring for prop firm challenges.
    
    Prevents violations that would disqualify the trader.
    """
    
    def __init__(self, user_id: str, firm: PropFirm, account_size: Decimal):
        self.user_id = user_id
        self.rules = CHALLENGE_RULES.get(firm, {}).get(int(account_size))
        if not self.rules:
            raise ValueError(f"No rules for {firm} ${account_size}")
        
        self.start_date = datetime.utcnow()
        self.daily_pnl: Dict[str, Decimal] = {}
        self.trades: List[Dict] = []
        self.violations: List[Dict] = []
        self.status = "active"  # active, passed, failed, verified
        
        # Statistics
        self.best_day_pct: Decimal = Decimal("0")
        self.worst_day_pct: Decimal = Decimal("0")
        
        # Subscribe to events
        event_bus.subscribe(EventType.ORDER_FILL, self._check_trade, priority=1)
        event_bus.subscribe(EventType.POSITION_CLOSE, self._update_pnl, priority=1)
    
    async def _check_trade(self, event: DomainEvent):
        """Pre-trade compliance check."""
        fill = event.payload
        
        # Check lot size limit
        lots = fill.get('quantity', 0) / 100000  # Standard lot size
        max_lots = (self.rules.account_size / 10000) * self.rules.max_lot_per_10k
        
        if lots > max_lots:
            await self._violation(
                "MAX_LOT_SIZE",
                f"Trade size {lots:.2f} lots exceeds limit {max_lots:.2f}",
                fill
            )
            return False
        
        # Check weekend holding (if applicable)
        if not self.rules.weekend_holding_allowed:
            if self._is_weekend(fill.get('timestamp')):
                await self._violation(
                    "WEEKEND_HOLDING",
                    "Weekend positions not allowed",
                    fill
                )
                return False
        
        return True
    
    async def _update_pnl(self, event: DomainEvent):
        """Track P&L for compliance."""
        pnl = Decimal(str(event.payload.get('realized_pnl', 0)))
        
        # Daily tracking
        today = datetime.utcnow().strftime("%Y-%m-%d")
        self.daily_pnl[today] = self.daily_pnl.get(today, Decimal("0")) + pnl
        
        # Update extremes
        day_pct = self.daily_pnl[today] / self.rules.account_size
        if day_pct > self.best_day_pct:
            self.best_day_pct = day_pct
        if day_pct < self.worst_day_pct:
            self.worst_day_pct = day_pct
        
        # Check daily loss limit
        daily_loss = abs(min(Decimal("0"), self.daily_pnl[today]))
        max_daily_loss = self.rules.account_size * self.rules.max_daily_loss_pct
        
        if daily_loss > max_daily_loss:
            await self._violation(
                "DAILY_LOSS_LIMIT",
                f"Daily loss ${daily_loss} exceeds limit ${max_daily_loss}",
                {"daily_pnl": str(self.daily_pnl[today])}
            )
            self.status = "failed"
        
        # Check total loss limit
        total_pnl = sum(self.daily_pnl.values())
        total_loss = abs(min(Decimal("0"), total_pnl))
        max_total_loss = self.rules.account_size * self.rules.max_total_loss_pct
        
        if total_loss > max_total_loss:
            await self._violation(
                "TOTAL_LOSS_LIMIT",
                f"Total loss ${total_loss} exceeds limit ${max_total_loss}",
                {"total_pnl": str(total_pnl)}
            )
            self.status = "failed"
        
        # Check profit target
        if total_pnl >= self.rules.account_size * self.rules.profit_target_pct:
            # Check minimum days
            trading_days = len(self.daily_pnl)
            if trading_days >= self.rules.min_trading_days:
                # Check consistency rule (FTMO)
                if self.rules.consistency_rule:
                    if not self._check_consistency():
                        return
                
                self.status = "passed"
                await event_bus.publish(DomainEvent(
                    event_type=EventType.COMPLIANCE_ALERT,
                    payload={
                        "alert_type": "CHALLENGE_PASSED",
                        "user_id": self.user_id,
                        "firm": self.rules.firm.value,
                        "final_pnl": str(total_pnl),
                        "trading_days": trading_days
                    }
                ))
    
    def _check_consistency(self) -> bool:
        """
        FTMO consistency rule: No single day > 30% of total profit.
        """
        if not self.daily_pnl:
            return True
        
        total_profit = sum(p for p in self.daily_pnl.values() if p > 0)
        if total_profit <= 0:
            return True
        
        for day_pnl in self.daily_pnl.values():
            if day_pnl > 0:
                day_pct = day_pnl / total_profit
                if day_pct > Decimal("0.30"):
                    return False
        
        return True
    
    def _is_weekend(self, timestamp) -> bool:
        """Check if timestamp is weekend."""
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return timestamp.weekday() >= 5  # Saturday=5, Sunday=6
    
        async def _violation(self, code: str, message: str, details: Dict):
        """Record compliance violation."""
        violation = {
            "timestamp": datetime.utcnow().isoformat(),
            "code": code,
            "message": message,
            "details": details
        }
        self.violations.append(violation)
        
        await event_bus.publish(DomainEvent(
            event_type=EventType.COMPLIANCE_ALERT,
            payload={
                "alert_type": "VIOLATION",
                "user_id": self.user_id,
                "violation": violation
            }
        ))
    
    def get_dashboard(self) -> Dict:
        """Get real-time compliance dashboard."""
        total_pnl = sum(self.daily_pnl.values(), Decimal("0"))
        days_traded = len(self.daily_pnl)
        days_remaining = self.rules.max_trading_days - (datetime.utcnow() - self.start_date).days
        
        return {
            "status": self.status,
            "firm": self.rules.firm.value,
            "account_size": float(self.rules.account_size),
            "current_equity": float(self.rules.account_size + total_pnl),
            "total_return_pct": float(total_pnl / self.rules.account_size * 100),
            "profit_target_pct": float(self.rules.profit_target_pct * 100),
            "progress_pct": float(min(total_pnl / (self.rules.account_size * self.rules.profit_target_pct), 1) * 100),
            
            "risk_metrics": {
                "daily_loss_used_pct": float(abs(min(Decimal("0"), self.daily_pnl.get(datetime.utcnow().strftime("%Y-%m-%d"), Decimal("0")))) / self.rules.account_size * 100),
                "daily_loss_limit_pct": float(self.rules.max_daily_loss_pct * 100),
                "total_loss_used_pct": float(abs(min(Decimal("0"), total_pnl)) / self.rules.account_size * 100),
                "total_loss_limit_pct": float(self.rules.max_total_loss_pct * 100),
            },
            
            "trading_days": {
                "completed": days_traded,
                "minimum_required": self.rules.min_trading_days,
                "remaining": max(0, days_remaining),
                "maximum": self.rules.max_trading_days
            },
            
            "consistency": {
                "best_day_pct": float(self.best_day_pct * 100),
                "worst_day_pct": float(self.worst_day_pct * 100),
                "passes_consistency": self._check_consistency()
            },
            
            "violations": self.violations,
            "can_trade": self.status == "active"
        }
    
    def export_report(self, filepath: str):
        """Export compliance report for prop firm submission."""
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "challenge": {
                "firm": self.rules.firm.value,
                "account_size": float(self.rules.account_size),
                "start_date": self.start_date.isoformat(),
                "rules": {
                    "max_daily_loss_pct": float(self.rules.max_daily_loss_pct),
                    "max_total_loss_pct": float(self.rules.max_total_loss_pct),
                    "profit_target_pct": float(self.rules.profit_target_pct)
                }
            },
            "performance": self.get_dashboard(),
            "daily_breakdown": [
                {
                    "date": date,
                    "pnl": float(pnl),
                    "pnl_pct": float(pnl / self.rules.account_size * 100)
                }
                for date, pnl in self.daily_pnl.items()
            ],
            "all_trades": self.trades,
            "certification": {
                "integrity_hash": self._calculate_integrity_hash(),
                "generated_by": "HOPEFX Institutional v4.0"
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        
        return filepath
    
    def _calculate_integrity_hash(self) -> str:
        """Calculate hash of all trading data for tamper detection."""
        import hashlib
        data = json.dumps({
            'daily_pnl': {k: str(v) for k, v in self.daily_pnl.items()},
            'trades': self.trades,
            'violations': self.violations
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]
