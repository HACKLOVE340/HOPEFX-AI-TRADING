"""
Simulated Execution Handler

Simulates order execution with realistic fills, slippage, and commissions.
"""

import logging
from typing import Optional
from backtesting.events import OrderEvent, FillEvent

logger = logging.getLogger(__name__)


class SimulatedExecutionHandler:
    """
    Simulates order execution for backtesting.
    
    Models market orders, limit orders, slippage, and commissions.
    """
    
    def __init__(self, data_handler, commission_pct: float = 0.001, slippage_pct: float = 0.0005):
        """
        Initialize execution handler.
        
        Args:
            data_handler: DataHandler instance
            commission_pct: Commission as percentage (0.001 = 0.1%)
            slippage_pct: Slippage as percentage (0.0005 = 0.05%)
        """
        self.data_handler = data_handler
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        
        logger.info(f"Initialized execution handler (commission: {commission_pct*100}%, slippage: {slippage_pct*100}%)")
        
    def execute_order(self, order: OrderEvent) -> Optional[FillEvent]:
        """
        Execute an order and create fill event.
        
        Args:
            order: OrderEvent to execute
            
        Returns:
            FillEvent if order filled, None otherwise
        """
        # Get current bar for symbol
        bar = self.data_handler.get_latest_bar(order.symbol)
        
        if bar is None:
            logger.warning(f"No data available for {order.symbol}, cannot execute order")
            return None
            
        # Determine fill price based on order type
        if order.order_type == 'MARKET':
            # Market orders fill at next open (assuming bar-by-bar)
            # In reality, might use close or a slippage model
            fill_price = bar['close']
            
            # Apply slippage
            if order.direction == 'BUY':
                fill_price *= (1 + self.slippage_pct)
            else:
                fill_price *= (1 - self.slippage_pct)
                
        elif order.order_type == 'LIMIT':
            # Check if limit price was reached
            if order.direction == 'BUY' and order.price >= bar['low']:
                fill_price = min(order.price, bar['high'])
            elif order.direction == 'SELL' and order.price <= bar['high']:
                fill_price = max(order.price, bar['low'])
            else:
                # Limit not reached
                return None
                
        elif order.order_type == 'STOP':
            # Check if stop was triggered
            if order.direction == 'BUY' and order.price <= bar['high']:
                fill_price = max(order.price, bar['low'])
                fill_price *= (1 + self.slippage_pct)  # Add slippage
            elif order.direction == 'SELL' and order.price >= bar['low']:
                fill_price = min(order.price, bar['high'])
                fill_price *= (1 - self.slippage_pct)  # Add slippage
            else:
                # Stop not triggered
                return None
        else:
            logger.error(f"Unknown order type: {order.order_type}")
            return None
            
        # Calculate commission
        commission = fill_price * order.quantity * self.commission_pct
        
        # Create fill event
        fill = FillEvent(
            symbol=order.symbol,
            quantity=order.quantity,
            direction=order.direction,
            fill_price=fill_price,
            commission=commission
        )
        
        logger.debug(f"Filled {order.direction} {order.quantity} {order.symbol} @ {fill_price:.4f}")
        
        return fill
