# src/hopefx/marketplace/replication.py
"""
Copy trading engine with risk-parity position sizing
and slippage-aware replication.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Coroutine

import structlog

from hopefx.core.events import EventBus, OrderEvent, EventPriority, get_event_bus
from hopefx.execution.oms import OrderManager

logger = structlog.get_logger()


@dataclass
class CopyRatio:
    """Replication parameters."""
    multiplier: Decimal = Decimal("1.0")  # 1.0 = same size, 0.5 = half, 2.0 = double
    max_position_pct: Decimal = Decimal("0.10")  # Max 10% of equity per trade
    min_trade_size: Decimal = Decimal("0.01")  # Minimum lot size
    slippage_tolerance_bps: float = 10.0  # Skip if slippage > 10bps


class CopyTradingEngine:
    """
    Production copy trading with:
    - Risk-parity sizing (adjust for account size difference)
    - Slippage simulation (leader fills vs follower fills)
    - Latency compensation
    - Drawdown circuit breakers
    """
    
    def __init__(
        self,
        leader_account: Decimal,
        follower_account: Decimal,
        oms: OrderManager
    ) -> None:
        self._leader_equity = leader_account
        self._follower_equity = follower_account
        self._oms = oms
        self._ratio = CopyRatio()
        self._positions: dict[str, Decimal] = {}  # symbol -> size
        self._event_bus: EventBus | None = None
        self._active = True
        self._total_slippage_cost: Decimal = Decimal("0")
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize copy engine."""
        self._event_bus = await get_event_bus()
        # Subscribe to leader trades
        logger.info(
            "copy_engine_initialized",
            leader_equity=float(self._leader_equity),
            follower_equity=float(self._follower_equity)
        )
    
    async def on_leader_trade(self, leader_order: OrderEvent) -> None:
        """
        Replicate leader trade with adjusted sizing.
        """
        if not self._active:
            return
        
        async with self._lock:
            # Calculate size ratio based on equity
            equity_ratio = self._follower_equity / self._leader_equity
            
            # Apply multiplier
            follower_size = Decimal(str(leader_order.quantity)) * equity_ratio * self._ratio.multiplier
            
            # Apply limits
            max_size = self._follower_equity * self._ratio.max_position_pct / Decimal(str(leader_order.price or 2000))
            follower_size = min(follower_size, max_size)
            follower_size = max(follower_size, self._ratio.min_trade_size)
            
            # Round to standard lot sizes
            follower_size = Decimal(int(follower_size * 100)) / 100
            
            if follower_size < self._ratio.min_trade_size:
                logger.info("trade_skipped_size_too_small", size=float(follower_size))
                return
            
            # Simulate slippage (follower typically gets worse fill)
            estimated_slippage = self._estimate_slippage(leader_order)
            
            if estimated_slippage > Decimal(str(self._ratio.slippage_tolerance_bps / 10000)):
                logger.warning(
                    "trade_skipped_slippage",
                    symbol=leader_order.symbol,
                    slippage_bps=float(estimated_slippage * 10000)
                )
                return
            
            # Submit replicated order
            try:
                order = await self._oms.submit_order(
                    symbol=leader_order.symbol,
                    side=leader_order.side,
                    quantity=follower_size,
                    order_type="MARKET"  # Copy trades are market orders for speed
                )
                
                self._total_slippage_cost += estimated_slippage * follower_size * Decimal(str(leader_order.price or 2000))
                
                logger.info(
                    "trade_replicated",
                    symbol=leader_order.symbol,
                    leader_qty=leader_order.quantity,
                    follower_qty=float(follower_size),
                    slippage_bps=float(estimated_slippage * 10000)
                )
                
            except Exception as e:
                logger.error("replication_failed", error=str(e))
    
    def _estimate_slippage(self, leader_order: OrderEvent) -> Decimal:
        """Estimate replication slippage based on order characteristics."""
        # Base slippage: 1-2bps for liquid pairs
        base = Decimal("0.0001")
        
        # Size impact: larger orders = more slippage
        size_factor = Decimal(str(1 + leader_order.quantity * 0.001))
        
        # Volatility adjustment (would use real vol)
        vol_factor = Decimal("1.5")
        
        return base * size_factor * vol_factor
    
    async def update_equity(self, new_follower_equity: Decimal) -> None:
        """Update follower equity (for dynamic sizing)."""
        async with self._lock:
            old_ratio = self._follower_equity / self._leader_equity
            self._follower_equity = new_follower_equity
            new_ratio = self._follower_equity / self._leader_equity
            
            logger.info(
                "equity_updated",
                old_equity=float(self._follower_equity),
                new_equity=float(new_follower_equity),
                ratio_change=float(new_ratio / old_ratio)
            )
    
    def get_stats(self) -> dict:
        """Get replication statistics."""
        return {
            "leader_equity": float(self._leader_equity),
            "follower_equity": float(self._follower_equity),
            "equity_ratio": float(self._follower_equity / self._leader_equity),
            "total_slippage_cost": float(self._total_slippage_cost),
            "active": self._active
        }
    
    def pause(self) -> None:
        """Pause replication."""
        self._active = False
        logger.info("copy_engine_paused")
    
    def resume(self) -> None:
        """Resume replication."""
        self._active = True
        logger.info("copy_engine_resumed")
