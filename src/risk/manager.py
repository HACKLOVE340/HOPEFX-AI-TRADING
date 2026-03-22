"""
Risk Manager - Central risk orchestration and monitoring.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.core.config import settings
from src.core.events import Event, RiskEvent, get_event_bus
from src.core.logging_config import get_logger
from src.domain.enums import RiskLevel, TradeDirection
from src.domain.models import Account, Signal
from src.risk.kill_switch import KillSwitch
from src.risk.position_sizing import PositionSizer
from src.risk.prop_firms import PropFirmCompliance
from src.risk.var_cvar import RiskMetrics

logger = get_logger(__name__)


class RiskManager:
    """
    Central risk management coordinating all risk modules.
    """
    
    def __init__(
        self,
        account: Account | None = None,
        prop_firm_compliance: PropFirmCompliance | None = None
    ):
        self.account = account
        self.prop_firm = prop_firm_compliance or PropFirmCompliance()
        
        self.position_sizer = PositionSizer(method="atr")
        self.risk_metrics = RiskMetrics(
            confidence=settings.risk.var_confidence,
            horizon_days=settings.risk.var_horizon_days,
            simulations=settings.risk.monte_carlo_sims
        )
        self.kill_switch = KillSwitch()
        
        self._price_history: dict[str, list[tuple[datetime, Decimal]]] = {}
        self._daily_pnl: Decimal = Decimal("0")
        self._consecutive_losses: int = 0
        self._event_bus = get_event_bus()
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize risk manager."""
        logger.info("Risk manager initialized")
    
    async def check_signal(self, signal: Signal) -> tuple[bool, str | None]:
        """
        Comprehensive signal validation.
        Returns (allowed, reason).
        """
        async with self._lock:
            # 1. Kill switch check
            if self.kill_switch.is_active:
                return False, "Kill switch active"
            
            # 2. Prop firm compliance
            if self.account:
                allowed, reason = self.prop_firm.check_trade_allowed(
                    current_balance=self.account.balance,
                    daily_pnl=self._daily_pnl,
                    total_pnl=self.account.total_pnl,
                    position_size=Decimal(str(signal.metadata.get("size", 1.0))),
                    is_news_time=self._is_news_time(),
                    is_weekend=self._is_weekend()
                )
                if not allowed:
                    await self._emit_risk_event("prop_firm_violation", reason)
                    return False, reason
            
            # 3. Position limits
            if self.account:
                total_exposure = sum(
                    p.quantity for p in self.account.open_positions.values()
                )
                max_exposure = self.account.equity * Decimal(
                    str(settings.risk.max_position_size_pct)
                )
                
                if total_exposure >= max_exposure:
                    return False, "Maximum position exposure reached"
            
            # 4. Signal quality check
            if signal.confidence < settings.ml.prediction_threshold:
                return False, f"Confidence {signal.confidence:.2f} below threshold"
            
            return True, None
    
    async def update_price(self, symbol: str, price: Decimal) -> None:
        """Update price history for risk calculations."""
        now = datetime.now(timezone.utc)
        
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        
        self._price_history[symbol].append((now, price))
        
        # Keep last 1000 prices
        if len(self._price_history[symbol]) > 1000:
            self._price_history[symbol] = self._price_history[symbol][-1000:]
        
        # Check kill switch conditions
        if self.account:
            current_dd = self._calculate_drawdown()
            daily_return = self._daily_pnl / self.account.balance if self.account.balance > 0 else 0
            
            # Auto-trigger kill switch on excessive drawdown
            if float(current_dd) > 0.2 or float(daily_return) < -0.05:
                self.kill_switch.trigger("Auto: risk limits exceeded")
    
    async def update_pnl(self, realized_pnl: Decimal) -> None:
        """Update P&L tracking."""
        self._daily_pnl += realized_pnl
        
        if realized_pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
    
    def calculate_position_size(
        self,
        signal: Signal,
        entry_price: Decimal,
        stop_loss: Decimal | None = None,
        atr: Decimal | None = None
    ) -> Decimal:
        """Calculate optimal position size."""
        if not self.account:
            return Decimal("1.0")
        
        return self.position_sizer.calculate_size(
            account=self.account,
            entry_price=entry_price,
            stop_loss=stop_loss,
            atr=atr,
            signal_confidence=signal.confidence
        )
    
    def get_risk_report(self) -> dict[str, Any]:
        """Generate comprehensive risk report."""
        return {
            "kill_switch_active": self.kill_switch.is_active,
            "daily_pnl": float(self._daily_pnl),
            "consecutive_losses": self._consecutive_losses,
            "prop_firm_status": self.prop_firm.get_status(),
            "exposure": self._calculate_exposure(),
            "var_95": self._calculate_var(),
        }
    
    def _calculate_drawdown(self) -> Decimal:
        """Calculate current drawdown."""
        if not self.account or self.account.equity <= 0:
            return Decimal("0")
        
        peak = self.account.equity + max(Decimal("0"), self.account.total_pnl)
        if peak <= 0:
            return Decimal("0")
        
        return (peak - self.account.equity) / peak
    
    def _calculate_exposure(self) -> dict[str, float]:
        """Calculate current exposure metrics."""
        if not self.account:
            return {}
        
        total_position_value = sum(
            p.quantity * p.entry_price 
            for p in self.account.open_positions.values()
        )
        
        return {
            "total_position_value": float(total_position_value),
            "exposure_pct": float(total_position_value / self.account.equity) if self.account.equity > 0 else 0,
            "num_positions": len(self.account.open_positions)
        }
    
    def _calculate_var(self) -> float:
        """Calculate current VaR."""
        # Simplified - would use actual returns distribution
        return 0.0
    
    def _is_news_time(self) -> bool:
        """Check if high-impact news period."""
        now = datetime.now(timezone.utc)
        # Major news times: 8:30, 10:00, 14:00 EST
        return now.hour in [12, 14, 18] and now.minute < 15
    
    def _is_weekend(self) -> bool:
        """Check if weekend."""
        return datetime.now(timezone.utc).weekday() >= 5
    
    async def _emit_risk_event(self, rule: str, message: str) -> None:
        """Emit risk violation event."""
        await self._event_bus.emit(
            Event.create(
                RiskEvent(
                    level=RiskLevel.HIGH.name,
                    metric=rule,
                    value=0.0,
                    threshold=0.0
                ),
                source="risk_manager",
                priority=2
            )
        )
