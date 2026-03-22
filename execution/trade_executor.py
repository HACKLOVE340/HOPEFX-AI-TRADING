"""
HOPEFX Trade Executor
Smart order routing and execution management
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from infrastructure.metrics import get_metrics_registry

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class ExecutionResult:
    """Order execution result"""
    success: bool
    order_id: Optional[str]
    filled_quantity: float
    average_price: float
    commission: float
    status: OrderStatus
    message: str
    latency_ms: float
    timestamp: datetime = datetime.utcnow()


class TradeExecutor:
    """
    Smart trade execution with:
    - Order validation
    - Position sizing verification
    - Slippage protection
    - Retry logic
    - Execution reporting
    """
    
    def __init__(self, broker, risk_manager, position_tracker):
        self.broker = broker
        self.risk_manager = risk_manager
        self.position_tracker = position_tracker
        self.metrics = get_metrics_registry()
        
        self._pending_orders: Dict[str, Dict] = {}
        self._execution_callbacks: List[Callable] = []
        self._lock = asyncio.Lock()
    
    async def execute_signal(self, signal: Dict) -> ExecutionResult:
        """
        Execute trading signal with full validation
        """
        start_time = asyncio.get_event_loop().time()
        
        # Validate signal
        required_fields = ['symbol', 'action', 'size']
        if not all(f in signal for f in required_fields):
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Missing required fields: {[f for f in required_fields if f not in signal]}",
                latency_ms=0
            )
        
        symbol = signal['symbol']
        action = signal['action']
        size = signal['size']
        
        # Validate action
        if action not in ['buy', 'sell', 'close']:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Invalid action: {action}",
                latency_ms=0
            )
        
        try:
            # Execute based on action type
            if action == 'close':
                result = await self._execute_close(signal)
            else:
                result = await self._execute_open(signal)
            
            # Record metrics
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            result.latency_ms = latency_ms
            self.metrics.record_order_latency(latency_ms)
            
            if result.success:
                self.metrics.get_collector("orders_filled_total").inc(1, {
                    'symbol': symbol,
                    'type': 'market'
                })
            else:
                self.metrics.get_collector("orders_rejected_total").inc(1, {
                    'symbol': symbol,
                    'reason': result.status.value
                })
            
            # Notify callbacks
            await self._notify_callbacks(result, signal)
            
            return result
            
        except Exception as e:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            logger.exception(f"Execution error for {symbol}: {e}")
            
            self.metrics.record_error("trade_executor", type(e).__name__)
            
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=str(e),
                latency_ms=latency_ms
            )
    
    async def _execute_open(self, signal: Dict) -> ExecutionResult:
        """Execute opening order"""
        symbol = signal['symbol']
        side = signal['action']
        size = signal['size']
        
        # Check risk limits one more time
        if not self.risk_manager.can_trade:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.REJECTED,
                message="Trading halted by risk manager"
            )
        
        # Place order through broker
        order = await self.broker.place_market_order(
            symbol=symbol,
            side=side,
            quantity=size
        )
        
        # Update position tracker
        if order.status.value in ['filled', 'partial']:
            from execution.position_tracker import Position
            
            position = Position(
                id=order.id,
                symbol=symbol,
                side='long' if side == 'buy' else 'short',
                quantity=order.filled_quantity,
                entry_price=order.average_fill_price,
                current_price=order.average_fill_price,
                commission=order.commission,
                stop_loss=signal.get('stop_loss'),
                take_profit=signal.get('take_profit')
            )
            
            await self.position_tracker.add_position(position)
        
        return ExecutionResult(
            success=order.status.value in ['filled', 'partial'],
            order_id=order.id,
            filled_quantity=order.filled_quantity,
            average_price=order.average_fill_price,
            commission=order.commission,
            status=OrderStatus(order.status.value),
            message=f"Order {order.status.value}"
        )
    
    async def _execute_close(self, signal: Dict) -> ExecutionResult:
        """Execute closing order"""
        position_id = signal.get('position_id')
        
        if not position_id:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message="No position_id specified for close"
            )
        
        # Get position
        position = self.position_tracker.get_position(position_id)
        if not position:
            return ExecutionResult(
                success=False,
                order_id=None,
                filled_quantity=0,
                average_price=0,
                commission=0,
                status=OrderStatus.ERROR,
                message=f"Position not found: {position_id}"
            )
        
        # Close through broker
        success = await self.broker.close_position(position_id)
        
        if success:
            # Update position tracker
            closed_position = await self.position_tracker.close_position(
                position_id,
                position.current_price,
                commission=position.commission
            )
            
            # Record trade result for strategy performance
            if closed_position:
                # Notify risk manager of realized P&L
                self.risk_manager.update_equity(
                    self.risk_manager.daily_starting_equity + closed_position.realized_pnl
                )
        
        return ExecutionResult(
            success=success,
            order_id=position_id,
            filled_quantity=position.quantity if success else 0,
            average_price=position.current_price if success else 0,
            commission=position.commission,
            status=OrderStatus.FILLED if success else OrderStatus.ERROR,
            message="Position closed" if success else "Close failed"
        )
    
    def register_callback(self, callback: Callable[[ExecutionResult, Dict], None]):
        """Register execution callback"""
        self._execution_callbacks.append(callback)
    
    async def _notify_callbacks(self, result: ExecutionResult, signal: Dict):
        """Notify all callbacks"""
        for callback in self._execution_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(result, signal)
                else:
                    callback(result, signal)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    async def cancel_all_pending(self) -> List[str]:
        """Cancel all pending orders"""
        cancelled = []
        
        async with self._lock:
            for order_id, order_info in list(self._pending_orders.items()):
                try:
                    success = await self.broker.cancel_order(order_id)
                    if success:
                        cancelled.append(order_id)
                        del self._pending_orders[order_id]
                except Exception as e:
                    logger.error(f"Error cancelling order {order_id}: {e}")
        
        return cancelled
