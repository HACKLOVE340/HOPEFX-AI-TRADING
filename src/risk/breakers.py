"""Multi-breaker risk management system."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog

from src.core.types import Tick
from src.risk.var import VaRCalculator

logger = structlog.get_logger()


@dataclass
class BreakerState:
    """Circuit breaker state."""
    name: str
    threshold: Decimal
    current: Decimal = Decimal("0")
    triggered: bool = False
    last_triggered: datetime | None = None
    cooldown_minutes: int = 15


class RiskManager:
    """Multi-layer risk management."""
    
    def __init__(self) -> None:
        self.breakers = {
            "daily_pnl": BreakerState("daily_pnl", Decimal("2000")),
            "position_count": BreakerState("position_count", Decimal("5")),
            "latency_ms": BreakerState("latency_ms", Decimal("500")),
            "slippage_bps": BreakerState("slippage_bps", Decimal("10")),
            "disconnect": BreakerState("disconnect", Decimal("3")),
        }
        
        self.var_calc = VaRCalculator()
        self._daily_pnl = Decimal("0")
        self._last_reset = datetime.utcnow()
        self._lock = asyncio.Lock()
    
    async def check_limits(
        self, 
        tick: Tick, 
        prediction: dict[str, Any]
    ) -> dict[str, Any]:
        """Check all risk limits."""
        async with self._lock:
            # Reset daily P&L if new day
            if datetime.utcnow().date() != self._last_reset.date():
                self._daily_pnl = Decimal("0")
                self._last_reset = datetime.utcnow()
            
            checks = []
            
            # Check daily P&L limit
            if abs(self._daily_pnl) > self.breakers["daily_pnl"].threshold:
                return {
                    "allowed": False,
                    "type": "DAILY_LOSS",
                    "severity": "CRITICAL",
                    "message": f"Daily loss limit exceeded: {self._daily_pnl}"
                }
            
            # Check prediction uncertainty
            if prediction.get("uncertainty", 0) > 0.5:
                checks.append({
                    "type": "HIGH_UNCERTAINTY",
                    "severity": "WARNING",
                    "message": "High prediction uncertainty"
                })
            
            # Check drift
            if prediction.get("drift_score", 0) > 0.1:
                return {
                    "allowed": False,
                    "type": "MODEL_DRIFT",
                    "severity": "CRITICAL",
                    "message": "Model drift detected, trading halted"
                }
            
            # All checks passed
            return {
                "allowed": True,
                "checks": checks,
                "daily_pnl": self._daily_pnl,
            }
    
    async def update_pnl(self, pnl: Decimal) -> None:
        """Update daily P&L."""
        async with self._lock:
            self._daily_pnl += pnl
    
    def get_breaker_status(self) -> dict[str, Any]:
        """Get current breaker states."""
        return {
            name: {
                "triggered": state.triggered,
                "current": float(state.current),
                "threshold": float(state.threshold),
            }
            for name, state in self.breakers.items()
        }
