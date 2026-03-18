"""
Institutional risk management with real-time monitoring.
"""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import structlog

from src.config.settings import get_settings

logger = structlog.get_logger()


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    max_daily_loss_pct: Decimal = Decimal("2.0")
    max_position_size_pct: Decimal = Decimal("5.0")
    max_drawdown_pct: Decimal = Decimal("10.0")
    max_trades_per_day: int = 50
    max_correlated_positions: int = 3


class RiskManager:
    """
    Production risk manager with kill switch and prop firm compliance.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._limits = RiskLimits(
            max_daily_loss_pct=Decimal(str(self._settings.risk.max_daily_loss_pct)),
            max_position_size_pct=Decimal(str(self._settings.risk.max_position_size_pct)),
            max_drawdown_pct=Decimal(str(self._settings.risk.max_drawdown_pct)),
        )
        
        self._daily_pnl: Decimal = Decimal("0")
        self._daily_trades: int = 0"
        self._peak_equity: Decimal = Decimal("0")
        self._current_drawdown: Decimal = Decimal("0")
        self._kill_switch_triggered: bool = False
        self._positions: Dict[str, dict] = {}
        self._trade_history: List[dict] = []
        self._lock = asyncio.Lock()
        
        # Reset at midnight
        self._last_reset = datetime.utcnow()
        
    async def can_trade(self, symbol: str, direction: str, 
                        size: Decimal, price: Decimal,
                        account_equity: Decimal) -> tuple[bool, str]:
        """
        Pre-trade risk check. Returns (allowed, reason).
        """
        async with self._lock:
            if self._kill_switch_triggered:
                return False, "KILL_SWITCH_ACTIVE"
            
            # Check daily reset
            await self._check_daily_reset()
            
            # Daily loss limit
            daily_loss_limit = account_equity * self._limits.max_daily_loss_pct / 100
            if self._daily_pnl < -daily_loss_limit:
                await self._trigger_kill_switch("Daily loss limit exceeded")
                return False, "DAILY_LOSS_LIMIT"
            
            # Drawdown limit
            if self._peak_equity > 0:
                current_dd = (self._peak_equity - account_equity) / self._peak_equity * 100
                if current_dd > self._limits.max_drawdown_pct:
                    await self._trigger_kill_switch("Max drawdown exceeded")
                    return False, "MAX_DRAWDOWN"
            
            # Position size limit
            position_value = size * price
            max_position = account_equity * self._limits.max_position_size_pct / 100
            if position_value > max_position:
                return False, f"POSITION_SIZE_EXCEEDS_LIMIT: {position_value} > {max_position}"
            
            # Trade frequency
            if self._daily_trades >= self._limits.max_trades_per_day:
                return False, "DAILY_TRADE_LIMIT_REACHED"
            
            # Correlation check (simplified)
            correlated = sum(1 for p in self._positions.values() 
                           if p.get("direction") == direction)
            if correlated >= self._limits.max_correlated_positions:
                return False, "MAX_CORRELATED_POSITIONS"
            
            return True, "OK"
    
    async def on_trade_executed(self, trade: dict) -> None:
        """Record executed trade for risk tracking."""
        async with self._lock:
            self._daily_trades += 1
            self._trade_history.append({
                **trade,
                "timestamp": datetime.utcnow()
            })
            
            symbol = trade["symbol"]
            self._positions[symbol] = {
                "direction": trade["direction"],
                "size": trade["size"],
                "entry_price": trade["price"]
            }
            
            logger.info("trade_recorded", 
                       symbol=symbol, 
                       daily_trades=self._daily_trades,
                       daily_pnl=float(self._daily_pnl))
    
    async def on_position_closed(self, trade: dict, pnl: Decimal) -> None:
        """Update P&L when position closes."""
        async with self._lock:
            self._daily_pnl += pnl
            
            symbol = trade["symbol"]
            if symbol in self._positions:
                del self._positions[symbol]
            
            logger.info("position_closed", 
                       symbol=symbol, 
                       pnl=float(pnl),
                       daily_pnl=float(self._daily_pnl))
    
    async def update_equity(self, equity: Decimal) -> None:
        """Update current equity and track drawdown."""
        async with self._lock:
            if equity > self._peak_equity:
                self._peak_equity = equity
            
            self._current_drawdown = (self._peak_equity - equity) / self._peak_equity * 100
            
            # Auto kill switch on drawdown
            if self._current_drawdown > self._limits.max_drawdown_pct:
                await self._trigger_kill_switch(f"Drawdown: {self._current_drawdown:.2f}%")
    
    async def _trigger_kill_switch(self, reason: str) -> None:
        """Activate emergency stop."""
        self._kill_switch_triggered = True
        logger.critical("KILL_SWITCH_TRIGGERED", reason=reason)
        
        # Notify all systems
        # TODO: Broadcast to trading engine
        
    async def reset_kill_switch(self, admin_password: str) -> bool:
        """Manual reset of kill switch (requires verification)."""
        # In production, verify against secure admin hash
        if admin_password == "RESET":  # Placeholder
            self._kill_switch_triggered = False
            self._daily_pnl = Decimal("0")
            self._daily_trades = 0
            logger.warning("KILL_SWITCH_RESET")
            return True
        return False
    
    async def _check_daily_reset(self) -> None:
        """Reset daily counters at midnight UTC."""
        now = datetime.utcnow()
        if now.date() > self._last_reset.date():
            self._daily_pnl = Decimal("0")
            self._daily_trades = 0
            self._last_reset = now
            logger.info("daily_counters_reset")
    
    def get_status(self) -> dict:
        """Get current risk status."""
        return {
            "kill_switch_active": self._kill_switch_triggered,
            "daily_pnl": float(self._daily_pnl),
            "daily_trades": self._daily_trades,
            "current_drawdown_pct": float(self._current_drawdown),
            "peak_equity": float(self._peak_equity),
            "open_positions": len(self._positions),
            "limits": {
                "max_daily_loss_pct": float(self._limits.max_daily_loss_pct),
                "max_position_size_pct": float(self._limits.max_position_size_pct),
                "max_drawdown_pct": float(self._limits.max_drawdown_pct),
            }
        }
