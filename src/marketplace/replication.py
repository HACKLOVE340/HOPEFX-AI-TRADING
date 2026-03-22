"""
Copy trading engine with risk-adjusted position sizing.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from src.core.events import Event, get_event_bus
from src.core.logging_config import get_logger
from src.domain.models import Order, Signal

logger = get_logger(__name__)


@dataclass
class CopyTrader:
    """Copy trader configuration."""
    trader_id: str
    leader_id: str
    copy_ratio: Decimal  # 0.1 to 10.0
    max_position_size: Decimal
    risk_adjustment: str  # "proportional", "fixed", "kelly"
    stop_copy_if_drawdown: Decimal  # Stop if leader hits this drawdown


class CopyTradingEngine:
    """
    Advanced copy trading with slippage estimation and risk parity.
    """
    
    def __init__(self):
        self.copiers: dict[str, list[CopyTrader]] = {}
        self.leader_performance: dict[str, list[float]] = {}
        self._event_bus = get_event_bus()
    
    async def start(self) -> None:
        """Start copy trading engine."""
        # Subscribe to leader trades
        await self._event_bus.subscribe(
            "leader_trade",
            self._on_leader_trade
        )
    
    async def register_copier(self, config: CopyTrader) -> None:
        """Register new copy trader."""
        if config.leader_id not in self.copiers:
            self.copiers[config.leader_id] = []
        
        self.copiers[config.leader_id].append(config)
        logger.info(f"Registered copier {config.trader_id} for leader {config.leader_id}")
    
    async def _on_leader_trade(self, event: Event) -> None:
        """Replicate leader trade for all copiers."""
        leader_id = event.payload.get("leader_id")
        leader_order: Order = event.payload.get("order")
        
        if leader_id not in self.copiers:
            return
        
        for copier in self.copiers[leader_id]:
            # Check if should copy
            if not await self._should_copy(copier, leader_id):
                continue
            
            # Calculate copy size
            copy_size = self._calculate_copy_size(copier, leader_order)
            
            # Estimate slippage
            slippage = self._estimate_replication_slippage(leader_order)
            
            # Create copy order
            copy_order = Order(
                symbol=leader_order.symbol,
                direction=leader_order.direction,
                order_type=leader_order.order_type,
                quantity=copy_size,
                metadata={
                    "copied_from": leader_id,
                    "copier_id": copier.trader_id,
                    "copy_ratio": float(copier.copy_ratio),
                    "estimated_slippage": slippage
                }
            )
            
            # Emit copy order
            await self._event_bus.emit(
                Event.create(
                    copy_order,
                    source="copy_trading"
                )
            )
    
    async def _should_copy(self, copier: CopyTrader, leader_id: str) -> bool:
        """Check if copier should continue copying."""
        # Check leader drawdown
        if leader_id in self.leader_performance:
            returns = self.leader_performance[leader_id]
            if len(returns) > 20:
                cumulative = (1 + pd.Series(returns)).cumprod()
                running_max = cumulative.expanding().max()
                drawdown = (cumulative - running_max) / running_max
                max_dd = drawdown.min()
                
                if abs(max_dd) > copier.stop_copy_if_drawdown:
                    logger.warning(
                        f"Stopping copy for {copier.trader_id}: "
                        f"leader drawdown {max_dd:.2%}"
                    )
                    return False
        
        return True
    
    def _calculate_copy_size(self, copier: CopyTrader, leader_order: Order) -> Decimal:
        """Calculate position size for copy."""
        base_size = leader_order.quantity * copier.copy_ratio
        
        if copier.risk_adjustment == "proportional":
            # Adjust based on relative account sizes
            # Simplified - would query actual account sizes
            return min(base_size, copier.max_position_size)
        
        elif copier.risk_adjustment == "fixed":
            # Fixed size regardless of leader
            return copier.max_position_size
        
        elif copier.risk_adjustment == "kelly":
            # Kelly criterion based on leader's track record
            # Simplified implementation
            win_rate = 0.55  # Would calculate from history
            avg_win = 2.0
            avg_loss = 1.0
            
            kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            kelly = max(0, min(kelly, 0.25))  # Half-Kelly, capped
            
            return base_size * Decimal(str(kelly))
        
        return min(base_size, copier.max_position_size)
    
    def _estimate_replication_slippage(self, leader_order: Order) -> float:
        """Estimate slippage from replication delay."""
        # Base slippage estimate
        base_slippage = 0.0001  # 1bp
        
        # Add latency component
        estimated_latency_ms = 500  # Half second delay
        volatility_per_ms = 0.000001  # Microstructure volatility
        
        latency_slippage = estimated_latency_ms * volatility_per_ms
        
        return base_slippage + latency_slippage
