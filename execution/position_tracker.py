"""
HOPEFX Position Tracker
Real-time position tracking with P&L calculation
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Trading position"""
    id: str
    symbol: str
    side: str  # 'long' or 'short'
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    commission: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    def update_price(self, new_price: float):
        """Update position with new price"""
        self.current_price = new_price
        self.updated_at = datetime.utcnow()
        
        # Calculate unrealized P&L
        if self.side == 'long':
            self.unrealized_pnl = (new_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - new_price) * self.quantity
    
    @property
    def market_value(self) -> float:
        """Current market value"""
        return self.quantity * self.current_price
    
    @property
    def total_pnl(self) -> float:
        """Total P&L"""
        return self.unrealized_pnl + self.realized_pnl - self.commission


class PositionTracker:
    """
    Track all positions with real-time P&L updates
    """
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self._lock = asyncio.Lock()
        self._price_subscriptions: Dict[str, List[str]] = defaultdict(list)
    
    async def add_position(self, position: Position) -> bool:
        """Add new position"""
        async with self._lock:
            self.positions[position.id] = position
            self._price_subscriptions[position.symbol].append(position.id)
            logger.info(f"Position added: {position.id} ({position.symbol})")
            return True
    
    async def update_position(self, position_id: str, **updates) -> bool:
        """Update position fields"""
        async with self._lock:
            if position_id not in self.positions:
                return False
            
            pos = self.positions[position_id]
            for key, value in updates.items():
                if hasattr(pos, key):
                    setattr(pos, key, value)
            
            pos.updated_at = datetime.utcnow()
            return True
    
    async def close_position(self, position_id: str, exit_price: float, 
                          commission: float = 0) -> Optional[Position]:
        """Close position"""
        async with self._lock:
            if position_id not in self.positions:
                return None
            
            pos = self.positions[position_id]
            pos.current_price = exit_price
            
            # Calculate realized P&L
            if pos.side == 'long':
                pos.realized_pnl = (exit_price - pos.entry_price) * pos.quantity
            else:
                pos.realized_pnl = (pos.entry_price - exit_price) * pos.quantity
            
            pos.commission += commission
            pos.unrealized_pnl = 0
            
            # Remove from tracking
            del self.positions[position_id]
            if position_id in self._price_subscriptions[pos.symbol]:
                self._price_subscriptions[pos.symbol].remove(position_id)
            
            logger.info(
                f"Position closed: {position_id} | "
                f"Realized P&L: ${pos.realized_pnl:.2f} | "
                f"Commission: ${pos.commission:.2f}"
            )
            
            return pos
    
    async def update_prices(self, symbol: str, price: float):
        """Update all positions for a symbol with new price"""
        async with self._lock:
            for pos_id in self._price_subscriptions.get(symbol, []):
                if pos_id in self.positions:
                    self.positions[pos_id].update_price(price)
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID"""
        return self.positions.get(position_id)
    
    def get_positions_by_symbol(self, symbol: str) -> List[Position]:
        """Get all positions for a symbol"""
        return [
            pos for pos in self.positions.values()
            if pos.symbol == symbol
        ]
    
    def get_all_positions(self) -> List[Position]:
        """Get all positions"""
        return list(self.positions.values())
    
    def get_exposure(self, symbol: Optional[str] = None) -> Dict[str, float]:
        """Get total exposure"""
        if symbol:
            positions = self.get_positions_by_symbol(symbol)
            return {
                'long': sum(p.quantity for p in positions if p.side == 'long'),
                'short': sum(p.quantity for p in positions if p.side == 'short'),
                'net': sum(
                    p.quantity if p.side == 'long' else -p.quantity
                    for p in positions
                )
            }
        else:
            total_long = sum(p.quantity for p in self.positions.values() if p.side == 'long')
            total_short = sum(p.quantity for p in self.positions.values() if p.side == 'short')
            return {
                'long': total_long,
                'short': total_short,
                'net': total_long - total_short
            }
    
    def get_total_pnl(self) -> Dict[str, float]:
        """Get total P&L across all positions"""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        realized = sum(p.realized_pnl for p in self.positions.values())
        commission = sum(p.commission for p in self.positions.values())
        
        return {
            'unrealized': unrealized,
            'realized': realized,
            'commission': commission,
            'total': unrealized + realized - commission
        }
