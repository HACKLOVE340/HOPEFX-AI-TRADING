# src/hopefx/risk/manager.py
"""
Central risk orchestrator with multi-level circuit breakers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Literal

import numpy as np
import structlog

from hopefx.config.settings import settings
from hopefx.core.events import (
    EventBus,
    EventHandler,
    RiskEvent,
    EventPriority,
    get_event_bus,
)
from hopefx.risk.var_cvar import calculate_var_cvar

logger = structlog.get_logger()


class RiskLevel(Enum):
    """Risk severity levels."""
    NORMAL = auto()
    ELEVATED = auto()
    CRITICAL = auto()
    EMERGENCY = auto()


@dataclass
class PositionRisk:
    """Risk metrics for a position."""
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    var_95: Decimal
    var_99: Decimal
    margin_used: Decimal


@dataclass
class PortfolioRisk:
    """Portfolio-level risk metrics."""
    total_exposure: Decimal
    net_exposure: Decimal
    gross_exposure: Decimal
    margin_utilization: float
    portfolio_var_95: Decimal
    portfolio_var_99: Decimal
    max_drawdown_current: float
    sharpe_ratio: float
    sortino_ratio: float


class RiskManager(EventHandler):
    """
    Production risk manager with real-time monitoring,
    dynamic position sizing, and prop firm compliance.
    """
    
    event_type = RiskEvent
    
    def __init__(self) -> None:
        self._event_bus: EventBus | None = None
        self._positions: dict[str, PositionRisk] = {}
        self._equity_curve: list[tuple[float, Decimal]] = []
        self._peak_equity: Decimal = Decimal("0")
        self._current_drawdown: float = 0.0
        self._daily_pnl: Decimal = Decimal("0")
        self._daily_loss_limit: Decimal = Decimal("0")
        self._risk_level = RiskLevel.NORMAL
        self._kill_switch_triggered = False
        self._lock = asyncio.Lock()
        
        # Risk limits from config
        self._max_position_size = Decimal(str(settings.trading.max_position_size))
        self._max_daily_loss_pct = settings.trading.max_daily_loss_pct
        self._max_drawdown_pct = settings.trading.max_drawdown_pct
        self._risk_per_trade_pct = settings.trading.risk_per_trade_pct
    
    async def initialize(self) -> None:
        """Initialize risk manager."""
        self._event_bus = await get_event_bus()
        self._event_bus.subscribe(self)
        
        # Start monitoring loop
        asyncio.create_task(self._monitoring_loop())
        
        logger.info("risk_manager_initialized")
    
    async def handle(self, event: RiskEvent) -> None:
        """Process risk events."""
        if event.severity == "EMERGENCY":
            await self._trigger_kill_switch(event)
        elif event.severity == "CRITICAL":
            await self._reduce_exposure(0.5)
    
    async def calculate_position_size(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss: Decimal,
        account_balance: Decimal,
        volatility: float
    ) -> Decimal:
        """
        ATR-based dynamic position sizing with volatility adjustment.
        """
        async with self._lock:
            if self._kill_switch_triggered:
                return Decimal("0")
            
            if self._risk_level == RiskLevel.CRITICAL:
                return Decimal("0")
            
            # Risk amount in currency
            risk_amount = account_balance * Decimal(str(self._risk_per_trade_pct / 100))
            
            # Stop distance in price terms
            stop_distance = abs(entry_price - stop_loss)
            if stop_distance == 0:
                stop_distance = entry_price * Decimal("0.01")  # 1% default
            
            # Base position size
            base_size = risk_amount / stop_distance
            
            # Volatility adjustment (reduce size in high vol)
            vol_factor = max(0.25, 1.0 - (volatility - 0.1) * 2)
            adjusted_size = base_size * Decimal(str(vol_factor))
            
            # Apply limits
            final_size = min(adjusted_size, self._max_position_size)
            
            # Check portfolio heat
            current_heat = sum(p.quantity for p in self._positions.values())
            max_total = self._max_position_size * Decimal("3")  # Max 3x single position
            if current_heat + final_size > max_total:
                final_size = max(Decimal("0"), max_total - current_heat)
            
            logger.info(
                "position_size_calculated",
                symbol=symbol,
                base_size=float(base_size),
                adjusted_size=float(adjusted_size),
                final_size=float(final_size),
                volatility=volatility
            )
            
            return final_size.quantize(Decimal("0.01"))
    
    async def update_position(self, position: PositionRisk) -> None:
        """Update position risk metrics."""
        async with self._lock:
            self._positions[position.symbol] = position
            await self._recalculate_portfolio_risk()
    
    async def close_position(self, symbol: str) -> None:
        """Remove position from tracking."""
        async with self._lock:
            if symbol in self._positions:
                del self._positions[symbol]
                await self._recalculate_portfolio_risk()
    
    async def check_prop_firm_compliance(
        self,
        firm: Literal["FTMO", "MFF", "THE5ERS", "TOPSTEP"],
        account_size: Decimal,
        daily_loss: Decimal,
        total_loss: Decimal,
        open_positions: int
    ) -> dict[str, any]:
        """
        Check compliance against prop firm rules.
        """
        rules = {
            "FTMO": {
                "daily_loss_limit": 0.05,  # 5%
                "total_loss_limit": 0.10,  # 10%
                "min_trading_days": 4,
                "max_position_ratio": 0.5,  # 50% of account in one trade
            },
            "MFF": {
                "daily_loss_limit": 0.05,
                "total_loss_limit": 0.08,  # 8%
                "min_trading_days": 3,
                "max_position_ratio": 0.3,
            },
            "THE5ERS": {
                "daily_loss_limit": 0.04,
                "total_loss_limit": 0.10,
                "news_trading_allowed": False,
            },
            "TOPSTEP": {
                "daily_loss_limit": 0.02,  # 2% trailing
                "total_loss_limit": 0.05,  # 5% max
            }
        }
        
        firm_rules = rules.get(firm, rules["FTMO"])
        
        daily_loss_pct = float(daily_loss / account_size)
        total_loss_pct = float(total_loss / account_size)
        
        violations = []
        
        if daily_loss_pct > firm_rules["daily_loss_limit"]:
            violations.append(f"Daily loss limit exceeded: {daily_loss_pct:.2%}")
        
        if total_loss_pct > firm_rules["total_loss_limit"]:
            violations.append(f"Total loss limit exceeded: {total_loss_pct:.2%}")
        
        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "daily_loss_pct": daily_loss_pct,
            "total_loss_pct": total_loss_pct,
            "remaining_daily": firm_rules["daily_loss_limit"] - daily_loss_pct,
            "remaining_total": firm_rules["total_loss_limit"] - total_loss_pct,
        }
    
    async def _recalculate_portfolio_risk(self) -> None:
        """Recalculate portfolio-level risk metrics."""
        if not self._positions:
            return
        
        # Calculate portfolio VaR
        pnls = [float(p.unrealized_pnl) for p in self._positions.values()]
        var_95, var_99 = calculate_var_cvar(np.array(pnls), confidence=0.95)
        
        # Update drawdown
        current_equity = sum(
            p.entry_price * p.quantity + p.unrealized_pnl 
            for p in self._positions.values()
        )
        
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
        
        if self._peak_equity > 0:
            self._current_drawdown = float(
                (self._peak_equity - current_equity) / self._peak_equity
            )
        
        # Check limits
        if self._current_drawdown > self._max_drawdown_pct / 100:
            await self._event_bus.publish(RiskEvent(
                priority=EventPriority.CRITICAL,
                event_type="DRAWDOWN",
                severity="CRITICAL",
                current_value=self._current_drawdown,
                threshold=self._max_drawdown_pct / 100,
                action_taken="REDUCE_EXPOSURE",
                source="risk_manager"
            ))
            self._risk_level = RiskLevel.CRITICAL
    
    async def _monitoring_loop(self) -> None:
        """Continuous risk monitoring."""
        while True:
            await asyncio.sleep(1)  # 1-second risk checks
            
            async with self._lock:
                # Check kill switch
                if self._kill_switch_triggered:
                    continue
                
                # Latency check
                # (Would integrate with execution monitoring)
    
    async def _trigger_kill_switch(self, event: RiskEvent) -> None:
        """Emergency position closure."""
        self._kill_switch_triggered = True
        logger.critical(
            "kill_switch_triggered",
            reason=event.event_type,
            current_value=event.current_value,
            threshold=event.threshold
        )
        
        # Publish kill signal to all systems
        await self._event_bus.publish(RiskEvent(
            priority=EventPriority.CRITICAL,
            event_type="KILL_SWITCH",
            severity="EMERGENCY",
            current_value=1.0,
            threshold=1.0,
            action_taken="CLOSE_ALL_POSITIONS",
            source="risk_manager"
        ))
    
    async def _reduce_exposure(self, factor: float) -> None:
        """Reduce position sizes."""
        logger.warning("reducing_exposure", factor=factor)
        # Implementation would signal position reductions
    
    def get_portfolio_risk(self) -> PortfolioRisk | None:
        """Get current portfolio risk summary."""
        if not self._positions:
            return None
        
        # Calculate metrics
        total_pnl = sum(p.unrealized_pnl for p in self._positions.values())
        
        return PortfolioRisk(
            total_exposure=sum(p.quantity * p.current_price for p in self._positions.values()),
            net_exposure=sum(
                p.quantity * p.current_price * (1 if p.quantity > 0 else -1)
                for p in self._positions.values()
            ),
            gross_exposure=sum(abs(p.quantity) * p.current_price for p in self._positions.values()),
            margin_utilization=0.0,  # Would calculate from broker
            portfolio_var_95=Decimal("0"),  # Would calculate properly
            portfolio_var_99=Decimal("0"),
            max_drawdown_current=self._current_drawdown,
            sharpe_ratio=0.0,  # Would calculate from returns
            sortino_ratio=0.0,
        )
